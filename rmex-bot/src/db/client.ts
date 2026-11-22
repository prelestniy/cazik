import { PrismaClient } from '@prisma/client';
import { logger } from '../utils/logger';

declare global {
  // eslint-disable-next-line no-var
  var __prisma: PrismaClient | undefined;
}

export const prisma: PrismaClient =
  global.__prisma ||
  new PrismaClient({
    log: [
      { level: 'warn', emit: 'event' },
      { level: 'error', emit: 'event' },
    ],
  });

prisma.$on('warn' as never, (e: { message: string }) => {
  logger.warn({ msg: e.message }, 'Prisma warning');
});

prisma.$on('error' as never, (e: { message: string }) => {
  logger.error({ msg: e.message }, 'Prisma error');
});

if (process.env.NODE_ENV !== 'production') {
  global.__prisma = prisma;
}

export async function connectDB(): Promise<void> {
  try {
    await prisma.$connect();
    logger.info('PostgreSQL connected via Prisma');
  } catch (err) {
    logger.error({ err }, 'Failed to connect to PostgreSQL');
    process.exit(1);
  }
}

export async function disconnectDB(): Promise<void> {
  await prisma.$disconnect();
  logger.info('PostgreSQL disconnected');
}
