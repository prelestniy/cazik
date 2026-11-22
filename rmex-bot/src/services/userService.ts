import { User, TransactionType } from '@prisma/client';
import { prisma } from '../db/client';
import { logger } from '../utils/logger';

export interface TelegramUserData {
  id: number;
  username?: string;
  first_name: string;
  last_name?: string;
}

export async function upsertUser(tgUser: TelegramUserData): Promise<User> {
  const telegramId = BigInt(tgUser.id);

  const user = await prisma.user.upsert({
    where: { telegramId },
    update: {
      username: tgUser.username ?? null,
      firstName: tgUser.first_name,
      lastName: tgUser.last_name ?? null,
      lastLoginAt: new Date(),
    },
    create: {
      telegramId,
      username: tgUser.username ?? null,
      firstName: tgUser.first_name,
      lastName: tgUser.last_name ?? null,
      balance: 100,
    },
  });

  logger.debug({ telegramId: tgUser.id }, 'User upserted');
  return user;
}

export async function getUserByTelegramId(telegramId: number): Promise<User | null> {
  return prisma.user.findUnique({
    where: { telegramId: BigInt(telegramId) },
  });
}

export async function getUserById(id: number): Promise<User | null> {
  return prisma.user.findUnique({ where: { id } });
}

export async function updateBalance(
  userId: number,
  delta: number,
  type: TransactionType,
  description: string,
): Promise<User> {
  const [user] = await prisma.$transaction([
    prisma.user.update({
      where: { id: userId },
      data: { balance: { increment: delta } },
    }),
    prisma.transaction.create({
      data: {
        userId,
        type,
        amount: Math.abs(delta),
        description,
      },
    }),
  ]);
  return user;
}

export async function getLeaderboard(limit = 10): Promise<User[]> {
  return prisma.user.findMany({
    where: { isBlocked: false },
    orderBy: [{ totalWins: 'desc' }, { balance: 'desc' }],
    take: limit,
  });
}

export async function getUserRank(userId: number): Promise<number> {
  const user = await prisma.user.findUnique({ where: { id: userId } });
  if (!user) return -1;

  const count = await prisma.user.count({
    where: {
      isBlocked: false,
      OR: [
        { totalWins: { gt: user.totalWins } },
        { totalWins: user.totalWins, balance: { gt: user.balance } },
      ],
    },
  });
  return count + 1;
}

export async function blockUser(userId: number, blocked: boolean): Promise<User> {
  return prisma.user.update({
    where: { id: userId },
    data: { isBlocked: blocked },
  });
}

export async function grantVip(userId: number, vip: boolean): Promise<User> {
  return prisma.user.update({
    where: { id: userId },
    data: { isVip: vip },
  });
}

export async function adminGrantPoints(
  userId: number,
  amount: number,
  adminId: number,
): Promise<User> {
  const description = `Admin grant by #${adminId}`;
  return updateBalance(userId, amount, TransactionType.ADMIN_GRANT, description);
}

export async function adminDeductPoints(
  userId: number,
  amount: number,
  adminId: number,
): Promise<User> {
  const description = `Admin deduct by #${adminId}`;
  return updateBalance(userId, -amount, TransactionType.ADMIN_DEDUCT, description);
}

export async function getAllUsersCount(): Promise<number> {
  return prisma.user.count();
}

export async function getActiveUsersCount(hours = 24): Promise<number> {
  const since = new Date(Date.now() - hours * 3_600_000);
  return prisma.user.count({ where: { lastLoginAt: { gte: since } } });
}

export async function getUserTransactions(userId: number, limit = 20) {
  return prisma.transaction.findMany({
    where: { userId },
    orderBy: { createdAt: 'desc' },
    take: limit,
  });
}
