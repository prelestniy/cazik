import { Bot, Context } from 'grammy';
import { prisma } from '../db/client';
import { logger } from '../utils/logger';
import {
  getAllUsersCount,
  getActiveUsersCount,
} from './userService';
import { getTotalGamesPlayed, getTopGameType } from './gameService';

export async function logEvent(
  eventType: string,
  userId?: number,
  payload?: Record<string, unknown>,
): Promise<void> {
  await prisma.systemEvent.create({
    data: {
      eventType,
      userId: userId ?? null,
      payload: payload ?? {},
    },
  });
}

export async function getSystemStats() {
  const [totalUsers, activeUsers24h, totalGames, topGame, totalTransactions, sumTransactions] =
    await Promise.all([
      getAllUsersCount(),
      getActiveUsersCount(24),
      getTotalGamesPlayed(),
      getTopGameType(),
      prisma.transaction.count(),
      prisma.transaction.aggregate({ _sum: { amount: true } }),
    ]);

  return {
    totalUsers,
    activeUsers24h,
    totalGames,
    topGame,
    totalTransactions,
    totalPoints: sumTransactions._sum.amount ?? 0,
  };
}

export async function getRecentEvents(limit = 20) {
  return prisma.systemEvent.findMany({
    orderBy: { createdAt: 'desc' },
    take: limit,
    include: { user: { select: { username: true, firstName: true } } },
  });
}

export async function broadcast<C extends Context>(
  bot: Bot<C>,
  message: string,
  adminId: number,
): Promise<{ sent: number; failed: number }> {
  const users = await prisma.user.findMany({
    where: { isBlocked: false },
    select: { telegramId: true },
  });

  let sent = 0;
  let failed = 0;

  for (const user of users) {
    try {
      await bot.api.sendMessage(Number(user.telegramId), message, { parse_mode: 'HTML' });
      sent++;
      // Rate limit: 30 messages/sec max per Telegram API
      await new Promise((r) => setTimeout(r, 40));
    } catch {
      failed++;
    }
  }

  await logEvent('BROADCAST', adminId, { message: message.slice(0, 100), sent, failed });
  logger.info({ sent, failed, adminId }, 'Broadcast completed');
  return { sent, failed };
}

export async function findUserForAdmin(query: string) {
  const isNumeric = /^\d+$/.test(query);

  if (isNumeric) {
    return prisma.user.findFirst({
      where: {
        OR: [
          { id: parseInt(query) },
          { telegramId: BigInt(query) },
        ],
      },
    });
  }

  return prisma.user.findFirst({
    where: { username: { contains: query.replace('@', ''), mode: 'insensitive' } },
  });
}
