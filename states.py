from aiogram.fsm.state import State, StatesGroup

class EventCreation(StatesGroup):
    TITLE = State()
    DESCRIPTION = State()
    DATE = State()
    TIME = State()
    CUSTOM_TIME = State()
    IMAGE = State()