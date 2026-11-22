import { Bot, Context, InlineKeyboard } from 'grammy';
import { User } from '@prisma/client';
import { playCoinflip } from '../../services/gameService';
import { updateTaskProgress } from '../../services/taskService';
import { TaskType } from '@prisma/client';
import { formatBalance, formatGameResult } from '../../utils/formatters';
import { getGameConfig } from '../../services/gameService';
import { logger } from '../../utils/logger';

// In-memory state: userId → { step, bet, messageId }
const coinflipState = new Map<number, { step: 'awaiting_bet' | 'awaiting_choice'; bet: number }>();

export function registerCoinflipGame<C extends Context>(bot: Bot<C>): void {
  // Entry
  bot.callbackQuery('game:coinflip', async (ctx) => {
    await ctx.answerCallbackQuery();
    const dbUser = (ctx as C & { dbUser: User }).dbUser;

    const [minBet, maxBet] = await Promise.all([
      getGameConfig('coinflip.min_bet'),
      getGameConfig('coinflip.max_bet'),
    ]);

    coinflipState.set(ctx.from.id, { step: 'awaiting_bet', bet: 0 });

    await ctx.editMessageText(
      `🪙 <b>Монетка</b>\n\n` +
        `💰 Баланс: <b>${formatBalance(dbUser.balance)}</b> очков\n` +
        `📌 Ставка: от ${minBet ?? 10} до ${maxBet ?? 500} очков\n\n` +
        `Введите сумму ставки:`,
      { parse_mode: 'HTML', reply_markup: new InlineKeyboard().text('« Отмена', 'menu:games') },
    );
  });

  // Choice keyboard after bet
  bot.callbackQuery(/^coinflip:choice:(\d+)$/, async (ctx) => {
    await ctx.answerCallbackQuery();
    const bet = parseInt(ctx.match[1]);
    const dbUser = (ctx as C & { dbUser: User }).dbUser;

    const kb = new InlineKeyboard()
      .text('🦅 Орёл', `coinflip:play:${bet}:heads`)
      .text('🪙 Решка', `coinflip:play:${bet}:tails`)
      .row()
      .text('« Отмена', 'menu:games');

    await ctx.editMessageText(
      `🪙 <b>Монетка</b>\n\n` +
        `💰 Ставка: <b>${formatBalance(bet)}</b> очков\n` +
        `🎯 Выберите сторону:`,
      { parse_mode: 'HTML', reply_markup: kb },
    );
  });

  // Play
  bot.callbackQuery(/^coinflip:play:(\d+):(heads|tails)$/, async (ctx) => {
    await ctx.answerCallbackQuery('🪙 Бросаем...');
    const bet = parseInt(ctx.match[1]);
    const choice = ctx.match[2] as 'heads' | 'tails';
    const dbUser = (ctx as C & { dbUser: User }).dbUser;

    if (dbUser.balance < bet) {
      await ctx.editMessageText('❌ Недостаточно очков!', {
        reply_markup: new InlineKeyboard().text('« Назад', 'menu:games'),
      });
      return;
    }

    try {
      const outcome = await playCoinflip(dbUser.id, bet, choice, dbUser.isVip);

      // Update tasks
      await updateTaskProgress(dbUser.id, TaskType.PLAY_GAMES, 1);
      if (outcome.won) {
        await updateTaskProgress(dbUser.id, TaskType.WIN_STREAK, 1);
      }

      const choiceLabel = choice === 'heads' ? '🦅 Орёл' : '🪙 Решка';
      const resultLabel = outcome.result === 'heads' ? '🦅 Орёл' : '🪙 Решка';

      const text =
        `🪙 <b>Монетка — результат</b>\n\n` +
        `🎯 Ваш выбор: <b>${choiceLabel}</b>\n` +
        `🎲 Выпало: <b>${resultLabel}</b>\n\n` +
        `${formatGameResult('COINFLIP', outcome.won, outcome.payout, bet)}\n\n` +
        `💰 Баланс: <b>${formatBalance(outcome.newBalance)}</b> очков`;

      const kb = new InlineKeyboard()
        .text('🔄 Играть снова', 'game:coinflip')
        .text('« Игры', 'menu:games');

      await ctx.editMessageText(text, { parse_mode: 'HTML', reply_markup: kb });
    } catch (err) {
      logger.error({ err }, 'Coinflip error');
      await ctx.editMessageText('❌ Ошибка. Попробуйте снова.', {
        reply_markup: new InlineKeyboard().text('« Назад', 'menu:games'),
      });
    }
  });

  // Text handler for bet input
  bot.on('message:text', async (ctx, next) => {
    if (!ctx.from) return next();
    const state = coinflipState.get(ctx.from.id);
    if (!state || state.step !== 'awaiting_bet') return next();

    const bet = parseInt(ctx.message.text.trim());
    const dbUser = (ctx as C & { dbUser: User }).dbUser;

    const [minBetStr, maxBetStr] = await Promise.all([
      getGameConfig('coinflip.min_bet'),
      getGameConfig('coinflip.max_bet'),
    ]);
    const minBet = parseInt(minBetStr ?? '10');
    const maxBet = parseInt(maxBetStr ?? '500');

    if (isNaN(bet) || bet < minBet || bet > maxBet) {
      await ctx.reply(`❌ Ставка должна быть от ${minBet} до ${maxBet} очков.`);
      return;
    }

    if (dbUser.balance < bet) {
      await ctx.reply(`❌ Недостаточно очков. Баланс: ${formatBalance(dbUser.balance)}`);
      return;
    }

    coinflipState.delete(ctx.from.id);

    const kb = new InlineKeyboard()
      .text('🦅 Орёл', `coinflip:choice:${bet}`)
      .text('🪙 Решка', `coinflip:choice:${bet}`);

    // We use choice in the next step
    await ctx.reply(
      `🪙 Ставка <b>${formatBalance(bet)}</b> очков. Выберите сторону:`,
      {
        parse_mode: 'HTML',
        reply_markup: new InlineKeyboard()
          .text('🦅 Орёл', `coinflip:play:${bet}:heads`)
          .text('🪙 Решка', `coinflip:play:${bet}:tails`),
      },
    );
  });
}
