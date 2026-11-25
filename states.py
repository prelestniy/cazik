from aiogram.fsm.state import StatesGroup, State


class CoinflipSt(StatesGroup):
    bet = State()


class DiceSt(StatesGroup):
    bet = State()


class SlotsSt(StatesGroup):
    bet = State()


class WithdrawSt(StatesGroup):
    amount = State()


class MinesSt(StatesGroup):
    bet = State()
    playing = State()   # поле открыто, мины и открытые клетки лежат в FSM data


class RouletteSt(StatesGroup):
    bet = State()
    kind = State()      # выбор ставки: цвет / чётность / число
    number = State()    # ввод конкретного числа


class JokerSt(StatesGroup):
    bet = State()


class BjSt(StatesGroup):
    bet = State()
    playing = State()   # колода и руки лежат в FSM data


class WheelSt(StatesGroup):
    bet = State()


class AdminSt(StatesGroup):
    find_user    = State()
    broadcast    = State()
    grant_amount = State()
    deduct_amount = State()

    # stores target uid between steps
    target_uid: int = 0
