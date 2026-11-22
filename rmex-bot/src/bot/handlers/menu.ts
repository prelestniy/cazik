import { Bot, Context, InlineKeyboard } from 'grammy';
import { User } from '@prisma/client';
import { mainMenuKeyboard } from '../commands/start';

export function registerMenuHandler<C extends Context>(bot: Bot<C>): void {
  // Games submenu
  bot.callbackQuery('menu:games', async (ctx) => {
    await ctx.answerCallbackQuery();
    const kb = new InlineKeyboard()
      .text('🪙 Монетка', 'game:coinflip')
      .text('🎲 Кубик', 'game:dice')
      .row()
      .text('🎰 Слоты', 'game:slots')
      .row()
      .text('« Назад', 'menu:main');

    await ctx.editMessageText(
      `🎮 <b>Мини-игры</b>\n\n` +
        `🪙 <b>Монетка</b> — орёл или решка × 2\n` +
        `🎲 <b>Кубик</b> — угадай число 1-6, точно × 5, рядом × 1\n` +
        `🎰 <b>Слоты</b> — три барабана, все = × 10, два = × 2`,
      { parse_mode: 'HTML', reply_markup: kb },
    );
  });

  // Help
  bot.callbackQuery('menu:help', async (ctx) => {
    await ctx.answerCallbackQuery();
    const text =
      `❓ <b>Помощь</b>\n\n` +
      `📌 <b>Как играть:</b>\n` +
      `Выбери игру, введи ставку и испытай удачу!\n\n` +
      `💎 <b>VIP-статус:</b>\n` +
      `+10% к каждому выигрышу во всех играх\n\n` +
      `📋 <b>Задания:</b>\n` +
      `Ежедневные задания сбрасываются в 00:00 UTC\n\n` +
      `💰 <b>Стартовый баланс:</b> 100 очков\n\n` +
      `🆘 Поддержка: @rmex_support`;

    await ctx.editMessageText(text, {
      parse_mode: 'HTML',
      reply_markup: new InlineKeyboard().text('« Назад', 'menu:main'),
    });
  });

  // Buy redirect
  bot.callbackQuery('menu:buy', async (ctx) => {
    await ctx.answerCallbackQuery();
    const kb = new InlineKeyboard()
      .text('💰 500 очков — 50 ⭐', 'buy:pack_500')
      .row()
      .text('💎 1500 очков — 130 ⭐', 'buy:pack_1500')
      .row()
      .text('👑 5000 очков — 400 ⭐', 'buy:pack_5000')
      .row()
      .text('⭐ VIP-статус — 150 ⭐', 'buy:vip_status')
      .row()
      .text('« Назад', 'menu:main');

    const dbUser = (ctx as C & { dbUser: User }).dbUser;
    await ctx.editMessageText(
      `💎 <b>Магазин</b>\n\n💰 Баланс: <b>${dbUser.balance} очков</b>\n\n` +
        `Выберите пакет для покупки:`,
      { parse_mode: 'HTML', reply_markup: kb },
    );
  });

  // Back to main menu
  bot.callbackQuery('menu:main', async (ctx) => {
    await ctx.answerCallbackQuery();
    const dbUser = (ctx as C & { dbUser: User }).dbUser;
    await ctx.editMessageText(
      `🏠 <b>Главное меню</b>\n\n💰 Баланс: <b>${dbUser.balance} очков</b>` +
        (dbUser.isVip ? '\n⭐ VIP активен' : ''),
      { parse_mode: 'HTML', reply_markup: mainMenuKeyboard() },
    );
  });
}
