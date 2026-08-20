import os

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
TELEGRAM_PROXY_HOST = os.getenv("TELEGRAM_PROXY_HOST", "")

# GitHub — хранилище файлов с подписками
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_REPO = os.getenv("GITHUB_REPO", "")  # формат: owner/repo
SUBSCRIPTIONS_FILE = os.getenv("SUBSCRIPTIONS_FILE", "subscriptions.txt")  # файл с ключами в репо
