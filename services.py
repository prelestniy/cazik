# [context: Linux x86_64, Python 3.12, aiogram 3, SQLAlchemy async]
# *services — the organs of the casino; each function a heartbeat*

from __future__ import annotations
import random
import logging
from datetime import datetime, timedelta
from dataclasses import dataclass
from typing import Optional, Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, or_, case

from models import User, GameResult, Transaction, Task, UserTask, GameConfig, SystemEvent

log = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════
#  FORMATTERS
# ═══════════════════════════════════════════════════════

def fmt_bal(n: int) -> str:
    return f"{n:,}".replace(",", " ")

def fmt_winrate(wins: int, total: int) -> str:
    if not total:
        return "0%"
    return f"{wins / total * 100:.1f}%"

def progress_bar(cur: int, total: int, width: int = 10) -> str:
    filled = int(min(cur, total) / max(total, 1) * width)
    return "█" * filled + "░" * (width - filled)

def fmt_time_left(expires_at: datetime) -> str:
    diff = expires_at - datetime.utcnow()
    if diff.total_seconds() <= 0:
        return "истекло"
    h, rem = divmod(int(diff.total_seconds()), 3600)
    m = rem // 60
    return f"{h}ч {m}м" if h else f"{m}м"

def fmt_username(user: User) -> str:
    if user.username:
        return f"@{user.username}"
    full = " ".join(filter(None, [user.first_name, user.last_name]))
    return full or f"User#{user.telegram_id}"


# ═══════════════════════════════════════════════════════
#  USER SERVICE
# ═══════════════════════════════════════════════════════

async def upsert_user(session: AsyncSession, tg_id: int, username: Optional[str],
                      first_name: str, last_name: Optional[str]) -> User:
    r = await session.execute(select(User).where(User.telegram_id == tg_id))
    user = r.scalar_one_or_none()
    if user:
        user.username = username
        user.first_name = first_name
        user.last_name = last_name
        user.last_login_at = datetime.utcnow()
    else:
        user = User(telegram_id=tg_id, username=username,
                    first_name=first_name, last_name=last_name, balance=100)
        session.add(user)
        await session.flush()
    return user


async def get_user(session: AsyncSession, tg_id: int) -> Optional[User]:
    r = await session.execute(select(User).where(User.telegram_id == tg_id))
    return r.scalar_one_or_none()


async def get_user_by_id(session: AsyncSession, uid: int) -> Optional[User]:
    r = await session.execute(select(User).where(User.id == uid))
    return r.scalar_one_or_none()


async def get_leaderboard(session: AsyncSession, limit: int = 10) -> list[User]:
    r = await session.execute(
        select(User).where(User.is_blocked == False)
        .order_by(User.total_wins.desc(), User.balance.desc())
        .limit(limit)
    )
    return list(r.scalars())


async def get_rank(session: AsyncSession, user: User) -> int:
    r = await session.execute(
        select(func.count()).where(
            and_(User.is_blocked == False,
                 or_(User.total_wins > user.total_wins,
                     and_(User.total_wins == user.total_wins,
                          User.balance > user.balance)))
        )
    )
    return (r.scalar() or 0) + 1


async def block_user(session: AsyncSession, uid: int, blocked: bool) -> User:
    user = await get_user_by_id(session, uid)
    user.is_blocked = blocked
    return user


async def toggle_vip(session: AsyncSession, uid: int, vip: bool) -> User:
    user = await get_user_by_id(session, uid)
    user.is_vip = vip
    return user


async def _add_tx(session: AsyncSession, uid: int, tx_type: str,
                  amount: int, desc: str, charge_id: Optional[str] = None) -> None:
    session.add(Transaction(user_id=uid, type=tx_type,
                            amount=abs(amount), description=desc,
                            payment_charge_id=charge_id))


async def admin_grant(session: AsyncSession, uid: int, amount: int, by: int) -> User:
    user = await get_user_by_id(session, uid)
    user.balance += amount
    await _add_tx(session, uid, "ADMIN_GRANT", amount, f"Grant by admin #{by}")
    return user


async def admin_deduct(session: AsyncSession, uid: int, amount: int, by: int) -> User:
    user = await get_user_by_id(session, uid)
    user.balance -= amount
    await _add_tx(session, uid, "ADMIN_DEDUCT", amount, f"Deduct by admin #{by}")
    return user


async def get_transactions(session: AsyncSession, uid: int, limit: int = 10) -> list[Transaction]:
    r = await session.execute(
        select(Transaction).where(Transaction.user_id == uid)
        .order_by(Transaction.created_at.desc()).limit(limit)
    )
    return list(r.scalars())


async def total_users(session: AsyncSession) -> int:
    r = await session.execute(select(func.count()).select_from(User))
    return r.scalar() or 0


async def active_users_24h(session: AsyncSession) -> int:
    since = datetime.utcnow() - timedelta(hours=24)
    r = await session.execute(
        select(func.count()).where(User.last_login_at >= since)
    )
    return r.scalar() or 0


async def find_user_admin(session: AsyncSession, query: str) -> Optional[User]:
    if query.isdigit():
        q = int(query)
        r = await session.execute(
            select(User).where(or_(User.id == q, User.telegram_id == q))
        )
        return r.scalar_one_or_none()
    uname = query.lstrip("@").lower()
    r = await session.execute(
        select(User).where(func.lower(User.username) == uname)
    )
    return r.scalar_one_or_none()


# ═══════════════════════════════════════════════════════
#  GAME SERVICE
# ═══════════════════════════════════════════════════════

SLOT_SYMS = ["🍒", "🍋", "🍊", "🍇", "⭐", "💎"]


@dataclass
class GameOut:
    won: bool
    payout: int
    result: str
    new_balance: int
    reels: Optional[list[str]] = None


async def _commit_game(session: AsyncSession, user: User, game_type: str,
                       bet: int, result: str, payout: int, won: bool) -> GameOut:
    if user.balance < bet:
        raise ValueError("Недостаточно очков")
    delta = payout - bet
    new_streak = user.win_streak + 1 if won else 0
    user.balance += delta
    user.total_games += 1
    if won:
        user.total_wins += 1
    user.win_streak = new_streak
    user.max_win_streak = max(user.max_win_streak, new_streak)
    session.add(GameResult(user_id=user.id, game_type=game_type,
                           bet=bet, result=result, payout=payout, won=won))
    await _add_tx(session, user.id,
                  "GAME_WIN" if won else "GAME_LOSS",
                  abs(delta) if delta else bet,
                  f"{game_type} bet:{bet} payout:{payout}")
    return GameOut(won=won, payout=payout, result=result, new_balance=user.balance)


async def play_coinflip(session: AsyncSession, user: User,
                        bet: int, choice: str) -> GameOut:
    roll = "heads" if random.random() < 0.5 else "tails"
    won = roll == choice
    mult = (2.2 if user.is_vip else 2.0) if won else 0.0
    payout = int(bet * mult)
    return await _commit_game(session, user, "COINFLIP", bet, roll, payout, won)


async def play_dice(session: AsyncSession, user: User,
                    bet: int, guess: int) -> GameOut:
    roll = random.randint(1, 6)
    exact = roll == guess
    adjacent = not exact and abs(roll - guess) == 1
    if exact:
        mult = 5.5 if user.is_vip else 5.0
    elif adjacent:
        mult = 1.1 if user.is_vip else 1.0
    else:
        mult = 0.0
    won = exact or adjacent
    payout = int(bet * mult)
    result_str = f"roll:{roll},guess:{guess}"
    return await _commit_game(session, user, "DICE", bet, result_str, payout, won)


async def play_slots(session: AsyncSession, user: User, bet: int) -> GameOut:
    reels = [random.choice(SLOT_SYMS) for _ in range(3)]
    all3 = reels[0] == reels[1] == reels[2]
    two  = not all3 and (reels[0] == reels[1] or reels[1] == reels[2] or reels[0] == reels[2])
    if all3:
        mult = 11.0 if user.is_vip else 10.0
    elif two:
        mult = 2.2 if user.is_vip else 2.0
    else:
        mult = 0.0
    won = all3 or two
    payout = int(bet * mult)
    out = await _commit_game(session, user, "SLOTS", bet, "|".join(reels), payout, won)
    out.reels = reels
    return out


async def get_config(session: AsyncSession, key: str, default: str = "0") -> str:
    r = await session.execute(select(GameConfig).where(GameConfig.key == key))
    cfg = r.scalar_one_or_none()
    return cfg.value if cfg else default


async def set_config(session: AsyncSession, key: str, value: str) -> None:
    r = await session.execute(select(GameConfig).where(GameConfig.key == key))
    cfg = r.scalar_one_or_none()
    if cfg:
        cfg.value = value
    else:
        session.add(GameConfig(key=key, value=value))


async def all_configs(session: AsyncSession) -> list[GameConfig]:
    r = await session.execute(select(GameConfig).order_by(GameConfig.key))
    return list(r.scalars())


async def seed_configs(session: AsyncSession) -> None:
    defaults = [
        ("coinflip.min_bet", "10",  "Мин ставка монетки"),
        ("coinflip.max_bet", "500", "Макс ставка монетки"),
        ("dice.min_bet",     "10",  "Мин ставка кубика"),
        ("dice.max_bet",     "300", "Макс ставка кубика"),
        ("slots.min_bet",    "20",  "Мин ставка слотов"),
        ("slots.max_bet",    "200", "Макс ставка слотов"),
    ]
    for key, val, desc in defaults:
        r = await session.execute(select(GameConfig).where(GameConfig.key == key))
        if not r.scalar_one_or_none():
            session.add(GameConfig(key=key, value=val, description=desc))


async def game_stats(session: AsyncSession, uid: int):
    r = await session.execute(
        select(
            GameResult.game_type,
            func.count(GameResult.id).label("total"),
            func.sum(case((GameResult.won == True, 1), else_=0)).label("wins"),
            func.sum(GameResult.bet).label("total_bet"),
            func.sum(GameResult.payout).label("total_payout"),
        )
        .where(GameResult.user_id == uid)
        .group_by(GameResult.game_type)
    )
    return r.all()


async def total_games_count(session: AsyncSession) -> int:
    r = await session.execute(select(func.count()).select_from(GameResult))
    return r.scalar() or 0


async def top_game_type(session: AsyncSession) -> str:
    r = await session.execute(
        select(GameResult.game_type, func.count(GameResult.id).label("n"))
        .group_by(GameResult.game_type)
        .order_by(func.count(GameResult.id).desc())
        .limit(1)
    )
    row = r.first()
    return row.game_type if row else "N/A"


# ═══════════════════════════════════════════════════════
#  ADMIN SERVICE
# ═══════════════════════════════════════════════════════

async def log_event(session: AsyncSession, event_type: str,
                    user_id: Optional[int] = None, payload: Optional[dict] = None) -> None:
    session.add(SystemEvent(event_type=event_type,
                            user_id=user_id, payload=payload or {}))


async def system_stats(session: AsyncSession) -> dict:
    return {
        "total_users":      await total_users(session),
        "active_users_24h": await active_users_24h(session),
        "total_games":      await total_games_count(session),
        "top_game":         await top_game_type(session),
    }


async def recent_events(session: AsyncSession, limit: int = 15):
    r = await session.execute(
        select(SystemEvent, User.username, User.first_name)
        .outerjoin(User, SystemEvent.user_id == User.id)
        .order_by(SystemEvent.created_at.desc())
        .limit(limit)
    )
    return r.all()


# ═══════════════════════════════════════════════════════
#  TASK SERVICE
# ═══════════════════════════════════════════════════════

TASK_DEFS = [
    {"title": "🎮 Игроман",  "description": "Сыграй 5 игр",             "type": "PLAY_GAMES", "target": 5,   "reward": 50},
    {"title": "🔥 На волне", "description": "Выиграй 2 игры подряд",    "type": "WIN_STREAK", "target": 2,   "reward": 100},
    {"title": "🏆 Элита",    "description": "Войди в топ-5 рейтинга",   "type": "TOP_RANK",   "target": 999, "reward": 200},
]


async def ensure_tasks(session: AsyncSession) -> None:
    for d in TASK_DEFS:
        r = await session.execute(select(Task).where(Task.type == d["type"]))
        if not r.scalar_one_or_none():
            session.add(Task(**d, is_active=True))


def _next_midnight() -> datetime:
    tom = datetime.utcnow().date() + timedelta(days=1)
    return datetime(tom.year, tom.month, tom.day, 0, 0, 0)


async def get_daily_tasks(session: AsyncSession, uid: int) -> list[tuple[UserTask, Task]]:
    now = datetime.utcnow()
    r = await session.execute(
        select(UserTask, Task)
        .join(Task, UserTask.task_id == Task.id)
        .where(UserTask.user_id == uid, UserTask.expires_at > now)
    )
    rows = r.all()
    if rows:
        return rows
    tasks_r = await session.execute(select(Task).where(Task.is_active == True))
    tasks = list(tasks_r.scalars())
    exp = _next_midnight()
    result = []
    for t in tasks:
        ut = UserTask(user_id=uid, task_id=t.id, expires_at=exp)
        session.add(ut)
        await session.flush()
        result.append((ut, t))
    return result


async def advance_task(session: AsyncSession, uid: int, task_type: str, inc: int = 1) -> None:
    now = datetime.utcnow()
    r = await session.execute(
        select(UserTask, Task)
        .join(Task, UserTask.task_id == Task.id)
        .where(UserTask.user_id == uid, UserTask.completed == False,
               UserTask.expires_at > now, Task.type == task_type)
    )
    for ut, t in r.all():
        ut.progress = min(ut.progress + inc, t.target)
        if ut.progress >= t.target:
            ut.completed = True
            ut.completed_at = now


async def advance_top_rank(session: AsyncSession, uid: int, rank: int) -> None:
    if rank <= 5:
        await advance_task(session, uid, "TOP_RANK", 999)


async def claim_reward(session: AsyncSession, uid: int, ut_id: int) -> Optional[dict]:
    now = datetime.utcnow()
    r = await session.execute(
        select(UserTask, Task)
        .join(Task, UserTask.task_id == Task.id)
        .where(UserTask.id == ut_id, UserTask.user_id == uid,
               UserTask.completed == True, UserTask.rewarded == False,
               UserTask.expires_at > now)
    )
    row = r.one_or_none()
    if not row:
        return None
    ut, t = row
    ut.rewarded = True
    user = await get_user_by_id(session, uid)
    user.balance += t.reward
    await _add_tx(session, uid, "TASK_REWARD", t.reward, f"Task: {t.title}")
    return {"reward": t.reward, "title": t.title}


# ═══════════════════════════════════════════════════════
#  PAYMENTS
# ═══════════════════════════════════════════════════════

SHOP_ITEMS = [
    {"id": "pack_500",    "title": "💰 Пакет 500 очков",   "points": 500,  "stars": 50,  "is_vip": False},
    {"id": "pack_1500",   "title": "💎 Пакет 1500 очков",  "points": 1500, "stars": 130, "is_vip": False},
    {"id": "pack_5000",   "title": "👑 Пакет 5000 очков",  "points": 5000, "stars": 400, "is_vip": False},
    {"id": "vip_status",  "title": "⭐ VIP-статус",         "points": 0,    "stars": 150, "is_vip": True},
]


def get_shop_item(item_id: str) -> Optional[dict]:
    return next((i for i in SHOP_ITEMS if i["id"] == item_id), None)


async def process_payment(session: AsyncSession, user: User,
                           item: dict, charge_id: str) -> bool:
    # idempotency
    r = await session.execute(
        select(Transaction).where(Transaction.payment_charge_id == charge_id)
    )
    if r.scalar_one_or_none():
        return False  # already processed
    if item["points"] > 0:
        user.balance += item["points"]
    if item["is_vip"]:
        user.is_vip = True
    await _add_tx(session, user.id, "PURCHASE",
                  item["points"] or item["stars"],
                  f"Purchase: {item['title']}", charge_id=charge_id)
    return True
