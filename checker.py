"""
checker.py — проверяет работоспособность VPN-сервера из VLESS/SS/Trojan ключа.

Шаги:
1. Парсинг ключа → IP + порт
2. Ping (ICMP через subprocess)
3. TCP connect на порт (аналог nc -zv)
"""

import asyncio
import re
import subprocess
from urllib.parse import urlparse


# ───────────────────────────── парсинг URI ────────────────────────────────

def parse_server_from_key(key: str) -> tuple[str, int] | tuple[None, None]:
    """
    Вытаскивает (host, port) из ключей вида:
      vless://uuid@host:port?...
      ss://...@host:port#...
      trojan://pass@host:port?...
      vmess://base64...  (пока не поддержан — вернёт None)
    """
    key = key.strip()
    try:
        parsed = urlparse(key)
        host = parsed.hostname
        port = parsed.port
        if host and port:
            return host, port
    except Exception:
        pass
    return None, None


# ─────────────────────────────── ping ────────────────────────────────────

async def ping_host(host: str, count: int = 3, timeout: int = 3) -> dict:
    """
    Запускает ping через subprocess (работает и на Linux).
    Возвращает: {"ok": bool, "loss": int, "avg_ms": float | None, "raw": str}
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            "ping", "-c", str(count), "-W", str(timeout), host,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout * count + 5)
        output = stdout.decode(errors="ignore")

        loss = 100
        avg_ms = None

        loss_match = re.search(r"(\d+)%\s+packet loss", output)
        if loss_match:
            loss = int(loss_match.group(1))

        rtt_match = re.search(r"rtt .+?= [\d.]+/([\d.]+)/", output)
        if rtt_match:
            avg_ms = float(rtt_match.group(1))

        return {"ok": loss < 100, "loss": loss, "avg_ms": avg_ms, "raw": output[:300]}
    except Exception as e:
        return {"ok": False, "loss": 100, "avg_ms": None, "raw": str(e)}


# ──────────────────────────── TCP port check ──────────────────────────────

async def check_port(host: str, port: int, timeout: float = 5.0) -> bool:
    """
    Пытается открыть TCP-соединение. Аналог: nc -zv host port
    """
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port),
            timeout=timeout,
        )
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        return True
    except Exception:
        return False


# ──────────────────────────── главная функция ─────────────────────────────

async def check_key(key: str) -> dict:
    """
    Полная проверка одного ключа.
    Возвращает словарь:
      {
        "key": str,
        "host": str | None,
        "port": int | None,
        "ping_ok": bool,
        "ping_loss": int,
        "ping_ms": float | None,
        "port_ok": bool,
        "alive": bool,       # итог: порт доступен
        "summary": str,      # человекочитаемый итог
      }
    """
    host, port = parse_server_from_key(key)
    result = {
        "key": key,
        "host": host,
        "port": port,
        "ping_ok": False,
        "ping_loss": 100,
        "ping_ms": None,
        "port_ok": False,
        "alive": False,
        "summary": "",
    }

    if not host or not port:
        result["summary"] = "❌ Не удалось распарсить хост/порт из ключа"
        return result

    ping_res, port_ok = await asyncio.gather(
        ping_host(host),
        check_port(host, port),
    )

    result["ping_ok"] = ping_res["ok"]
    result["ping_loss"] = ping_res["loss"]
    result["ping_ms"] = ping_res["avg_ms"]
    result["port_ok"] = port_ok
    result["alive"] = port_ok  # порт — основной критерий; ping ICMP часто закрыт

    parts = []
    if ping_res["ok"]:
        ms = f"{ping_res['avg_ms']:.0f} мс" if ping_res["avg_ms"] else "?"
        parts.append(f"🏓 Ping: {ms}, потери {ping_res['loss']}%")
    else:
        parts.append(f"🏓 Ping: нет ответа (ICMP может быть закрыт)")

    parts.append(f"🔌 Порт {port}: {'✅ открыт' if port_ok else '❌ недоступен'}")
    result["summary"] = "\n".join(parts)

    return result
