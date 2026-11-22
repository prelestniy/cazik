import { Bot, Context, InlineKeyboard } from 'grammy';
import { User } from '@prisma/client';
import { formatBalance } from '../../utils/formatters';

export function mainMenuKeyboard(): InlineKeyboard {
  return new InlineKeyboard()
    .text('🎮 Игры', 'menu:games')
    .text('👤 Профиль', 'menu:profile')
    .row()
    .text('📊 Статистика', 'menu:stats')
    .text('🏆 Рейтинг', 'menu:leaderboard')
    .row()
    .text('📋 Задания', 'menu:tasks')
    .text('💎 Купить', 'menu:buy')
    .row()
    .text('❓ Помощь', 'menu:help');
}

export function registerStartCommand<C extends Context>(bot: Bot<C>): void {
  bot.command('start', async (ctx) => {
    const dbUser = (ctx as C & { dbUser: User }).dbUser;
    const isNew = dbUser.totalGames === 0 && dbUser.balance === 100;

    const welcomeText = isNew
      ? `👋 Добро пожаловать в <b>Казино - BOT</b>, <b>${dbUser.firstName}</b>!\n\n` +
        `🎁 Тебе начислено <b>100 стартовых очков</b>.\n\n` +
        `Играй в мини-игры, выполняй задания и зарабатывай очки!\n\n` +
        `💰 Баланс: <b>${formatBalance(dbUser.balance)} очков</b>`
      : `👋 С возвращением, <b>${dbUser.firstName}</b>!\n\n` +
        `💰 Баланс: <b>${formatBalance(dbUser.balance)} очков</b>` +
        (dbUser.isVip ? '\n⭐ VIP-статус активен (+10% к выигрышам)' : '');

    await ctx.reply(welcomeText, {
      parse_mode: 'HTML',
      reply_markup: mainMenuKeyboard(),
    });
  });
}
