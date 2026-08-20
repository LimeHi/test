"""
github_storage.py — читает файл подписок из GitHub репозитория.
Файл содержит VPN-ключи (по одному на строку или base64-список).
"""

import aiohttp
import base64
import re
import config as cfg

GITHUB_RAW = "https://api.github.com/repos/{repo}/contents/{path}"

# Синонимы регионов для поиска в ключах/именах
REGION_ALIASES = {
    "ru": [
        "россия", "russia", "ru", "🇷🇺", "рф", "moscow", "москва",
        "spb", "питер", "saint-petersburg", "msk",
    ],
    "de": ["germany", "германия", "de", "🇩🇪", "berlin", "берлин", "frankfurt"],
    "nl": ["netherlands", "нидерланды", "nl", "🇳🇱", "amsterdam", "амстердам"],
    "us": ["usa", "united states", "us", "🇺🇸", "america", "new york", "los angeles"],
    "fi": ["finland", "финляндия", "fi", "🇫🇮", "helsinki"],
    "fr": ["france", "франция", "fr", "🇫🇷", "paris"],
    "gb": ["uk", "united kingdom", "gb", "🇬🇧", "london"],
    "jp": ["japan", "япония", "jp", "🇯🇵", "tokyo"],
    "sg": ["singapore", "сингапур", "sg", "🇸🇬"],
}

# Одна структура: code → aliases (для поиска)
def get_aliases(region_code: str) -> list[str]:
    return REGION_ALIASES.get(region_code.lower(), [region_code.lower()])


async def _fetch_github_file(path: str) -> str | None:
    """Читает файл из GitHub через API, возвращает текст."""
    url = GITHUB_RAW.format(repo=cfg.GITHUB_REPO, path=path)
    headers = {
        "Authorization": f"token {cfg.GITHUB_TOKEN}",
        "Cache-Control": "no-cache",
    }
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as resp:
            if resp.status != 200:
                return None
            data = await resp.json()
            content_b64 = data.get("content", "")
            content = base64.b64decode(content_b64).decode("utf-8", errors="ignore")
            return content


def _parse_keys(raw: str) -> list[str]:
    """
    Принимает сырой текст файла подписок.
    Поддерживает:
      - Обычный список ключей по одному на строку
      - base64-закодированный список (subscription format)
    """
    raw = raw.strip()
    # Попытка декодировать как base64 (subscription URL format)
    try:
        decoded = base64.b64decode(raw + "==").decode("utf-8", errors="ignore")
        if any(decoded.startswith(p) for p in ("vless://", "ss://", "trojan://", "vmess://")):
            raw = decoded
    except Exception:
        pass

    lines = [l.strip() for l in raw.splitlines() if l.strip()]
    keys = [l for l in lines if re.match(r"^(vless|ss|trojan|vmess)://", l)]
    return keys


def _filter_by_region(keys: list[str], region_code: str) -> list[str]:
    """
    Фильтрует ключи по региону: ищет алиасы в теге (#name) или в самом URI.
    """
    aliases = get_aliases(region_code)
    result = []
    for key in keys:
        key_lower = key.lower()
        for alias in aliases:
            if alias in key_lower:
                result.append(key)
                break
    return result


async def get_keys_by_region(region_code: str) -> list[str]:
    """
    Главная функция: читает файл из GitHub, парсит, фильтрует по региону.
    """
    raw = await _fetch_github_file(cfg.SUBSCRIPTIONS_FILE)
    if raw is None:
        return []
    all_keys = _parse_keys(raw)
    return _filter_by_region(all_keys, region_code)


async def get_all_keys() -> list[str]:
    raw = await _fetch_github_file(cfg.SUBSCRIPTIONS_FILE)
    if raw is None:
        return []
    return _parse_keys(raw)
