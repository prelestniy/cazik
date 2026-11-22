import { Bot, Context, InlineKeyboard } from 'grammy';
import { User } from '@prisma/client';
import {
  getSystemStats,
  getRecentEvents,
  broadcast,
  findUserForAdmin,
  logEvent,
} from '../../services/adminService';
import {
  blockUser,
  grantVip,
  adminGrantPoints,
  adminDeductPoints,
  getUserById,
} from '../../services/userService';
import { getAllGameConfigs, setGameConfig } from '../../services/gameService';
import { formatBalance, formatUserName } from '../../utils/formatters';
import { logger } from '../../utils/logger';

function adminMenuKeyboard(): InlineKeyboard {
  return new InlineKeyboard()
    .text('📊 Статистика', 'admin:stats')
    .text('📋 События', 'admin:events')
    .row()
    .text('👤 Найти юзера', 'admin:find_user')
    .text('⚙️ Конфиг игр', 'admin:configs')
    .row()
    .text('📢 Рассылка', 'admin:broadcast');
}

function userManageKeyboard(userId: number, isBlocked: boolean, isVip: boolean): InlineKeyboard {
  return new InlineKeyboard()
    .text(isBlocked ? '✅ Разблокировать' : '🚫 Заблокировать', `admin:toggle_block:${userId}`)
    .text(isVip ? '❌ Снять VIP' : '⭐ Дать VIP', `admin:toggle_vip:${userId}`)
    .row()
    .text('➕ Начислить очки', `admin:grant:${userId}`)
    .text('➖ Снять очки', `admin:deduct:${userId}`)
    .row()
    .text('« Назад', 'admin:main');
}

// Pending actions store (in-memory, simple state machine)
const pendingActions = new Map<
  number,
  { action: string; targetId?: number; step?: string }
>();

export function registerAdminCommand<C extends Context>(
  bot: Bot<C>,
  adminIds: number[],
): void {
  // /admin — entry point
  bot.command('admin', async (ctx) => {
    if (!ctx.from || !adminIds.includes(ctx.from.id)) {
      await ctx.reply('⛔ Нет доступа.');
      return;
    }

    await ctx.reply(
      '🛠 <b>Панель администратора</b>\n\nВыберите действие:',
      { parse_mode: 'HTML', reply_markup: adminMenuKeyboard() },
    );
  });

  // ─── Stats ───────────────────────────────────────────────────
  bot.callbackQuery('admin:stats', async (ctx) => {
    if (!adminIds.includes(ctx.from.id)) return ctx.answerCallbackQuery('⛔');
    await ctx.answerCallbackQuery();

    const stats = await getSystemStats();

    const text =
      `📊 <b>Системная статистика</b>\n\n` +
      `👥 Всего пользователей: <b>${stats.totalUsers}</b>\n` +
      `🟢 Активных за 24ч: <b>${stats.activeUsers24h}</b>\n` +
      `🎮 Всего игр: <b>${stats.totalGames}</b>\n` +
      `🏆 Топ игра: <b>${stats.topGame}</b>\n` +
      `💳 Транзакций: <b>${stats.totalTransactions}</b>\n` +
      `💰 Оборот очков: <b>${formatBalance(stats.totalPoints)}</b>`;

    await ctx.editMessageText(text, {
      parse_mode: 'HTML',
      reply_markup: new InlineKeyboard().text('« Назад', 'admin:main'),
    });
  });

  // ─── Events log ──────────────────────────────────────────────
  bot.callbackQuery('admin:events', async (ctx) => {
    if (!adminIds.includes(ctx.from.id)) return ctx.answerCallbackQuery('⛔');
    await ctx.answerCallbackQuery();

    const events = await getRecentEvents(15);
    const lines = events.map((e) => {
      const name = e.user ? e.user.username || e.user.firstName : 'system';
      const time = e.createdAt.toISOString().slice(11, 19);
      return `[${time}] <code>${e.eventType}</code> — ${name}`;
    });

    await ctx.editMessageText(
      `📋 <b>Последние события</b>\n\n${lines.join('\n')}`,
      {
        parse_mode: 'HTML',
        reply_markup: new InlineKeyboard().text('« Назад', 'admin:main'),
      },
    );
  });

  // ─── Back to main ─────────────────────────────────────────────
  bot.callbackQuery('admin:main', async (ctx) => {
    if (!adminIds.includes(ctx.from.id)) return ctx.answerCallbackQuery('⛔');
    await ctx.answerCallbackQuery();
    await ctx.editMessageText('🛠 <b>Панель администратора</b>\n\nВыберите действие:', {
      parse_mode: 'HTML',
      reply_markup: adminMenuKeyboard(),
    });
  });

  // ─── Find user ────────────────────────────────────────────────
  bot.callbackQuery('admin:find_user', async (ctx) => {
    if (!adminIds.includes(ctx.from.id)) return ctx.answerCallbackQuery('⛔');
    await ctx.answerCallbackQuery();
    pendingActions.set(ctx.from.id, { action: 'find_user' });
    await ctx.reply('🔍 Введите Telegram ID, @username или внутренний ID пользователя:');
  });

  // ─── Game configs ─────────────────────────────────────────────
  bot.callbackQuery('admin:configs', async (ctx) => {
    if (!adminIds.includes(ctx.from.id)) return ctx.answerCallbackQuery('⛔');
    await ctx.answerCallbackQuery();

    const configs = await getAllGameConfigs();
    const lines = configs.map((c) => `<code>${c.key}</code> = <b>${c.value}</b>`);

    await ctx.editMessageText(
      `⚙️ <b>Конфигурация игр</b>\n\n${lines.join('\n')}\n\n` +
        `Для изменения отправьте: <code>/setconfig ключ значение</code>`,
      {
        parse_mode: 'HTML',
        reply_markup: new InlineKeyboard().text('« Назад', 'admin:main'),
      },
    );
  });

  // ─── Broadcast ────────────────────────────────────────────────
  bot.callbackQuery('admin:broadcast', async (ctx) => {
    if (!adminIds.includes(ctx.from.id)) return ctx.answerCallbackQuery('⛔');
    await ctx.answerCallbackQuery();
    pendingActions.set(ctx.from.id, { action: 'broadcast' });
    await ctx.reply(
      '📢 Введите сообщение для рассылки всем пользователям.\n' +
        'Поддерживается HTML. Отправьте /cancel для отмены.',
    );
  });

  // ─── Toggle block ─────────────────────────────────────────────
  bot.callbackQuery(/^admin:toggle_block:(\d+)$/, async (ctx) => {
    if (!adminIds.includes(ctx.from.id)) return ctx.answerCallbackQuery('⛔');
    const targetId = parseInt(ctx.match[1]);
    const target = await getUserById(targetId);
    if (!target) return ctx.answerCallbackQuery('Юзер не найден');

    const updated = await blockUser(targetId, !target.isBlocked);
    await logEvent('ADMIN_BLOCK_TOGGLE', ctx.from.id, {
      targetId,
      blocked: updated.isBlocked,
    });
    await ctx.answerCallbackQuery(updated.isBlocked ? '🚫 Заблокирован' : '✅ Разблокирован');
    await ctx.editMessageReplyMarkup({
      reply_markup: userManageKeyboard(targetId, updated.isBlocked, updated.isVip),
    });
  });

  // ─── Toggle VIP ──────────────────────────────────────────────
  bot.callbackQuery(/^admin:toggle_vip:(\d+)$/, async (ctx) => {
    if (!adminIds.includes(ctx.from.id)) return ctx.answerCallbackQuery('⛔');
    const targetId = parseInt(ctx.match[1]);
    const target = await getUserById(targetId);
    if (!target) return ctx.answerCallbackQuery('Юзер не найден');

    const updated = await grantVip(targetId, !target.isVip);
    await logEvent('ADMIN_VIP_TOGGLE', ctx.from.id, { targetId, vip: updated.isVip });
    await ctx.answerCallbackQuery(updated.isVip ? '⭐ VIP выдан' : '❌ VIP снят');
    await ctx.editMessageReplyMarkup({
      reply_markup: userManageKeyboard(targetId, updated.isBlocked, updated.isVip),
    });
  });

  // ─── Grant/deduct points (step 1) ────────────────────────────
  bot.callbackQuery(/^admin:(grant|deduct):(\d+)$/, async (ctx) => {
    if (!adminIds.includes(ctx.from.id)) return ctx.answerCallbackQuery('⛔');
    await ctx.answerCallbackQuery();
    const action = ctx.match[1]; // 'grant' or 'deduct'
    const targetId = parseInt(ctx.match[2]);
    pendingActions.set(ctx.from.id, { action: `${action}_points`, targetId });
    await ctx.reply(`💬 Введите количество очков для ${action === 'grant' ? 'начисления' : 'снятия'}:`);
  });

  // /setconfig command
  bot.command('setconfig', async (ctx) => {
    if (!ctx.from || !adminIds.includes(ctx.from.id)) {
      await ctx.reply('⛔ Нет доступа.');
      return;
    }
    const args = ctx.message?.text?.split(' ').slice(1);
    if (!args || args.length < 2) {
      await ctx.reply('Использование: /setconfig ключ значение');
      return;
    }
    const [key, ...rest] = args;
    const value = rest.join(' ');
    await setGameConfig(key, value);
    await logEvent('ADMIN_CONFIG_CHANGE', ctx.from.id, { key, value });
    await ctx.reply(`✅ Конфиг обновлён: <code>${key}</code> = <b>${value}</b>`, {
      parse_mode: 'HTML',
    });
  });

  // ─── Text handler for pending admin actions ───────────────────
  bot.on('message:text', async (ctx, next) => {
    if (!ctx.from || !adminIds.includes(ctx.from.id)) return next();

    const pending = pendingActions.get(ctx.from.id);
    if (!pending) return next();

    const text = ctx.message.text.trim();

    if (text === '/cancel') {
      pendingActions.delete(ctx.from.id);
      await ctx.reply('❌ Действие отменено.');
      return;
    }

    // find_user
    if (pending.action === 'find_user') {
      pendingActions.delete(ctx.from.id);
      const found = await findUserForAdmin(text);
      if (!found) {
        await ctx.reply('❌ Пользователь не найден.');
        return;
      }
      const info =
        `👤 <b>Пользователь</b>\n\n` +
        `🆔 ID: <code>${found.id}</code>\n` +
        `📱 Telegram ID: <code>${found.telegramId}</code>\n` +
        `👤 Имя: ${found.firstName} ${found.lastName ?? ''}\n` +
        `🔖 Username: ${found.username ? `@${found.username}` : 'нет'}\n` +
        `💰 Баланс: <b>${formatBalance(found.balance)}</b>\n` +
        `🎮 Игр: ${found.totalGames} | Побед: ${found.totalWins}\n` +
        `⭐ VIP: ${found.isVip ? 'Да' : 'Нет'}\n` +
        `🚫 Блок: ${found.isBlocked ? 'Да' : 'Нет'}\n` +
        `📅 Регистрация: ${found.createdAt.toLocaleDateString('ru-RU')}`;

      await ctx.reply(info, {
        parse_mode: 'HTML',
        reply_markup: userManageKeyboard(found.id, found.isBlocked, found.isVip),
      });
      return;
    }

    // broadcast
    if (pending.action === 'broadcast') {
      pendingActions.delete(ctx.from.id);
      await ctx.reply('📤 Начинаю рассылку...');
      const { sent, failed } = await broadcast(bot, text, ctx.from.id);
      await ctx.reply(
        `✅ Рассылка завершена\n📤 Отправлено: ${sent}\n❌ Ошибок: ${failed}`,
      );
      return;
    }

    // grant/deduct points
    if (pending.action === 'grant_points' || pending.action === 'deduct_points') {
      const amount = parseInt(text);
      if (isNaN(amount) || amount <= 0) {
        await ctx.reply('❌ Введите положительное число.');
        return;
      }
      const targetId = pending.targetId!;
      pendingActions.delete(ctx.from.id);

      try {
        if (pending.action === 'grant_points') {
          await adminGrantPoints(targetId, amount, ctx.from.id);
          await logEvent('ADMIN_GRANT', ctx.from.id, { targetId, amount });
          await ctx.reply(`✅ Начислено ${formatBalance(amount)} очков пользователю #${targetId}`);
        } else {
          await adminDeductPoints(targetId, amount, ctx.from.id);
          await logEvent('ADMIN_DEDUCT', ctx.from.id, { targetId, amount });
          await ctx.reply(`✅ Снято ${formatBalance(amount)} очков с пользователя #${targetId}`);
        }
      } catch (err) {
        logger.error({ err }, 'Admin points error');
        await ctx.reply('❌ Ошибка при изменении баланса.');
      }
      return;
    }

    return next();
  });
}
