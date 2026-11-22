import { Bot, Context, InlineKeyboard } from 'grammy';
import { User, TaskType } from '@prisma/client';
import { playSlots, getGameConfig } from '../../services/gameService';
import { updateTaskProgress } from '../../services/taskService';
import { formatBalance, formatGameResult } from '../../utils/formatters';
import { logger } from '../../utils/logger';

const slotsState = new Map<number, { step: 'awaiting_bet' }>();

function animateReels(reels: string[]): string {
  return `[ ${reels[0]} | ${reels[1]} | ${reels[2]} ]`;
}

export function registerSlotsGame<C extends Context>(bot: Bot<C>): void {
  bot.callbackQuery('game:slots', async (ctx) => {
    await ctx.answerCallbackQuery();
    const dbUser = (ctx as C & { dbUser: User }).dbUser;

    const [minBet, maxBet] = await Promise.all([
      getGameConfig('slots.min_bet'),
      getGameConfig('slots.max_bet'),
    ]);

    slotsState.set(ctx.from.id, { step: 'awaiting_bet' });

    await ctx.editMessageText(
      `🎰 <b>Слоты</b>\n\n` +
        `💰 Баланс: <b>${formatBalance(dbUser.balance)}</b>\n` +
        `📌 Ставка: от ${minBet ?? 20} до ${maxBet ?? 200} очков\n\n` +
        `🏆 Три одинаковых → ×10\n` +
        `🎯 Два одинаковых → ×2\n\n` +
        `Введите ставку:`,
      { parse_mode: 'HTML', reply_markup: new InlineKeyboard().text('« Отмена', 'menu:games') },
    );
  });

  // Text handler for bet
  bot.on('message:text', async (ctx, next) => {
    if (!ctx.from) return next();
    const state = slotsState.get(ctx.from.id);
    if (!state || state.step !== 'awaiting_bet') return next();

    const bet = parseInt(ctx.message.text.trim());
    const dbUser = (ctx as C & { dbUser: User }).dbUser;

    const [minBetStr, maxBetStr] = await Promise.all([
      getGameConfig('slots.min_bet'),
      getGameConfig('slots.max_bet'),
    ]);
    const minBet = parseInt(minBetStr ?? '20');
    const maxBet = parseInt(maxBetStr ?? '200');

    if (isNaN(bet) || bet < minBet || bet > maxBet) {
      await ctx.reply(`❌ Ставка: от ${minBet} до ${maxBet} очков.`);
      return;
    }

    if (dbUser.balance < bet) {
      await ctx.reply(`❌ Недостаточно очков. Баланс: ${formatBalance(dbUser.balance)}`);
      return;
    }

    slotsState.delete(ctx.from.id);

    // Spinning animation message
    const spinMsg = await ctx.reply(
      `🎰 <b>Крутим барабаны...</b>\n\n[ 🔄 | 🔄 | 🔄 ]`,
      { parse_mode: 'HTML' },
    );

    try {
      const outcome = await playSlots(dbUser.id, bet, dbUser.isVip);

      await updateTaskProgress(dbUser.id, TaskType.PLAY_GAMES, 1);
      if (outcome.won) await updateTaskProgress(dbUser.id, TaskType.WIN_STREAK, 1);

      const reelDisplay = animateReels(outcome.reels);
      const allSame = outcome.reels[0] === outcome.reels[1] && outcome.reels[1] === outcome.reels[2];
      const twoSame = !allSame && (
        outcome.reels[0] === outcome.reels[1] ||
        outcome.reels[1] === outcome.reels[2] ||
        outcome.reels[0] === outcome.reels[2]
      );

      let comboLine = '';
      if (allSame) comboLine = `\n✨ <b>ДЖЕКПОТ! Три одинаковых!</b>`;
      else if (twoSame) comboLine = `\n🎯 Два одинаковых!`;

      const text =
        `🎰 <b>Слоты — результат</b>\n\n` +
        `${reelDisplay}${comboLine}\n\n` +
        `${formatGameResult('SLOTS', outcome.won, outcome.payout, bet)}\n\n` +
        `💰 Баланс: <b>${formatBalance(outcome.newBalance)}</b>`;

      await ctx.api.editMessageText(
        ctx.chat.id,
        spinMsg.message_id,
        text,
        {
          parse_mode: 'HTML',
          reply_markup: new InlineKeyboard()
            .text('🔄 Снова', 'game:slots')
            .text('« Игры', 'menu:games'),
        },
      );
    } catch (err) {
      logger.error({ err }, 'Slots error');
      await ctx.api.editMessageText(
        ctx.chat.id,
        spinMsg.message_id,
        '❌ Ошибка. Попробуйте снова.',
        { reply_markup: new InlineKeyboard().text('« Назад', 'menu:games') },
      );
    }
  });
}
