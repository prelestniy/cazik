# [context: Linux x86_64, aiogram 3.13, Python 3.12, casino bot]
# *handlers — where user intent meets database reality*

from __future__ import annotations
import html
import json
import logging
from typing import Optional

from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, LabeledPrice, PreCheckoutQuery
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest

from sqlalchemy.ext.asyncio import AsyncSession

from config import ADMIN_USERNAMES, NFT_CONTACT
from models import User, SessionMaker
from services import (
    # user
    get_rank, get_leaderboard, get_transactions, find_user_admin, get_user_by_id,
    block_user, toggle_vip, admin_grant, admin_deduct,
    # game
    play_coinflip, play_dice, play_slots, game_stats,
    get_config, set_config, all_configs,
    # admin
    log_event, system_stats, recent_events,
    # task
    get_daily_tasks, advance_task, advance_top_rank, claim_reward, ensure_tasks,
    # payment
    SHOP_ITEMS, get_shop_item, process_payment,
    # fmt
    fmt_bal, fmt_winrate, progress_bar, fmt_time_left, fmt_username,
    # withdraw
    withdraw_min, cooldown_left, fmt_duration, create_withdrawal,
    decide_withdrawal, get_admin_users,
    # free nft
    create_nft_claim, decide_nft_claim, get_nft_claims, nft_state,
)
from keyboards import (
    main_menu, games_menu, back_main, coinflip_choice, dice_choice,
    shop_keyboard, admin_menu, user_manage, back_admin, withdraw_decision, nft_decision,
)
from states import CoinflipSt, DiceSt, SlotsSt, AdminSt, WithdrawSt, MinesSt, RouletteSt, JokerSt, BjSt, WheelSt
from keyboards import mines_board, roulette_kinds, bj_actions
from services import settle_game, calc_payout
from casino_games import (
    mines_place, mines_multiplier, MINES_SAFE, roulette_spin, roulette_win, RED_NUMBERS,
    joker_draw, joker_multiplier, new_deck, hand_value, is_blackjack, blackjack_settle,
    dealer_play, wheel_spin,
)

log = logging.getLogger(__name__)
router = Router()


# ═══════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════

def _is_admin(username: Optional[str]) -> bool:
    return (username or "").lower() in ADMIN_USERNAMES


async def _safe_edit(cq: CallbackQuery, text: str, **kwargs) -> None:
    try:
        await cq.message.edit_text(text, **kwargs)
    except TelegramBadRequest:
        pass


# ═══════════════════════════════════════════════════════
#  /start
# ═══════════════════════════════════════════════════════

@router.message(Command("start"))
async def cmd_start(message: Message, db_user: User) -> None:
    is_new = db_user.total_games == 0 and db_user.balance == 100
    if is_new:
        text = (
            f"👋 Добро пожаловать в <b>Казино - BOT</b>, <b>{db_user.first_name}</b>!\n\n"
            f"🎁 Тебе начислено <b>100 стартовых очков</b>.\n\n"
            f"Играй в мини-игры, выполняй задания и зарабатывай очки!\n\n"
            f"💰 Баланс: <b>{fmt_bal(db_user.balance)} очков</b>"
        )
    else:
        vip_line = "\n⭐ VIP-статус активен (+5% к выигрышам)" if db_user.is_vip else ""
        text = (
            f"👋 С возвращением, <b>{db_user.first_name}</b>!\n\n"
            f"💰 Баланс: <b>{fmt_bal(db_user.balance)} очков</b>{vip_line}"
        )
    await message.answer(text, parse_mode="HTML", reply_markup=main_menu())


# ═══════════════════════════════════════════════════════
#  MENU NAVIGATION
# ═══════════════════════════════════════════════════════

@router.callback_query(F.data == "menu:main")
async def cb_main_menu(cq: CallbackQuery, db_user: User, state: FSMContext) -> None:
    await state.clear()
    await cq.answer()
    vip_line = "\n⭐ VIP-статус активен" if db_user.is_vip else ""
    text = (
        f"🎰 <b>Главное меню</b>\n\n"
        f"💰 Баланс: <b>{fmt_bal(db_user.balance)} очков</b>{vip_line}"
    )
    await _safe_edit(cq, text, parse_mode="HTML", reply_markup=main_menu())


@router.callback_query(F.data == "menu:games")
async def cb_games(cq: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await cq.answer()
    await _safe_edit(cq, "🎮 <b>Выбери игру:</b>",
                     parse_mode="HTML", reply_markup=games_menu())


@router.callback_query(F.data == "menu:help")
async def cb_help(cq: CallbackQuery) -> None:
    await cq.answer()
    text = (
        "❓ <b>Помощь</b>\n\n"
        "🪙 <b>Монетка</b> — угадай орёл/решка. Победа ×2 (VIP ×2.1)\n"
        "🎲 <b>Кубик</b> — угадай точное число: ×5 (VIP ×5.25)\n"
        "   Соседнее число: ×1 (VIP ×1.05)\n"
        "🎰 <b>Слоты</b> — три одинаковых: ×10 (VIP ×10.5)\n"
        "   Два одинаковых: ×2 (VIP ×2.1)\n\n"
        "⭐ VIP-статус даёт +5% к каждому выигрышу\n"
        "📋 Задания обновляются каждый день в 00:00 UTC"
    )
    await _safe_edit(cq, text, parse_mode="HTML", reply_markup=back_main())


# ═══════════════════════════════════════════════════════
#  PROFILE
# ═══════════════════════════════════════════════════════

@router.callback_query(F.data == "menu:profile")
async def cb_profile(cq: CallbackQuery, db_user: User, session: AsyncSession) -> None:
    await cq.answer()
    rank = await get_rank(session, db_user)
    wr   = fmt_winrate(db_user.total_wins, db_user.total_games)
    vip  = "⭐ VIP" if db_user.is_vip else "—"
    text = (
        f"👤 <b>Профиль</b>\n\n"
        f"🔖 {fmt_username(db_user)}\n"
        f"💰 Баланс: <b>{fmt_bal(db_user.balance)} очков</b>\n"
        f"🏆 Место в рейтинге: <b>#{rank}</b>\n"
        f"🎮 Игр сыграно: <b>{db_user.total_games}</b>\n"
        f"✅ Побед: <b>{db_user.total_wins}</b> ({wr})\n"
        f"🔥 Серия побед: <b>{db_user.win_streak}</b> (макс: {db_user.max_win_streak})\n"
        f"⭐ VIP: {vip}\n"
        f"📅 В игре с: {db_user.created_at.strftime('%d.%m.%Y')}"
    )
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    b = InlineKeyboardBuilder()
    b.button(text="📜 История транзакций", callback_data="profile:txs")
    b.button(text="« Главное меню",         callback_data="menu:main")
    b.adjust(1)
    await _safe_edit(cq, text, parse_mode="HTML", reply_markup=b.as_markup())


@router.callback_query(F.data == "profile:txs")
async def cb_transactions(cq: CallbackQuery, db_user: User, session: AsyncSession) -> None:
    await cq.answer()
    txs = await get_transactions(session, db_user.id)
    if not txs:
        text = "📜 <b>История транзакций</b>\n\nПока пусто."
    else:
        lines = []
        for tx in txs:
            sign = "+" if tx.type in ("GAME_WIN", "ADMIN_GRANT", "TASK_REWARD", "PURCHASE") else "−"
            lines.append(f"{sign}{fmt_bal(tx.amount)} | {tx.type} | {tx.created_at.strftime('%d.%m %H:%M')}")
        text = "📜 <b>Последние транзакции</b>\n\n" + "\n".join(lines)
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    b = InlineKeyboardBuilder()
    b.button(text="« Назад", callback_data="menu:profile")
    await _safe_edit(cq, text, parse_mode="HTML", reply_markup=b.as_markup())


# ═══════════════════════════════════════════════════════
#  STATS
# ═══════════════════════════════════════════════════════

@router.callback_query(F.data == "menu:stats")
async def cb_stats(cq: CallbackQuery, db_user: User, session: AsyncSession) -> None:
    await cq.answer()
    rows = await game_stats(session, db_user.id)
    if not rows:
        text = "📊 <b>Статистика</b>\n\nЕщё нет сыгранных игр."
    else:
        lines = []
        for row in rows:
            wr = fmt_winrate(row.wins or 0, row.total or 0)
            profit = (row.total_payout or 0) - (row.total_bet or 0)
            sign   = "+" if profit >= 0 else ""
            lines.append(
                f"<b>{row.game_type}</b>: {row.total} игр | {row.wins}/{row.total} побед ({wr}) | "
                f"P/L: {sign}{fmt_bal(profit)}"
            )
        text = "📊 <b>Статистика по играм</b>\n\n" + "\n".join(lines)
    await _safe_edit(cq, text, parse_mode="HTML", reply_markup=back_main())


# ═══════════════════════════════════════════════════════
#  LEADERBOARD
# ═══════════════════════════════════════════════════════

@router.callback_query(F.data == "menu:leaderboard")
async def cb_leaderboard(cq: CallbackQuery, db_user: User, session: AsyncSession) -> None:
    await cq.answer()
    top = await get_leaderboard(session, 10)
    lines = []
    medals = ["🥇", "🥈", "🥉"]
    for i, u in enumerate(top):
        prefix = medals[i] if i < 3 else f"{i + 1}."
        name   = fmt_username(u)
        is_me  = " 👈" if u.id == db_user.id else ""
        lines.append(f"{prefix} {name} — {fmt_bal(u.total_wins)} побед{is_me}")
    rank = await get_rank(session, db_user)
    footer = f"\n\n📍 Ваша позиция: <b>#{rank}</b>"
    text = "🏆 <b>Таблица лидеров</b>\n\n" + ("\n".join(lines) or "Пока пусто.") + footer
    # update TOP_RANK task progress
    await advance_top_rank(session, db_user.id, rank)
    await session.commit()
    await _safe_edit(cq, text, parse_mode="HTML", reply_markup=back_main())


# ═══════════════════════════════════════════════════════
#  TASKS
# ═══════════════════════════════════════════════════════

@router.callback_query(F.data == "menu:tasks")
async def cb_tasks(cq: CallbackQuery, db_user: User, session: AsyncSession) -> None:
    await cq.answer()
    rows = await get_daily_tasks(session, db_user.id)
    await session.commit()
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    b = InlineKeyboardBuilder()
    lines = []
    for ut, t in rows:
        prog = min(ut.progress, t.target)
        bar  = progress_bar(prog, t.target)
        status = ""
        if ut.rewarded:
            status = "✅"
        elif ut.completed:
            status = "🎁"
            b.button(text=f"Забрать: {t.title} (+{fmt_bal(t.reward)})",
                     callback_data=f"task:claim:{ut.id}")
        else:
            status = f"{prog}/{t.target}"
        tl = fmt_time_left(ut.expires_at)
        lines.append(f"{status} <b>{t.title}</b>\n{t.description}\n{bar} ({tl})\n+{fmt_bal(t.reward)} очков")
    b.button(text="« Главное меню", callback_data="menu:main")
    b.adjust(1)
    text = "📋 <b>Ежедневные задания</b>\n\n" + "\n\n".join(lines)
    await _safe_edit(cq, text, parse_mode="HTML", reply_markup=b.as_markup())


@router.callback_query(F.data.startswith("task:claim:"))
async def cb_task_claim(cq: CallbackQuery, db_user: User, session: AsyncSession) -> None:
    ut_id = int(cq.data.split(":")[2])
    result = await claim_reward(session, db_user.id, ut_id)
    await session.commit()
    if result:
        await cq.answer(f"🎉 Получено {fmt_bal(result['reward'])} очков!", show_alert=True)
    else:
        await cq.answer("❌ Нельзя получить награду", show_alert=True)
    # Refresh tasks view
    rows = await get_daily_tasks(session, db_user.id)
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    b = InlineKeyboardBuilder()
    lines = []
    for ut, t in rows:
        prog = min(ut.progress, t.target)
        bar  = progress_bar(prog, t.target)
        status = ""
        if ut.rewarded:
            status = "✅"
        elif ut.completed:
            status = "🎁"
            b.button(text=f"Забрать: {t.title} (+{fmt_bal(t.reward)})",
                     callback_data=f"task:claim:{ut.id}")
        else:
            status = f"{prog}/{t.target}"
        tl = fmt_time_left(ut.expires_at)
        lines.append(f"{status} <b>{t.title}</b>\n{t.description}\n{bar} ({tl})\n+{fmt_bal(t.reward)} очков")
    b.button(text="« Главное меню", callback_data="menu:main")
    b.adjust(1)
    text = "📋 <b>Ежедневные задания</b>\n\n" + "\n\n".join(lines)
    await _safe_edit(cq, text, parse_mode="HTML", reply_markup=b.as_markup())


# ═══════════════════════════════════════════════════════
#  SHOP / BUY
# ═══════════════════════════════════════════════════════

@router.callback_query(F.data == "menu:buy")
async def cb_buy_menu(cq: CallbackQuery, db_user: User) -> None:
    await cq.answer()
    vip_line = "⭐ VIP-статус: активен\n" if db_user.is_vip else ""
    text = (
        f"💎 <b>Магазин очков</b>\n\n"
        f"💰 Ваш баланс: <b>{fmt_bal(db_user.balance)} очков</b>\n"
        f"{vip_line}\n"
        f"📌 Оплата через Telegram Stars (⭐)"
    )
    await _safe_edit(cq, text, parse_mode="HTML", reply_markup=shop_keyboard())


@router.callback_query(F.data.startswith("buy:"))
async def cb_buy_item(cq: CallbackQuery, bot: Bot) -> None:
    await cq.answer()
    item_id = cq.data.split(":", 1)[1]
    item = get_shop_item(item_id)
    if not item:
        return
    desc = "VIP-статус: +5% к каждому выигрышу" if item["is_vip"] else f"{item['points']} виртуальных очков"
    await bot.send_invoice(
        chat_id=cq.from_user.id,
        title=item["title"],
        description=desc,
        payload=json.dumps({"item_id": item_id}),
        currency="XTR",
        prices=[LabeledPrice(label=item["title"], amount=item["stars"])],
    )


@router.pre_checkout_query()
async def pre_checkout(pq: PreCheckoutQuery) -> None:
    await pq.answer(ok=True)


@router.message(F.successful_payment)
async def on_payment(message: Message, db_user: User, session: AsyncSession) -> None:
    payment  = message.successful_payment
    charge_id = payment.telegram_payment_charge_id
    try:
        payload = json.loads(payment.invoice_payload)
    except Exception:
        log.error("bad payment payload: %s", payment.invoice_payload)
        return
    item = get_shop_item(payload.get("item_id", ""))
    if not item:
        return
    ok = await process_payment(session, db_user, item, charge_id)
    await session.commit()
    if not ok:
        await message.answer("✅ Платёж уже обработан ранее.")
        return
    if item["is_vip"]:
        text = "⭐ <b>VIP-статус активирован!</b>\n\nТеперь вы получаете +5% к каждому выигрышу."
    else:
        text = (
            f"✅ <b>Успешная покупка!</b>\n\n"
            f"💰 Начислено: <b>{fmt_bal(item['points'])} очков</b>"
        )
    await message.answer(text, parse_mode="HTML")


# ═══════════════════════════════════════════════════════
#  COINFLIP
# ═══════════════════════════════════════════════════════

@router.callback_query(F.data == "game:coinflip")
async def cb_coinflip_start(cq: CallbackQuery, db_user: User, session: AsyncSession,
                             state: FSMContext) -> None:
    await cq.answer()
    mn = 1  # без минимума: только больше 0
    mx = None  # без максимума
    text = (
        f"🪙 <b>Монетка</b>\n\n"
        f"💰 Баланс: {fmt_bal(db_user.balance)} очков\n"
        f"📌 Ставка: от {mn} очков, без максимума\n"
        f"🏆 Победа: ×{'2.1' if db_user.is_vip else '2'}\n\n"
        f"Введи сумму ставки:"
    )
    await state.set_state(CoinflipSt.bet)
    await state.update_data(min_bet=mn, max_bet=mx)
    await _safe_edit(cq, text, parse_mode="HTML", reply_markup=back_main())


@router.message(CoinflipSt.bet)
async def msg_coinflip_bet(message: Message, db_user: User, state: FSMContext,
                            session: AsyncSession) -> None:
    data = await state.get_data()
    mn, mx = data["min_bet"], data["max_bet"]
    if not message.text or not message.text.strip().isdigit():
        await message.answer(f"❌ Введи целое число больше 0:")
        return
    bet = int(message.text.strip())
    if bet < mn:
        await message.answer(f"❌ Ставка должна быть не меньше {mn} очков:")
        return
    if db_user.balance < bet:
        await message.answer(f"❌ Недостаточно очков. Баланс: {fmt_bal(db_user.balance)}")
        return
    await state.update_data(bet=bet)
    await state.set_state(None)
    await message.answer(
        f"🪙 Ставка <b>{fmt_bal(bet)}</b> очков. Выбери сторону:",
        parse_mode="HTML",
        reply_markup=coinflip_choice()
    )


@router.callback_query(F.data.startswith("cf:"))
async def cb_coinflip_play(cq: CallbackQuery, db_user: User, session: AsyncSession,
                            state: FSMContext) -> None:
    data = await state.get_data()
    bet  = data.get("bet")
    if not bet:
        await cq.answer("❌ Сначала введи ставку через /start → Игры → Монетка")
        return
    choice = cq.data.split(":")[1]  # heads or tails
    await cq.answer()
    try:
        out = await play_coinflip(session, db_user, bet, choice)
        await session.commit()
    except ValueError as e:
        await cq.answer(str(e), show_alert=True)
        return

    emoji_map = {"heads": "🦅", "tails": "🪙"}
    result_emoji = emoji_map.get(out.result, "?")
    choice_emoji = emoji_map.get(choice, "?")
    if out.won:
        profit = out.payout - bet
        result_text = f"🎉 <b>Победа!</b> {result_emoji}\n+{fmt_bal(profit)} очков → итого {fmt_bal(out.payout)}"
    else:
        result_text = f"💀 <b>Проигрыш</b>\nВыпало {result_emoji}, ты ставил {choice_emoji}\n−{fmt_bal(bet)} очков"

    text = (
        f"🪙 <b>Монетка</b>\n\n"
        f"{result_text}\n\n"
        f"💰 Баланс: <b>{fmt_bal(out.new_balance)} очков</b>"
    )
    # advance tasks — same session; a loss resets WIN_STREAK progress
    await advance_task(session, db_user.id, "PLAY_GAMES")
    if out.won:
        await advance_task(session, db_user.id, "WIN_STREAK")
    else:
        await advance_task(session, db_user.id, "WIN_STREAK", inc=-999)
    await session.commit()

    await _safe_edit(cq, text, parse_mode="HTML", reply_markup=games_menu())


# ═══════════════════════════════════════════════════════
#  DICE
# ═══════════════════════════════════════════════════════

@router.callback_query(F.data == "game:dice")
async def cb_dice_start(cq: CallbackQuery, db_user: User, session: AsyncSession,
                         state: FSMContext) -> None:
    await cq.answer()
    mn = 1  # без минимума: только больше 0
    mx = None  # без максимума
    text = (
        f"🎲 <b>Кубик</b>\n\n"
        f"💰 Баланс: {fmt_bal(db_user.balance)} очков\n"
        f"📌 Ставка: от {mn} очков, без максимума\n"
        f"🏆 Точное попадание: ×{'5.25' if db_user.is_vip else '5'}\n"
        f"🎯 Соседнее число (±1): ×{'1.05' if db_user.is_vip else '1'}\n\n"
        f"Введи сумму ставки:"
    )
    await state.set_state(DiceSt.bet)
    await state.update_data(min_bet=mn, max_bet=mx)
    await _safe_edit(cq, text, parse_mode="HTML", reply_markup=back_main())


@router.message(DiceSt.bet)
async def msg_dice_bet(message: Message, db_user: User, state: FSMContext,
                        session: AsyncSession) -> None:
    data = await state.get_data()
    mn, mx = data["min_bet"], data["max_bet"]
    if not message.text or not message.text.strip().isdigit():
        await message.answer(f"❌ Введи целое число больше 0:")
        return
    bet = int(message.text.strip())
    if bet < mn:
        await message.answer(f"❌ Ставка должна быть не меньше {mn} очков:")
        return
    if db_user.balance < bet:
        await message.answer(f"❌ Недостаточно очков. Баланс: {fmt_bal(db_user.balance)}")
        return
    await state.update_data(bet=bet)
    await state.set_state(None)
    await message.answer(
        f"🎲 Ставка <b>{fmt_bal(bet)}</b>. Выбери число от 1 до 6:",
        parse_mode="HTML",
        reply_markup=dice_choice(bet)
    )


@router.callback_query(F.data.startswith("dice:"))
async def cb_dice_play(cq: CallbackQuery, db_user: User, session: AsyncSession) -> None:
    parts = cq.data.split(":")
    guess = int(parts[1])
    bet   = int(parts[2])
    await cq.answer()
    try:
        out = await play_dice(session, db_user, bet, guess)
        await session.commit()
    except ValueError as e:
        await cq.answer(str(e), show_alert=True)
        return

    nums  = out.result  # "roll:4,guess:3"
    rpart = dict(p.split(":") for p in nums.split(","))
    roll  = int(rpart["roll"])

    if out.won and out.payout >= bet * 4:
        result_text = f"🎯 <b>Точное попадание!</b> Выпало {roll}\n+{fmt_bal(out.payout - bet)} очков"
    elif out.won:
        result_text = f"🎯 <b>Соседнее число!</b> Выпало {roll}, угадал {guess}\n+{fmt_bal(out.payout - bet)} очков"
    else:
        result_text = f"💀 <b>Промах</b>\nВыпало {roll}, ты угадывал {guess}\n−{fmt_bal(bet)} очков"

    text = (
        f"🎲 <b>Кубик</b>\n\n"
        f"{result_text}\n\n"
        f"💰 Баланс: <b>{fmt_bal(out.new_balance)} очков</b>"
    )
    await advance_task(session, db_user.id, "PLAY_GAMES")
    if out.won:
        await advance_task(session, db_user.id, "WIN_STREAK")
    else:
        await advance_task(session, db_user.id, "WIN_STREAK", inc=-999)  # reset streak
    await session.commit()

    await _safe_edit(cq, text, parse_mode="HTML", reply_markup=games_menu())


# ═══════════════════════════════════════════════════════
#  SLOTS
# ═══════════════════════════════════════════════════════

@router.callback_query(F.data == "game:slots")
async def cb_slots_start(cq: CallbackQuery, db_user: User, session: AsyncSession,
                          state: FSMContext) -> None:
    await cq.answer()
    mn = 1  # без минимума: только больше 0
    mx = None  # без максимума
    text = (
        f"🎰 <b>Слоты</b>\n\n"
        f"💰 Баланс: {fmt_bal(db_user.balance)} очков\n"
        f"📌 Ставка: от {mn} очков, без максимума\n"
        f"🏆 Три одинаковых: ×{'10.5' if db_user.is_vip else '10'}\n"
        f"🎯 Два одинаковых: ×{'2.1' if db_user.is_vip else '2'}\n\n"
        f"Введи сумму ставки:"
    )
    await state.set_state(SlotsSt.bet)
    await state.update_data(min_bet=mn, max_bet=mx)
    await _safe_edit(cq, text, parse_mode="HTML", reply_markup=back_main())


@router.message(SlotsSt.bet)
async def msg_slots_bet(message: Message, db_user: User, state: FSMContext,
                         session: AsyncSession) -> None:
    data = await state.get_data()
    mn, mx = data["min_bet"], data["max_bet"]
    if not message.text or not message.text.strip().isdigit():
        await message.answer(f"❌ Введи целое число больше 0:")
        return
    bet = int(message.text.strip())
    if bet < mn:
        await message.answer(f"❌ Ставка должна быть не меньше {mn} очков:")
        return
    if db_user.balance < bet:
        await message.answer(f"❌ Недостаточно очков. Баланс: {fmt_bal(db_user.balance)}")
        return
    await state.set_state(None)
    # Spin immediately
    try:
        out = await play_slots(session, db_user, bet)
        await session.commit()
    except ValueError as e:
        await message.answer(f"❌ {e}")
        return

    reels = " ".join(out.reels or ["?", "?", "?"])
    if out.won and out.payout >= bet * 8:
        result_text = f"🎰 <b>ДЖЕКПОТ!</b>\n{reels}\n+{fmt_bal(out.payout - bet)} очков"
    elif out.won:
        result_text = f"🎯 <b>Два одинаковых!</b>\n{reels}\n+{fmt_bal(out.payout - bet)} очков"
    else:
        result_text = f"💀 <b>Не повезло</b>\n{reels}\n−{fmt_bal(bet)} очков"

    text = (
        f"🎰 <b>Слоты</b>\n\n"
        f"{result_text}\n\n"
        f"💰 Баланс: <b>{fmt_bal(out.new_balance)} очков</b>"
    )
    await advance_task(session, db_user.id, "PLAY_GAMES")
    if out.won:
        await advance_task(session, db_user.id, "WIN_STREAK")
    else:
        await advance_task(session, db_user.id, "WIN_STREAK", inc=-999)  # reset streak
    await session.commit()

    await message.answer(text, parse_mode="HTML", reply_markup=games_menu())


# ═══════════════════════════════════════════════════════
#  ADMIN PANEL
# ═══════════════════════════════════════════════════════

@router.message(Command("admin"))
async def cmd_admin(message: Message) -> None:
    if not _is_admin(message.from_user.username if message.from_user else None):
        await message.answer("⛔ Нет доступа.")
        return
    await message.answer("🛠 <b>Панель администратора</b>\n\nВыберите действие:",
                         parse_mode="HTML", reply_markup=admin_menu())


@router.callback_query(F.data == "admin:main")
async def cb_admin_main(cq: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(cq.from_user.username):
        await cq.answer("⛔"); return
    await state.clear()
    await cq.answer()
    await _safe_edit(cq, "🛠 <b>Панель администратора</b>\n\nВыберите действие:",
                     parse_mode="HTML", reply_markup=admin_menu())


@router.callback_query(F.data == "admin:stats")
async def cb_admin_stats(cq: CallbackQuery, session: AsyncSession) -> None:
    if not _is_admin(cq.from_user.username):
        await cq.answer("⛔"); return
    await cq.answer()
    s = await system_stats(session)
    text = (
        f"📊 <b>Системная статистика</b>\n\n"
        f"👥 Всего пользователей: <b>{s['total_users']}</b>\n"
        f"🟢 Активных за 24ч: <b>{s['active_users_24h']}</b>\n"
        f"🎮 Всего игр: <b>{s['total_games']}</b>\n"
        f"🏆 Топ игра: <b>{s['top_game']}</b>"
    )
    await _safe_edit(cq, text, parse_mode="HTML", reply_markup=back_admin())


@router.callback_query(F.data == "admin:events")
async def cb_admin_events(cq: CallbackQuery, session: AsyncSession) -> None:
    if not _is_admin(cq.from_user.username):
        await cq.answer("⛔"); return
    await cq.answer()
    evs = await recent_events(session, 15)
    lines = []
    for ev, uname, fname in evs:
        name = f"@{uname}" if uname else (fname or "system")
        t    = ev.created_at.strftime("%H:%M:%S")
        lines.append(f"[{t}] <code>{ev.event_type}</code> — {name}")
    text = "📋 <b>Последние события</b>\n\n" + ("\n".join(lines) or "Пусто.")
    await _safe_edit(cq, text, parse_mode="HTML", reply_markup=back_admin())


@router.callback_query(F.data == "admin:configs")
async def cb_admin_configs(cq: CallbackQuery, session: AsyncSession) -> None:
    if not _is_admin(cq.from_user.username):
        await cq.answer("⛔"); return
    await cq.answer()
    cfgs = await all_configs(session)
    lines = [f"<code>{c.key}</code> = <b>{c.value}</b>" for c in cfgs]
    text = (
        "⚙️ <b>Конфигурация игр</b>\n\n"
        + "\n".join(lines)
        + "\n\nДля изменения: <code>/setconfig ключ значение</code>"
    )
    await _safe_edit(cq, text, parse_mode="HTML", reply_markup=back_admin())


@router.message(Command("setconfig"))
async def cmd_setconfig(message: Message, session: AsyncSession) -> None:
    if not _is_admin(message.from_user.username if message.from_user else None):
        await message.answer("⛔ Нет доступа."); return
    args = (message.text or "").split(None, 2)[1:]
    if len(args) < 2:
        await message.answer("Использование: /setconfig ключ значение"); return
    key, value = args[0], args[1]
    await set_config(session, key, value)
    await session.commit()
    if message.from_user:
        await log_event(session, "ADMIN_CONFIG_CHANGE", message.from_user.id,
                        {"key": key, "value": value})
        await session.commit()
    await message.answer(f"✅ <code>{key}</code> = <b>{value}</b>", parse_mode="HTML")


@router.callback_query(F.data == "admin:find_user")
async def cb_admin_find(cq: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(cq.from_user.username):
        await cq.answer("⛔"); return
    await cq.answer()
    await state.set_state(AdminSt.find_user)
    await cq.message.answer("🔍 Введите Telegram ID, @username или внутренний ID:")


@router.message(AdminSt.find_user)
async def msg_admin_find(message: Message, state: FSMContext, session: AsyncSession) -> None:
    if not _is_admin(message.from_user.username if message.from_user else None):
        return
    q = (message.text or "").strip()
    await state.clear()
    found = await find_user_admin(session, q)
    if not found:
        await message.answer("❌ Пользователь не найден.")
        return
    info = (
        f"👤 <b>Пользователь</b>\n\n"
        f"🆔 ID: <code>{found.id}</code>\n"
        f"📱 Telegram ID: <code>{found.telegram_id}</code>\n"
        f"👤 Имя: {found.first_name} {found.last_name or ''}\n"
        f"🔖 Username: {'@' + found.username if found.username else 'нет'}\n"
        f"💰 Баланс: <b>{fmt_bal(found.balance)}</b>\n"
        f"🎮 Игр: {found.total_games} | Побед: {found.total_wins}\n"
        f"⭐ VIP: {'Да' if found.is_vip else 'Нет'}\n"
        f"🚫 Блок: {'Да' if found.is_blocked else 'Нет'}\n"
        f"📅 Регистрация: {found.created_at.strftime('%d.%m.%Y')}"
    )
    await message.answer(info, parse_mode="HTML",
                         reply_markup=user_manage(found.id, found.is_blocked, found.is_vip))


@router.callback_query(F.data.startswith("admin:block:"))
async def cb_admin_block(cq: CallbackQuery, session: AsyncSession) -> None:
    if not _is_admin(cq.from_user.username):
        await cq.answer("⛔"); return
    parts  = cq.data.split(":")
    uid, v = int(parts[2]), bool(int(parts[3]))
    try:
        updated = await block_user(session, uid, v)
        await log_event(session, "ADMIN_BLOCK_TOGGLE", cq.from_user.id, {"uid": uid, "blocked": v})
        await session.commit()
        await cq.answer("🚫 Заблокирован" if v else "✅ Разблокирован", show_alert=True)
        try:
            await cq.message.edit_reply_markup(
                reply_markup=user_manage(uid, updated.is_blocked, updated.is_vip))
        except TelegramBadRequest:
            pass
    except ValueError as e:
        await session.rollback()
        await cq.answer(f"❌ {e}", show_alert=True)
    except Exception as e:
        await session.rollback()
        log.error("block_user failed uid=%s: %s", uid, e)
        await cq.answer("❌ Ошибка при блокировке", show_alert=True)


@router.callback_query(F.data.startswith("admin:vip:"))
async def cb_admin_vip(cq: CallbackQuery, session: AsyncSession) -> None:
    if not _is_admin(cq.from_user.username):
        await cq.answer("⛔"); return
    parts  = cq.data.split(":")
    uid, v = int(parts[2]), bool(int(parts[3]))
    try:
        updated = await toggle_vip(session, uid, v)
        await log_event(session, "ADMIN_VIP_TOGGLE", cq.from_user.id, {"uid": uid, "vip": v})
        await session.commit()
        await cq.answer("⭐ VIP выдан" if v else "❌ VIP снят", show_alert=True)
        try:
            await cq.message.edit_reply_markup(
                reply_markup=user_manage(uid, updated.is_blocked, updated.is_vip))
        except TelegramBadRequest:
            pass
    except ValueError as e:
        await session.rollback()
        await cq.answer(f"❌ {e}", show_alert=True)
    except Exception as e:
        await session.rollback()
        log.error("toggle_vip failed uid=%s: %s", uid, e)
        await cq.answer("❌ Ошибка при изменении VIP", show_alert=True)


@router.callback_query(F.data.startswith("admin:grant:"))
async def cb_admin_grant_start(cq: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(cq.from_user.username):
        await cq.answer("⛔"); return
    await cq.answer()
    uid = int(cq.data.split(":")[2])
    await state.set_state(AdminSt.grant_amount)
    await state.update_data(target_uid=uid)
    await cq.message.answer(f"➕ Введите количество очков для начисления пользователю #{uid}:")


@router.message(AdminSt.grant_amount)
async def msg_admin_grant(message: Message, state: FSMContext, session: AsyncSession) -> None:
    if not _is_admin(message.from_user.username if message.from_user else None):
        return
    data = await state.get_data()
    uid  = data["target_uid"]
    txt  = (message.text or "").strip()
    if not txt.isdigit() or int(txt) <= 0:
        await message.answer("❌ Введи положительное число:"); return
    amount = int(txt)
    await state.clear()
    await admin_grant(session, uid, amount, message.from_user.id)
    await log_event(session, "ADMIN_GRANT", message.from_user.id, {"uid": uid, "amount": amount})
    await session.commit()
    await message.answer(f"✅ Начислено {fmt_bal(amount)} очков пользователю #{uid}")


@router.callback_query(F.data.startswith("admin:deduct:"))
async def cb_admin_deduct_start(cq: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(cq.from_user.username):
        await cq.answer("⛔"); return
    await cq.answer()
    uid = int(cq.data.split(":")[2])
    await state.set_state(AdminSt.deduct_amount)
    await state.update_data(target_uid=uid)
    await cq.message.answer(f"➖ Введите количество очков для снятия с пользователя #{uid}:")


@router.message(AdminSt.deduct_amount)
async def msg_admin_deduct(message: Message, state: FSMContext, session: AsyncSession) -> None:
    if not _is_admin(message.from_user.username if message.from_user else None):
        return
    data = await state.get_data()
    uid  = data["target_uid"]
    txt  = (message.text or "").strip()
    if not txt.isdigit() or int(txt) <= 0:
        await message.answer("❌ Введи положительное число:"); return
    amount = int(txt)
    await state.clear()
    await admin_deduct(session, uid, amount, message.from_user.id)
    await log_event(session, "ADMIN_DEDUCT", message.from_user.id, {"uid": uid, "amount": amount})
    await session.commit()
    await message.answer(f"✅ Снято {fmt_bal(amount)} очков с пользователя #{uid}")


@router.callback_query(F.data == "admin:broadcast")
async def cb_admin_broadcast_start(cq: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(cq.from_user.username):
        await cq.answer("⛔"); return
    await cq.answer()
    await state.set_state(AdminSt.broadcast)
    await cq.message.answer(
        "📢 Введите сообщение для рассылки всем пользователям.\n"
        "Поддерживается HTML. /cancel для отмены."
    )


@router.message(AdminSt.broadcast)
async def msg_admin_broadcast(message: Message, bot: Bot, state: FSMContext,
                               session: AsyncSession) -> None:
    if not _is_admin(message.from_user.username if message.from_user else None):
        return
    if message.text == "/cancel":
        await state.clear()
        await message.answer("❌ Отменено.")
        return
    text = message.text or message.caption or ""
    await state.clear()
    await message.answer("📤 Начинаю рассылку...")
    from sqlalchemy import select as sa_select
    from models import User as UserModel
    r = await session.execute(sa_select(UserModel).where(UserModel.is_blocked == False))
    users = list(r.scalars())
    sent = failed = 0
    for u in users:
        try:
            await bot.send_message(u.telegram_id, text, parse_mode="HTML")
            sent += 1
        except Exception:
            failed += 1
    await log_event(session, "BROADCAST", message.from_user.id if message.from_user else None,
                    {"sent": sent, "failed": failed})
    await session.commit()
    await message.answer(f"✅ Рассылка завершена\n📤 Отправлено: {sent}\n❌ Ошибок: {failed}")


# ═══════════════════════════════════════════════════════
#  FALLBACK
# ═══════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════
#  WITHDRAW (вывод очков, одобряет админ)
# ═══════════════════════════════════════════════════════

@router.callback_query(F.data == "menu:withdraw")
async def cb_withdraw_start(cq: CallbackQuery, db_user: User, session: AsyncSession,
                            state: FSMContext) -> None:
    await cq.answer()
    await state.clear()
    left = await cooldown_left(session, db_user.id)
    if left:
        text = (
            "💸 <b>Вывод очков</b>\n\n"
            f"⏳ Заявка уже подана сегодня. Следующая будет доступна через <b>{fmt_duration(left)}</b>"
        )
        await _safe_edit(cq, text, parse_mode="HTML", reply_markup=back_main())
        return
    mn = withdraw_min(db_user)
    text = (
        "💸 <b>Вывод очков</b>\n\n"
        f"💰 Баланс: <b>{fmt_bal(db_user.balance)} очков</b>\n"
        f"📌 Минимум: {fmt_bal(mn)} очков{' (VIP)' if db_user.is_vip else ''}\n"
        "📅 Одна заявка в сутки, максимума нет\n\n"
        "Введи сумму для вывода:"
    )
    await state.set_state(WithdrawSt.amount)
    await _safe_edit(cq, text, parse_mode="HTML", reply_markup=back_main())


@router.message(WithdrawSt.amount)
async def msg_withdraw_amount(message: Message, bot: Bot, db_user: User, state: FSMContext,
                              session: AsyncSession) -> None:
    txt = (message.text or "").strip()
    if not txt.isdigit():
        await message.answer("❌ Введи целое число очков:")
        return
    try:
        w = await create_withdrawal(session, db_user.id, int(txt))
    except ValueError as e:
        # ничего не менялось до raise, откат не нужен (и опасен: сбрасывает db_user)
        await message.answer(f"❌ {e}")
        if "в сутки" in str(e):
            await state.clear()
        return

    # уведомляем админов с кнопками; если никто не получил — заявку не создаём
    text = (
        f"💸 <b>Заявка на вывод #{w.id}</b>\n"
        f"👤 {html.escape(fmt_username(db_user))} (tg: <code>{db_user.telegram_id}</code>)\n"
        f"💰 Сумма: <b>{fmt_bal(w.amount)} очков</b>\n"
        f"⭐ VIP: {'да' if db_user.is_vip else 'нет'}"
    )
    sent = 0
    for adm in await get_admin_users(session):
        try:
            await bot.send_message(adm.telegram_id, text, parse_mode="HTML",
                                   reply_markup=withdraw_decision(w.id))
            sent += 1
        except Exception as exc:
            log.warning("withdraw notify failed admin=%s: %s", adm.telegram_id, exc)

    if sent == 0:
        await session.rollback()
        await state.clear()
        await message.answer("❌ Заявка не отправлена: админы недоступны. Очки не списаны, попробуй позже.")
        return

    await session.commit()
    await state.clear()
    await message.answer(
        f"✅ Заявка #{w.id} на <b>{fmt_bal(w.amount)} очков</b> отправлена.\n"
        "Ответ придёт сюда после проверки.",
        parse_mode="HTML", reply_markup=back_main(),
    )


@router.callback_query(F.data.startswith("wd:"))
async def cb_withdraw_decide(cq: CallbackQuery, bot: Bot, session: AsyncSession) -> None:
    if not _is_admin(cq.from_user.username):
        await cq.answer("⛔"); return
    _, action, wid_s = cq.data.split(":")
    approve = action == "approve"
    w = await decide_withdrawal(session, int(wid_s), approve)
    if w is None:
        await session.rollback()
        await cq.answer("Заявка уже обработана", show_alert=True)
        try:
            await cq.message.edit_reply_markup(reply_markup=None)
        except TelegramBadRequest:
            pass
        return

    user = await get_user_by_id(session, w.user_id)
    await log_event(session, "WITHDRAW_APPROVED" if approve else "WITHDRAW_REJECTED",
                    cq.from_user.id, {"wid": w.id, "amount": w.amount})
    await session.commit()

    # убираем кнопки и дописываем решение в сообщение админа
    verdict = "✅ Одобрено" if approve else "❌ Отклонено, очки возвращены"
    base = html.escape(cq.message.text or "")
    try:
        await cq.message.edit_text(f"{base}\n\n{verdict} @{cq.from_user.username or cq.from_user.id}",
                                   parse_mode="HTML")
    except TelegramBadRequest:
        pass

    # ответ юзеру
    try:
        if approve:
            msg = f"✅ Вывод <b>{fmt_bal(w.amount)} очков</b> (заявка #{w.id}) одобрен."
        else:
            msg = (f"❌ Заявка #{w.id} на вывод отклонена. "
                   f"<b>{fmt_bal(w.amount)} очков</b> вернулись на баланс.")
        await bot.send_message(user.telegram_id, msg, parse_mode="HTML")
    except Exception as exc:
        log.warning("withdraw notify user failed: %s", exc)
    await cq.answer("Готово")


# ═══════════════════════════════════════════════════════
#  FREE NFT (админ одобряет; после отказа можно подать снова)
# ═══════════════════════════════════════════════════════

async def _notify_admins(bot: Bot, session: AsyncSession, text: str, markup) -> int:
    """Отправляет сообщение всем админам, возвращает сколько доставлено."""
    sent = 0
    for adm in await get_admin_users(session):
        try:
            await bot.send_message(adm.telegram_id, text, parse_mode="HTML", reply_markup=markup)
            sent += 1
        except Exception as exc:
            log.warning("notify admin failed admin=%s: %s", adm.telegram_id, exc)
    return sent


def _nft_contact() -> str:
    c = NFT_CONTACT.strip()
    return c if c.startswith("@") else f"@{c}"


@router.callback_query(F.data == "menu:nft")
async def cb_nft_start(cq: CallbackQuery, bot: Bot, db_user: User, session: AsyncSession) -> None:
    claims = await get_nft_claims(session, db_user.id)
    state = nft_state(claims)

    # ответы без новых сообщений админам
    if state == "APPROVED":
        text = ("🎁 <b>Бесплатный NFT</b>\n\n✅ Заявка одобрена. "
                f"Напишите сюда за своим бесплатным NFT: {_nft_contact()}")
        await cq.answer()
        await _safe_edit(cq, text, parse_mode="HTML", reply_markup=back_main())
        return
    if state == "DENIED":
        await cq.answer()
        await _safe_edit(cq, "🎁 <b>Бесплатный NFT</b>\n\n🚫 NFT увы, но вы не получите.",
                         parse_mode="HTML", reply_markup=back_main())
        return
    if state == "PENDING":
        await cq.answer()
        await _safe_edit(cq, "🎁 <b>Бесплатный NFT</b>\n\n⏳ Заявка на рассмотрении. Ответ придёт сюда после проверки.",
                         parse_mode="HTML", reply_markup=back_main())
        return

    # новая заявка или подача после отказа
    resubmit = bool(claims)
    try:
        claim = await create_nft_claim(session, db_user.id)
    except ValueError as e:
        await cq.answer(str(e), show_alert=True)
        return

    admin_text = (
        f"🎁 <b>Заявка на бесплатный NFT #{claim.id}</b>"
        f"{' (повторная)' if resubmit else ''}\n"
        f"👤 {html.escape(fmt_username(db_user))} (tg: <code>{db_user.telegram_id}</code>)"
    )
    if await _notify_admins(bot, session, admin_text, nft_decision(claim.id, allow_deny=resubmit)) == 0:
        await session.rollback()  # заявку не создаём, чтобы юзер мог попробовать позже
        await cq.answer("❌ Заявка не отправлена: админы недоступны. Попробуй позже.", show_alert=True)
        return

    await session.commit()
    await cq.answer()
    await _safe_edit(
        cq,
        "🎁 <b>Бесплатный NFT</b>\n\n✅ Заявка отправлена. Ответ придёт сюда после проверки.",
        parse_mode="HTML", reply_markup=back_main(),
    )


@router.callback_query(F.data.startswith("nft:"))
async def cb_nft_decide(cq: CallbackQuery, bot: Bot, session: AsyncSession) -> None:
    if not _is_admin(cq.from_user.username):
        await cq.answer("⛔"); return
    _, action, cid_s = cq.data.split(":")
    if action not in ("approve", "reject", "deny"):
        await cq.answer("❓ Неизвестное действие"); return

    claim = await decide_nft_claim(session, int(cid_s), action)
    if claim is None:
        await session.rollback()
        await cq.answer("Заявка уже обработана", show_alert=True)
        try:
            await cq.message.edit_reply_markup(reply_markup=None)
        except TelegramBadRequest:
            pass
        return

    user = await get_user_by_id(session, claim.user_id)
    await log_event(session, f"NFT_{action.upper()}", cq.from_user.id, {"cid": claim.id})
    await session.commit()

    verdict = {"approve": "✅ Одобрено", "reject": "❌ Отклонено",
               "deny": "🚫 Отказано полностью"}[action]
    base = html.escape(cq.message.text or "")
    try:
        await cq.message.edit_text(f"{base}\n\n{verdict} @{cq.from_user.username or cq.from_user.id}",
                                   parse_mode="HTML")
    except TelegramBadRequest:
        pass

    user_msgs = {
        "approve": f"Напишите сюда за своим бесплатным NFT: {_nft_contact()}",
        "reject": "❌ Заявка на бесплатный NFT отклонена. Можно подать снова.",
        "deny": "NFT увы, но вы не получите.",
    }
    try:
        await bot.send_message(user.telegram_id, user_msgs[action])
    except Exception as exc:
        log.warning("nft notify user failed: %s", exc)
    await cq.answer("Готово")


# ═══════════════════════════════════════════════════════
#  NEW GAMES: мины, рулетка, джокер, блэкджек, колесо
#  Правила и множители — в casino_games.py. Ставка от NEW_MIN_BET, без максимума.
# ═══════════════════════════════════════════════════════

NEW_MIN_BET = 100

RULES = {
    "mines": "Поле 5×5, 3 мины. Открывай клетки: каждая безопасная поднимает множитель. "
             "Забрать можно в любой момент. На мине ставка сгорает.",
    "roulette": "Числа 0–36. Цвет или чётное/нечётное ×2, конкретное число ×36. "
                "0 зелёный: на цвет и чётность ставка проигрывает.",
    "joker": "Одна карта из 53 (с джокером). Джокер ×3, J/Q/K/A ×2, остальные проигрыш.",
    "blackjack": "Дилер берёт до 17. Победа ×2, блэкджек ×2.5, ничья — возврат ставки. Перебор — проигрыш.",
    "wheel": "8 секторов от ×0 до ×10. Сектор выпадает случайно, с весом.",
}


def _bet_prompt(title: str, key: str, db_user: User) -> str:
    return (f"{title}\n\n{RULES[key]}\n\n"
            f"💰 Баланс: <b>{fmt_bal(db_user.balance)} очков</b>\n"
            f"📌 Ставка: от {NEW_MIN_BET}, без максимума\n\n"
            "Введи сумму ставки:")


def _check_bet(text: Optional[str], balance: int) -> tuple[Optional[int], Optional[str]]:
    t = (text or "").strip()
    if not t.isdigit():
        return None, f"❌ Введи целое число, от {NEW_MIN_BET}:"
    bet = int(t)
    if bet < NEW_MIN_BET:
        return None, f"❌ Минимальная ставка {NEW_MIN_BET} очков:"
    if bet > balance:
        return None, f"❌ Недостаточно очков. Баланс: {fmt_bal(balance)}"
    return bet, None


async def _start_bet(cq: CallbackQuery, db_user: User, state: FSMContext,
                     key: str, title: str, bet_state) -> None:
    await cq.answer()
    await state.clear()
    await state.set_state(bet_state)
    await _safe_edit(cq, _bet_prompt(title, key, db_user), parse_mode="HTML", reply_markup=back_main())


async def _after_game(session: AsyncSession, uid: int, won: bool) -> None:
    await advance_task(session, uid, "PLAY_GAMES")
    if won:
        await advance_task(session, uid, "WIN_STREAK")
    else:
        await advance_task(session, uid, "WIN_STREAK", inc=-999)  # проигрыш сбрасывает серию


async def _settle_report(session: AsyncSession, db_user: User, bet: int, game_type: str,
                         base_mult: float, result: str, title: str, detail: str) -> str:
    """Расчёт ставки + текст результата. При ошибке баланса возвращает текст ошибки."""
    try:
        out = await settle_game(session, db_user, game_type, bet, result, base_mult)
    except ValueError as e:
        return f"❌ {e}"
    await _after_game(session, db_user.id, out.won)
    await session.commit()
    if out.won:
        head = f"🎉 <b>Выиграл!</b> +{fmt_bal(out.payout - bet)} очков"
    elif out.payout == bet:
        head = "🤝 <b>Ничья</b>, ставка возвращена"
    else:
        head = f"💀 <b>Проигрыш</b> −{fmt_bal(bet)} очков"
    return f"{title}\n\n{detail}\n\n{head}\n💰 Баланс: <b>{fmt_bal(out.new_balance)} очков</b>"


# ─── МИНЫ ───────────────────────────────────────────────

def _mines_text(bet: int, opened: list[int], db_user: User) -> str:
    k = len(opened)
    mult = mines_multiplier(k)
    text = (f"💣 <b>Мины</b>\nСтавка: {fmt_bal(bet)}\n"
            f"Открыто безопасных: {k}/{MINES_SAFE}\nМножитель: ×{mult:.2f}")
    if k:
        text += f"\nЗабрать: <b>{fmt_bal(calc_payout(db_user, bet, mult))}</b>"
    return text


@router.callback_query(F.data == "game:mines")
async def cb_mines_start(cq: CallbackQuery, db_user: User, state: FSMContext) -> None:
    await _start_bet(cq, db_user, state, "mines", "💣 <b>Мины</b>", MinesSt.bet)


@router.message(MinesSt.bet)
async def msg_mines_bet(message: Message, db_user: User, state: FSMContext) -> None:
    bet, err = _check_bet(message.text, db_user.balance)
    if err:
        await message.answer(err)
        return
    await state.set_state(MinesSt.playing)
    await state.update_data(bet=bet, mines=mines_place(), opened=[])
    await message.answer(_mines_text(bet, [], db_user), parse_mode="HTML",
                         reply_markup=mines_board([], None, None))


@router.callback_query(F.data.startswith("mines:"))
async def cb_mines_play(cq: CallbackQuery, db_user: User, session: AsyncSession, state: FSMContext) -> None:
    if await state.get_state() != MinesSt.playing.state:
        await cq.answer("Игра уже закончилась", show_alert=True)
        return
    parts = cq.data.split(":")
    if parts[1] == "noop":
        await cq.answer()
        return
    data = await state.get_data()
    bet, mines, opened = data["bet"], data["mines"], list(data["opened"])

    if parts[1] == "cash":
        if not opened:
            await cq.answer("Сначала открой клетку", show_alert=True)
            return
        await cq.answer()
        await _mines_end(cq, session, db_user, state, bet, opened, mines, win=True)
        return

    i = int(parts[2])
    if i in opened:
        await cq.answer()
        return
    await cq.answer()
    if i in mines:
        await _mines_end(cq, session, db_user, state, bet, opened, mines, win=False)
        return

    opened.append(i)
    if len(opened) == MINES_SAFE:  # все безопасные открыты — авто-забор
        await _mines_end(cq, session, db_user, state, bet, opened, mines, win=True)
        return
    await state.update_data(opened=opened)
    pay = calc_payout(db_user, bet, mines_multiplier(len(opened)))
    await _safe_edit(cq, _mines_text(bet, opened, db_user), parse_mode="HTML",
                     reply_markup=mines_board(opened, None, f"💰 Забрать {fmt_bal(pay)}"))


async def _mines_end(cq: CallbackQuery, session: AsyncSession, db_user: User, state: FSMContext,
                     bet: int, opened: list[int], mines: list[int], win: bool) -> None:
    k = len(opened)
    base = mines_multiplier(k) if win else 0.0
    result = f"cash:{k}" if win else f"boom:{k}"
    try:
        out = await settle_game(session, db_user, "MINES", bet, result, base)
    except ValueError as e:
        await state.clear()
        await _safe_edit(cq, f"❌ {e}", reply_markup=back_main())
        return
    await _after_game(session, db_user.id, out.won)
    await session.commit()
    await state.clear()
    if win:
        head = f"💎 <b>Забрал!</b> ×{base:.2f}, +{fmt_bal(out.payout - bet)} очков"
    else:
        head = f"💥 <b>Мина!</b> Ставка {fmt_bal(bet)} сгорела"
    text = f"💣 <b>Мины</b>\n\n{head}\n💰 Баланс: <b>{fmt_bal(out.new_balance)} очков</b>"
    await _safe_edit(cq, text, parse_mode="HTML", reply_markup=mines_board(opened, mines, None))


# ─── РУЛЕТКА ────────────────────────────────────────────

async def _roulette_play(session: AsyncSession, db_user: User, bet: int, kind: str,
                         pick: Optional[int]) -> str:
    spin = roulette_spin()
    _, mult = roulette_win(kind, pick, spin)
    color = "🟢" if spin == 0 else ("🔴" if spin in RED_NUMBERS else "⚫")
    return await _settle_report(session, db_user, bet, "ROULETTE", mult, f"{spin}:{kind}",
                                "🎡 <b>Рулетка</b>", f"Выпало: {color} <b>{spin}</b>")


@router.callback_query(F.data == "game:roulette")
async def cb_roulette_start(cq: CallbackQuery, db_user: User, state: FSMContext) -> None:
    await _start_bet(cq, db_user, state, "roulette", "🎡 <b>Рулетка</b>", RouletteSt.bet)


@router.message(RouletteSt.bet)
async def msg_roulette_bet(message: Message, db_user: User, state: FSMContext) -> None:
    bet, err = _check_bet(message.text, db_user.balance)
    if err:
        await message.answer(err)
        return
    await state.update_data(bet=bet)
    await state.set_state(RouletteSt.kind)
    await message.answer(f"🎡 Ставка <b>{fmt_bal(bet)}</b>. Выбери ставку:", parse_mode="HTML",
                         reply_markup=roulette_kinds())


@router.callback_query(F.data.startswith("roul:"))
async def cb_roulette_kind(cq: CallbackQuery, db_user: User, session: AsyncSession, state: FSMContext) -> None:
    if await state.get_state() != RouletteSt.kind.state:
        await cq.answer("Начни игру заново", show_alert=True)
        return
    kind = cq.data.split(":")[1]
    await cq.answer()
    if kind == "num":
        await state.set_state(RouletteSt.number)
        await cq.message.answer("🎯 Введи число от 0 до 36:")
        return
    bet = (await state.get_data())["bet"]
    await state.clear()
    text = await _roulette_play(session, db_user, bet, kind, None)
    await _safe_edit(cq, text, parse_mode="HTML", reply_markup=games_menu())


@router.message(RouletteSt.number)
async def msg_roulette_number(message: Message, db_user: User, session: AsyncSession, state: FSMContext) -> None:
    t = (message.text or "").strip()
    if not t.isdigit() or not 0 <= int(t) <= 36:
        await message.answer("❌ Введи число от 0 до 36:")
        return
    bet = (await state.get_data())["bet"]
    await state.clear()
    text = await _roulette_play(session, db_user, bet, "number", int(t))
    await message.answer(text, parse_mode="HTML", reply_markup=games_menu())


# ─── ДЖОКЕР ─────────────────────────────────────────────

@router.callback_query(F.data == "game:joker")
async def cb_joker_start(cq: CallbackQuery, db_user: User, state: FSMContext) -> None:
    await _start_bet(cq, db_user, state, "joker", "🃏 <b>Джокер</b>", JokerSt.bet)


@router.message(JokerSt.bet)
async def msg_joker_bet(message: Message, db_user: User, session: AsyncSession, state: FSMContext) -> None:
    bet, err = _check_bet(message.text, db_user.balance)
    if err:
        await message.answer(err)
        return
    card = joker_draw()
    mult = joker_multiplier(card)
    await state.clear()
    text = await _settle_report(session, db_user, bet, "JOKER", mult, card,
                                "🃏 <b>Джокер</b>", f"Карта: <b>{card}</b> (×{mult:g})")
    await message.answer(text, parse_mode="HTML", reply_markup=games_menu())


# ─── БЛЭКДЖЕК ───────────────────────────────────────────

def _bj_table(player: list[str], dealer: list[str], hidden: bool) -> str:
    dealer_str = f"{dealer[0]} 🂠" if hidden else f"{' '.join(dealer)} = {hand_value(dealer)}"
    return (f"🃏 <b>Блэкджек</b>\nДилер: {dealer_str}\n"
            f"Ты: {' '.join(player)} = {hand_value(player)}")


@router.callback_query(F.data == "game:blackjack")
async def cb_bj_start(cq: CallbackQuery, db_user: User, state: FSMContext) -> None:
    await _start_bet(cq, db_user, state, "blackjack", "🃏 <b>Блэкджек</b>", BjSt.bet)


@router.message(BjSt.bet)
async def msg_bj_bet(message: Message, db_user: User, session: AsyncSession, state: FSMContext) -> None:
    bet, err = _check_bet(message.text, db_user.balance)
    if err:
        await message.answer(err)
        return
    deck = new_deck()
    player = [deck.pop(), deck.pop()]
    dealer = [deck.pop(), deck.pop()]
    if is_blackjack(player):  # натуральный блэкджек — сразу расчёт
        outcome, mult = blackjack_settle(player, dealer)
        await state.clear()
        text = await _settle_report(session, db_user, bet, "BLACKJACK", mult, outcome,
                                    "🃏 <b>Блэкджек</b>", _bj_table(player, dealer, hidden=False))
        await message.answer(text, parse_mode="HTML", reply_markup=games_menu())
        return
    await state.set_state(BjSt.playing)
    await state.update_data(bet=bet, deck=deck, player=player, dealer=dealer)
    await message.answer(_bj_table(player, dealer, hidden=True) + f"\n\nСтавка: {fmt_bal(bet)}",
                         parse_mode="HTML", reply_markup=bj_actions())


@router.callback_query(F.data.in_({"bj:hit", "bj:stand"}))
async def cb_bj_play(cq: CallbackQuery, db_user: User, session: AsyncSession, state: FSMContext) -> None:
    if await state.get_state() != BjSt.playing.state:
        await cq.answer("Игра уже закончилась", show_alert=True)
        return
    await cq.answer()
    data = await state.get_data()
    bet, deck, player, dealer = data["bet"], data["deck"], data["player"], data["dealer"]

    if cq.data == "bj:hit":
        player.append(deck.pop())
        if hand_value(player) > 21:  # перебор
            await state.clear()
            text = await _settle_report(session, db_user, bet, "BLACKJACK", 0.0, "bust",
                                        "🃏 <b>Блэкджек</b>", _bj_table(player, dealer, hidden=False))
            await _safe_edit(cq, text, parse_mode="HTML", reply_markup=games_menu())
            return
        await state.update_data(deck=deck, player=player)
        await _safe_edit(cq, _bj_table(player, dealer, hidden=True) + f"\n\nСтавка: {fmt_bal(bet)}",
                         parse_mode="HTML", reply_markup=bj_actions())
        return

    # stand: дилер добирает до 17, потом расчёт
    dealer_play(dealer, deck)
    outcome, mult = blackjack_settle(player, dealer)
    await state.clear()
    text = await _settle_report(session, db_user, bet, "BLACKJACK", mult, outcome,
                                "🃏 <b>Блэкджек</b>", _bj_table(player, dealer, hidden=False))
    await _safe_edit(cq, text, parse_mode="HTML", reply_markup=games_menu())


# ─── КОЛЕСО ФОРТУНЫ ─────────────────────────────────────

@router.callback_query(F.data == "game:wheel")
async def cb_wheel_start(cq: CallbackQuery, db_user: User, state: FSMContext) -> None:
    await _start_bet(cq, db_user, state, "wheel", "🎠 <b>Колесо фортуны</b>", WheelSt.bet)


@router.message(WheelSt.bet)
async def msg_wheel_bet(message: Message, db_user: User, session: AsyncSession, state: FSMContext) -> None:
    bet, err = _check_bet(message.text, db_user.balance)
    if err:
        await message.answer(err)
        return
    mult = wheel_spin()
    await state.clear()
    text = await _settle_report(session, db_user, bet, "WHEEL", mult, f"x{mult:g}",
                                "🎠 <b>Колесо фортуны</b>", f"Сектор: <b>×{mult:g}</b>")
    await message.answer(text, parse_mode="HTML", reply_markup=games_menu())


@router.callback_query()
async def cb_fallback(cq: CallbackQuery) -> None:
    await cq.answer("❓ Неизвестное действие")
