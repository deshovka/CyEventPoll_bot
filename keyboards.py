from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from datetime import datetime, timedelta

def start_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📅 Создать событие"), KeyboardButton(text="📋 Посмотреть события")]
        ],
        resize_keyboard=True,
        one_time_keyboard=False
    )

def create_calendar(year: int, month: int) -> InlineKeyboardMarkup:
    buttons = []
    today = datetime.now()
    buttons.append([
        InlineKeyboardButton(text=f"{datetime(year, month, 1).strftime('%B %Y')}", callback_data="ignore"),
        InlineKeyboardButton(text="⬅️", callback_data=f"calendar_prev_{year}_{month}"),
        InlineKeyboardButton(text="➡️", callback_data=f"calendar_next_{year}_{month}")
    ])
    buttons.append([
        InlineKeyboardButton(text=day, callback_data="ignore") for day in ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    ])
    first_day = datetime(year, month, 1)
    last_day = (datetime(year, month + 1, 1) - timedelta(days=1) if month < 12 else datetime(year + 1, 1, 1) - timedelta(days=1)).day
    weekday = first_day.weekday()
    week = []
    for _ in range(weekday):
        week.append(InlineKeyboardButton(text=" ", callback_data="ignore"))
    for day in range(1, last_day + 1):
        date = datetime(year, month, day)
        text = f"[{day}]" if date.date() == today.date() else str(day)
        week.append(InlineKeyboardButton(text=text, callback_data=f"date_{year}_{month}_{day}"))
        if len(week) == 7:
            buttons.append(week)
            week = []
    if week:
        while len(week) < 7:
            week.append(InlineKeyboardButton(text=" ", callback_data="ignore"))
        buttons.append(week)
    buttons.append([InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_calendar")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def create_time_keyboard() -> InlineKeyboardMarkup:
    buttons = []
    for hour in range(6, 24):
        row = []
        for minute in [0, 30]:
            time_str = f"{hour:02d}:{minute:02d}"
            row.append(InlineKeyboardButton(text=time_str, callback_data=f"time_{time_str}"))
        buttons.append(row)
    for hour in range(0, 4):
        row = []
        for minute in [0, 30]:
            time_str = f"{hour:02d}:{minute:02d}"
            row.append(InlineKeyboardButton(text=time_str, callback_data=f"time_{time_str}"))
        buttons.append(row)
    buttons.append([InlineKeyboardButton(text="✍️ Ввести своё время", callback_data="custom_time")])
    buttons.append([InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_time")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)