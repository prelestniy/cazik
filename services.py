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

from models import User, GameResult, Transaction, Task, UserTask, GameConfig, SystemEvent, Withdrawal, NftClaim
from config import ADMIN_USERNAMES

log = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════
#  FORMATTERS
# ═══════════════════════════════════════════════════════

def fmt_bal(n: int) -> str:
    return f"⭐ {n:,}".replace(",", " ")

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
        # Only mark dirty if something actually changed (avoids pointless UPDATE on every request)
        if user.username != username or user.first_name != first_name or user.last_name != last_name:
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
    if user is None:
        raise ValueError(f"User #{uid} not found")
    user.is_blocked = blocked
    await session.flush()
    return user


async def toggle_vip(session: AsyncSession, uid: int, vip: bool) -> User:
    user = await get_user_by_id(session, uid)
    if user is None:
        raise ValueError(f"User #{uid} not found")
    user.is_vip = vip
    await session.flush()
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

# VIP даёт +5% к каждому выигрышу (множитель к базовому коэффициенту)
VIP_MULT = 1.05


def _vip(user: User) -> float:
    return VIP_MULT if user.is_vip else 1.0


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
    mult = (2.0 * _vip(user)) if won else 0.0
    payout = int(bet * mult)
    return await _commit_game(session, user, "COINFLIP", bet, roll, payout, won)


async def play_dice(session: AsyncSession, user: User,
                    bet: int, guess: int) -> GameOut:
    roll = random.randint(1, 6)
    exact = roll == guess
    adjacent = not exact and abs(roll - guess) == 1
    if exact:
        mult = 5.0 * _vip(user)
    elif adjacent:
        mult = 1.0 * _vip(user)
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
        mult = 10.0 * _vip(user)
    elif two:
        mult = 2.0 * _vip(user)
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
        # clamp to [0, target]: a loss resets WIN_STREAK by passing a large negative inc
        ut.progress = max(0, min(ut.progress + inc, t.target))
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
    {"id": "pack_100",   "title": "🪙 Пакет 100 очков",   "points": 100,  "stars": 100,  "is_vip": False},
    {"id": "pack_500",    "title": "💰 Пакет 500 очков",   "points": 500,  "stars": 500,  "is_vip": False},
    {"id": "pack_1000",   "title": "💎 Пакет 1000 очков",  "points": 1000, "stars": 1000, "is_vip": False},
    {"id": "pack_1500",   "title": "🏦 Пакет 1500 очков",  "points": 1500, "stars": 1500, "is_vip": False},
    {"id": "pack_2000",   "title": "👑 Пакет 2000 очков",  "points": 2000, "stars": 2000, "is_vip": False},
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


# ═══════════════════════════════════════════════════════
#  WITHDRAW
# ═══════════════════════════════════════════════════════

WITHDRAW_MIN      = 2000                     # обычный минимум, очки
WITHDRAW_MIN_VIP  = 1200                     # минимум для VIP
WITHDRAW_COOLDOWN = timedelta(hours=24)      # одна заявка в сутки
# ДОПУЩЕНИЯ:
#  - "в сутки" = скользящие 24 часа от последней поданной заявки (не календарные сутки).
#    Считаются все заявки, включая отклонённые.
#  - Очки списываются сразу при подаче, при отклонении возвращаются.
#  - Максимума нет: можно вывести любую сумму от минимума до баланса.


def withdraw_min(user: User) -> int:
    return WITHDRAW_MIN_VIP if user.is_vip else WITHDRAW_MIN


def fmt_duration(td: timedelta) -> str:
    total = int(td.total_seconds())
    h, rem = divmod(total, 3600)
    m = rem // 60
    return f"{h}ч {m}м" if h else f"{max(m, 1)}м"


async def last_withdrawal(session: AsyncSession, uid: int) -> Optional[Withdrawal]:
    r = await session.execute(
        select(Withdrawal).where(Withdrawal.user_id == uid)
        .order_by(Withdrawal.created_at.desc()).limit(1)
    )
    return r.scalars().first()


async def cooldown_left(session: AsyncSession, uid: int) -> Optional[timedelta]:
    """Сколько осталось до следующей заявки, или None если можно подавать."""
    last = await last_withdrawal(session, uid)
    if not last:
        return None
    left = last.created_at + WITHDRAW_COOLDOWN - datetime.utcnow()
    return left if left.total_seconds() > 0 else None


async def create_withdrawal(session: AsyncSession, uid: int, amount: int) -> Withdrawal:
    """Бросает ValueError с текстом для юзера, если заявку подать нельзя."""
    # блокируем строку юзера, чтобы два быстрых тапа не прошли проверку лимита оба
    r = await session.execute(select(User).where(User.id == uid).with_for_update())
    user = r.scalar_one()
    if amount <= 0:
        raise ValueError("Сумма должна быть больше 0")
    if amount < withdraw_min(user):
        raise ValueError(f"Минимум для вывода: {withdraw_min(user)} очков")
    if amount > user.balance:
        raise ValueError("Недостаточно очков")
    left = await cooldown_left(session, uid)
    if left:
        raise ValueError(f"Одна заявка в сутки. Следующая будет через {fmt_duration(left)}")
    user.balance -= amount
    w = Withdrawal(user_id=uid, amount=amount, status="PENDING")
    session.add(w)
    await session.flush()
    await _add_tx(session, uid, "WITHDRAW_REQUEST", amount, f"Withdraw request #{w.id}")
    return w


async def decide_withdrawal(session: AsyncSession, wid: int, approve: bool) -> Optional[Withdrawal]:
    """None — заявка не найдена или уже обработана (двойной клик / другой админ)."""
    r = await session.execute(select(Withdrawal).where(Withdrawal.id == wid).with_for_update())
    w = r.scalar_one_or_none()
    if not w or w.status != "PENDING":
        return None
    w.status = "APPROVED" if approve else "REJECTED"
    w.decided_at = datetime.utcnow()
    if not approve:
        user = await get_user_by_id(session, w.user_id)
        user.balance += w.amount
        await _add_tx(session, w.user_id, "WITHDRAW_REFUND", w.amount, f"Refund withdraw #{w.id}")
    return w


async def get_admin_users(session: AsyncSession) -> list[User]:
    # ДОПУЩЕНИЕ: админы определяются по ADMIN_USERNAMES и должны хотя бы раз открыть бота
    if not ADMIN_USERNAMES:
        return []
    r = await session.execute(
        select(User).where(func.lower(User.username).in_(ADMIN_USERNAMES))
    )
    return list(r.scalars())


# ═══════════════════════════════════════════════════════
#  FREE NFT
# ═══════════════════════════════════════════════════════
# ДОПУЩЕНИЯ:
#  - заявка создаётся сразу при нажатии кнопки, без подтверждения;
#  - отклонённую заявку можно подать снова; пока есть заявка на рассмотрении, новую не подать;
#  - при повторной подаче (после отказа) админ видит третью кнопку «Отказать полностью»:
#    она ставит статус DENIED, и юзер больше не может подавать заявки;
#  - APPROVED: юзер пишет админу-контакту из NFT_CONTACT (по умолчанию @support).

async def get_nft_claims(session: AsyncSession, uid: int) -> list[NftClaim]:
    r = await session.execute(select(NftClaim).where(NftClaim.user_id == uid).order_by(NftClaim.id))
    return list(r.scalars())


def nft_state(claims: list[NftClaim]) -> str:
    """Итоговое состояние по всем заявкам юзера: APPROVED > DENIED > PENDING > REJECTED > NONE."""
    statuses = {c.status for c in claims}
    for s in ("APPROVED", "DENIED", "PENDING"):
        if s in statuses:
            return s
    return "REJECTED" if statuses else "NONE"


async def create_nft_claim(session: AsyncSession, uid: int) -> NftClaim:
    """Бросает ValueError с текстом для юзера, если подать заявку нельзя."""
    # лочим строку юзера, чтобы два быстрых нажатия не создали две заявки
    await session.execute(select(User).where(User.id == uid).with_for_update())
    state = nft_state(await get_nft_claims(session, uid))
    if state == "APPROVED":
        raise ValueError("Заявка уже одобрена")
    if state == "DENIED":
        raise ValueError("NFT увы, но вы не получите")
    if state == "PENDING":
        raise ValueError("Заявка уже на рассмотрении")
    c = NftClaim(user_id=uid, status="PENDING")
    session.add(c)
    await session.flush()
    return c


async def decide_nft_claim(session: AsyncSession, cid: int, action: str) -> Optional[NftClaim]:
    """action: approve / reject / deny. None — заявка не найдена или уже обработана."""
    r = await session.execute(select(NftClaim).where(NftClaim.id == cid).with_for_update())
    c = r.scalar_one_or_none()
    if not c or c.status != "PENDING":
        return None
    c.status = {"approve": "APPROVED", "reject": "REJECTED", "deny": "DENIED"}[action]
    c.decided_at = datetime.utcnow()
    return c


# ═══════════════════════════════════════════════════════
#  GAME SETTLE (новые игры: мины, рулетка, джокер, блэкджек, колесо)
# ═══════════════════════════════════════════════════════

def vip_mult(user: User) -> float:
    return VIP_MULT if user.is_vip else 1.0


def calc_payout(user: User, bet: int, base_mult: float) -> int:
    """VIP +5% только к выигрышу. При ×1 (возврат) и проигрыше бонуса нет."""
    if base_mult > 1.0:
        return int(bet * base_mult * vip_mult(user))
    return int(bet * base_mult)


async def settle_game(session: AsyncSession, user: User, game_type: str, bet: int,
                      result: str, base_mult: float) -> GameOut:
    """Бросает ValueError, если баланса не хватает на ставку (ничего не меняется)."""
    payout = calc_payout(user, bet, base_mult)
    return await _commit_game(session, user, game_type, bet, result, payout, won=payout > bet)
