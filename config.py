import os

BOT_TOKEN = os.getenv("BOT_TOKEN", "")

# Максимум конфигов из одной подписки за раз
MAX_CONFIGS = int(os.getenv("MAX_CONFIGS", "500"))

# Concurrency для быстрых проверок (tcp/tls/ping)
CHECK_CONCURRENCY = int(os.getenv("CHECK_CONCURRENCY", "50"))

# Concurrency для тяжёлой проверки через xray-core (каждая — отдельный процесс!)
DEEP_CHECK_CONCURRENCY = int(os.getenv("DEEP_CHECK_CONCURRENCY", "8"))

# Таймауты
TCP_TIMEOUT = float(os.getenv("TCP_TIMEOUT", "3"))
PING_TIMEOUT = float(os.getenv("PING_TIMEOUT", "1"))
DEEP_CHECK_TIMEOUT = float(os.getenv("DEEP_CHECK_TIMEOUT", "6"))
XRAY_STARTUP_TIMEOUT = float(os.getenv("XRAY_STARTUP_TIMEOUT", "2"))

# ICMP ping — часто режется провайдером, поэтому НЕ влияет на итоговый вердикт "жив/мёртв",
# только информационное поле в отчёте
ENABLE_ICMP_PING = os.getenv("ENABLE_ICMP_PING", "1") == "1"

# Deep-check через реальный xray-core процесс + HTTP-запрос сквозь прокси.
# Это самый точный, но и самый тяжёлый уровень проверки (ловит DPI-блокировки).
ENABLE_DEEP_CHECK = os.getenv("ENABLE_DEEP_CHECK", "0") == "1"
XRAY_BIN = os.getenv("XRAY_BIN", "./bin/xray")
CHECK_URL = os.getenv("CHECK_URL", "https://cp.cloudflare.com/generate_204")

# Если True — итоговый вердикт "жив/мёртв" берётся из deep-check (когда он реально выполнился),
# а не из TCP/TLS. Это и есть защита от "TCP врёт, порт открыт а прокси не работает".
DEEP_CHECK_AUTHORITATIVE = os.getenv("DEEP_CHECK_AUTHORITATIVE", "1") == "1"
