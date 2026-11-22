import { Bot, Context, InlineKeyboard } from 'grammy';
import { User } from '@prisma/client';
import { getUserGameStats } from '../../services/gameService';
import { formatBalance, formatWinRate } from '../../utils/formatters';

const GAME_LABELS: Record<string, string> = {
  COINFLIP: '🪙 Монетка',
  DICE: '🎲 Кубик',
  SLOTS: '🎰 Слоты',
};

export function registerStatsHandler<C extends Context>(bot: Bot<C>): void {
  bot.callbackQuery('menu:stats', async (ctx) => {
    await ctx.answerCallbackQuery();
    const dbUser = (ctx as C & { dbUser: User }).dbUser;
    const { results, wins } = await getUserGameStats(dbUser.id);

    if (results.length === 0) {
      await ctx.editMessageText(
        '📊 <b>Статистика</b>\n\nУ вас пока нет сыгранных игр. Вперёд!',
        {
          parse_mode: 'HTML',
          reply_markup: new InlineKeyboard()
            .text('🎮 Играть', 'menu:games')
            .row()
            .text('« Назад', 'menu:main'),
        },
      );
      return;
    }

    const winsMap = Object.fromEntries(wins.map((w) => [w.gameType, w._count.id]));

    const lines = results.map((r) => {
      const label = GAME_LABELS[r.gameType] ?? r.gameType;
      const played = r._count.id;
      const won = winsMap[r.gameType] ?? 0;
      const wr = formatWinRate(won, played);
      const profit = (r._sum.payout ?? 0) - (r._sum.bet ?? 0);
      const profitStr = profit >= 0 ? `+${formatBalance(profit)}` : formatBalance(profit);
      return `${label}\n  🎮 Игр: ${played} | 🏆 Побед: ${won} | 📈 ${wr}\n  💰 Итог: ${profitStr}`;
    });

    const totalGames = results.reduce((s, r) => s + r._count.id, 0);
    const totalWins = Object.values(winsMap).reduce((s, v) => s + v, 0);

    const text =
      `📊 <b>Статистика</b>\n\n` +
      `🎮 Всего игр: <b>${totalGames}</b>\n` +
      `🏆 Побед: <b>${totalWins}</b> (${formatWinRate(totalWins, totalGames)})\n` +
      `🔥 Макс. серия: <b>${dbUser.maxWinStreak}</b>\n\n` +
      `<b>По играм:</b>\n\n${lines.join('\n\n')}`;

    await ctx.editMessageText(text, {
      parse_mode: 'HTML',
      reply_markup: new InlineKeyboard().text('« Назад', 'menu:main'),
    });
  });
}
