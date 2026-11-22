import { Context, NextFunction } from 'grammy';
import { upsertUser } from '../../services/userService';
import { logEvent } from '../../services/adminService';
import { logger } from '../../utils/logger';

export async function authMiddleware(ctx: Context, next: NextFunction): Promise<void> {
  if (!ctx.from) return next();

  try {
    const user = await upsertUser({
      id: ctx.from.id,
      username: ctx.from.username,
      first_name: ctx.from.first_name,
      last_name: ctx.from.last_name,
    });

    if (user.isBlocked) {
      await ctx.reply('⛔ Ваш аккаунт заблокирован. Обратитесь в поддержку.');
      return;
    }

    // Attach to context
    (ctx as Context & { dbUser: typeof user }).dbUser = user;
  } catch (err) {
    logger.error({ err, userId: ctx.from.id }, 'Auth middleware error');
    await ctx.reply('❌ Произошла ошибка. Попробуйте позже.');
    return;
  }

  return next();
}

export function requireAdmin(adminIds: number[]) {
  return async (ctx: Context, next: NextFunction): Promise<void> => {
    if (!ctx.from || !adminIds.includes(ctx.from.id)) {
      await ctx.reply('⛔ Нет доступа.');
      return;
    }
    await logEvent('ADMIN_ACCESS', ctx.from.id, { command: ctx.message?.text });
    return next();
  };
}
