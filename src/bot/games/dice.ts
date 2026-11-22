import { Bot, Context, InlineKeyboard } from 'grammy';
import { User, TaskType } from '@prisma/client';
import { playDice, getGameConfig } from '../../services/gameService';
import { updateTaskProgress } from '../../services/taskService';
import { formatBalance, formatGameResult } from '../../utils/formatters';
import { logger } from '../../utils/logger';

const diceState = new Map<number, { step: 'awaiting_bet'; bet: number }>();

function guessKeyboard(bet: number): InlineKeyboard {
  const kb = new InlineKeyboard();
  for (let i = 1; i <= 6; i++) {
    kb.text(`${i}`, `dice:play:${bet}:${i}`);
    if (i === 3) kb.row();
  }
  kb.row().text('« Отмена', 'menu:games');
  return kb;
}

export function registerDiceGame<C extends Context>(bot: Bot<C>): void {
  bot.callbackQuery('game:dice', async (ctx) => {
    await ctx.answerCallbackQuery();
    const dbUser = (ctx as C & { dbUser: User }).dbUser;

    const [minBet, maxBet] = await Promise.all([
      getGameConfig('dice.min_bet'),
      getGameConfig('dice.max_bet'),
    ]);

    diceState.set(ctx.from.id, { step: 'awaiting_bet', bet: 0 });

    await ctx.editMessageText(
      `🎲 <b>Кубик</b>\n\n` +
        `💰 Баланс: <b>${formatBalance(dbUser.balance)}</b>\n` +
        `📌 Ставка: от ${minBet ?? 10} до ${maxBet ?? 300} очков\n\n` +
        `🎯 Угадай точно → ×5 | Соседнее число → ×1\n\n` +
        `Введите ставку:`,
      { parse_mode: 'HTML', reply_markup: new InlineKeyboard().text('« Отмена', 'menu:games') },
    );
  });

  bot.callbackQuery(/^dice:play:(\d+):(\d)$/, async (ctx) => {
    await ctx.answerCallbackQuery('🎲 Бросаем кубик...');
    const bet = parseInt(ctx.match[1]);
    const guess = parseInt(ctx.match[2]);
    const dbUser = (ctx as C & { dbUser: User }).dbUser;

    if (dbUser.balance < bet) {
      await ctx.editMessageText('❌ Недостаточно очков!', {
        reply_markup: new InlineKeyboard().text('« Назад', 'menu:games'),
      });
      return;
    }

    try {
      const outcome = await playDice(dbUser.id, bet, guess, dbUser.isVip);
      const rolledNum = parseInt(outcome.result.split(',')[0].split(':')[1]);

      await updateTaskProgress(dbUser.id, TaskType.PLAY_GAMES, 1);
      if (outcome.won) await updateTaskProgress(dbUser.id, TaskType.WIN_STREAK, 1);

      const diceEmoji = ['⚀', '⚁', '⚂', '⚃', '⚄', '⚅'][rolledNum - 1] ?? '🎲';
      const exact = rolledNum === guess;

      const text =
        `🎲 <b>Кубик — результат</b>\n\n` +
        `🎯 Ваш выбор: <b>${guess}</b>\n` +
        `${diceEmoji} Выпало: <b>${rolledNum}</b>\n` +
        (exact ? `✨ Точное попадание!\n` : outcome.won ? `〰️ Соседнее число!\n` : '') +
        `\n${formatGameResult('DICE', outcome.won, outcome.payout, bet)}\n\n` +
        `💰 Баланс: <b>${formatBalance(outcome.newBalance)}</b>`;

      await ctx.editMessageText(text, {
        parse_mode: 'HTML',
        reply_markup: new InlineKeyboard()
          .text('🔄 Снова', 'game:dice')
          .text('« Игры', 'menu:games'),
      });
    } catch (err) {
      logger.error({ err }, 'Dice error');
      await ctx.editMessageText('❌ Ошибка.', {
        reply_markup: new InlineKeyboard().text('« Назад', 'menu:games'),
      });
    }
  });

  // Text handler for bet
  bot.on('message:text', async (ctx, next) => {
    if (!ctx.from) return next();
    const state = diceState.get(ctx.from.id);
    if (!state || state.step !== 'awaiting_bet') return next();

    const bet = parseInt(ctx.message.text.trim());
    const dbUser = (ctx as C & { dbUser: User }).dbUser;

    const [minBetStr, maxBetStr] = await Promise.all([
      getGameConfig('dice.min_bet'),
      getGameConfig('dice.max_bet'),
    ]);
    const minBet = parseInt(minBetStr ?? '10');
    const maxBet = parseInt(maxBetStr ?? '300');

    if (isNaN(bet) || bet < minBet || bet > maxBet) {
      await ctx.reply(`❌ Ставка: от ${minBet} до ${maxBet} очков.`);
      return;
    }

    if (dbUser.balance < bet) {
      await ctx.reply(`❌ Нет очков. Баланс: ${formatBalance(dbUser.balance)}`);
      return;
    }

    diceState.delete(ctx.from.id);

    await ctx.reply(
      `🎲 Ставка <b>${formatBalance(bet)}</b>. Выберите число от 1 до 6:`,
      { parse_mode: 'HTML', reply_markup: guessKeyboard(bet) },
    );
  });
}
