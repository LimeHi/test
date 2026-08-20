import asyncio
import json
import os
import tempfile
import time

from config_converter import to_outbound

try:
    from aiohttp_socks import ProxyConnector
    import aiohttp
    _HAS_SOCKS = True
except ImportError:
    _HAS_SOCKS = False


def build_xray_config(outbound: dict, socks_port: int) -> dict:
    return {
        "log": {"loglevel": "none"},
        "inbounds": [{
            "listen": "127.0.0.1",
            "port": socks_port,
            "protocol": "socks",
            "settings": {"udp": False},
        }],
        "outbounds": [outbound],
    }


async def _wait_port(port: int, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            _, writer = await asyncio.open_connection("127.0.0.1", port)
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
            return True
        except Exception:
            await asyncio.sleep(0.1)
    return False


async def deep_check(entry, cfg) -> dict:
    """Реальная проверка: поднимает локальный xray-core с конфигом конкретного
    сервера (SOCKS5 инбаунд) и делает HTTP GET на cfg.CHECK_URL через него.
    Если DPI режет протокол/SNI после хендшейка — этот запрос не пройдёт,
    даже если голый TCP-порт отвечал нормально."""
    result = {"deep_ok": False, "deep_status": None, "deep_latency": None, "deep_error": None}

    if not _HAS_SOCKS:
        result["deep_error"] = "не установлен пакет aiohttp_socks"
        return result
    if not cfg.XRAY_BIN or not os.path.exists(cfg.XRAY_BIN):
        result["deep_error"] = "xray-core бинарь не найден (XRAY_BIN)"
        return result

    outbound = to_outbound(entry.raw, entry.protocol)
    if not outbound:
        result["deep_error"] = "протокол/транспорт не поддержан для deep-check"
        return result

    socks_port = 20000 + (abs(hash(entry.raw)) % 20000)
    xr_config = build_xray_config(outbound, socks_port)

    tmp_path = None
    proc = None
    try:
        fd, tmp_path = tempfile.mkstemp(suffix=".json", prefix="xr_")
        with os.fdopen(fd, "w") as f:
            json.dump(xr_config, f)

        proc = await asyncio.create_subprocess_exec(
            cfg.XRAY_BIN, "run", "-c", tmp_path,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )

        ready = await _wait_port(socks_port, cfg.XRAY_STARTUP_TIMEOUT)
        if not ready:
            result["deep_error"] = "xray не успел подняться"
            return result

        connector = ProxyConnector.from_url(f"socks5://127.0.0.1:{socks_port}")
        start = time.monotonic()
        async with aiohttp.ClientSession(connector=connector) as session:
            async with session.get(
                cfg.CHECK_URL, timeout=aiohttp.ClientTimeout(total=cfg.DEEP_CHECK_TIMEOUT)
            ) as resp:
                await resp.read()
                result["deep_status"] = resp.status
                result["deep_ok"] = resp.status < 400
        result["deep_latency"] = round((time.monotonic() - start) * 1000, 1)
    except Exception as e:
        result["deep_error"] = str(e)[:150]
    finally:
        if proc is not None:
            try:
                proc.kill()
                await proc.wait()
            except Exception:
                pass
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass

    return result
