import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN: str = os.environ["BOT_TOKEN"]
BOT_API_ROOT: str = os.getenv("BOT_API_ROOT", "https://api.respegram.ru")

_raw_db = os.environ["DATABASE_URL"]
DATABASE_URL: str = (
    _raw_db.replace("postgres://", "postgresql+asyncpg://", 1)
           .replace("postgresql://", "postgresql+asyncpg://", 1)
)

ADMIN_USERNAMES: list[str] = [
    u.strip().lstrip("@").lower()
    for u in os.getenv("ADMIN_USERNAMES", "").split(",")
    if u.strip()
]

PORT: int = int(os.getenv("PORT", "3000"))

# Юзернейм, куда пишет юзер за бесплатным NFT после одобрения. Если не задан — @support.
NFT_CONTACT: str = os.getenv("NFT_CONTACT", "@support")
