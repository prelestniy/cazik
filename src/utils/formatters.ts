import { User } from '@prisma/client';

export function formatBalance(amount: number): string {
  return amount.toLocaleString('ru-RU');
}

export function formatUserName(user: User): string {
  if (user.username) return `@${user.username}`;
  const full = [user.firstName, user.lastName].filter(Boolean).join(' ');
  return full || `User#${user.telegramId}`;
}

export function formatWinRate(wins: number, total: number): string {
  if (total === 0) return '0%';
  return `${Math.round((wins / total) * 100)}%`;
}

export function formatDuration(ms: number): string {
  const hours = Math.floor(ms / 3_600_000);
  const minutes = Math.floor((ms % 3_600_000) / 60_000);
  if (hours > 0) return `${hours}ч ${minutes}м`;
  return `${minutes}м`;
}

export function escapeMarkdown(text: string): string {
  return text.replace(/[_*[\]()~`>#+\-=|{}.!]/g, (c) => `\\${c}`);
}

export function formatGameResult(
  gameType: string,
  won: boolean,
  payout: number,
  bet: number,
): string {
  const emoji = won ? '🏆' : '💀';
  const sign = won ? '+' : '-';
  const amount = won ? payout - bet : bet;
  return `${emoji} ${won ? 'Победа' : 'Поражение'} | ${sign}${formatBalance(amount)} очков`;
}

export function progressBar(current: number, target: number, length = 10): string {
  const filled = Math.min(Math.round((current / target) * length), length);
  const empty = length - filled;
  return '█'.repeat(filled) + '░'.repeat(empty);
}

export function formatTimeLeft(expiresAt: Date): string {
  const diff = expiresAt.getTime() - Date.now();
  if (diff <= 0) return 'истекло';
  return formatDuration(diff);
}
