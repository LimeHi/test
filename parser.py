import base64
import json
from dataclasses import dataclass
from urllib.parse import urlparse, parse_qs, unquote

SCHEMES = ("vless://", "vmess://", "trojan://", "ss://", "ssr://")


@dataclass
class ConfigEntry:
    raw: str
    protocol: str
    host: str = None
    port: int = None
    name: str = ""

    # параметры, нужные для TLS/DPI-проверок
    security: str = "none"   # none | tls | reality
    sni: str = ""
    network: str = "tcp"     # tcp | ws | grpc | xhttp | http

    # результаты проверок
    alive: bool = False
    latency: float = None
    ping_ok: bool = None
    tls_ok: bool = None
    tls_latency: float = None
    deep_ok: bool = None
    deep_status: int = None
    deep_latency: float = None
    deep_error: str = None


def _b64_decode(s: str) -> str:
    s = s.strip()
    padded = s + "=" * (-len(s) % 4)
    return base64.b64decode(padded).decode("utf-8", errors="ignore")


def decode_subscription(content: str) -> str:
    """Подписка обычно приходит как base64-блоб. Если это не base64 —
    считаем, что это уже голый список ссылок построчно."""
    content = content.strip()
    try:
        decoded = _b64_decode(content)
        if "://" in decoded:
            return decoded
    except Exception:
        pass
    return content


def parse_line(line: str) -> ConfigEntry | None:
    line = line.strip()
    if not line or not line.startswith(SCHEMES):
        return None

    scheme = line.split("://", 1)[0]
    entry = ConfigEntry(raw=line, protocol=scheme)

    try:
        if scheme == "vmess":
            body = line[len("vmess://"):]
            data = json.loads(_b64_decode(body))
            entry.host = data.get("add")
            entry.port = int(data.get("port"))
            entry.name = data.get("ps", "")
            tls_val = (data.get("tls") or "").lower()
            entry.security = "tls" if tls_val == "tls" else ("reality" if tls_val == "reality" else "none")
            entry.sni = data.get("sni") or data.get("host") or entry.host
            entry.network = data.get("net", "tcp")

        elif scheme in ("vless", "trojan"):
            parsed = urlparse(line)
            qs = parse_qs(parsed.query)
            host, port = parsed.hostname, parsed.port

            if not host or not port:
                host, port = None, None  # у vless/trojan адрес всегда в открытом виде

            entry.host = host
            entry.port = int(port) if port else None
            entry.name = unquote(parsed.fragment) if parsed.fragment else ""
            entry.security = qs.get("security", ["none"])[0]
            entry.sni = qs.get("sni", [host or ""])[0]
            entry.network = qs.get("type", ["tcp"])[0]

        else:  # ss / ssr
            parsed = urlparse(line)
            host, port = parsed.hostname, parsed.port

            if not host or not port:
                netloc_part = line[len(scheme) + 3:].split("#")[0]
                try:
                    decoded = _b64_decode(netloc_part)
                    if "@" in decoded:
                        hostport = decoded.rsplit("@", 1)[-1]
                        if ":" in hostport:
                            host, port_s = hostport.rsplit(":", 1)
                            port = int(port_s)
                except Exception:
                    pass

            entry.host = host
            entry.port = int(port) if port else None
            entry.name = unquote(parsed.fragment) if parsed.fragment else ""
            entry.security = "none"
    except Exception:
        return None

    if not entry.host or not entry.port:
        return None
    return entry


def parse_subscription(content: str, max_configs: int) -> list[ConfigEntry]:
    text = decode_subscription(content)
    entries: list[ConfigEntry] = []
    for line in text.splitlines():
        entry = parse_line(line)
        if entry:
            entries.append(entry)
        if len(entries) >= max_configs:
            break
    return entries
