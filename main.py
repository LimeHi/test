import asyncio
import logging

import aiohttp
from aiogram import Bot, Dispatcher, Router, F
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

import config as cfg
from parser import parse_subscription
from queue_manager import JobQueue, Job

logging.basicConfig(level=logging.INFO)
router = Router()
job_queue: JobQueue | None = None


class SubStates(StatesGroup):
    waiting_text = State()


@router.message(Command("start"))
async def start_handler(message: Message):
    checks = "TCP"
    if cfg.ENABLE_ICMP_PING:
        checks += " + ICMP ping (информационно)"
    checks += " + TLS-хендшейк (для tls/reality)"
    if cfg.ENABLE_DEEP_CHECK:
        checks += " + deep-check через xray-core (реальный HTTP-запрос сквозь прокси, ловит DPI)"

    await message.answer(
        "Привет! Пришли мне подписку VPN — ссылкой, .txt файлом или base64-текстом.\n\n"
        f"Проверка: {checks}.\n"
        f"Максимум {cfg.MAX_CONFIGS} конфигов за раз.\n\n"
        "После проверки пришлю report.txt (все сервера) и working_configs.txt "
        "(только рабочие, отсортированы по задержке)."
    )


@router.message(Command("queue"))
async def queue_handler(message: Message):
    if job_queue is None:
        return
    size = job_queue.queue.qsize()
    busy = message.from_user.id in job_queue.active_users
    text = f"В очереди: {size}"
    if busy:
        text += "\nТвоя задача уже в обработке."
    await message.answer(text)


# --- шаг "спросить свой текст к именам" ---

@router.message(SubStates.waiting_text, Command("skip"))
async def skip_custom_text(message: Message, state: FSMContext):
    data = await state.get_data()
    await _start_job(message, data["entries"], custom_text="")
    await state.clear()


@router.message(SubStates.waiting_text, F.text)
async def set_custom_text(message: Message, state: FSMContext):
    data = await state.get_data()
    await _start_job(message, data["entries"], custom_text=message.text.strip())
    await state.clear()


# --- приём подписки ---

@router.message(F.document)
async def document_handler(message: Message, state: FSMContext):
    file = await message.bot.get_file(message.document.file_id)
    buf = await message.bot.download_file(file.file_path)
    content = buf.read().decode("utf-8", errors="ignore")
    await handle_subscription(message, content, state)


@router.message(F.text)
async def text_handler(message: Message, state: FSMContext):
    text = message.text.strip()
    if text.startswith("http://") or text.startswith("https://"):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(text, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    content = await resp.text(errors="ignore")
        except Exception:
            await message.answer("Не удалось скачать подписку по ссылке.")
            return
    else:
        content = text
    await handle_subscription(message, content, state)


async def handle_subscription(message: Message, content: str, state: FSMContext):
    entries = parse_subscription(content, cfg.MAX_CONFIGS)
    if not entries:
        await message.answer(
            "Не нашёл ни одного конфига (vless/vmess/trojan/ss/ssr) в этой подписке."
        )
        return

    await state.update_data(entries=entries)
    await state.set_state(SubStates.waiting_text)
    await message.answer(
        f"Найдено {len(entries)} конфигов.\n\n"
        "Хочешь добавить свой текст к именам итоговых конфигов? "
        "Флаг страны (если он был в названии) сохранится, текст добавится рядом.\n"
        "Пришли текст, или отправь /skip, чтобы оставить имена как есть."
    )


async def _start_job(message: Message, entries: list, custom_text: str):
    status_msg = await message.answer("Ставлю в очередь...")

    job = Job(
        user_id=message.from_user.id,
        chat_id=message.chat.id,
        message_id=status_msg.message_id,
        entries=entries,
        custom_text=custom_text,
    )

    accepted = await job_queue.submit(job)
    if not accepted:
        await status_msg.edit_text(
            "У тебя уже есть задача в обработке. Дождись её завершения, потом пришли новую."
        )
        return

    position = job_queue.position_of(job)
    if position > 0:
        await status_msg.edit_text(f"В очереди. Позиция: {position}. Ожидай...")


def build_bot():
    if cfg.TELEGRAM_PROXY_HOST:
        proxy_api = TelegramAPIServer.from_base(f"https://{cfg.TELEGRAM_PROXY_HOST}")
        session = AiohttpSession(api=proxy_api)
        session._connector_init["ssl"] = False
        return Bot(token=cfg.BOT_TOKEN, session=session)
    return Bot(token=cfg.BOT_TOKEN)


async def main():
    global job_queue
    if not cfg.BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN не задан в переменных окружения")

    bot = build_bot()
    dp = Dispatcher()
    dp.include_router(router)

    job_queue = JobQueue(bot, cfg)
    job_queue.start()

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
