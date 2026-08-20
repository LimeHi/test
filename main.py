"""
main.py — LimeVPN Key Bot
Бот раздаёт VPN-ключи из файла подписок на GitHub,
предварительно проверяя работоспособность сервера.
"""

import asyncio
import logging

from aiogram import Bot, Dispatcher, F
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

import config as cfg
from checker import check_key
from github_storage import REGION_ALIASES, get_all_keys, get_keys_by_region

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# ─────────────────────────────── bot init ────────────────────────────────

def build_bot() -> Bot:
    if cfg.TELEGRAM_PROXY_HOST:
        proxy_api = TelegramAPIServer.from_base(f"https://{cfg.TELEGRAM_PROXY_HOST}")
        session = AiohttpSession(api=proxy_api)
        session._connector_init["ssl"] = False
        return Bot(token=cfg.BOT_TOKEN, session=session)
    return Bot(token=cfg.BOT_TOKEN)


bot = build_bot()
dp = Dispatcher()

# ────────────────────────────── keyboards ────────────────────────────────

REGION_LABELS = {
    "ru": "🇷🇺 Россия",
    "de": "🇩🇪 Германия",
    "nl": "🇳🇱 Нидерланды",
    "us": "🇺🇸 США",
    "fi": "🇫🇮 Финляндия",
    "fr": "🇫🇷 Франция",
    "gb": "🇬🇧 Великобритания",
    "jp": "🇯🇵 Япония",
    "sg": "🇸🇬 Сингапур",
}


def regions_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text=label, callback_data=f"region:{code}")]
        for code, label in REGION_LABELS.items()
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back")],
    ])


def key_keyboard(region: str, idx: int, total: int) -> InlineKeyboardMarkup:
    rows = []
    nav = []
    if idx > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"key:{region}:{idx - 1}"))
    if idx < total - 1:
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"key:{region}:{idx + 1}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton(text="🔄 Проверить", callback_data=f"check:{region}:{idx}")])
    rows.append([InlineKeyboardButton(text="◀️ К регионам", callback_data="back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ──────────────────────────────── handlers ───────────────────────────────

@dp.message(CommandStart())
async def cmd_start(msg: Message):
    await msg.answer(
        "👋 <b>LimeVPN Key Bot</b>\n\n"
        "Выбери регион, чтобы получить рабочий VPN-ключ.\n"
        "Бот проверит сервер перед выдачей.",
        parse_mode="HTML",
        reply_markup=regions_keyboard(),
    )


@dp.message(Command("keys"))
async def cmd_keys(msg: Message):
    await msg.answer("Выбери регион:", reply_markup=regions_keyboard())


# ── выбор региона ──

@dp.callback_query(F.data == "back")
async def cb_back(cb: CallbackQuery):
    await cb.message.edit_text(
        "Выбери регион:",
        reply_markup=regions_keyboard(),
    )
    await cb.answer()


@dp.callback_query(F.data.startswith("region:"))
async def cb_region(cb: CallbackQuery):
    region = cb.data.split(":")[1]
    label = REGION_LABELS.get(region, region.upper())

    await cb.message.edit_text(f"⏳ Ищу ключи для {label}…")
    await cb.answer()

    keys = await get_keys_by_region(region)
    if not keys:
        await cb.message.edit_text(
            f"😔 Ключи для {label} не найдены в файле подписок.",
            reply_markup=back_keyboard(),
        )
        return

    await _show_key(cb.message, region, keys, idx=0, edit=True)


# ── навигация по ключам ──

@dp.callback_query(F.data.startswith("key:"))
async def cb_key_nav(cb: CallbackQuery):
    _, region, idx_str = cb.data.split(":")
    idx = int(idx_str)

    keys = await get_keys_by_region(region)
    if not keys:
        await cb.answer("Ключи не найдены", show_alert=True)
        return

    await _show_key(cb.message, region, keys, idx=min(idx, len(keys) - 1), edit=True)
    await cb.answer()


# ── проверка ──

@dp.callback_query(F.data.startswith("check:"))
async def cb_check(cb: CallbackQuery):
    _, region, idx_str = cb.data.split(":")
    idx = int(idx_str)

    keys = await get_keys_by_region(region)
    if not keys or idx >= len(keys):
        await cb.answer("Ключ не найден", show_alert=True)
        return

    key = keys[idx]
    await cb.message.edit_text(f"🔍 Проверяю сервер…\n\n<code>{_short_key(key)}</code>", parse_mode="HTML")
    await cb.answer()

    res = await check_key(key)
    status = "✅ Сервер доступен" if res["alive"] else "❌ Сервер недоступен"
    text = (
        f"{status}\n\n"
        f"🌐 <b>Хост:</b> <code>{res['host']}</code>\n"
        f"🔌 <b>Порт:</b> {res['port']}\n\n"
        f"{res['summary']}\n\n"
        f"🔑 <b>Ключ:</b>\n<code>{key}</code>"
    )
    await cb.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=key_keyboard(region, idx, len(keys)),
    )


# ─────────────────────────────── helpers ─────────────────────────────────

async def _show_key(message: Message, region: str, keys: list[str], idx: int, edit: bool = False):
    key = keys[idx]
    label = REGION_LABELS.get(region, region.upper())
    text = (
        f"🔑 <b>{label}</b> — ключ {idx + 1}/{len(keys)}\n\n"
        f"<code>{key}</code>\n\n"
        f"Нажми <b>🔄 Проверить</b>, чтобы убедиться, что сервер работает."
    )
    kb = key_keyboard(region, idx, len(keys))
    if edit:
        await message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    else:
        await message.answer(text, parse_mode="HTML", reply_markup=kb)


def _short_key(key: str, max_len: int = 60) -> str:
    return key if len(key) <= max_len else key[:max_len] + "…"


# ─────────────────────────────── admin ───────────────────────────────────

@dp.message(Command("admin"))
async def cmd_admin(msg: Message):
    if msg.from_user.id != cfg.ADMIN_ID:
        return
    all_keys = await get_all_keys()
    await msg.answer(
        f"📊 <b>Статус хранилища</b>\n\n"
        f"Всего ключей в файле: <b>{len(all_keys)}</b>",
        parse_mode="HTML",
    )


@dp.message(Command("checkall"))
async def cmd_checkall(msg: Message):
    """Проверяет все ключи и выводит сводку (только для админа)."""
    if msg.from_user.id != cfg.ADMIN_ID:
        return

    all_keys = await get_all_keys()
    if not all_keys:
        await msg.answer("Ключей нет.")
        return

    status_msg = await msg.answer(f"⏳ Проверяю {len(all_keys)} ключей…")

    results = await asyncio.gather(*[check_key(k) for k in all_keys])
    alive = [r for r in results if r["alive"]]
    dead = [r for r in results if not r["alive"]]

    lines = [f"✅ Живых: {len(alive)} / ❌ Мёртвых: {len(dead)}\n"]
    for r in dead:
        lines.append(f"❌ {r['host']}:{r['port']}")

    await status_msg.edit_text("\n".join(lines)[:4000])


# ──────────────────────────────── main ───────────────────────────────────

async def main():
    log.info("Starting LimeVPN Key Bot…")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
