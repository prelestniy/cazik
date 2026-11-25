# [context: aiogram 3 InlineKeyboardBuilder]

from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def main_menu() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="🎮 Игры",       callback_data="menu:games")
    b.button(text="👤 Профиль",    callback_data="menu:profile")
    b.button(text="📊 Статистика", callback_data="menu:stats")
    b.button(text="🏆 Рейтинг",   callback_data="menu:leaderboard")
    b.button(text="📋 Задания",    callback_data="menu:tasks")
    b.button(text="💎 Купить",     callback_data="menu:buy")
    b.button(text="💸 Вывод",      callback_data="menu:withdraw")
    b.button(text="❓ Помощь",     callback_data="menu:help")
    b.button(text="🎁 Бесплатный NFT", callback_data="menu:nft")
    b.adjust(2, 2, 2, 2, 1)
    return b.as_markup()


def games_menu() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="🪙 Монетка",     callback_data="game:coinflip")
    b.button(text="🎲 Кубик",       callback_data="game:dice")
    b.button(text="🎰 Слоты",       callback_data="game:slots")
    b.button(text="💣 Мины",        callback_data="game:mines")
    b.button(text="🎡 Рулетка",     callback_data="game:roulette")
    b.button(text="🃏 Джокер",      callback_data="game:joker")
    b.button(text="🂡 Блэкджек",    callback_data="game:blackjack")
    b.button(text="🎠 Колесо",      callback_data="game:wheel")
    b.button(text="« Назад",        callback_data="menu:main")
    b.adjust(2, 2, 2, 2, 1)
    return b.as_markup()


def mines_board(opened: list[int], reveal: list[int] | None, cash_label: str | None) -> InlineKeyboardMarkup:
    """Поле 5×5. reveal не None — игра закончилась, мины показаны."""
    b = InlineKeyboardBuilder()
    ended = reveal is not None
    for i in range(25):
        if ended and i in reveal:
            b.button(text="💣", callback_data="mines:noop")
        elif i in opened:
            b.button(text="💎", callback_data="mines:noop")
        elif ended:
            b.button(text="▫️", callback_data="mines:noop")
        else:
            b.button(text="▫️", callback_data=f"mines:open:{i}")
    if cash_label:
        b.button(text=cash_label, callback_data="mines:cash")
    else:
        b.button(text="« Игры", callback_data="menu:games")
    b.adjust(5, 5, 5, 5, 5, 1)
    return b.as_markup()


def roulette_kinds() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="🔴 Красное ×2",  callback_data="roul:red")
    b.button(text="⚫ Чёрное ×2",    callback_data="roul:black")
    b.button(text="Чётное ×2",      callback_data="roul:even")
    b.button(text="Нечётное ×2",    callback_data="roul:odd")
    b.button(text="🎯 Число ×36",   callback_data="roul:num")
    b.adjust(2, 2, 1)
    return b.as_markup()


def bj_actions() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="➕ Ещё карту", callback_data="bj:hit")
    b.button(text="✋ Хватит",     callback_data="bj:stand")
    b.adjust(2)
    return b.as_markup()


def back_main() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="« Главное меню", callback_data="menu:main")
    return b.as_markup()


def coinflip_choice() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="🦅 Орёл",   callback_data="cf:heads")
    b.button(text="🪙 Решка",  callback_data="cf:tails")
    b.button(text="« Назад",   callback_data="game:coinflip")
    b.adjust(2, 1)
    return b.as_markup()


def dice_choice(bet: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for i in range(1, 7):
        b.button(text=str(i), callback_data=f"dice:{i}:{bet}")
    b.button(text="« Назад", callback_data="game:dice")
    b.adjust(3, 3, 1)
    return b.as_markup()


def shop_keyboard() -> InlineKeyboardMarkup:
    from services import SHOP_ITEMS
    b = InlineKeyboardBuilder()
    for item in SHOP_ITEMS:
        b.button(text=f"{item['title']} — {item['stars']} ⭐",
                 callback_data=f"buy:{item['id']}")
    b.button(text="« Главное меню", callback_data="menu:main")
    b.adjust(1)
    return b.as_markup()


def admin_menu() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="📊 Статистика",   callback_data="admin:stats")
    b.button(text="📋 События",      callback_data="admin:events")
    b.button(text="👤 Найти юзера",  callback_data="admin:find_user")
    b.button(text="⚙️ Конфиг игр",  callback_data="admin:configs")
    b.button(text="📢 Рассылка",     callback_data="admin:broadcast")
    b.adjust(2, 2, 1)
    return b.as_markup()


def user_manage(uid: int, blocked: bool, vip: bool) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="✅ Разблокировать" if blocked else "🚫 Заблокировать",
             callback_data=f"admin:block:{uid}:{int(not blocked)}")
    b.button(text="❌ Снять VIP" if vip else "⭐ Дать VIP",
             callback_data=f"admin:vip:{uid}:{int(not vip)}")
    b.button(text="➕ Начислить очки", callback_data=f"admin:grant:{uid}")
    b.button(text="➖ Снять очки",     callback_data=f"admin:deduct:{uid}")
    b.button(text="« Назад",           callback_data="admin:main")
    b.adjust(2, 2, 1)
    return b.as_markup()


def back_admin() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="« Назад", callback_data="admin:main")
    return b.as_markup()


def nft_decision(cid: int, allow_deny: bool = False) -> InlineKeyboardMarkup:
    """Кнопки админа под заявкой на бесплатный NFT.
    allow_deny — третья кнопка «Отказать полностью», только при повторной подаче."""
    b = InlineKeyboardBuilder()
    b.button(text="✅ Одобрить",  callback_data=f"nft:approve:{cid}")
    b.button(text="❌ Отклонить", callback_data=f"nft:reject:{cid}")
    if allow_deny:
        b.button(text="🚫 Отказать полностью", callback_data=f"nft:deny:{cid}")
        b.adjust(2, 1)
    else:
        b.adjust(2)
    return b.as_markup()


def withdraw_decision(wid: int) -> InlineKeyboardMarkup:
    """Кнопки под заявкой на вывод, которые видят админы."""
    b = InlineKeyboardBuilder()
    b.button(text="✅ Одобрить",  callback_data=f"wd:approve:{wid}")
    b.button(text="❌ Отклонить", callback_data=f"wd:reject:{wid}")
    b.adjust(2)
    return b.as_markup()
