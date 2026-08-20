import asyncio
import ssl
import time

from xray_manager import deep_check


async def tcp_check(host: str, port: int, timeout: float):
    """Проверяет доступность порта. Возвращает (alive, latency_ms).
    ВНИМАНИЕ: открытый TCP-порт не гарантирует, что за ним реально работает прокси —
    смотри tls_check и deep_check ниже."""
    start = time.monotonic()
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=timeout
        )
        latency = (time.monotonic() - start) * 1000
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        return True, round(latency, 1)
    except Exception:
        return False, None


async def tls_check(host: str, port: int, timeout: float, sni: str = None):
    """TLS-хендшейк поверх открытого порта. Ловит случаи, когда порт открыт
    (например, DPI/firewall отвечает вместо реального сервера), но нормального
    TLS-сертификата/handshake за ним нет."""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    start = time.monotonic()
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port, ssl=ctx, server_hostname=sni or host),
            timeout=timeout,
        )
        latency = (time.monotonic() - start) * 1000
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        return True, round(latency, 1)
    except Exception:
        return False, None


async def icmp_ping(host: str, timeout: float) -> bool:
    """Информационная проверка. Провайдер часто режет ICMP, поэтому False здесь
    НЕ считается признаком мёртвого сервера — итоговый вердикт строится по
    tcp/tls/deep."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "ping", "-c", "1", "-W", str(max(1, int(timeout))), host,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.wait_for(proc.wait(), timeout=timeout + 2)
        return proc.returncode == 0
    except Exception:
        return False


async def check_config(entry, semaphore: asyncio.Semaphore, deep_semaphore: asyncio.Semaphore, cfg):
    # --- быстрые проверки (tcp/tls/ping) под общим лимитом concurrency ---
    async with semaphore:
        alive, latency = await tcp_check(entry.host, entry.port, cfg.TCP_TIMEOUT)
        entry.alive = alive
        entry.latency = latency

        if alive and cfg.ENABLE_ICMP_PING:
            entry.ping_ok = await icmp_ping(entry.host, cfg.PING_TIMEOUT)

        if alive and entry.security in ("tls", "reality"):
            tls_ok, tls_latency = await tls_check(
                entry.host, entry.port, cfg.TCP_TIMEOUT, sni=entry.sni
            )
            entry.tls_ok = tls_ok
            entry.tls_latency = tls_latency
            if not tls_ok:
                # порт открыт, но TLS не поднимается — считаем нерабочим
                entry.alive = False

    # --- тяжёлая проверка через xray-core, отдельный (меньший) лимит concurrency ---
    if entry.alive and cfg.ENABLE_DEEP_CHECK:
        async with deep_semaphore:
            deep = await deep_check(entry, cfg)
        entry.deep_ok = deep["deep_ok"]
        entry.deep_status = deep["deep_status"]
        entry.deep_latency = deep["deep_latency"]
        entry.deep_error = deep["deep_error"]

        # если deep-check реально смог выполниться (бинарь есть, протокол поддержан) —
        # его результат становится финальным вердиктом, т.к. это самая точная проверка
        if cfg.DEEP_CHECK_AUTHORITATIVE and entry.deep_error is None:
            entry.alive = entry.deep_ok

    return entry
