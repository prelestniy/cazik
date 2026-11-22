// Payment lifecycle hooks are registered in src/bot/commands/buy.ts
// This module re-exports for clean imports if needed in the future

export const PAYMENT_CURRENCY = 'XTR'; // Telegram Stars

export function formatStarsAmount(stars: number): string {
  return `${stars} ⭐`;
}
