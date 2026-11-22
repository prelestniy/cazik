import { GameType, TransactionType } from '@prisma/client';
import { prisma } from '../db/client';
import { logger } from '../utils/logger';

export interface GameOutcome {
  won: boolean;
  payout: number;
  result: string;
  newBalance: number;
}

// ─── Coinflip ──────────────────────────────────────────────────────────────

export async function playCoinflip(
  userId: number,
  bet: number,
  choice: 'heads' | 'tails',
  isVip: boolean,
): Promise<GameOutcome> {
  const result = Math.random() < 0.5 ? 'heads' : 'tails';
  const won = result === choice;
  const multiplier = won ? (isVip ? 2.2 : 2) : 0;
  const payout = Math.floor(bet * multiplier);
  const delta = payout - bet;

  return saveGameResult(userId, GameType.COINFLIP, bet, result, payout, won, delta);
}

// ─── Dice ──────────────────────────────────────────────────────────────────

export async function playDice(
  userId: number,
  bet: number,
  guess: number,
  isVip: boolean,
): Promise<GameOutcome> {
  const roll = Math.floor(Math.random() * 6) + 1;
  const exact = roll === guess;
  const adjacent = !exact && Math.abs(roll - guess) === 1;

  let multiplier = 0;
  if (exact) multiplier = isVip ? 5.5 : 5;
  else if (adjacent) multiplier = isVip ? 1.1 : 1;

  const won = exact || adjacent;
  const payout = Math.floor(bet * multiplier);
  const delta = payout - bet;
  const resultStr = `rolled:${roll},guess:${guess}`;

  return saveGameResult(userId, GameType.DICE, bet, resultStr, payout, won, delta);
}

// ─── Slots ─────────────────────────────────────────────────────────────────

const SLOT_SYMBOLS = ['🍒', '🍋', '🍊', '🍇', '⭐', '💎'];

export async function playSlots(
  userId: number,
  bet: number,
  isVip: boolean,
): Promise<GameOutcome & { reels: string[] }> {
  const reels = [
    SLOT_SYMBOLS[Math.floor(Math.random() * SLOT_SYMBOLS.length)],
    SLOT_SYMBOLS[Math.floor(Math.random() * SLOT_SYMBOLS.length)],
    SLOT_SYMBOLS[Math.floor(Math.random() * SLOT_SYMBOLS.length)],
  ];

  const allSame = reels[0] === reels[1] && reels[1] === reels[2];
  const twoSame =
    !allSame && (reels[0] === reels[1] || reels[1] === reels[2] || reels[0] === reels[2]);

  let multiplier = 0;
  if (allSame) multiplier = isVip ? 11 : 10;
  else if (twoSame) multiplier = isVip ? 2.2 : 2;

  const won = allSame || twoSame;
  const payout = Math.floor(bet * multiplier);
  const delta = payout - bet;
  const resultStr = reels.join('|');

  const outcome = await saveGameResult(userId, GameType.SLOTS, bet, resultStr, payout, won, delta);
  return { ...outcome, reels };
}

// ─── Shared persistence ────────────────────────────────────────────────────

async function saveGameResult(
  userId: number,
  gameType: GameType,
  bet: number,
  result: string,
  payout: number,
  won: boolean,
  delta: number,
): Promise<GameOutcome> {
  const user = await prisma.user.findUnique({ where: { id: userId } });
  if (!user) throw new Error(`User ${userId} not found`);
  if (user.balance < bet) throw new Error('Недостаточно очков');

  const newStreak = won ? user.winStreak + 1 : 0;
  const newMaxStreak = Math.max(user.maxWinStreak, newStreak);

  const [updatedUser] = await prisma.$transaction([
    prisma.user.update({
      where: { id: userId },
      data: {
        balance: { increment: delta },
        totalGames: { increment: 1 },
        totalWins: won ? { increment: 1 } : undefined,
        winStreak: newStreak,
        maxWinStreak: newMaxStreak,
      },
    }),
    prisma.gameResult.create({
      data: { userId, gameType, bet, result, payout, won },
    }),
    prisma.transaction.create({
      data: {
        userId,
        type: won ? TransactionType.GAME_WIN : TransactionType.GAME_LOSS,
        amount: Math.abs(delta),
        description: `${gameType} | bet:${bet} | payout:${payout}`,
      },
    }),
  ]);

  logger.debug({ userId, gameType, won, delta }, 'Game result saved');

  return {
    won,
    payout,
    result,
    newBalance: updatedUser.balance,
  };
}

// ─── Stats ─────────────────────────────────────────────────────────────────

export async function getUserGameStats(userId: number) {
  const results = await prisma.gameResult.groupBy({
    by: ['gameType'],
    where: { userId },
    _count: { id: true },
    _sum: { payout: true, bet: true },
  });

  const wins = await prisma.gameResult.groupBy({
    by: ['gameType'],
    where: { userId, won: true },
    _count: { id: true },
  });

  return { results, wins };
}

export async function getTotalGamesPlayed(): Promise<number> {
  return prisma.gameResult.count();
}

export async function getTopGameType(): Promise<string> {
  const result = await prisma.gameResult.groupBy({
    by: ['gameType'],
    _count: { id: true },
    orderBy: { _count: { id: 'desc' } },
    take: 1,
  });
  return result[0]?.gameType ?? 'N/A';
}

// ─── GameConfig ────────────────────────────────────────────────────────────

export async function getGameConfig(key: string): Promise<string | null> {
  const config = await prisma.gameConfig.findUnique({ where: { key } });
  return config?.value ?? null;
}

export async function setGameConfig(key: string, value: string, description?: string) {
  return prisma.gameConfig.upsert({
    where: { key },
    update: { value },
    create: { key, value, description },
  });
}

export async function getAllGameConfigs() {
  return prisma.gameConfig.findMany({ orderBy: { key: 'asc' } });
}

export async function seedDefaultConfigs() {
  const defaults = [
    { key: 'coinflip.min_bet', value: '10', description: 'Минимальная ставка монетки' },
    { key: 'coinflip.max_bet', value: '500', description: 'Максимальная ставка монетки' },
    { key: 'dice.min_bet', value: '10', description: 'Минимальная ставка кубика' },
    { key: 'dice.max_bet', value: '300', description: 'Максимальная ставка кубика' },
    { key: 'slots.min_bet', value: '20', description: 'Минимальная ставка слотов' },
    { key: 'slots.max_bet', value: '200', description: 'Максимальная ставка слотов' },
  ];

  for (const cfg of defaults) {
    await prisma.gameConfig.upsert({
      where: { key: cfg.key },
      update: {},
      create: cfg,
    });
  }
}
