import { Bot, Context, InlineKeyboard } from 'grammy';
import { User, TransactionType } from '@prisma/client';
import { prisma } from '../../db/client';
import { grantVip } from '../../services/userService';
import { logEvent } from '../../services/adminService';
import { formatBalance } from '../../utils/formatters';
import { logger } from '../../utils/logger';

interface ShopItem {
  id: string;
  title: string;
  description: string;
  points: number;
  stars: number;
  isVip?: boolean;
}

const SHOP_ITEMS: ShopItem[] = [
  {
    id: 'pack_500',
    title: '💰 Пакет 500 очков',
    description: 'Получи 500 виртуальных очков для игр',
    points: 500,
    stars: 50,
  },
  {
    id: 'pack_1500',
    title: '💎 Пакет 1500 очков',
    description: 'Получи 1500 виртуальных очков — выгодно!',
    points: 1500,
    stars: 130,
  },
  {
    id: 'pack_5000',
    title: '👑 Пакет 5000 очков',
    description: 'Максимальный набор — 5000 очков',
    points: 5000,
    stars: 400,
  },
  {
    id: 'vip_status',
    title: '⭐ VIP-статус (30 дней)',
    description: '+10% к каждому выигрышу навсегда',
    points: 0,
    stars: 150,
    isVip: true,
  },
];

function shopKeyboard(): InlineKeyboard {
  const kb = new InlineKeyboard();
  SHOP_ITEMS.forEach((item) => {
    kb.text(`${item.title} — ${item.stars} ⭐`, `buy:${item.id}`).row();
  });
  kb.text('« Главное меню', 'menu:main');
  return kb;
}

export function registerBuyCommand<C extends Context>(bot: Bot<C>): void {
  bot.command('buy', async (ctx) => {
    const dbUser = (ctx as C & { dbUser: User }).dbUser;

    const text =
      `💎 <b>Магазин очков</b>\n\n` +
      `💰 Ваш баланс: <b>${formatBalance(dbUser.balance)} очков</b>\n` +
      (dbUser.isVip ? `⭐ VIP-статус: активен\n` : '') +
      `\n📌 Оплата через Telegram Stars (⭐)`;

    await ctx.reply(text, { parse_mode: 'HTML', reply_markup: shopKeyboard() });
  });

  // Callback when user taps buy button
  bot.callbackQuery(/^buy:(.+)$/, async (ctx) => {
    await ctx.answerCallbackQuery();
    const itemId = ctx.match[1];
    const item = SHOP_ITEMS.find((i) => i.id === itemId);
    if (!item) return;

    // Send Telegram Stars invoice
    await ctx.replyWithInvoice(
      item.title,
      item.description,
      JSON.stringify({ itemId }),      // payload — parsed on successful_payment
      'XTR',                            // currency for Telegram Stars
      [{ label: item.title, amount: item.stars }],
    );
  });

  // Pre-checkout — always approve
  bot.on('pre_checkout_query', async (ctx) => {
    await ctx.answerPreCheckoutQuery(true);
  });

  // Successful payment — idempotency via payment_charge_id
  bot.on('message:successful_payment', async (ctx) => {
    const payment = ctx.message.successful_payment;
    const chargeId = payment.telegram_payment_charge_id;
    const dbUser = (ctx as C & { dbUser: User }).dbUser;

    // Idempotency check
    const existing = await prisma.transaction.findUnique({
      where: { paymentChargeId: chargeId },
    });
    if (existing) {
      logger.warn({ chargeId, userId: dbUser.id }, 'Duplicate payment ignored');
      await ctx.reply('✅ Платёж уже обработан ранее.');
      return;
    }

    let payload: { itemId: string };
    try {
      payload = JSON.parse(payment.invoice_payload);
    } catch {
      logger.error({ chargeId }, 'Invalid invoice payload');
      return;
    }

    const item = SHOP_ITEMS.find((i) => i.id === payload.itemId);
    if (!item) {
      logger.error({ payload }, 'Unknown shop item');
      return;
    }

    try {
      await prisma.$transaction(async (tx) => {
        if (item.points > 0) {
          await tx.user.update({
            where: { id: dbUser.id },
            data: { balance: { increment: item.points } },
          });
        }

        if (item.isVip) {
          await tx.user.update({
            where: { id: dbUser.id },
            data: { isVip: true },
          });
        }

        await tx.transaction.create({
          data: {
            userId: dbUser.id,
            type: TransactionType.PURCHASE,
            amount: item.points || item.stars,
            description: `Purchase: ${item.title}`,
            paymentChargeId: chargeId,
          },
        });
      });

      await logEvent('PURCHASE', dbUser.id, {
        itemId: item.id,
        stars: item.stars,
        chargeId,
      });

      const successText = item.isVip
        ? `⭐ <b>VIP-статус активирован!</b>\n\nТеперь вы получаете +10% к каждому выигрышу.`
        : `✅ <b>Успешная покупка!</b>\n\n💰 Начислено: <b>${formatBalance(item.points)} очков</b>\n` +
          `📊 Новый баланс: (обновите профиль)`;

      await ctx.reply(successText, { parse_mode: 'HTML' });

      logger.info({ userId: dbUser.id, itemId: item.id, chargeId }, 'Purchase completed');
    } catch (err) {
      logger.error({ err, chargeId }, 'Payment processing error');
      await ctx.reply('❌ Ошибка обработки платежа. Поддержка: @admin');
    }
  });
}
