import 'dotenv/config';
import express from 'express';
import { connectDB, disconnectDB } from './db/client';
import { createBot, seedDatabase } from './bot/index';
import { logger } from './utils/logger';

const PORT = parseInt(process.env.PORT ?? '3000', 10);

async function main(): Promise<void> {
  // ─── Connect DB ─────────────────────────────────────────────
  await connectDB();

  // ─── Seed defaults ──────────────────────────────────────────
  await seedDatabase();

  // ─── Create bot ─────────────────────────────────────────────
  const bot = createBot();

  // ─── Express health server ──────────────────────────────────
  const app = express();
  app.use(express.json());

  app.get('/health', (_req, res) => {
    res.json({
      status: 'ok',
      uptime: Math.floor(process.uptime()),
      timestamp: new Date().toISOString(),
      bot: 'running',
    });
  });

  app.get('/', (_req, res) => {
    res.json({ name: 'Казино - BOT', version: '1.0.0' });
  });

  const server = app.listen(PORT, () => {
    logger.info({ port: PORT }, 'Health server listening');
  });

  // ─── Start bot (long polling) ───────────────────────────────
  logger.info('Starting bot in long polling mode...');

  bot.start({
    onStart: (botInfo) => {
      logger.info({ username: botInfo.username, id: botInfo.id }, 'Bot started successfully');
    },
    drop_pending_updates: true,
    allowed_updates: [
      'message',
      'callback_query',
      'pre_checkout_query',
      'inline_query',
    ],
  });

  // ─── Graceful shutdown ──────────────────────────────────────
  const shutdown = async (signal: string): Promise<void> => {
    logger.info({ signal }, 'Shutdown signal received');

    try {
      await bot.stop();
      logger.info('Bot stopped');
    } catch (err) {
      logger.error({ err }, 'Error stopping bot');
    }

    server.close(() => {
      logger.info('Express server closed');
    });

    await disconnectDB();
    logger.info('Shutdown complete');
    process.exit(0);
  };

  process.on('SIGINT', () => shutdown('SIGINT'));
  process.on('SIGTERM', () => shutdown('SIGTERM'));

  // ─── Uncaught errors ────────────────────────────────────────
  process.on('uncaughtException', (err) => {
    logger.error({ err }, 'Uncaught exception');
    process.exit(1);
  });

  process.on('unhandledRejection', (reason) => {
    logger.error({ reason }, 'Unhandled rejection');
    process.exit(1);
  });
}

main().catch((err) => {
  logger.error({ err }, 'Fatal startup error');
  process.exit(1);
});
