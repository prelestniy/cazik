from aiogram.fsm.state import StatesGroup, State


class CoinflipSt(StatesGroup):
    bet = State()


class DiceSt(StatesGroup):
    bet = State()


class SlotsSt(StatesGroup):
    bet = State()


class AdminSt(StatesGroup):
    find_user    = State()
    broadcast    = State()
    grant_amount = State()
    deduct_amount = State()

    # stores target uid between steps
    target_uid: int = 0
