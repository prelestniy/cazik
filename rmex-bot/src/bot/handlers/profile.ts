import { Bot, Context, InlineKeyboard } from 'grammy';
import { User } from '@prisma/client';
import { getUserRank, getUserTransactions } from '../../services/userService';
import { formatBalance, formatWinRate, formatUserName } from '../../utils/formatters';

export function registerProfileHandler<C extends Context>(bot: Bot<C>): void {
  bot.callbackQuery('menu:profile', async (ctx) => {
    await ctx.answerCallbackQuery();
    const dbUser = (ctx as C & { dbUser: User }).dbUser;
    const rank = await getUserRank(dbUser.id);

    const text =
      `👤 <b>Профиль</b>\n\n` +
      `🆔 ID: <code>${dbUser.telegramId}</code>\n` +
      `👤 Имя: <b>${dbUser.firstName}${dbUser.lastName ? ' ' + dbUser.lastName : ''}</b>\n` +
      (dbUser.username ? `🔖 @${dbUser.username}\n` : '') +
      `\n💰 Баланс: <b>${formatBalance(dbUser.balance)} очков</b>\n` +
      (dbUser.isVip ? `⭐ VIP-статус: активен\n` : '') +
      `\n🎮 Всего игр: <b>${dbUser.totalGames}</b>\n` +
      `🏆 Побед: <b>${dbUser.totalWins}</b>\n` +
      `📈 Винрейт: <b>${formatWinRate(dbUser.totalWins, dbUser.totalGames)}</b>\n` +
      `🔥 Серия побед: <b>${dbUser.winStreak}</b> (макс: ${dbUser.maxWinStreak})\n` +
      `\n🏅 Место в рейтинге: <b>#${rank}</b>\n` +
      `📅 Регистрация: ${dbUser.createdAt.toLocaleDateString('ru-RU')}`;

    const kb = new InlineKeyboard()
      .text('💳 История транзакций', 'profile:transactions')
      .row()
      .text('« Назад', 'menu:main');

    await ctx.editMessageText(text, { parse_mode: 'HTML', reply_markup: kb });
  });

  bot.callbackQuery('profile:transactions', async (ctx) => {
    await ctx.answerCallbackQuery();
    const dbUser = (ctx as C & { dbUser: User }).dbUser;
    const txs = await getUserTransactions(dbUser.id, 10);

    if (txs.length === 0) {
      await ctx.editMessageText('💳 История транзакций пуста.', {
        reply_markup: new InlineKeyboard().text('« Назад', 'menu:profile'),
      });
      return;
    }

    const lines = txs.map((tx) => {
      const sign = tx.type === 'GAME_WIN' || tx.type === 'TASK_REWARD' || tx.type === 'PURCHASE' || tx.type === 'ADMIN_GRANT' ? '+' : '-';
      const emoji =
        tx.type === 'GAME_WIN' ? '🏆' :
        tx.type === 'GAME_LOSS' ? '💀' :
        tx.type === 'TASK_REWARD' ? '📋' :
        tx.type === 'PURCHASE' ? '💎' :
        tx.type === 'ADMIN_GRANT' ? '➕' : '➖';
      const date = tx.createdAt.toLocaleDateString('ru-RU');
      return `${emoji} ${sign}${formatBalance(tx.amount)} | ${date}`;
    });

    await ctx.editMessageText(
      `💳 <b>История транзакций</b>\n\n${lines.join('\n')}`,
      {
        parse_mode: 'HTML',
        reply_markup: new InlineKeyboard().text('« Назад', 'menu:profile'),
      },
    );
  });
}
