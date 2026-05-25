import logging
from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError

from bot import config

logger = logging.getLogger(__name__)

# Бот-инстанс и username кэшируются при старте — дорогой API-вызов делаем один раз
_bot: Bot | None = None
_bot_username: str = ""


def set_bot(bot: Bot) -> None:
    """Регистрируем бот-инстанс для отправки уведомлений."""
    global _bot
    _bot = bot


def set_bot_username(username: str) -> None:
    """Кэшируем username бота чтобы не делать get_me() при каждом инвайте."""
    global _bot_username
    _bot_username = username


def get_bot_username() -> str:
    """Возвращаем закэшированный username бота."""
    return _bot_username


async def _send(telegram_id: int, text: str, **kwargs) -> bool:
    """Безопасная отправка — не падаем если пользователь заблокировал бота."""
    try:
        await _bot.send_message(telegram_id, text, **kwargs)
        return True
    except TelegramForbiddenError:
        logger.warning(f"Пользователь {telegram_id} заблокировал бота")
        return False
    except Exception as e:
        logger.error(f"Ошибка отправки сообщения {telegram_id}: {e}")
        return False


# ──────────────────────────────────────────────
# УВЕДОМЛЕНИЯ РОДИТЕЛЮ
# ──────────────────────────────────────────────

async def notify_parent_reminder_24h(
    parent_tg_id: int,
    student_name: str,
    lesson_time: str,
    lesson_id: int,
) -> None:
    """Напоминание родителю за 24 часа."""
    from bot.keyboards.parent_kb import lesson_reminder_keyboard
    await _send(
        parent_tg_id,
        f"📅 Завтра урок!\n\n"
        f"Ученик: <b>{student_name}</b>\n"
        f"Время: <b>{lesson_time}</b>\n\n"
        f"Подтвердите посещение:",
        reply_markup=lesson_reminder_keyboard(lesson_id),
        parse_mode="HTML"
    )


async def notify_parent_lesson_rescheduled(
    parent_tg_id: int,
    student_name: str,
    new_time: str,
) -> None:
    """Уведомление родителю что урок перенесён на новое время."""
    await _send(
        parent_tg_id,
        f"📅 <b>Урок перенесён!</b>\n\n"
        f"Ученик: <b>{student_name}</b>\n"
        f"Новое время: <b>{new_time}</b>",
        parse_mode="HTML"
    )


async def notify_parent_reminder_15m(
    parent_tg_id: int,
    student_name: str,
    lesson_time: str,
) -> None:
    """Напоминание родителю за 15 минут."""
    await _send(
        parent_tg_id,
        f"🔔 Через 15 минут урок!\n\n"
        f"Ученик: <b>{student_name}</b>\n"
        f"Время: <b>{lesson_time}</b>",
        parse_mode="HTML"
    )


async def notify_parent_reminder_1h(
    parent_tg_id: int,
    student_name: str,
    lesson_time: str,
    lesson_id: int,
) -> None:
    """Напоминание родителю за 1 час."""
    from bot.keyboards.parent_kb import lesson_reminder_keyboard
    await _send(
        parent_tg_id,
        f"⏰ Через час урок!\n\n"
        f"Ученик: <b>{student_name}</b>\n"
        f"Время: <b>{lesson_time}</b>",
        reply_markup=lesson_reminder_keyboard(lesson_id),
        parse_mode="HTML"
    )


async def notify_parent_lesson_completed(
    parent_tg_id: int,
    student_name: str,
    new_balance: int,
    payment_type: str = "prepaid",
) -> None:
    """Уведомление что урок зачтён — для postpaid баланс не показываем."""
    if payment_type == "postpaid":
        await _send(
            parent_tg_id,
            f"✅ Урок проведён!\n\nУченик: <b>{student_name}</b>",
            parse_mode="HTML"
        )
        return

    balance_note = ""
    if new_balance == 0:
        balance_note = "\n\n⚠️ Уроки закончились! Свяжитесь с преподавателем для продления."
    elif new_balance <= 2:
        balance_note = f"\n\n🟡 Осталось мало уроков ({new_balance}). Скоро нужно продлить."

    await _send(
        parent_tg_id,
        f"✅ Урок проведён!\n\n"
        f"Ученик: <b>{student_name}</b>\n"
        f"Остаток уроков: <b>{new_balance}</b>{balance_note}",
        parse_mode="HTML"
    )


async def notify_parent_payment_received(
    parent_tg_id: int,
    student_name: str,
    lessons_count: int,
    new_balance: int,
) -> None:
    """Уведомление об успешном зачислении оплаты."""
    await _send(
        parent_tg_id,
        f"💳 Оплата зачислена!\n\n"
        f"Ученик: <b>{student_name}</b>\n"
        f"Добавлено: <b>{lessons_count}</b> ур.\n"
        f"Текущий баланс: <b>{new_balance}</b> ур.",
        parse_mode="HTML"
    )


async def notify_parent_referral_bonus(
    parent_tg_id: int,
    bonus_type: str,
    amount: int,
    milestone: str,
) -> None:
    """Уведомление о начислении реферального бонуса."""
    milestone_labels = {
        "signup": "ваш друг записался и оплатил",
        "month_1": "ваш друг учится 1 месяц",
        "month_3": "ваш друг учится 3 месяца",
        "month_6": "ваш друг учится 6 месяцев",
    }
    reason = milestone_labels.get(milestone, milestone)

    if bonus_type == "lesson":
        bonus_text = f"+{amount} урок к вашему балансу"
    else:
        bonus_text = f"+{amount:,} руб (свяжитесь с менеджером для получения)".replace(",", " ")

    await _send(
        parent_tg_id,
        f"🎁 Реферальный бонус!\n\n"
        f"Причина: {reason}\n"
        f"Бонус: <b>{bonus_text}</b>",
        parse_mode="HTML"
    )


# ──────────────────────────────────────────────
# УВЕДОМЛЕНИЯ МЕНЕДЖЕРУ
# ──────────────────────────────────────────────

async def notify_manager_referral_visit(
    visitor_name: str,
    referrer_name: str,
) -> None:
    """Новый пользователь перешёл по реферальной ссылке — ещё не оставил заявку."""
    await _send(
        config.MANAGER_TELEGRAM_ID,
        f"👀 <b>Новый переход по реферальной ссылке!</b>\n\n"
        f"Кто пришёл: <b>{visitor_name}</b>\n"
        f"Пригласил: <b>{referrer_name}</b>\n\n"
        f"Пользователь видит лендинг — ждём заявку на пробный урок.",
        parse_mode="HTML"
    )


async def notify_manager_new_parent(parent_name: str, student_name: str) -> None:
    """Новый родитель зарегистрировался."""
    await _send(
        config.MANAGER_TELEGRAM_ID,
        f"🆕 Новый родитель зарегистрировался!\n\n"
        f"Родитель: <b>{parent_name}</b>\n"
        f"Ученик: <b>{student_name}</b>",
        parse_mode="HTML"
    )


async def notify_manager_lesson_confirmed(lesson_id: int) -> None:
    """Родитель подтвердил что придёт на урок."""
    from bot.database.session import get_session
    from bot.database import crud

    async with get_session() as session:
        lesson = await crud.get_lesson_by_id(session, lesson_id)
        if not lesson:
            return
        student_name = lesson.student.name
        time_str = lesson.scheduled_at.strftime("%d.%m %H:%M")

    await _send(
        config.MANAGER_TELEGRAM_ID,
        f"✅ Подтверждение!\n\n"
        f"{student_name} — {time_str}\n"
        f"Родитель подтвердил что придут."
    )


async def notify_manager_lesson_cancelled(lesson_id: int, reason: str) -> None:
    """Родитель отменил урок."""
    from bot.database.session import get_session
    from bot.database import crud

    async with get_session() as session:
        lesson = await crud.get_lesson_by_id(session, lesson_id)
        if not lesson:
            return
        student_name = lesson.student.name
        time_str = lesson.scheduled_at.strftime("%d.%m %H:%M")

    await _send(
        config.MANAGER_TELEGRAM_ID,
        f"❌ Отмена урока!\n\n"
        f"{student_name} — {time_str}\n"
        f"Причина: {reason}"
    )


async def notify_manager_feedback(parent_name: str, message: str, feedback_id: int) -> None:
    """Новое сообщение обратной связи от родителя."""
    await _send(
        config.MANAGER_TELEGRAM_ID,
        f"💬 Новое сообщение от родителя!\n\n"
        f"От: <b>{parent_name}</b>\n\n"
        f"{message}\n\n"
        f"Ответьте в разделе «Обратная связь».",
        parse_mode="HTML"
    )


async def notify_manager_lesson_reminder(
    student_name: str,
    lesson_time: str,
    parent_confirmed: bool | None,
) -> None:
    """Напоминание менеджеру за 1 час до урока."""
    if parent_confirmed is True:
        confirmed_text = "✅ родитель подтвердил"
    elif parent_confirmed is False:
        confirmed_text = "❌ родитель отменил"
    else:
        confirmed_text = "❓ без ответа"

    await _send(
        config.MANAGER_TELEGRAM_ID,
        f"⏰ Через час урок!\n\n"
        f"Ученик: <b>{student_name}</b>\n"
        f"Время: <b>{lesson_time}</b>\n"
        f"Статус: {confirmed_text}",
        parse_mode="HTML"
    )


async def notify_manager_trial_request(trial_id: int, data: dict) -> None:
    """Новая заявка на пробный урок — уведомляем менеджера с кнопками."""
    from bot.keyboards.manager_kb import trial_request_keyboard
    age_text = f"{data['child_age']} лет" if data.get("child_age") else "не указан"
    phone_text = data.get("phone") or "не указан"
    time_text = data.get("preferred_time") or "не указано"

    await _send(
        config.MANAGER_TELEGRAM_ID,
        f"🆕 <b>Новая заявка на пробный урок!</b>\n\n"
        f"👤 Родитель: <b>{data['parent_name']}</b>\n"
        f"👦 Ребёнок: <b>{data['child_name']}</b>\n"
        f"🎂 Возраст: {age_text}\n"
        f"📱 Телефон: {phone_text}\n"
        f"🕐 Удобное время: {time_text}",
        reply_markup=trial_request_keyboard(trial_id),
        parse_mode="HTML"
    )


async def notify_manager_bug_report(user_full_name: str, user_info: str, description: str) -> None:
    """Родитель сообщил об ошибке — пересылаем менеджеру."""
    await _send(
        config.MANAGER_TELEGRAM_ID,
        f"🐛 <b>Сообщение об ошибке!</b>\n\n"
        f"От: <b>{user_full_name}</b> ({user_info})\n\n"
        f"{description}",
        parse_mode="HTML",
    )


async def notify_manager_news_subscription(parent_name: str, subscribed: bool) -> None:
    """Родитель подписался или отписался от IT-новостей."""
    icon = "🔔" if subscribed else "🔕"
    action = "подписался на IT-новости" if subscribed else "отписался от IT-новостей"
    await _send(
        config.MANAGER_TELEGRAM_ID,
        f"{icon} <b>{parent_name}</b> {action}",
        parse_mode="HTML"
    )


async def notify_manager_report_requested(
    parent_name: str,
    student_name: str,
    student_id: int,
    parent_tg_id: int,
) -> None:
    """Родитель запросил отчёт о прогрессе — уведомляем менеджера с кнопкой ответа."""
    from bot.keyboards.manager_kb import write_report_keyboard
    await _send(
        config.MANAGER_TELEGRAM_ID,
        f"📝 Запрос отчёта о прогрессе!\n\n"
        f"Родитель: <b>{parent_name}</b>\n"
        f"Ученик: <b>{student_name}</b>\n\n"
        f"Нажмите кнопку чтобы написать отчёт:",
        reply_markup=write_report_keyboard(student_id, parent_tg_id),
        parse_mode="HTML"
    )


async def send_daily_schedule(lessons: list) -> None:
    """Утренний отчёт менеджеру — все уроки на сегодня."""
    if not lessons:
        await _send(
            config.MANAGER_TELEGRAM_ID,
            "📋 Сегодня уроков нет. Хорошего дня!"
        )
        return

    lines = ["📋 <b>Уроки сегодня:</b>\n"]
    for lesson in lessons:
        time_str = lesson.scheduled_at.strftime("%H:%M")
        lines.append(f"• {time_str} — {lesson.student.name}")

    await _send(
        config.MANAGER_TELEGRAM_ID,
        "\n".join(lines),
        parse_mode="HTML"
    )
