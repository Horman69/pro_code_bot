import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore

logger = logging.getLogger(__name__)


def create_scheduler() -> AsyncIOScheduler:
    """
    Создаём планировщик с SQLAlchemy job store.
    Jobs сохраняются в БД — выживают при перезапуске бота.
    """
    jobstores = {
        # Используем отдельный файл для jobs чтобы не мешать основной БД
        "default": SQLAlchemyJobStore(url="sqlite:///data/scheduler.db")
    }

    scheduler = AsyncIOScheduler(jobstores=jobstores)
    return scheduler


def setup_recurring_jobs(scheduler: AsyncIOScheduler) -> None:
    """
    Регистрируем повторяющиеся задачи:
    - Утренний отчёт менеджеру в 9:00 каждый день
    - Проверка реферальных milestone в полночь
    - Генерация уроков по шаблонам в 00:30
    """
    from bot.scheduler.jobs import (
        send_morning_schedule, check_referral_milestones, generate_recurring_lessons
    )

    # Утренний отчёт — каждый день в 9:00
    scheduler.add_job(
        send_morning_schedule,
        trigger="cron",
        hour=9,
        minute=0,
        id="morning_schedule",
        replace_existing=True,
        misfire_grace_time=300,  # 5 минут допуска если бот был выключен
    )

    # Проверка рефералов — каждую ночь в 00:05
    scheduler.add_job(
        check_referral_milestones,
        trigger="cron",
        hour=0,
        minute=5,
        id="referral_milestones",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    # Генерация уроков по шаблонам — каждую ночь в 00:30
    scheduler.add_job(
        generate_recurring_lessons,
        trigger="cron",
        hour=0,
        minute=30,
        id="generate_recurring_lessons",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    logger.info("Повторяющиеся задачи зарегистрированы")
