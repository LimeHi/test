import asyncio
import logging
from dataclasses import dataclass, field

from aiogram.types import BufferedInputFile
from aiogram.exceptions import TelegramBadRequest

from checker import check_config
from flags import build_display_name, rebrand_raw

log = logging.getLogger("queue_manager")


@dataclass
class Job:
    user_id: int
    chat_id: int
    message_id: int
    entries: list
    custom_text: str = ""


class JobQueue:
    def __init__(self, bot, cfg):
        self.bot = bot
        self.cfg = cfg
        self.queue: asyncio.Queue[Job] = asyncio.Queue()
        self.active_users: set[int] = set()

    def start(self):
        asyncio.create_task(self._worker())

    async def submit(self, job: Job) -> bool:
        if job.user_id in self.active_users:
            return False
        self.active_users.add(job.user_id)
        await self.queue.put(job)
        return True

    def position_of(self, job: Job) -> int:
        return self.queue.qsize()

    async def _worker(self):
        while True:
            job = await self.queue.get()
            try:
                await self._process(job)
            except Exception:
                log.exception("job failed for user %s", job.user_id)
                await self._safe_edit(job, "Что-то пошло не так при проверке. Попробуй ещё раз.")
            finally:
                self.active_users.discard(job.user_id)
                self.queue.task_done()

    async def _safe_edit(self, job: Job, text: str):
        try:
            await self.bot.edit_message_text(text, chat_id=job.chat_id, message_id=job.message_id)
        except TelegramBadRequest:
            pass

    async def _process(self, job: Job):
        total = len(job.entries)
        await self._safe_edit(job, f"Проверяю серверы: 0/{total}...")

        semaphore = asyncio.Semaphore(self.cfg.CHECK_CONCURRENCY)
        deep_semaphore = asyncio.Semaphore(self.cfg.DEEP_CHECK_CONCURRENCY)
        tasks = [
            asyncio.create_task(check_config(e, semaphore, deep_semaphore, self.cfg))
            for e in job.entries
        ]

        done = 0
        step = max(1, total // 10)
        deep_note = " (+ deep-check)" if self.cfg.ENABLE_DEEP_CHECK else ""
        for coro in asyncio.as_completed(tasks):
            await coro
            done += 1
            if done % step == 0 or done == total:
                await self._safe_edit(job, f"Проверяю серверы{deep_note}: {done}/{total}...")

        await self._finish(job)

    def _format_line(self, e, custom_text: str) -> str:
        mark = "✅" if e.alive else "❌"
        lat = f"{e.latency}ms" if e.latency is not None else "-"
        bits = [f"{mark} {e.host}:{e.port}", e.protocol, lat]

        if e.tls_ok is not None:
            bits.append(f"TLS:{'✅' if e.tls_ok else '❌'}")

        if e.deep_ok is not None:
            status = f"{e.deep_status}" if e.deep_status else "-"
            bits.append(f"DEEP:{'✅' if e.deep_ok else '❌'}({status},{e.deep_latency}ms)")
        elif e.deep_error and self.cfg.ENABLE_DEEP_CHECK:
            bits.append(f"DEEP:skip({e.deep_error})")

        if e.ping_ok is not None:
            bits.append(f"ping:{'✅' if e.ping_ok else '❌'}")

        name = build_display_name(e, custom_text)
        if name:
            bits.append(name)

        return " | ".join(bits)

    async def _finish(self, job: Job):
        working = [e for e in job.entries if e.alive]
        working.sort(key=lambda e: e.latency if e.latency is not None else 9999)
        dead_count = len(job.entries) - len(working)

        report_lines = [self._format_line(e, job.custom_text) for e in job.entries]
        report_text = "\n".join(report_lines) if report_lines else "Пусто"
        report_file = BufferedInputFile(report_text.encode("utf-8"), filename="report.txt")
        await self.bot.send_document(job.chat_id, report_file, caption="Полный отчёт по всем серверам")

        if working:
            sub_text = "\n".join(rebrand_raw(e, job.custom_text) for e in working)
            sub_file = BufferedInputFile(sub_text.encode("utf-8"), filename="working_configs.txt")
            caption = f"Рабочие конфиги: {len(working)}"
            if job.custom_text:
                caption += f" (имена: флаг + «{job.custom_text}»)"
            await self.bot.send_document(job.chat_id, sub_file, caption=caption)

        deep_summary = ""
        if self.cfg.ENABLE_DEEP_CHECK:
            deep_ran = [e for e in job.entries if e.deep_ok is not None]
            if deep_ran:
                deep_summary = f"\nDeep-check пройден: {sum(1 for e in deep_ran if e.deep_ok)}/{len(deep_ran)}"

        await self._safe_edit(
            job,
            "Готово!\n"
            f"Всего проверено: {len(job.entries)}\n"
            f"✅ Рабочих: {len(working)}\n"
            f"❌ Нерабочих: {dead_count}"
            f"{deep_summary}",
        )
