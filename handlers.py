import aiosqlite
import logging
import asyncio
from aiogram import Router, F
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.fsm.context import FSMContext
from datetime import datetime, timedelta
import pytz
from configparser import ConfigParser
from models import Event
from keyboards import start_keyboard, create_calendar, create_time_keyboard
from states import EventCreation
from utils import check_access

router = Router()
logger = logging.getLogger(__name__)
config = ConfigParser()
config.read("config.ini")
CHANNEL_ID = config["Bot"]["channel_id"]

@router.message(CommandStart())
async def start_command(message: Message, bot):
    if not check_access(message.from_user.id):
        await message.reply("🚫 Доступ запрещён.")
        return
    await message.reply(
        "🎉 **Добро пожаловать в бот для управления событиями!**\n\n"
        "Выберите действие ниже:",
        reply_markup=start_keyboard()
    )

@router.message(Command("cancel"))
async def cancel_command(message: Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state is None:
        await message.reply("❌ Нет активного процесса для отмены.")
        return
    await state.clear()
    await message.reply("✅ Процесс создания события отменён.", reply_markup=start_keyboard())

@router.callback_query(F.data.in_(["cancel_calendar", "cancel_time"]))
async def cancel_calendar_time(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.reply("✅ Процесс создания события отменён.", reply_markup=start_keyboard())
    try:
        await callback.message.delete()
    except Exception as e:
        logger.error(f"Ошибка при удалении сообщения календаря: {e}")
    await callback.answer()

@router.message(F.text.in_(["📅 Создать событие", "📋 Посмотреть события"]))
async def process_action(message: Message, state: FSMContext):
    if not check_access(message.from_user.id):
        await message.reply("🚫 Доступ запрещён.")
        return
    if message.text == "📅 Создать событие":
        await state.set_state(EventCreation.TITLE)
        await message.reply("✍️ Введите название события (до 100 символов):", reply_markup=None)
    elif message.text == "📋 Посмотреть события":
        await show_events(message)

@router.message(EventCreation.TITLE)
async def process_title(message: Message, state: FSMContext):
    try:
        tomorrow = (datetime.now(pytz.timezone("EET")) + timedelta(days=1)).strftime("%d.%m.%Y %H:%M")
        Event(title=message.text, description="test", date=tomorrow)
        await state.update_data(title=message.text.strip())
        await state.set_state(EventCreation.DESCRIPTION)
        await message.reply("📝 Введите описание события (до 1000 символов):")
    except ValueError as e:
        error_msg = str(e).replace("_", "\\_").replace("*", "\\*").replace("`", "\\`")
        await message.reply(f"❌ Ошибка: {error_msg}. Попробуйте снова.")

@router.message(EventCreation.DESCRIPTION)
async def process_description(message: Message, state: FSMContext):
    try:
        tomorrow = (datetime.now(pytz.timezone("EET")) + timedelta(days=1)).strftime("%d.%m.%Y %H:%M")
        Event(description=message.text, title="test", date=tomorrow)
        await state.update_data(description=message.text.strip())
        await state.set_state(EventCreation.DATE)
        current_date = datetime.now(pytz.timezone("EET"))
        await message.reply(
            "📅 Выберите дату события:",
            reply_markup=create_calendar(current_date.year, current_date.month)
        )
    except ValueError as e:
        error_msg = str(e).replace("_", "\\_").replace("*", "\\*").replace("`", "\\`")
        await message.reply(f"❌ Ошибка: {error_msg}. Попробуйте снова.")

@router.callback_query(F.data.startswith("calendar_"), EventCreation.DATE)
async def process_calendar_navigation(callback: CallbackQuery, state: FSMContext):
    try:
        parts = callback.data.split("_")
        if len(parts) != 4:
            raise ValueError(f"Invalid callback data format: {callback.data}")
        _, action, year, month = parts
        year, month = int(year), int(month)
        logger.info(f"Navigating calendar: action={action}, year={year}, month={month}")

        if action == "prev":
            month -= 1
            if month == 0:
                month = 12
                year -= 1
        elif action == "next":
            month += 1
            if month == 13:
                month = 1
                year += 1
        if year < 1970 or year > 9999:
            raise ValueError(f"Invalid year: {year}")

        new_calendar = create_calendar(year, month)
        calendar_text = f"📅 Выберите дату события ({datetime(year, month, 1).strftime('%B %Y')}):"

        new_message = await callback.message.answer(
            text=calendar_text,
            reply_markup=new_calendar
        )
        await state.update_data(calendar_message_id=new_message.message_id)
        await asyncio.sleep(0.1)
        try:
            await callback.message.delete()
        except Exception as delete_error:
            logger.error(f"Failed to delete old calendar message: {delete_error}")

        await callback.answer()
    except Exception as e:
        logger.error(f"Ошибка при навигации календаря: {e}")
        error_msg = str(e).replace("_", "\\_").replace("*", "\\*").replace("`", "\\`")
        await callback.message.answer(f"❌ Ошибка при обновлении календаря: {error_msg}. Попробуйте снова.")
        await callback.answer()

@router.callback_query(F.data.startswith("date_"), EventCreation.DATE)
async def process_date_callback(callback: CallbackQuery, state: FSMContext):
    try:
        parts = callback.data.split("_")
        if len(parts) != 4:
            raise ValueError("Invalid date callback data")
        _, year, month, day = parts
        date_str = f"{int(day):02d}.{int(month):02d}.{year}"
        tomorrow = (datetime.now(pytz.timezone("EET")) + timedelta(days=1)).strftime("%d.%m.%Y %H:%M")
        Event(date=date_str + " 00:00", title="test", description="test")
        await state.update_data(date=date_str)
        await state.set_state(EventCreation.TIME)
        new_message = await callback.message.answer(
            text="🕒 Выберите время события (6:00–3:00, интервал 30 минут) или нажмите 'Ввести своё время' (например, 17:33):",
            reply_markup=create_time_keyboard()
        )
        await state.update_data(time_message_id=new_message.message_id)
        await asyncio.sleep(0.1)
        try:
            await callback.message.delete()
        except Exception as delete_error:
            logger.error(f"Failed to delete old calendar message: {delete_error}")
        await callback.answer()
    except ValueError as e:
        logger.error(f"Ошибка при выборе даты: {e}")
        error_msg = str(e).replace("_", "\\_").replace("*", "\\*").replace("`", "\\`")
        await callback.message.answer(f"❌ Ошибка при выборе даты: {error_msg}. Попробуйте снова.")
        await callback.answer()

@router.callback_query(F.data.startswith("time_"), EventCreation.TIME)
async def process_time_callback(callback: CallbackQuery, state: FSMContext):
    try:
        time_str = callback.data.replace("time_", "")
        data = await state.get_data()
        date_str = data["date"]
        full_date = f"{date_str} {time_str}"
        Event(date=full_date, title="test", description="test")
        await state.update_data(date=full_date)
        await state.set_state(EventCreation.IMAGE)
        new_message = await callback.message.answer(
            text="🖼 Загрузите изображение для события (или отправьте /skip, чтобы пропустить):"
        )
        await state.update_data(image_message_id=new_message.message_id)
        await asyncio.sleep(0.1)
        try:
            await callback.message.delete()
        except Exception as delete_error:
            logger.error(f"Failed to delete old time message: {delete_error}")
        await callback.answer()
    except ValueError as e:
        logger.error(f"Ошибка при выборе времени: {e}")
        error_msg = str(e).replace("_", "\\_").replace("*", "\\*").replace("`", "\\`")
        await callback.message.answer(f"❌ Ошибка: {error_msg}. Попробуйте снова.")
        await callback.answer()

@router.callback_query(F.data == "custom_time", EventCreation.TIME)
async def request_custom_time(callback: CallbackQuery, state: FSMContext):
    await state.set_state(EventCreation.CUSTOM_TIME)
    new_message = await callback.message.answer(
        text="✍️ Введите время события в формате ЧЧ:ММ (например, 17:33):"
    )
    await state.update_data(custom_time_message_id=new_message.message_id)
    await asyncio.sleep(0.1)
    try:
        await callback.message.delete()
    except Exception as delete_error:
        logger.error(f"Failed to delete old time message: {delete_error}")
    await callback.answer()

@router.message(EventCreation.CUSTOM_TIME)
async def process_custom_time(message: Message, state: FSMContext):
    time_str = message.text.strip()
    try:
        parsed_time = datetime.strptime(time_str, "%H:%M")
        data = await state.get_data()
        date_str = data["date"]
        full_date = f"{date_str} {time_str}"
        Event(date=full_date, title="test", description="test")
        await state.update_data(date=full_date)
        await state.set_state(EventCreation.IMAGE)
        new_message = await message.answer(
            text="🖼 Загрузите изображение для события (или отправьте /skip, чтобы пропустить):"
        )
        await state.update_data(image_message_id=new_message.message_id)
        await message.delete()
    except ValueError as e:
        logger.error(f"Ошибка при вводе кастомного времени: {e}")
        error_msg = str(e).replace("_", "\\_").replace("*", "\\*").replace("`", "\\`")
        await message.answer(f"❌ Ошибка: {error_msg}. Введите время в формате ЧЧ:ММ (например, 17:33).")

@router.message(F.photo, EventCreation.IMAGE)
async def process_image(message: Message, state: FSMContext, bot):
    await state.update_data(image_id=message.photo[-1].file_id)
    await save_event(message, state, bot)

@router.message(EventCreation.IMAGE, ~F.text.startswith("/"))
async def process_invalid_image(message: Message):
    await message.reply("❌ Пожалуйста, загрузите изображение или отправьте /skip.")

@router.message(Command("skip"), EventCreation.IMAGE)
async def skip_image(message: Message, state: FSMContext, bot):
    await state.update_data(image_id=None)
    await save_event(message, state, bot)
    await message.delete()

async def save_event(message: Message, state: FSMContext, bot):
    data = await state.get_data()
    try:
        event = Event(title=data["title"], description=data["description"], date=data["date"], image_id=data.get("image_id"))
        async with aiosqlite.connect("events.db") as db:
            try:
                cursor = await db.execute(
                    "INSERT INTO events (title, description, date, image_id) VALUES (?, ?, ?, ?)",
                    (event.title, event.description, event.date, event.image_id)
                )
                event_id = cursor.lastrowid
                await db.commit()
                logger.info(f"Event saved to DB, event_id={event_id}")
            except aiosqlite.IntegrityError:
                await message.reply("❌ Событие с таким названием и датой уже существует.")
                await state.clear()
                return

            keyboard = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="✅ Участвую", callback_data=f"join_{event_id}"),
                InlineKeyboardButton(text="❌ Не участвую", callback_data=f"decline_{event_id}")
            ]])

            text = f"📅 **_{event.title}_**\n\n{event.description}\n\n🕒 **Дата и время**: {event.date}"
            logger.info(f"Preparing to send to CHANNEL_ID={CHANNEL_ID}, text length={len(text)}")

            try:
                if event.image_id:
                    message_sent = await bot.send_photo(
                        chat_id=CHANNEL_ID,
                        photo=event.image_id,
                        caption=text,
                        reply_markup=keyboard
                    )
                else:
                    message_sent = await bot.send_message(
                        chat_id=CHANNEL_ID,
                        text=text,
                        reply_markup=keyboard
                    )
                logger.info(f"Message sent successfully, chat_id={CHANNEL_ID}, message_id={message_sent.message_id}")
                await db.execute("UPDATE events SET message_id = ? WHERE event_id = ?", (message_sent.message_id, event_id))
                await db.commit()
            except Exception as e:
                logger.error(f"Error sending to channel: {e}")
                await message.reply("❌ Ошибка: не удалось опубликовать событие в канал. Проверьте доступность канала.")
                await db.execute("DELETE FROM events WHERE event_id = ?", (event_id,))
                await db.commit()
                return

        await message.reply("🎉 Событие создано и опубликовано в канале!", reply_markup=start_keyboard())
        await state.clear()
    except ValueError as e:
        error_msg = str(e).replace("_", "\\_").replace("*", "\\*").replace("`", "\\`")
        await message.reply(f"❌ Ошибка: {error_msg}. Попробуйте снова.")
    except Exception as e:
        logger.error(f"Error saving event: {e}")
        await message.reply("❌ Произошла ошибка при создании события. Попробуйте снова.")

async def show_events(message: Message):
    async with aiosqlite.connect("events.db") as db:
        cursor = await db.execute("SELECT event_id, title, date FROM events ORDER BY date")
        events = await cursor.fetchall()
        if not events:
            await message.reply("📭 Нет активных событий.")
            return
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"📅 {title} ({date})", callback_data=f"view_{event_id}")]
            for event_id, title, date in events
        ])
        await message.reply("📋 **Выберите событие**:", reply_markup=keyboard)

@router.callback_query(F.data.startswith("view_"))
async def view_event(callback: CallbackQuery):
    event_id = int(callback.data.replace("view_", ""))
    async with aiosqlite.connect("events.db") as db:
        cursor = await db.execute("SELECT title, description, date FROM events WHERE event_id = ?", (event_id,))
        event = await cursor.fetchone()
        if not event:
            await callback.message.reply("❌ Событие не найдено.")
            return
        title, description, date = event
        cursor = await db.execute(
            "SELECT username, participation_status FROM participants WHERE event_id = ? AND participation_status = 'Участвую'",
            (event_id,)
        )
        participants = await cursor.fetchall()
        participants_text = "\n".join(f"👤 @{username}" for username, _ in participants) or "🚶‍♂️ Нет участников."
        text = f"📅 **{title}**\n\n📝 {description}\n\n🕒 **Дата и время**: {date}\n\n👥 **Участники**:\n{participants_text}"
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="🗑 Удалить событие", callback_data=f"delete_{event_id}")
        ]] if check_access(callback.from_user.id) else [])
        await callback.message.reply(text, reply_markup=keyboard)
        await callback.answer()

@router.callback_query(F.data.startswith("delete_"))
async def delete_event(callback: CallbackQuery, bot):
    if not check_access(callback.from_user.id):
        await callback.message.reply("🚫 Доступ запрещён.")
        return
    event_id = int(callback.data.replace("delete_", ""))
    async with aiosqlite.connect("events.db") as db:
        cursor = await db.execute("SELECT message_id FROM events WHERE event_id = ?", (event_id,))
        event = await cursor.fetchone()
        if event and event[0]:
            try:
                await bot.delete_message(CHANNEL_ID, event[0])
            except Exception as e:
                logger.error(f"Ошибка при удалении сообщения: {e}")
        await db.execute("DELETE FROM events WHERE event_id = ?", (event_id,))
        await db.commit()
    await callback.message.reply("🗑 Событие удалено.")
    await callback.answer()

@router.callback_query(F.data.startswith(("join_", "decline_")))
async def handle_participation(callback: CallbackQuery):
    action, event_id = callback.data.split("_")
    event_id = int(event_id)
    user_id = callback.from_user.id
    username = callback.from_user.username or callback.from_user.first_name
    new_status = "Участвую" if action == "join" else "Не участвую"

    async with aiosqlite.connect("events.db") as db:
        cursor = await db.execute("SELECT event_id FROM events WHERE event_id = ?", (event_id,))
        if not await cursor.fetchone():
            await callback.message.reply("❌ Событие не найдено.")
            return

        cursor = await db.execute(
            "SELECT participation_status FROM participants WHERE event_id = ? AND user_id = ?",
            (event_id, user_id)
        )
        current_status = await cursor.fetchone()

        if current_status and current_status[0] == new_status:
            await callback.answer()
            return

        should_notify = (
            (current_status is None and action == "join") or
            (current_status and current_status[0] == "Участвую" and action == "decline") or
            (current_status and current_status[0] == "Не участвую" and action == "join")
        )

        await db.execute(
            """
            INSERT OR REPLACE INTO participants (event_id, user_id, username, participation_status)
            VALUES (?, ?, ?, ?)
            """,
            (event_id, user_id, username, new_status)
        )
        await db.commit()

        if should_notify:
            await callback.message.reply(f"👤 @{username} отметил: {new_status}")

    await callback.answer()

@router.errors()
async def errors_handler(update, exception=None):
    logger.error(f"Ошибка: {exception}", exc_info=True)
    error_msg = str(exception).replace("_", "\\_").replace("*", "\\*").replace("`", "\\`")[:200] if exception else "Неизвестная ошибка"
    if isinstance(update, Message):
        await update.reply(f"❌ Ошибка: {error_msg}. Попробуйте снова.")
    elif isinstance(update, CallbackQuery):
        await update.message.reply(f"❌ Ошибка: {error_msg}. Попробуйте снова.")
    return True