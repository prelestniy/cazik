# [context: Linux x86_64, Python 3.12, aiogram 3.13, asyncpg, Railway]
# *main.py — the ignition; one file, one flame*

import asyncio
import logging
from aiohttp import web

from aiogram import Bot, Dispatcher
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from config import BOT_TOKEN, BOT_API_ROOT, PORT
from models import init_db, SessionMaker
from middleware import DBMiddleware, RateLimitMiddleware, BlockMiddleware
from handlers import router
from services import seed_configs, ensure_tasks

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger(__name__)


async def on_startup(bot: Bot) -> None:
    log.info("Initialising database…")
    await init_db()
    async with SessionMaker() as session:
        await seed_configs(session)
        await ensure_tasks(session)
        await session.commit()
    info = await bot.get_me()
    log.info("Bot @%s (id=%d) is up — API root: %s", info.username, info.id, BOT_API_ROOT)


async def health(_: web.Request) -> web.Response:
    return web.Response(text="OK")


async def main() -> None:
    # ── Custom API server ──────────────────────────────────────
    session = AiohttpSession(
        api=TelegramAPIServer(
            base=f"{BOT_API_ROOT}/bot{{token}}/{{method}}",
            file=f"{BOT_API_ROOT}/file/bot{{token}}/{{path}}",
        )
    )

    bot = Bot(
        token=BOT_TOKEN,
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    dp = Dispatcher(storage=MemoryStorage())

    # Middleware order: rate-limit → db/auth → block
    dp.update.outer_middleware(RateLimitMiddleware())
    dp.update.outer_middleware(DBMiddleware())
    dp.update.outer_middleware(BlockMiddleware())

    dp.include_router(router)
    dp.startup.register(lambda: on_startup(bot))

    # ── Health-check HTTP server ───────────────────────────────
    app = web.Application()
    app.router.add_get("/health", health)
    app.router.add_get("/",       health)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    log.info("Health server on port %d", PORT)

    # ── Start polling ──────────────────────────────────────────
    try:
        await dp.start_polling(bot, drop_pending_updates=True)
    finally:
        await runner.cleanup()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
