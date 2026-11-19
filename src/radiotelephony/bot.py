"""Native Telegram quiz MVP; all user-visible strings are English.

Run with: python -m radiotelephony
Private chats only; poll_answer events are persisted in SQLite.
"""

import asyncio
import json
import logging

from aiogram import Bot, Dispatcher, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    PollAnswer,
)

from radiotelephony.config import BOT_TOKEN
from radiotelephony.database import initialize_database
from radiotelephony.quiz_storage import (
    book_by_selector,
    list_books,
    list_topics,
    random_question,
    record_answer,
    register_poll,
    register_user,
    user_stats,
)

logger = logging.getLogger(__name__)
router = Router()


def menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Browse Books", callback_data="books")],
            [InlineKeyboardButton(text="Random Quiz", callback_data="r")],
            [InlineKeyboardButton(text="Choose Difficulty", callback_data="diff")],
            [InlineKeyboardButton(text="My Statistics", callback_data="stats")],
        ]
    )


def next_keyboard(scope: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Next Question", callback_data=f"n:{scope}")],
            [InlineKeyboardButton(text="Main Menu", callback_data="menu")],
        ]
    )


def back_keyboard() -> list[InlineKeyboardButton]:
    return [InlineKeyboardButton(text="Main Menu", callback_data="menu")]


async def track_user(user) -> None:
    await register_user(
        user.id,
        user.username,
        user.first_name,
        user.language_code,
    )


async def show_books(bot: Bot, user_id: int) -> None:
    books = await list_books()
    if not books:
        await bot.send_message(user_id, "No active question books are available yet.")
        return
    keyboard = [
        [InlineKeyboardButton(
            text=f"{book['title']} ({book['count']})",
            callback_data=f"b:{book['selector']}",
        )]
        for book in books
    ]
    keyboard.append(back_keyboard())
    await bot.send_message(
        user_id,
        "Select a book:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
    )


async def show_topics(bot: Bot, user_id: int, selector: int) -> None:
    book = await book_by_selector(selector)
    if book is None:
        await bot.send_message(user_id, "Book not found. Please select a book again.")
        return
    topics = await list_topics(selector)
    keyboard = [
        [
            InlineKeyboardButton(
                text="All Chapters — Random Quiz", callback_data=f"s:{selector}"
            )
        ]
    ]
    for topic in topics:
        title = topic["title"]
        if topic["kind"] == "chapter":
            title = f"{topic['code'].replace('chapter:', 'Chapter ')} — {title}"
        keyboard.append([
            InlineKeyboardButton(
                text=f"{title} ({topic['count']})"[:64],
                callback_data=f"t:{topic['topic_id']}",
            )
        ])
    keyboard.append([InlineKeyboardButton(text="Back to Books", callback_data="books")])
    await bot.send_message(
        user_id,
        f"{book['title']}\n\nChoose a chapter or start a random quiz:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
    )


async def show_difficulty(bot: Bot, user_id: int) -> None:
    keyboard = [
        [InlineKeyboardButton(text="Basic", callback_data="d:1")],
        [InlineKeyboardButton(text="Intermediate", callback_data="d:2")],
        [InlineKeyboardButton(text="Advanced", callback_data="d:3")],
        back_keyboard(),
    ]
    await bot.send_message(
        user_id,
        "Choose a difficulty (all books):",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
    )


async def show_stats(bot: Bot, user_id: int) -> None:
    stats = await user_stats(user_id)
    total, correct = stats["total"], stats["correct"]
    percent = (100 * correct / total) if total else 0
    await bot.send_message(
        user_id,
        f"Your Quiz Statistics\n"
        f"Questions answered: {total}\n"
        f"Correct answers: {correct}\n"
        f"Accuracy: {percent:.1f}%",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[back_keyboard()]),
    )


async def send_quiz(bot: Bot, user_id: int, scope: str) -> None:
    try:
        question = await random_question(scope)
    except ValueError:
        await bot.send_message(user_id, "Invalid quiz selection.")
        return

    if question is None:
        await bot.send_message(user_id, "No active questions match this selection.")
        return

    options = json.loads(question["options_json"])
    try:
        message = await bot.send_poll(
            chat_id=user_id,
            question=question["question_text"],
            options=options,
            type="quiz",
            is_anonymous=False,
            correct_option_id=question["answer_index"],
            reply_markup=next_keyboard(scope),
        )
    except TelegramAPIError:
        logger.exception("Telegram rejected quiz question %s", question["external_id"])
        await bot.send_message(
            user_id, "This question could not be sent. Please try another."
        )
        return

    if message.poll is None:
        logger.error(
            "Telegram returned a message without a poll: %s", message.message_id
        )
        await bot.send_message(user_id, "An error occurred while tracking this quiz.")
        return

    await register_poll(
        message.poll.id, question["question_pk"], user_id, message.message_id
    )


@router.message(CommandStart())
async def command_start(message: Message) -> None:
    if message.chat.type != "private" or message.from_user is None:
        return
    await track_user(message.from_user)
    await message.answer(
        "Welcome to Aviation Radiotelephony Quiz!\n"
        "Practice with native Telegram quizzes. Select a book or start a random quiz.",
        reply_markup=menu_keyboard(),
    )


@router.message(Command("help"))
async def command_help(message: Message) -> None:
    if message.chat.type != "private":
        return
    await message.answer(
        "Commands:\n"
        "/start — Main menu\n"
        "/books — Browse books and chapters\n"
        "/random — Random quiz\n"
        "/stats — Your statistics\n"
        "/help — Show this help\n\n"
        "Tap an answer in each Telegram quiz. Your first answer is saved automatically."
    )


@router.message(Command("books"))
async def command_books(message: Message, bot: Bot) -> None:
    if message.chat.type != "private" or message.from_user is None:
        return
    await track_user(message.from_user)
    await show_books(bot, message.from_user.id)


@router.message(Command("random"))
async def command_random(message: Message, bot: Bot) -> None:
    if message.chat.type != "private" or message.from_user is None:
        return
    await track_user(message.from_user)
    await send_quiz(bot, message.from_user.id, "r")


@router.message(Command("stats"))
async def command_stats(message: Message, bot: Bot) -> None:
    if message.chat.type != "private" or message.from_user is None:
        return
    await track_user(message.from_user)
    await show_stats(bot, message.from_user.id)


@router.callback_query()
async def on_callback(callback: CallbackQuery, bot: Bot) -> None:
    if callback.message is None or callback.message.chat.type != "private":
        await callback.answer("Open this bot in a private chat.", show_alert=True)
        return

    await callback.answer()
    await track_user(callback.from_user)
    user_id = callback.from_user.id
    action = callback.data or ""

    if action == "menu":
        await bot.send_message(user_id, "Main Menu", reply_markup=menu_keyboard())
    elif action == "books":
        await show_books(bot, user_id)
    elif action.startswith("b:") and action[2:].isdigit():
        await show_topics(bot, user_id, int(action[2:]))
    elif action == "diff":
        await show_difficulty(bot, user_id)
    elif action == "stats":
        await show_stats(bot, user_id)
    elif action == "r":
        await send_quiz(bot, user_id, "r")
    elif action.startswith("n:"):
        await send_quiz(bot, user_id, action[2:])
    elif action.startswith(("s:", "t:", "d:")):
        await send_quiz(bot, user_id, action)
    else:
        await bot.send_message(user_id, "This menu has expired. Use /start.")


@router.poll_answer()
async def on_poll_answer(answer: PollAnswer, bot: Bot) -> None:
    if answer.user is None or len(answer.option_ids) != 1:
        return
    result = await record_answer(answer.poll_id, answer.user.id, answer.option_ids[0])
    if result is None:
        return

    feedback = "Correct!" if result["correct"] else "Incorrect."
    chapter = result["reference_chapter"]
    section = result["reference_section"]
    page = result["page_printed"]
    reference = " / ".join(
        item for item in (
            f"Chapter {chapter}" if chapter is not None else None,
            f"Section {section}" if section else None,
            f"Page {page}" if page else None,
        ) if item
    )
    await bot.send_message(
        answer.user.id,
        f"{feedback}\n"
        f"Correct answer: {result['correct_option']}\n"
        f"Source: {result['source_title']}\n"
        f"Reference: {reference or 'Not specified'}\n\n"
        "Select Next Question below the quiz to continue.",
    )


@router.message()
async def other_messages(message: Message) -> None:
    if message.chat.type == "private":
        await message.answer("Choose an option using /start or /help.")


async def main() -> None:
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is missing. Set it in the local .env file.")

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    await initialize_database()
    async with Bot(token=BOT_TOKEN) as bot:
        info = await bot.get_webhook_info()
        if info.url:
            raise RuntimeError(
                "A webhook is configured. Do not disconnect the live bot; "
                "use a separate development token or plan a controlled cutover."
            )
        identity = await bot.get_me()
        logger.info("Starting Telegram quiz bot: @%s", identity.username)
        dispatcher = Dispatcher()
        dispatcher.include_router(router)
        await dispatcher.start_polling(
            bot,
            allowed_updates=["message", "callback_query", "poll_answer"],
            handle_as_tasks=False,
        )


if __name__ == "__main__":
    asyncio.run(main())
