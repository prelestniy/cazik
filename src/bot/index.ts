import { Bot, session, Context, SessionFlavor } from 'grammy';
import { logger } from '../utils/logger';

// Middleware
import { authMiddleware } from './middleware/auth';
import { rateLimitMiddleware } from './middleware/rateLimit';

// Commands
import { registerStartCommand } from './commands/start';
import { registerAdminCommand } from './commands/admin';
import { registerBuyCommand } from './commands/buy';

// Handlers
import { registerMenuHandler } from './handlers/menu';
import { registerProfileHandler } from './handlers/profile';
import { registerStatsHandler } from './handlers/stats';
import { registerLeaderboardHandler } from './handlers/leaderboard';
import { registerTasksHandler } from './handlers/tasks';

// Games
import { registerCoinflipGame } from './games/coinflip';
import { registerDiceGame } from './games/dice';
import { registerSlotsGame } from './games/slots';

// Services
import { seedDefaultConfigs } from '../services/gameService';
import { ensureTasksExist } from '../services/taskService';
import { User } from '@prisma/client';

export type BotContext = Context & { dbUser: User };

export function createBot(): Bot<BotContext> {
  const token = process.env.BOT_TOKEN;
  if (!token) throw new Error('BOT_TOKEN is not set');

  const adminIds = (process.env.ADMIN_IDS ?? '')
    .split(',')
    .map((id) => parseInt(id.trim()))
    .filter((id) => !isNaN(id));

  logger.info({ adminCount: adminIds.length }, 'Admin IDs loaded');

  const bot = new Bot<BotContext>(token, {
    client: {
      apiRoot: process.env.BOT_API_ROOT ?? 'https://api.respegram.ru',
    },
  });

  // ─── Global middleware ──────────────────────────────────────
  bot.use(rateLimitMiddleware);
  bot.use(authMiddleware);

  // ─── Error handler ─────────────────────────────────────────
  bot.catch((err) => {
    const ctx = err.ctx;
    logger.error(
      {
        err: err.error,
        update: ctx.update,
        userId: ctx.from?.id,
      },
      'Unhandled bot error',
    );
  });

  // ─── Commands ──────────────────────────────────────────────
  registerStartCommand(bot);
  registerAdminCommand(bot, adminIds);
  registerBuyCommand(bot);

  // ─── Menu & navigation ─────────────────────────────────────
  registerMenuHandler(bot);

  // ─── Profile / Stats / Leaderboard / Tasks ─────────────────
  registerProfileHandler(bot);
  registerStatsHandler(bot);
  registerLeaderboardHandler(bot);
  registerTasksHandler(bot);

  // ─── Games ─────────────────────────────────────────────────
  // Order matters: slots text handler must be last to avoid swallowing
  registerCoinflipGame(bot);
  registerDiceGame(bot);
  registerSlotsGame(bot);

  // ─── Fallback for unknown callbacks ────────────────────────
  bot.on('callback_query:data', async (ctx) => {
    logger.warn({ data: ctx.callbackQuery.data, userId: ctx.from.id }, 'Unknown callback');
    await ctx.answerCallbackQuery('❓ Неизвестное действие');
  });

  return bot;
}

export async function seedDatabase(): Promise<void> {
  await seedDefaultConfigs();
  await ensureTasksExist();
  logger.info('Database seeded with default configs and tasks');
}
