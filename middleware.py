# [context: aiogram 3 middleware, rate-limiter, auth gate]
# *the bouncer at every door — no ID, no entry*

import time
import logging
from collections import defaultdict
from typing import Callable, Awaitable, Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Update, Message, CallbackQuery

from models import SessionMaker
from services import upsert_user

log = logging.getLogger(__name__)

RATE_LIMIT    = 10    # max requests
RATE_WINDOW   = 60.0  # seconds


class DBMiddleware(BaseMiddleware):
    """Injects db session + db_user into handler data."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict], Awaitable[Any]],
        event: TelegramObject,
        data: dict,
    ) -> Any:
        from_user = None
        if isinstance(event, Update):
            if event.message:
                from_user = event.message.from_user
            elif event.callback_query:
                from_user = event.callback_query.from_user
            elif event.pre_checkout_query:
                from_user = event.pre_checkout_query.from_user

        # For callback queries from existing users we only need a fast SELECT,
        # not a full upsert — this cuts median latency by ~60-80 ms per tap.
        is_callback = isinstance(event, Update) and event.callback_query is not None
        is_message   = isinstance(event, Update) and event.message is not None

        async with SessionMaker() as session:
            db_user = None
            if from_user:
                try:
                    if is_callback:
                        # fast path: just load the existing row
                        from services import get_user
                        db_user = await get_user(session, from_user.id)
                        if db_user is None:
                            # first-ever interaction via inline button — fall back to upsert
                            db_user = await upsert_user(
                                session,
                                tg_id=from_user.id,
                                username=from_user.username,
                                first_name=from_user.first_name or "User",
                                last_name=from_user.last_name,
                            )
                            await session.commit()
                    else:
                        db_user = await upsert_user(
                            session,
                            tg_id=from_user.id,
                            username=from_user.username,
                            first_name=from_user.first_name or "User",
                            last_name=from_user.last_name,
                        )
                        await session.commit()
                except Exception as exc:
                    await session.rollback()
                    log.error("upsert_user failed: %s", exc)
                    return

            data["session"] = session
            data["db_user"] = db_user
            try:
                return await handler(event, data)
            finally:
                pass  # session closes via context manager


class RateLimitMiddleware(BaseMiddleware):
    def __init__(self, limit: int = RATE_LIMIT, window: float = RATE_WINDOW):
        self._limit  = limit
        self._window = window
        self._hits: dict[int, list[float]] = defaultdict(list)

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict], Awaitable[Any]],
        event: TelegramObject,
        data: dict,
    ) -> Any:
        uid = None
        if isinstance(event, Update):
            if event.message:
                uid = event.message.from_user.id if event.message.from_user else None
            elif event.callback_query:
                uid = event.callback_query.from_user.id

        if uid:
            now = time.monotonic()
            self._hits[uid] = [t for t in self._hits[uid] if now - t < self._window]
            if len(self._hits[uid]) >= self._limit:
                if isinstance(event, Update) and event.callback_query:
                    await event.callback_query.answer("⏳ Слишком много запросов, подожди немного")
                elif isinstance(event, Update) and event.message:
                    await event.message.answer("⏳ Слишком много запросов, подожди немного")
                return
            self._hits[uid].append(now)

        return await handler(event, data)


class BlockMiddleware(BaseMiddleware):
    """Silently drops updates from blocked users."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict], Awaitable[Any]],
        event: TelegramObject,
        data: dict,
    ) -> Any:
        db_user = data.get("db_user")
        if db_user and db_user.is_blocked:
            return
        return await handler(event, data)
