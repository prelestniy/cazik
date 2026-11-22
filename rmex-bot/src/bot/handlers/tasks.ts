import { Bot, Context, InlineKeyboard } from 'grammy';
import { User } from '@prisma/client';
import {
  getUserDailyTasks,
  claimTaskReward,
} from '../../services/taskService';
import { formatBalance, progressBar, formatTimeLeft } from '../../utils/formatters';

export function registerTasksHandler<C extends Context>(bot: Bot<C>): void {
  bot.callbackQuery('menu:tasks', async (ctx) => {
    await ctx.answerCallbackQuery();
    const dbUser = (ctx as C & { dbUser: User }).dbUser;
    const tasks = await getUserDailyTasks(dbUser.id);

    const kb = new InlineKeyboard();
    const lines: string[] = [];

    for (const ut of tasks) {
      const statusEmoji = ut.rewarded ? '✅' : ut.completed ? '🎁' : '⏳';
      const bar = progressBar(Math.min(ut.progress, ut.task.target), ut.task.target);
      const timeLeft = formatTimeLeft(ut.expiresAt);
      const pct = Math.min(Math.round((ut.progress / ut.task.target) * 100), 100);

      lines.push(
        `${statusEmoji} <b>${ut.task.title}</b>\n` +
          `  ${ut.task.description}\n` +
          `  ${bar} ${pct}% (${Math.min(ut.progress, ut.task.target)}/${ut.task.target})\n` +
          `  🏆 Награда: +${formatBalance(ut.task.reward)} очков | ⏱ ${timeLeft}`,
      );

      if (ut.completed && !ut.rewarded) {
        kb.text(`🎁 Забрать: ${ut.task.title}`, `task:claim:${ut.id}`).row();
      }
    }

    kb.text('« Назад', 'menu:main');

    const text =
      `📋 <b>Ежедневные задания</b>\n\n` +
      `Сбрасываются каждые 24 часа в 00:00 UTC\n\n` +
      lines.join('\n\n');

    await ctx.editMessageText(text, {
      parse_mode: 'HTML',
      reply_markup: kb,
    });
  });

  // Claim reward callback
  bot.callbackQuery(/^task:claim:(\d+)$/, async (ctx) => {
    const userTaskId = parseInt(ctx.match[1]);
    const dbUser = (ctx as C & { dbUser: User }).dbUser;

    const result = await claimTaskReward(dbUser.id, userTaskId);
    if (!result) {
      await ctx.answerCallbackQuery('❌ Награда недоступна.');
      return;
    }

    await ctx.answerCallbackQuery(`🎉 Получено +${result.reward} очков!`);

    // Refresh tasks view
    const tasks = await getUserDailyTasks(dbUser.id);
    const kb = new InlineKeyboard();
    const lines: string[] = [];

    for (const ut of tasks) {
      const statusEmoji = ut.rewarded ? '✅' : ut.completed ? '🎁' : '⏳';
      const bar = progressBar(Math.min(ut.progress, ut.task.target), ut.task.target);
      const pct = Math.min(Math.round((ut.progress / ut.task.target) * 100), 100);

      lines.push(
        `${statusEmoji} <b>${ut.task.title}</b>\n` +
          `  ${ut.task.description}\n` +
          `  ${bar} ${pct}%\n` +
          `  🏆 +${formatBalance(ut.task.reward)} очков`,
      );

      if (ut.completed && !ut.rewarded) {
        kb.text(`🎁 Забрать: ${ut.task.title}`, `task:claim:${ut.id}`).row();
      }
    }

    kb.text('« Назад', 'menu:main');

    await ctx.editMessageText(
      `📋 <b>Ежедневные задания</b>\n\n✅ Получено: <b>+${formatBalance(result.reward)}</b> очков!\n\n` +
        lines.join('\n\n'),
      { parse_mode: 'HTML', reply_markup: kb },
    );
  });
}
