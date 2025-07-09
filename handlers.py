import aiosqlite
import logging
import asyncio
from aiogram import Router, F
from aiogram import Bot
from collections import defaultdict
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
import re

router = Router()
logger = logging.getLogger(__name__)
config = ConfigParser()
config.read("config.ini")
CHANNEL_ID = config["Bot"]["channel_id"]


# Хранилище для временного кэширования количества участников
participant_counts = defaultdict(lambda: {"join": 0, "decline": 0})
update_lock = asyncio.Lock()
pending_updates = defaultdict(list)

async def schedule_keyboard_update(event_id: int, join_count: int, decline_count: int, bot: Bot, message_id: int):
    """Планирует обновление клавиатуры с дебouncing'ом."""
    async with update_lock:
        pending_updates[event_id].append((join_count, decline_count))

        # Ждем 100 мс для сбора всех изменений
        await asyncio.sleep(0.1)
        if not pending_updates[event_id]:
            return

        # Берем последнее состояние
        join_count, decline_count = pending_updates[event_id][-1]
        del pending_updates[event_id]

        # Обновляем кэш
        participant_counts[event_id]["join"] = join_count
        participant_counts[event_id]["decline"] = decline_count

        # Создаем клавиатуру
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(
                text=f"✅ Участвую ({join_count})",
                callback_data=f"join_{event_id}"
            ),
            InlineKeyboardButton(
                text=f"❌ Не участвую ({decline_count})",
                callback_data=f"decline_{event_id}"
            )
        ]])

        # Пробуем обновить клавиатуру с повторными попытками
        for attempt in range(3):
            try:
                await bot.edit_message_reply_markup(
                    chat_id=CHANNEL_ID,
                    message_id=message_id,
                    reply_markup=keyboard
                )
                logger.info(f"Keyboard updated for event_id={event_id}, message_id={message_id}")
                return
            except Exception as e:
                logger.warning(f"Attempt {attempt + 1} failed to update keyboard: {e}")
                if attempt < 2:
                    await asyncio.sleep(0.2 * (2 ** attempt))  # Экспоненциальная задержка
                else:
                    logger.error(f"Failed to update keyboard after 3 attempts: {e}")

def escape_markdown(text: str) -> str:
    """Escape markdown-sensitive characters for Telegram MarkdownV2, preserving backslashes, usernames, and dates."""
    if not text:
        return text

    # Characters to escape (excluding \ to preserve backslashes in dates and usernames)
    characters = r'_*[]()~`>#+-=|{}!'

    # Экранируем все специальные символы, кроме точек
    for char in characters:
        text = text.replace(char, f"\\{char}")

    # Экранируем точки, но только если они не находятся в формате даты (DD.MM.YYYY или DD.MM.YYYY HH:MM)
    def escape_dots(match):
        # Если строка соответствует формату даты, возвращаем её без изменений
        if re.match(r'\d{1,2}\.\d{1,2}\.\d{4}(?:\s\d{1,2}:\d{2})?', match.group(0)):
            return match.group(0)
        # Иначе экранируем точку
        return match.group(0).replace('.', r'\.')

    # Применяем экранирование точек только вне формата дат
    text = re.sub(r'\d*\.\d*\.\d*|\S*\.\S*', escape_dots, text)

    return text
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
        await message.reply(f"❌ Ошибка: {escape_markdown(str(e))}. Попробуйте снова.")


@router.message(EventCreation.DESCRIPTION)
async def process_description(message: Message, state: FSMContext):
    try:
        tomorrow = (datetime.now(pytz.timezone("EET")) + timedelta(days=1)).strftime("%d.%m.%Y %H:%M")
        Event(description=message.text, title="test", date=tomorrow)
        await state.update_data(description=message.text.strip())
        await state.set_state(EventCreation.DATE)
        current_date = datetime.now(pytz.timezone("EET"))
        # Use current_date.year and current_date.month instead of undefined year and month
        calendar_text = f"📅 Выберите дату события ({escape_markdown(datetime(current_date.year, current_date.month, 1).strftime('%B %Y'))}):"
        await message.reply(
            calendar_text,
            reply_markup=create_calendar(current_date.year, current_date.month)
        )
    except ValueError as e:
        await message.reply(f"❌ Ошибка: {escape_markdown(str(e))}. Попробуйте снова.")

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
        calendar_text = f"📅 Выберите дату события ({escape_markdown(datetime(year, month, 1).strftime('%B %Y'))}):"

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
        await callback.message.answer(
            f"❌ Ошибка при обновлении календаря: {escape_markdown(str(e))}. Попробуйте снова.")
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
        await callback.message.answer(f"❌ Ошибка при выборе даты: {escape_markdown(str(e))}. Попробуйте снова.")
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
        await callback.message.answer(f"❌ Ошибка: {escape_markdown(str(e))}. Попробуйте снова.")
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
        await message.answer(f"❌ Ошибка: {escape_markdown(str(e))}. Введите время в формате ЧЧ:ММ (например, 17:33).")


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
        event = Event(title=data["title"], description=data["description"], date=data["date"],
                      image_id=data.get("image_id"))
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

            text = f"📅 **{escape_markdown(event.title)}**\n\n{escape_markdown(event.description)}\n\n🕒 **Дата и время**: {escape_markdown(event.date)}"
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
                await db.execute("UPDATE events SET message_id = ? WHERE event_id = ?",
                                 (message_sent.message_id, event_id))
                await db.commit()
            except Exception as e:
                logger.error(f"Error sending to channel: {e}")
                await message.reply(f"❌ Ошибка: {escape_markdown(str(e))}. Проверьте доступность канала.")
                await db.execute("DELETE FROM events WHERE event_id = ?", (event_id,))
                await db.commit()
                return

        await message.reply("🎉 Событие создано и опубликовано в канале!", reply_markup=start_keyboard())
        await state.clear()
    except ValueError as e:
        await message.reply(f"❌ Ошибка: {escape_markdown(str(e))}. Попробуйте снова.")
    except Exception as e:
        logger.error(f"Error saving event: {e}")
        await message.reply(f"❌ Произошла ошибка при создании события: {escape_markdown(str(e))}. Попробуйте снова.")


async def show_events(message: Message):
    async with aiosqlite.connect("events.db") as db:
        cursor = await db.execute("SELECT event_id, title, date FROM events ORDER BY date")
        events = await cursor.fetchall()
        if not events:
            await message.reply("📭 Нет активных событий.")
            return
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"📅 {escape_markdown(title)} ({escape_markdown(date)})",
                                  callback_data=f"view_{event_id}")]
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

        # Escape markdown characters
        title = escape_markdown(title)
        description = escape_markdown(description)
        date = escape_markdown(date)

        cursor = await db.execute(
            "SELECT username, participation_status FROM participants WHERE event_id = ? AND participation_status = 'Участвую'",
            (event_id,)
        )
        participants = await cursor.fetchall()
        participants_text = "\n".join(
            f"👤 @{escape_markdown(username)}" for username, _ in participants) or "🚶‍♂️ Нет участников."

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
async def handle_participation(callback: CallbackQuery, bot: Bot):
    """Обрабатывает нажатия кнопок 'Участвую' и 'Не участвую' с уведомлениями."""
    action, event_id = callback.data.split("_")
    event_id = int(event_id)
    user_id = callback.from_user.id
    username = callback.from_user.username or callback.from_user.first_name
    new_status = "Участвую" if action == "join" else "Не участвую"

    try:
        async with aiosqlite.connect("events.db") as db:
            # Проверяем существование события и получаем message_id
            async with db.execute(
                    "SELECT message_id FROM events WHERE event_id = ?",
                    (event_id,)
            ) as cursor:
                event = await cursor.fetchone()
                if not event:
                    await callback.answer("❌ Событие не найдено.", show_alert=True)
                    return
                message_id = event[0]

            # Проверяем текущий статус пользователя
            async with db.execute(
                    "SELECT participation_status FROM participants WHERE event_id = ? AND user_id = ?",
                    (event_id, user_id)
            ) as cursor:
                current_status = await cursor.fetchone()

            # Проверяем условия для уведомлений
            if current_status and current_status[0] == new_status:
                await callback.answer(
                    f"ℹ️ Вы уже отметили: {new_status}.",
                    show_alert=True
                )
                return
            if action == "decline" and not current_status:
                await callback.answer(
                    "ℹ️ Вы ещё не были участником этого события.",
                    show_alert=True
                )
                return

            # Обновляем или вставляем статус участия
            await db.execute(
                """
                INSERT OR REPLACE INTO participants (event_id, user_id, username, participation_status)
                VALUES (?, ?, ?, ?)
                """,
                (event_id, user_id, username, new_status)
            )

            # Подсчитываем количество участников
            async with db.execute(
                    """
                    SELECT participation_status, COUNT(*)
                    FROM participants
                    WHERE event_id = ?
                    GROUP BY participation_status
                    """,
                    (event_id,)
            ) as cursor:
                counts = {status: count for status, count in await cursor.fetchall()}

            join_count = counts.get("Участвую", 0)
            decline_count = counts.get("Не участвую", 0)

            # Сохраняем изменения в базе
            await db.commit()

        # Планируем обновление клавиатуры
        await schedule_keyboard_update(event_id, join_count, decline_count, bot, message_id)

        # Уведомляем только при значимом изменении статуса
        should_notify = (
            (current_status is None and action == "join") or
            (current_status and current_status[0] == "Участвую" and action == "decline") or
            (current_status and current_status[0] == "Не участвую" and action == "join")
        )
        if should_notify:
            logger.info(f"User @{username} changed status to {new_status} for event_id={event_id}")
            await callback.answer(
                f"ℹ️ Вы отметили: {new_status}.",
                show_alert=True
            )

    except Exception as e:
        logger.error(f"Error in handle_participation: {e}", exc_info=True)
        await callback.answer(
            f"❌ Ошибка: {escape_markdown(str(e))[:100]}. Попробуйте снова.",
            show_alert=True
        )


@router.errors()
async def errors_handler(update, exception=None):
    logger.error(f"Ошибка: {exception}", exc_info=True)
    error_msg = escape_markdown(str(exception)[:200] if exception else "Неизвестная ошибка")
    if isinstance(update, Message):
        await update.reply(f"❌ Ошибка: {error_msg}. Попробуйте снова.")
    elif isinstance(update, CallbackQuery):
        await update.message.reply(f"❌ Ошибка: {error_msg}. Попробуйте снова.")
    return True