"""FSM-состояния."""
from aiogram.fsm.state import State, StatesGroup


class RegistrationStates(StatesGroup):
    name = State()
    lookup_city = State()
    lookup = State()
    category = State()
    subcategory = State()
    description = State()
    services = State()
    materials = State()
    country = State()
    region = State()
    city = State()
    address = State()
    work_hours = State()
    phone = State()
    telegram = State()
    email = State()
    website = State()
    logo = State()
    photos = State()
    confirm = State()


class CityStates(StatesGroup):
    city = State()


class SearchStates(StatesGroup):
    query = State()


class ReviewStates(StatesGroup):
    text = State()


class CompanyEditStates(StatesGroup):
    value = State()
    logo = State()
    photos = State()


class AdminStates(StatesGroup):
    reject_reason = State()
    edit_value = State()
    edit_logo = State()
    broadcast_text = State()
    broadcast_confirm = State()
    restore_file = State()
    setting_value = State()
