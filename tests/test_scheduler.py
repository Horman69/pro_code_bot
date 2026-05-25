"""
Тесты планировщика — проверяем логику напоминаний и генерации повторяющихся уроков.
"""
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from bot.database import crud
from bot.utils import local_now
from tests.conftest import MockScheduler

# Фиксированное "сейчас" для детерминированных проверок таймингов
FIXED_NOW = datetime(2026, 5, 25, 10, 0, 0)  # Понедельник


# ──────────────────────────────────────────────
# НАПОМИНАНИЯ — КОЛИЧЕСТВО ЗАДАЧ
# ──────────────────────────────────────────────

async def test_schedule_reminders_30_days_ahead_creates_3_jobs(mock_scheduler):
    """Урок через 30 дней — все три напоминания (24ч, 1ч, 15мин)."""
    from bot.scheduler.jobs import schedule_lesson_reminders
    scheduled_at = FIXED_NOW + timedelta(days=30)
    with patch("bot.scheduler.jobs.local_now", return_value=FIXED_NOW):
        await schedule_lesson_reminders(lesson_id=1, scheduled_at=scheduled_at)
    assert len(mock_scheduler.jobs) == 3
    assert "reminder_24h_1" in mock_scheduler.jobs
    assert "reminder_1h_1" in mock_scheduler.jobs
    assert "reminder_15m_1" in mock_scheduler.jobs


async def test_schedule_reminders_22h_ahead_creates_2_jobs(mock_scheduler):
    """Урок через 22 часа — только 1ч и 15мин (24ч уже в прошлом)."""
    from bot.scheduler.jobs import schedule_lesson_reminders
    scheduled_at = FIXED_NOW + timedelta(hours=22)
    with patch("bot.scheduler.jobs.local_now", return_value=FIXED_NOW):
        await schedule_lesson_reminders(lesson_id=2, scheduled_at=scheduled_at)
    assert len(mock_scheduler.jobs) == 2
    assert "reminder_24h_2" not in mock_scheduler.jobs
    assert "reminder_1h_2" in mock_scheduler.jobs
    assert "reminder_15m_2" in mock_scheduler.jobs


async def test_schedule_reminders_30min_ahead_creates_1_job(mock_scheduler):
    """Урок через 30 минут — только 15мин (24ч и 1ч уже в прошлом)."""
    from bot.scheduler.jobs import schedule_lesson_reminders
    scheduled_at = FIXED_NOW + timedelta(minutes=30)
    with patch("bot.scheduler.jobs.local_now", return_value=FIXED_NOW):
        await schedule_lesson_reminders(lesson_id=3, scheduled_at=scheduled_at)
    assert len(mock_scheduler.jobs) == 1
    assert "reminder_15m_3" in mock_scheduler.jobs


async def test_schedule_reminders_5min_ahead_creates_no_jobs(mock_scheduler):
    """Урок через 5 минут — все напоминания уже в прошлом, задачи не создаются."""
    from bot.scheduler.jobs import schedule_lesson_reminders
    scheduled_at = FIXED_NOW + timedelta(minutes=5)
    with patch("bot.scheduler.jobs.local_now", return_value=FIXED_NOW):
        await schedule_lesson_reminders(lesson_id=4, scheduled_at=scheduled_at)
    assert len(mock_scheduler.jobs) == 0


async def test_schedule_reminders_past_lesson_creates_no_jobs(mock_scheduler):
    """Урок в прошлом — ни одной задачи."""
    from bot.scheduler.jobs import schedule_lesson_reminders
    scheduled_at = FIXED_NOW - timedelta(hours=1)
    with patch("bot.scheduler.jobs.local_now", return_value=FIXED_NOW):
        await schedule_lesson_reminders(lesson_id=5, scheduled_at=scheduled_at)
    assert len(mock_scheduler.jobs) == 0


async def test_schedule_reminders_correct_run_dates(mock_scheduler):
    """Проверяем точное время запуска каждого напоминания."""
    from bot.scheduler.jobs import schedule_lesson_reminders
    scheduled_at = FIXED_NOW + timedelta(days=2)
    with patch("bot.scheduler.jobs.local_now", return_value=FIXED_NOW):
        await schedule_lesson_reminders(lesson_id=6, scheduled_at=scheduled_at)
    assert mock_scheduler.jobs["reminder_24h_6"]["run_date"] == scheduled_at - timedelta(hours=24)
    assert mock_scheduler.jobs["reminder_1h_6"]["run_date"] == scheduled_at - timedelta(hours=1)
    assert mock_scheduler.jobs["reminder_15m_6"]["run_date"] == scheduled_at - timedelta(minutes=15)


# ──────────────────────────────────────────────
# ОТМЕНА НАПОМИНАНИЙ
# ──────────────────────────────────────────────

async def test_cancel_lesson_reminders_removes_all_jobs(mock_scheduler):
    """После переноса/отмены урока все три задачи удаляются."""
    from bot.scheduler.jobs import schedule_lesson_reminders, cancel_lesson_reminders
    scheduled_at = FIXED_NOW + timedelta(days=2)
    with patch("bot.scheduler.jobs.local_now", return_value=FIXED_NOW):
        await schedule_lesson_reminders(lesson_id=7, scheduled_at=scheduled_at)
    assert len(mock_scheduler.jobs) == 3
    cancel_lesson_reminders(7)
    assert len(mock_scheduler.jobs) == 0


async def test_cancel_lesson_reminders_silent_if_no_jobs(mock_scheduler):
    """Отмена несуществующих задач не должна падать с исключением."""
    from bot.scheduler.jobs import cancel_lesson_reminders
    cancel_lesson_reminders(999)  # не должно вызвать исключение


async def test_cancel_reminders_replace_existing(mock_scheduler):
    """При повторном планировании старые задачи заменяются на новые."""
    from bot.scheduler.jobs import schedule_lesson_reminders
    dt1 = FIXED_NOW + timedelta(days=2)
    dt2 = FIXED_NOW + timedelta(days=5)
    with patch("bot.scheduler.jobs.local_now", return_value=FIXED_NOW):
        await schedule_lesson_reminders(lesson_id=8, scheduled_at=dt1)
        await schedule_lesson_reminders(lesson_id=8, scheduled_at=dt2)
    # replace_existing=True — задач всё ещё 3, но с новыми датами
    assert len(mock_scheduler.jobs) == 3
    assert mock_scheduler.jobs["reminder_24h_8"]["run_date"] == dt2 - timedelta(hours=24)


# ──────────────────────────────────────────────
# ГЕНЕРАЦИЯ ПОВТОРЯЮЩИХСЯ УРОКОВ
# ──────────────────────────────────────────────

def _make_session_ctx(s):
    """Фабрика патча get_session — возвращает наш тестовый сеанс вместо реального."""
    @asynccontextmanager
    async def _ctx():
        yield s
    return _ctx


async def test_generate_recurring_lessons_creates_lessons(session, mock_scheduler):
    """generate_recurring_lessons должна создать уроки по шаблону расписания."""
    from bot.scheduler.jobs import generate_recurring_lessons

    s = await crud.create_student(session, name="Повтор", payment_type="prepaid")
    # Завтрашний день недели — гарантированно попадает в окно 14 дней
    tomorrow_weekday = (local_now().weekday() + 1) % 7
    await crud.create_recurring_schedule(session, s.id, tomorrow_weekday, 15, 0)
    await session.flush()

    with patch("bot.database.session.get_session", _make_session_ctx(session)):
        with patch("bot.scheduler.jobs.schedule_lesson_reminders", AsyncMock()):
            await generate_recurring_lessons()

    lessons = await crud.get_upcoming_lessons(session, s.id, limit=20)
    assert len(lessons) > 0


async def test_generate_recurring_lessons_idempotent(session, mock_scheduler):
    """Повторный вызов не создаёт дубликаты — lesson_exists_at защищает от этого."""
    from bot.scheduler.jobs import generate_recurring_lessons

    s = await crud.create_student(session, name="Повтор", payment_type="prepaid")
    tomorrow_weekday = (local_now().weekday() + 1) % 7
    await crud.create_recurring_schedule(session, s.id, tomorrow_weekday, 15, 0)
    await session.flush()

    with patch("bot.database.session.get_session", _make_session_ctx(session)):
        mock_remind = AsyncMock()
        with patch("bot.scheduler.jobs.schedule_lesson_reminders", mock_remind):
            await generate_recurring_lessons()
            first_call_count = mock_remind.call_count
            await generate_recurring_lessons()
            second_call_count = mock_remind.call_count

    # Второй вызов не создал ни одного нового урока
    assert second_call_count == first_call_count


async def test_generate_recurring_lessons_skips_inactive_students(session, mock_scheduler):
    """Деактивированный ученик — расписание игнорируется."""
    from bot.scheduler.jobs import generate_recurring_lessons

    s = await crud.create_student(session, name="Деакт", payment_type="prepaid")
    tomorrow_weekday = (local_now().weekday() + 1) % 7
    await crud.create_recurring_schedule(session, s.id, tomorrow_weekday, 15, 0)
    await crud.deactivate_student(session, s.id)
    await session.flush()

    with patch("bot.database.session.get_session", _make_session_ctx(session)):
        mock_remind = AsyncMock()
        with patch("bot.scheduler.jobs.schedule_lesson_reminders", mock_remind):
            await generate_recurring_lessons()

    # Для деактивированного ученика уроков создано не было
    assert mock_remind.call_count == 0
