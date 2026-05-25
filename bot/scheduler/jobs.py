import logging
from datetime import datetime, timedelta

from bot.utils import local_now

logger = logging.getLogger(__name__)

# Планировщик передаётся снаружи при инициализации
_scheduler = None


def set_scheduler(scheduler) -> None:
    """Регистрируем планировщик чтобы jobs могли добавлять задачи."""
    global _scheduler
    _scheduler = scheduler


async def schedule_lesson_reminders(lesson_id: int, scheduled_at: datetime) -> None:
    """
    Планируем все напоминания для урока:
    - за 24 часа родителю и менеджеру
    - за 1 час родителю и менеджеру
    - за 15 минут родителю (финальный сигнал)
    """
    now = local_now()

    # Напоминание за 24 часа
    remind_24h = scheduled_at - timedelta(hours=24)
    if remind_24h > now:
        _scheduler.add_job(
            _send_reminder_24h,
            trigger="date",
            run_date=remind_24h,
            args=[lesson_id],
            id=f"reminder_24h_{lesson_id}",
            replace_existing=True,
        )

    # Напоминание за 1 час
    remind_1h = scheduled_at - timedelta(hours=1)
    if remind_1h > now:
        _scheduler.add_job(
            _send_reminder_1h,
            trigger="date",
            run_date=remind_1h,
            args=[lesson_id],
            id=f"reminder_1h_{lesson_id}",
            replace_existing=True,
        )

    # Напоминание за 15 минут — только родителю
    remind_15m = scheduled_at - timedelta(minutes=15)
    if remind_15m > now:
        _scheduler.add_job(
            _send_reminder_15m,
            trigger="date",
            run_date=remind_15m,
            args=[lesson_id],
            id=f"reminder_15m_{lesson_id}",
            replace_existing=True,
        )

    logger.info(f"Напоминания запланированы для урока id={lesson_id} на {scheduled_at}")


def cancel_lesson_reminders(lesson_id: int) -> None:
    """Отменяем все напоминания при удалении или переносе урока."""
    for job_id in [
        f"reminder_24h_{lesson_id}",
        f"reminder_1h_{lesson_id}",
        f"reminder_15m_{lesson_id}",
    ]:
        try:
            _scheduler.remove_job(job_id)
        except Exception:
            pass  # Job уже не существует — нормально


async def _send_reminder_24h(lesson_id: int) -> None:
    """Отправляем напоминание за 24 часа родителю и менеджеру."""
    from bot.database.session import get_session
    from bot.database import crud
    from bot.services import notifications

    async with get_session() as session:
        lesson = await crud.get_lesson_by_id(session, lesson_id)

        # Урок мог быть отменён пока ждали — проверяем
        if not lesson or lesson.status != "scheduled":
            return

        student = lesson.student
        parent = student.parent
        time_str = lesson.scheduled_at.strftime("%d.%m.%Y %H:%M")

        if parent:
            await notifications.notify_parent_reminder_24h(
                parent.telegram_id, student.name, time_str, lesson_id
            )

        # Уведомляем менеджера о предстоящем уроке завтра
        await notifications.notify_manager_lesson_reminder(
            student.name, time_str, lesson.parent_confirmed
        )
        await crud.mark_reminder_sent(session, lesson_id, "24h")

    logger.info(f"Напоминание 24ч отправлено: урок id={lesson_id}")


async def _send_reminder_1h(lesson_id: int) -> None:
    """Отправляем напоминание за 1 час родителю и менеджеру."""
    from bot.database.session import get_session
    from bot.database import crud
    from bot.services import notifications

    async with get_session() as session:
        lesson = await crud.get_lesson_by_id(session, lesson_id)

        if not lesson or lesson.status != "scheduled":
            return

        student = lesson.student
        parent = student.parent
        time_str = lesson.scheduled_at.strftime("%H:%M")

        if parent:
            await notifications.notify_parent_reminder_1h(
                parent.telegram_id, student.name, time_str, lesson_id
            )

        await notifications.notify_manager_lesson_reminder(
            student.name, time_str, lesson.parent_confirmed
        )

        await crud.mark_reminder_sent(session, lesson_id, "1h")

    logger.info(f"Напоминание 1ч отправлено: урок id={lesson_id}")


async def _send_reminder_15m(lesson_id: int) -> None:
    """Отправляем напоминание за 15 минут — только родителю."""
    from bot.database.session import get_session
    from bot.database import crud
    from bot.services import notifications

    async with get_session() as session:
        lesson = await crud.get_lesson_by_id(session, lesson_id)

        if not lesson or lesson.status != "scheduled":
            return

        student = lesson.student
        parent = student.parent
        time_str = lesson.scheduled_at.strftime("%H:%M")

        if parent:
            await notifications.notify_parent_reminder_15m(
                parent.telegram_id, student.name, time_str
            )

    logger.info(f"Напоминание 15мин отправлено: урок id={lesson_id}")


async def send_morning_schedule() -> None:
    """Ежедневный отчёт менеджеру в 9:00 — все уроки на сегодня."""
    from bot.database.session import get_session
    from bot.database import crud
    from bot.services import notifications

    async with get_session() as session:
        lessons = await crud.get_lessons_today(session)

    await notifications.send_daily_schedule(lessons)
    logger.info(f"Утренний отчёт отправлен: {len(lessons)} уроков сегодня")


async def generate_recurring_lessons() -> None:
    """
    Ежедневная генерация уроков по шаблонам расписания.
    Смотрит на 14 дней вперёд — создаёт уроки которых ещё нет.
    """
    from bot.database.session import get_session
    from bot.database import crud

    now = local_now()
    created_count = 0

    async with get_session() as session:
        schedules = await crud.get_all_active_recurring_schedules(session)

        for schedule in schedules:
            for days_ahead in range(1, 15):
                candidate = now + timedelta(days=days_ahead)
                if candidate.weekday() != schedule.day_of_week:
                    continue

                scheduled_at = candidate.replace(
                    hour=schedule.hour,
                    minute=schedule.minute,
                    second=0,
                    microsecond=0,
                )

                # Не создаём если урок уже есть (idempotency)
                exists = await crud.lesson_exists_at(session, schedule.student_id, scheduled_at)
                if exists:
                    continue

                lesson = await crud.create_lesson(session, schedule.student_id, scheduled_at)
                await schedule_lesson_reminders(lesson.id, scheduled_at)
                created_count += 1

    logger.info(f"Генерация повторяющихся уроков завершена: создано {created_count}")


async def check_referral_milestones() -> None:
    """
    Ежедневная проверка реферальных milestone.
    Запускается в полночь — начисляем бонусы за 1/3/6 месяцев.
    """
    from bot.database.session import get_session
    from bot.database import crud
    from bot.services import notifications
    from bot import config

    async with get_session() as session:
        referrals = await crud.get_active_referrals_for_milestones(session)
        now = local_now()

        for referral in referrals:
            if not referral.first_payment_at:
                continue

            days_active = (now - referral.first_payment_at).days

            # Бонус за 1 месяц (30 дней) — +1 урок
            if days_active >= 30 and not referral.bonus_month_1:
                referral.bonus_month_1 = True
                referrer_students = await crud.get_students_by_parent(session, referral.referrer_id)
                if referrer_students:
                    referrer_students[0].lessons_balance += config.REFERRAL_BONUS_MONTH_1_LESSONS
                await crud.add_referral_bonus(
                    session, referral.id, referral.referrer_id,
                    "lesson", config.REFERRAL_BONUS_MONTH_1_LESSONS, "month_1"
                )
                await notifications.notify_parent_referral_bonus(
                    referral.referrer.telegram_id,
                    "lesson", config.REFERRAL_BONUS_MONTH_1_LESSONS, "month_1"
                )

            # Бонус за 3 месяца (90 дней) — кэш
            if days_active >= 90 and not referral.bonus_month_3:
                referral.bonus_month_3 = True
                await crud.add_referral_bonus(
                    session, referral.id, referral.referrer_id,
                    "cash", config.REFERRAL_BONUS_MONTH_3_CASH, "month_3"
                )
                await notifications.notify_parent_referral_bonus(
                    referral.referrer.telegram_id,
                    "cash", config.REFERRAL_BONUS_MONTH_3_CASH, "month_3"
                )

            # Бонус за 6 месяцев (180 дней) — кэш
            if days_active >= 180 and not referral.bonus_month_6:
                referral.bonus_month_6 = True
                await crud.add_referral_bonus(
                    session, referral.id, referral.referrer_id,
                    "cash", config.REFERRAL_BONUS_MONTH_6_CASH, "month_6"
                )
                await notifications.notify_parent_referral_bonus(
                    referral.referrer.telegram_id,
                    "cash", config.REFERRAL_BONUS_MONTH_6_CASH, "month_6"
                )

    logger.info("Проверка реферальных milestone завершена")
