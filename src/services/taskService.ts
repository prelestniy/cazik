import { TaskType, TransactionType } from '@prisma/client';
import { prisma } from '../db/client';
import { logger } from '../utils/logger';

const DAILY_TASK_DEFINITIONS = [
  {
    title: '🎮 Игроман',
    description: 'Сыграй 5 игр',
    type: TaskType.PLAY_GAMES,
    target: 5,
    reward: 50,
  },
  {
    title: '🔥 На волне',
    description: 'Выиграй 2 игры подряд',
    type: TaskType.WIN_STREAK,
    target: 2,
    reward: 100,
  },
  {
    title: '🏆 Элита',
    description: 'Войди в топ-5 рейтинга',
    type: TaskType.TOP_RANK,
    target: 5,
    reward: 200,
  },
];

function getNextMidnight(): Date {
  const d = new Date();
  d.setUTCHours(24, 0, 0, 0);
  return d;
}

export async function ensureTasksExist(): Promise<void> {
  for (const def of DAILY_TASK_DEFINITIONS) {
    await prisma.task.upsert({
      where: { id: DAILY_TASK_DEFINITIONS.indexOf(def) + 1 },
      update: {},
      create: { ...def, isActive: true },
    });
  }
  logger.debug('Default tasks ensured');
}

export async function getUserDailyTasks(userId: number) {
  const now = new Date();

  // Check if user already has tasks assigned today
  const existingTasks = await prisma.userTask.findMany({
    where: {
      userId,
      expiresAt: { gt: now },
    },
    include: { task: true },
  });

  if (existingTasks.length > 0) return existingTasks;

  // Assign fresh daily tasks
  const tasks = await prisma.task.findMany({ where: { isActive: true }, take: 3 });
  const expiresAt = getNextMidnight();

  const userTasks = await Promise.all(
    tasks.map((task) =>
      prisma.userTask.create({
        data: {
          userId,
          taskId: task.id,
          progress: 0,
          completed: false,
          rewarded: false,
          expiresAt,
        },
        include: { task: true },
      }),
    ),
  );

  logger.debug({ userId, count: userTasks.length }, 'Daily tasks assigned');
  return userTasks;
}

export async function updateTaskProgress(userId: number, type: TaskType, increment = 1) {
  const now = new Date();

  const userTasks = await prisma.userTask.findMany({
    where: {
      userId,
      completed: false,
      expiresAt: { gt: now },
      task: { type },
    },
    include: { task: true },
  });

  for (const userTask of userTasks) {
    const newProgress = userTask.progress + increment;
    const completed = newProgress >= userTask.task.target;

    await prisma.userTask.update({
      where: { id: userTask.id },
      data: {
        progress: newProgress,
        completed,
        completedAt: completed ? now : null,
      },
    });

    logger.debug({ userId, taskId: userTask.taskId, newProgress, completed }, 'Task progress updated');
  }
}

export async function claimTaskReward(
  userId: number,
  userTaskId: number,
): Promise<{ reward: number; taskTitle: string } | null> {
  const userTask = await prisma.userTask.findFirst({
    where: {
      id: userTaskId,
      userId,
      completed: true,
      rewarded: false,
      expiresAt: { gt: new Date() },
    },
    include: { task: true },
  });

  if (!userTask) return null;

  await prisma.$transaction([
    prisma.userTask.update({
      where: { id: userTaskId },
      data: { rewarded: true },
    }),
    prisma.user.update({
      where: { id: userId },
      data: { balance: { increment: userTask.task.reward } },
    }),
    prisma.transaction.create({
      data: {
        userId,
        type: TransactionType.TASK_REWARD,
        amount: userTask.task.reward,
        description: `Task reward: ${userTask.task.title}`,
      },
    }),
  ]);

  logger.info({ userId, taskId: userTask.taskId, reward: userTask.task.reward }, 'Task reward claimed');
  return { reward: userTask.task.reward, taskTitle: userTask.task.title };
}

export async function checkTopRankTask(userId: number, rank: number) {
  if (rank > 5) return;
  await updateTaskProgress(userId, TaskType.TOP_RANK, 999); // force complete
}
