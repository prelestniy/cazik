import { Bot, Context, InlineKeyboard } from 'grammy';
import { User } from '@prisma/client';
import { getLeaderboard, getUserRank } from '../../services/userService';
import { checkTopRankTask } from '../../services/taskService';
import { formatBalance, formatWinRate } from '../../utils/formatters';

const MEDALS = ['🥇', '🥈', '🥉', '4️⃣', '5️⃣', '6️⃣', '7️⃣', '8️⃣', '9️⃣', '🔟'];

export function registerLeaderboardHandler<C extends Context>(bot: Bot<C>): void {
  bot.callbackQuery('menu:leaderboard', async (ctx) => {
    await ctx.answerCallbackQuery();
    const dbUser = (ctx as C & { dbUser: User }).dbUser;

    const [leaders, myRank] = await Promise.all([
      getLeaderboard(10),
      getUserRank(dbUser.id),
    ]);

    // Check top-rank task
    await checkTopRankTask(dbUser.id, myRank);

    const lines = leaders.map((user, i) => {
      const medal = MEDALS[i] ?? `${i + 1}.`;
      const name = user.username ? `@${user.username}` : user.firstName;
      const wr = formatWinRate(user.totalWins, user.totalGames);
      const vip = user.isVip ? ' ⭐' : '';
      const marker = user.id === dbUser.id ? ' ← вы' : '';
      return `${medal} <b>${name}</b>${vip}${marker}\n  🏆 ${user.totalWins} побед | 💰 ${formatBalance(user.balance)} | 📈 ${wr}`;
    });

    const myRankLine =
      myRank <= 10
        ? ''
        : `\n📍 Ваше место: <b>#${myRank}</b>`;

    const text =
      `🏆 <b>Рейтинг игроков</b>\n\n` +
      lines.join('\n\n') +
      myRankLine;

    await ctx.editMessageText(text, {
      parse_mode: 'HTML',
      reply_markup: new InlineKeyboard().text('« Назад', 'menu:main'),
    });
  });
}
