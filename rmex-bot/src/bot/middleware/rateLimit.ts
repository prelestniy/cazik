import { Context, NextFunction } from 'grammy';
import { logger } from '../../utils/logger';

interface RateLimitEntry {
  count: number;
  resetAt: number;
}

const store = new Map<number, RateLimitEntry>();
const WINDOW_MS = 60_000;
const MAX_REQUESTS = 10;

// Cleanup stale entries every 5 minutes
setInterval(() => {
  const now = Date.now();
  for (const [key, entry] of store.entries()) {
    if (entry.resetAt < now) store.delete(key);
  }
}, 300_000);

export async function rateLimitMiddleware(ctx: Context, next: NextFunction): Promise<void> {
  if (!ctx.from) return next();

  const userId = ctx.from.id;
  const now = Date.now();

  let entry = store.get(userId);

  if (!entry || entry.resetAt < now) {
    entry = { count: 0, resetAt: now + WINDOW_MS };
    store.set(userId, entry);
  }

  entry.count++;

  if (entry.count > MAX_REQUESTS) {
    const secondsLeft = Math.ceil((entry.resetAt - now) / 1000);
    logger.warn({ userId, count: entry.count }, 'Rate limit exceeded');
    await ctx.reply(`⏳ Слишком много запросов. Подождите ${secondsLeft} сек.`);
    return;
  }

  return next();
}
