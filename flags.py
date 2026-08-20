import base64
import json
import re
from urllib.parse import urlparse, urlunparse, quote

# emoji-флаги = пара regional indicator символов (U+1F1E6..U+1F1FF)
FLAG_RE = re.compile(r'[\U0001F1E6-\U0001F1FF]{2}')


def extract_flag(name: str) -> str:
    if not name:
        return ""
    m = FLAG_RE.search(name)
    return m.group(0) if m else ""


def build_display_name(entry, custom_text: str) -> str:
    flag = extract_flag(entry.name)
    parts = [p for p in (flag, custom_text) if p]
    return " ".join(parts) if parts else entry.name


def rebrand_raw(entry, custom_text: str) -> str:
    """Возвращает raw-ссылку конфига с новым именем (флаг из оригинала сохраняется)."""
    if not custom_text:
        return entry.raw

    new_name = build_display_name(entry, custom_text)
    if not new_name:
        return entry.raw

    if entry.protocol == "vmess":
        try:
            body = entry.raw[len("vmess://"):]
            padded = body + "=" * (-len(body) % 4)
            data = json.loads(base64.b64decode(padded).decode("utf-8", errors="ignore"))
            data["ps"] = new_name
            new_body = base64.b64encode(json.dumps(data).encode("utf-8")).decode("utf-8")
            return f"vmess://{new_body}"
        except Exception:
            return entry.raw
    else:
        try:
            parsed = urlparse(entry.raw)
            new_fragment = quote(new_name)
            return urlunparse(parsed._replace(fragment=new_fragment))
        except Exception:
            return entry.raw
