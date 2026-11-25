"""
Чистая логика мини-игр: без БД и Telegram, только правила, множители и случайность.
Расчёт очков делает services.settle_game, интерфейс — handlers.py.

ОБЩЕЕ:
  - ставка на новые игры от 100, без максимума (проверка в handlers._check_bet);
  - VIP даёт +5% к выигрышу (services.calc_payout), к возврату ставки и проигрышу не применяется;
  - ставка списывается при расчёте, а не при старте (для мин и блэкджека на время игры баланс не трогается).
"""
from __future__ import annotations

import random
from math import comb

# ═══════════════════════════════════════════════════════
#  МИНЫ
# ═══════════════════════════════════════════════════════
# Поле 5×5 (25 клеток), 3 мины. Открываешь клетки: каждая безопасная поднимает множитель.
# Забрать выигрыш можно в любой момент. На мине ставка сгорает.
# Множитель после k безопасных клеток: C(25,k) / C(22,k) * EDGE — честный коэффициент с преимуществом казино.
# ДОПУЩЕНИЕ: EDGE = 0.97 (3% преимущество казино). Открыты все 22 безопасные клетки — авто-забор.

MINES_SIZE = 25
MINES_COUNT = 3
MINES_SAFE = MINES_SIZE - MINES_COUNT
MINES_EDGE = 0.97


def mines_place(rng=random) -> list[int]:
    """Индексы клеток 0..24, где лежат мины."""
    return rng.sample(range(MINES_SIZE), MINES_COUNT)


def mines_multiplier(opened_safe: int) -> float:
    if opened_safe <= 0:
        return 1.0
    return comb(MINES_SIZE, opened_safe) / comb(MINES_SAFE, opened_safe) * MINES_EDGE


# ═══════════════════════════════════════════════════════
#  РУЛЕТКА (европейская: 0–36)
# ═══════════════════════════════════════════════════════
# Ставки: красное / чёрное ×2, чётное / нечётное ×2, конкретное число ×36.
# 0 зелёный: на цвет и на чётность ставки проигрывают.

RED_NUMBERS = {1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36}


def roulette_spin(rng=random) -> int:
    return rng.randint(0, 36)


def roulette_win(kind: str, pick: int | None, spin: int) -> tuple[bool, float]:
    """kind: red / black / even / odd / number. Возвращает (выиграл, множитель к ставке)."""
    if kind == "number":
        hit = spin == pick
        return hit, 36.0 if hit else 0.0
    if spin == 0:
        return False, 0.0
    if kind == "red":
        won = spin in RED_NUMBERS
    elif kind == "black":
        won = spin not in RED_NUMBERS
    elif kind == "even":
        won = spin % 2 == 0
    elif kind == "odd":
        won = spin % 2 == 1
    else:
        raise ValueError(f"unknown roulette bet: {kind}")
    return won, 2.0 if won else 0.0


# ═══════════════════════════════════════════════════════
#  ДЖОКЕР
# ═══════════════════════════════════════════════════════
# Одна карта из колоды 52 + джокер (53 карты).
# Джокер ×3, старшие карты ×2, остальные проигрыш.
# ДОПУЩЕНИЕ: «старшие» = J, Q, K, A. Вероятности: джокер 1/53, старшие 16/53.
# Матожидание ~0.66 от ставки — заметное преимущество казино, если хотите мягче, меняйте множители здесь.

JOKER_RANKS = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"]
HIGH_RANKS = {"J", "Q", "K", "A"}


def joker_draw(rng=random) -> str:
    deck = [r for r in JOKER_RANKS for _ in range(4)] + ["JOKER"]
    return rng.choice(deck)


def joker_multiplier(card: str) -> float:
    if card == "JOKER":
        return 3.0
    if card in HIGH_RANKS:
        return 2.0
    return 0.0


# ═══════════════════════════════════════════════════════
#  БЛЭКДЖЕК
# ═══════════════════════════════════════════════════════
# Колода 52 карты. 2–10 по номиналу, J/Q/K = 10, туз = 1 или 11 (как выгоднее).
# Игрок: Hit (ещё карту) или Stand (хватит). Перебор (>21) — проигрыш.
# Дилер: берёт карты, пока у него меньше 17, на 17 и больше останавливается.
# Выплаты: победа ×2 (1:1), блэкджек игрока (2 карты = 21) ×2.5 (3:2), ничья — ставка возвращается ×1.
# ДОПУЩЕНИЕ: блэкджек дилера побеждает обычный блэкджек игрока; оба блэкджека — ничья.

BJ_RANKS = {"2": 2, "3": 3, "4": 4, "5": 5, "6": 6, "7": 7, "8": 8, "9": 9, "10": 10,
            "J": 10, "Q": 10, "K": 10, "A": 11}


def new_deck(rng=random) -> list[str]:
    deck = [r for r in BJ_RANKS for _ in range(4)]
    rng.shuffle(deck)
    return deck


def hand_value(cards: list[str]) -> int:
    total = sum(BJ_RANKS[c] for c in cards)
    aces = cards.count("A")
    while total > 21 and aces:
        total -= 10
        aces -= 1
    return total


def is_blackjack(cards: list[str]) -> bool:
    return len(cards) == 2 and hand_value(cards) == 21


def dealer_play(dealer: list[str], deck: list[str]) -> list[str]:
    """Дилер добирает до 17 (включительно останавливается). Меняет список на месте."""
    while hand_value(dealer) < 17:
        dealer.append(deck.pop())
    return dealer


def blackjack_settle(player: list[str], dealer: list[str]) -> tuple[str, float]:
    """Возвращает (исход, множитель к ставке): win / blackjack / push / lose / bust."""
    pv, dv = hand_value(player), hand_value(dealer)
    if pv > 21:
        return "bust", 0.0
    p_bj, d_bj = is_blackjack(player), is_blackjack(dealer)
    if p_bj and d_bj:
        return "push", 1.0
    if p_bj:
        return "blackjack", 2.5
    if d_bj:
        return "lose", 0.0
    if dv > 21 or pv > dv:
        return "win", 2.0
    if pv == dv:
        return "push", 1.0
    return "lose", 0.0


# ═══════════════════════════════════════════════════════
#  КОЛЕСО ФОРТУНЫ
# ═══════════════════════════════════════════════════════
# 8 секторов с множителями. Сектор выпадает случайно, с весом (вес = шанс, сумма 100).
# ДОПУЩЕНИЕ: веса и множители наши. Матожидание ~0.88 — преимущество казино ~12%.

WHEEL_SECTORS: list[tuple[float, float]] = [
    (0.0, 30),   # ×0 — проигрыш
    (0.5, 25),
    (1.0, 20),   # ×1 — возврат ставки
    (1.5, 12),
    (2.0, 8),
    (3.0, 3),
    (5.0, 1.5),
    (10.0, 0.5),
]


def wheel_spin(rng=random) -> float:
    mults = [m for m, _ in WHEEL_SECTORS]
    weights = [w for _, w in WHEEL_SECTORS]
    return rng.choices(mults, weights=weights, k=1)[0]
