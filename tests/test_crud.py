"""
Тесты CRUD-слоя — проверяем каждую функцию работы с базой данных.
Используется in-memory SQLite: каждый тест изолирован и не зависит от других.
"""
from datetime import timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database import crud
from bot.utils import local_now


# ──────────────────────────────────────────────
# Вспомогательные фабрики тестовых объектов
# ──────────────────────────────────────────────

async def _parent(s: AsyncSession, tg_id: int = 100, name: str = "Тест Тестов"):
    return await crud.create_parent(s, telegram_id=tg_id, name=name)


async def _student(s: AsyncSession, name: str = "Миша", ptype: str = "prepaid"):
    return await crud.create_student(s, name=name, payment_type=ptype)


async def _lesson(s: AsyncSession, student_id: int, dt=None):
    dt = dt or (local_now() + timedelta(days=1))
    return await crud.create_lesson(s, student_id, dt)


# ──────────────────────────────────────────────
# РОДИТЕЛИ
# ──────────────────────────────────────────────

async def test_create_parent_gets_id(session):
    p = await _parent(session)
    assert p.id is not None
    assert p.name == "Тест Тестов"
    assert len(p.referral_code) == 32


async def test_get_parent_by_telegram_id_found(session):
    await _parent(session, tg_id=999)
    found = await crud.get_parent_by_telegram_id(session, 999)
    assert found is not None
    assert found.telegram_id == 999


async def test_get_parent_by_telegram_id_not_found(session):
    found = await crud.get_parent_by_telegram_id(session, 999)
    assert found is None


async def test_get_parent_by_referral_code(session):
    p = await _parent(session)
    found = await crud.get_parent_by_referral_code(session, p.referral_code)
    assert found is not None
    assert found.id == p.id


# ──────────────────────────────────────────────
# УЧЕНИКИ
# ──────────────────────────────────────────────

async def test_create_student_prepaid_defaults(session):
    s = await _student(session, ptype="prepaid")
    assert s.id is not None
    assert s.lessons_balance == 0
    assert s.lessons_completed == 0
    assert s.payment_type == "prepaid"
    assert s.invite_token is not None
    assert s.is_active is True


async def test_create_student_postpaid(session):
    s = await _student(session, ptype="postpaid")
    assert s.payment_type == "postpaid"
    assert s.lessons_balance == 0


async def test_get_student_by_id_found(session):
    s = await _student(session)
    found = await crud.get_student_by_id(session, s.id)
    assert found is not None
    assert found.name == "Миша"


async def test_get_student_by_id_not_found(session):
    found = await crud.get_student_by_id(session, 9999)
    assert found is None


async def test_get_all_students_excludes_inactive(session):
    await _student(session, name="Активный")
    inactive = await _student(session, name="Неактивный")
    await crud.deactivate_student(session, inactive.id)
    await session.flush()
    students = await crud.get_all_students(session)
    names = [s.name for s in students]
    assert "Активный" in names
    assert "Неактивный" not in names


async def test_deactivate_student_sets_inactive(session):
    s = await _student(session)
    result = await crud.deactivate_student(session, s.id)
    assert result is not None
    assert result.is_active is False


async def test_deactivate_student_not_found_returns_none(session):
    result = await crud.deactivate_student(session, 9999)
    assert result is None


async def test_link_parent_to_student_clears_token(session):
    p = await _parent(session)
    s = await _student(session)
    assert s.invite_token is not None
    await crud.link_parent_to_student(session, s, p)
    assert s.parent_id == p.id
    assert s.invite_token is None


async def test_get_student_by_invite_token(session):
    s = await _student(session)
    token = s.invite_token
    found = await crud.get_student_by_invite_token(session, token)
    assert found is not None
    assert found.id == s.id


# ──────────────────────────────────────────────
# БАЛАНС УРОКОВ
# ──────────────────────────────────────────────

async def test_add_lessons_prepaid_increments_balance(session):
    s = await _student(session, ptype="prepaid")
    await crud.add_lessons_to_balance(session, s, count=8)
    assert s.lessons_balance == 8


async def test_add_lessons_postpaid_does_not_increment_balance(session):
    """Для постоплаты баланс не трогаем — долг считается отдельно через payments."""
    s = await _student(session, ptype="postpaid")
    await crud.add_lessons_to_balance(session, s, count=8)
    assert s.lessons_balance == 0


async def test_complete_lesson_prepaid_decrements_balance(session):
    s = await _student(session, ptype="prepaid")
    await crud.add_lessons_to_balance(session, s, count=4)
    lesson = await _lesson(session, s.id)
    result = await crud.complete_lesson(session, lesson.id)
    assert result is not None
    assert s.lessons_balance == 3
    assert s.lessons_completed == 1


async def test_complete_lesson_postpaid_no_balance_change(session):
    """Постоплата: баланс не меняется, но lessons_completed растёт."""
    s = await _student(session, ptype="postpaid")
    lesson = await _lesson(session, s.id)
    result = await crud.complete_lesson(session, lesson.id)
    assert result is not None
    assert s.lessons_balance == 0
    assert s.lessons_completed == 1


async def test_complete_lesson_zero_prepaid_balance_stays_zero(session):
    """Менеджер может провести урок даже при нулевом балансе — он не уходит в минус."""
    s = await _student(session, ptype="prepaid")
    assert s.lessons_balance == 0
    lesson = await _lesson(session, s.id)
    result = await crud.complete_lesson(session, lesson.id)
    assert result is not None
    assert s.lessons_balance == 0
    assert s.lessons_completed == 1


async def test_complete_already_completed_returns_none(session):
    """Двойное завершение урока — второй вызов возвращает None."""
    s = await _student(session, ptype="prepaid")
    lesson = await _lesson(session, s.id)
    await crud.complete_lesson(session, lesson.id)
    result = await crud.complete_lesson(session, lesson.id)
    assert result is None


# ──────────────────────────────────────────────
# ДОЛГ ПОСТОПЛАТЫ
# ──────────────────────────────────────────────

async def test_get_postpaid_debt_calculates_correctly(session):
    s = await _student(session, ptype="postpaid")
    # Проводим 3 урока
    for _ in range(3):
        lesson = await _lesson(session, s.id)
        await crud.complete_lesson(session, lesson.id)
    # Оплачено 2 урока
    await crud.add_lessons_to_balance(session, s, count=2)
    await session.flush()
    debt = await crud.get_postpaid_debt(session, s.id)
    assert debt == 1  # 3 проведено - 2 оплачено = 1


async def test_get_postpaid_debt_zero_when_fully_paid(session):
    s = await _student(session, ptype="postpaid")
    lesson = await _lesson(session, s.id)
    await crud.complete_lesson(session, lesson.id)
    await crud.add_lessons_to_balance(session, s, count=5)  # переплата — долга нет
    await session.flush()
    debt = await crud.get_postpaid_debt(session, s.id)
    assert debt == 0


async def test_get_postpaid_debt_zero_with_no_lessons(session):
    s = await _student(session, ptype="postpaid")
    debt = await crud.get_postpaid_debt(session, s.id)
    assert debt == 0


# ──────────────────────────────────────────────
# УРОКИ
# ──────────────────────────────────────────────

async def test_create_lesson_scheduled_status(session):
    s = await _student(session)
    lesson = await _lesson(session, s.id)
    assert lesson.id is not None
    assert lesson.status == "scheduled"
    assert lesson.parent_confirmed is None


async def test_get_upcoming_lessons_future_only(session):
    s = await _student(session)
    past_dt = local_now() - timedelta(hours=2)
    future_dt = local_now() + timedelta(days=1)
    await crud.create_lesson(session, s.id, past_dt)
    await crud.create_lesson(session, s.id, future_dt)
    lessons = await crud.get_upcoming_lessons(session, s.id)
    assert len(lessons) == 1
    assert lessons[0].scheduled_at == future_dt


async def test_get_completable_lessons_includes_24h_past(session):
    """Уроки из последних 24 часов должны попасть в список для завершения."""
    s = await _student(session)
    recent_past = local_now() - timedelta(hours=1)   # 1 час назад — входит
    old_past = local_now() - timedelta(hours=25)     # 25 часов назад — не входит
    await crud.create_lesson(session, s.id, recent_past)
    await crud.create_lesson(session, s.id, old_past)
    lessons = await crud.get_completable_lessons(session, s.id)
    assert len(lessons) == 1
    assert lessons[0].scheduled_at == recent_past


async def test_get_completable_lessons_includes_future(session):
    """Будущие уроки тоже входят — менеджер может пометить урок заранее."""
    s = await _student(session)
    future_dt = local_now() + timedelta(hours=2)
    await crud.create_lesson(session, s.id, future_dt)
    lessons = await crud.get_completable_lessons(session, s.id)
    assert len(lessons) == 1


async def test_lesson_exists_at_true(session):
    s = await _student(session)
    dt = local_now() + timedelta(days=2)
    await crud.create_lesson(session, s.id, dt)
    await session.flush()
    assert await crud.lesson_exists_at(session, s.id, dt) is True


async def test_lesson_exists_at_false_different_time(session):
    s = await _student(session)
    dt1 = local_now() + timedelta(days=2)
    dt2 = local_now() + timedelta(days=3)
    await crud.create_lesson(session, s.id, dt1)
    await session.flush()
    assert await crud.lesson_exists_at(session, s.id, dt2) is False


async def test_lesson_exists_at_false_after_cancel(session):
    """Отменённый урок не блокирует создание нового на то же время (для recurring)."""
    s = await _student(session)
    dt = local_now() + timedelta(days=2)
    lesson = await crud.create_lesson(session, s.id, dt)
    await crud.cancel_lesson(session, lesson.id, "тест", "parent")
    await session.flush()
    assert await crud.lesson_exists_at(session, s.id, dt) is False


async def test_cancel_lesson_sets_status_and_reason(session):
    s = await _student(session)
    lesson = await _lesson(session, s.id)
    result = await crud.cancel_lesson(session, lesson.id, "болеем", "parent")
    assert result is not None
    assert result.status == "cancelled_parent"
    assert result.cancellation_reason == "болеем"


async def test_cancel_already_cancelled_returns_none(session):
    s = await _student(session)
    lesson = await _lesson(session, s.id)
    await crud.cancel_lesson(session, lesson.id, "тест", "parent")
    result = await crud.cancel_lesson(session, lesson.id, "тест2", "teacher")
    assert result is None


async def test_reschedule_lesson_updates_time_and_resets_flags(session):
    s = await _student(session)
    lesson = await _lesson(session, s.id)
    lesson.reminder_24h_sent = True
    lesson.reminder_1h_sent = True
    lesson.parent_confirmed = True
    new_dt = local_now() + timedelta(days=5)
    result = await crud.reschedule_lesson(session, lesson.id, new_dt)
    assert result is not None
    assert result.scheduled_at == new_dt
    assert result.reminder_24h_sent is False
    assert result.reminder_1h_sent is False
    assert result.parent_confirmed is None


# ──────────────────────────────────────────────
# РЕФЕРАЛЫ
# ──────────────────────────────────────────────

async def test_get_referral_by_referred_loads_referrer(session):
    """
    Регрессионный тест: referral.referrer должен загружаться через selectinload.
    Без него — MissingGreenlet при доступе к referral.referrer.telegram_id.
    """
    referrer = await _parent(session, tg_id=1, name="Пригласивший")
    referred = await _parent(session, tg_id=2, name="Приглашённый")
    await crud.create_referral(session, referrer.id, referred.id)
    await session.flush()

    referral = await crud.get_referral_by_referred(session, referred.id)

    # Доступ к relationship без исключения — основная проверка
    assert referral.referrer.telegram_id == 1
    assert referral.referrer.name == "Пригласивший"


async def test_create_referral_pending_status(session):
    referrer = await _parent(session, tg_id=1)
    referred = await _parent(session, tg_id=2)
    referral = await crud.create_referral(session, referrer.id, referred.id)
    assert referral.id is not None
    assert referral.status == "pending"
    assert referral.bonus_signup is False


# ──────────────────────────────────────────────
# ОБРАТНАЯ СВЯЗЬ
# ──────────────────────────────────────────────

async def test_create_feedback_id_is_set_after_flush(session):
    """Регрессионный тест: flush() в create_feedback гарантирует что id не None."""
    p = await _parent(session)
    fb = await crud.create_feedback(session, p.id, "Тест сообщение")
    assert fb.id is not None


async def test_get_unread_feedback_returns_only_unread(session):
    p = await _parent(session)
    fb1 = await crud.create_feedback(session, p.id, "Непрочитанное")
    fb2 = await crud.create_feedback(session, p.id, "Тоже непрочитанное")
    await crud.mark_feedback_read(session, fb1.id)
    await session.flush()
    unread = await crud.get_unread_feedback(session)
    ids = [f.id for f in unread]
    assert fb1.id not in ids
    assert fb2.id in ids


async def test_mark_feedback_read_removes_from_unread(session):
    p = await _parent(session)
    fb = await crud.create_feedback(session, p.id, "Сообщение")
    await crud.mark_feedback_read(session, fb.id)
    await session.flush()
    unread = await crud.get_unread_feedback(session)
    assert all(f.id != fb.id for f in unread)


# ──────────────────────────────────────────────
# ПОВТОРЯЮЩЕЕСЯ РАСПИСАНИЕ
# ──────────────────────────────────────────────

async def test_create_recurring_schedule(session):
    s = await _student(session)
    sched = await crud.create_recurring_schedule(session, s.id, 1, 15, 30)
    assert sched.id is not None
    assert sched.day_of_week == 1
    assert sched.hour == 15
    assert sched.minute == 30
    assert sched.is_active is True


async def test_get_recurring_schedules_returns_active_only(session):
    s = await _student(session)
    active = await crud.create_recurring_schedule(session, s.id, 0, 10, 0)
    inactive = await crud.create_recurring_schedule(session, s.id, 1, 11, 0)
    await crud.delete_recurring_schedule(session, inactive.id)
    await session.flush()
    schedules = await crud.get_recurring_schedules_by_student(session, s.id)
    ids = [sc.id for sc in schedules]
    assert active.id in ids
    assert inactive.id not in ids


async def test_delete_recurring_schedule_soft_delete(session):
    s = await _student(session)
    sched = await crud.create_recurring_schedule(session, s.id, 2, 12, 0)
    result = await crud.delete_recurring_schedule(session, sched.id)
    assert result is True
    await session.flush()
    schedules = await crud.get_recurring_schedules_by_student(session, s.id)
    assert len(schedules) == 0


async def test_delete_recurring_schedule_not_found_returns_false(session):
    result = await crud.delete_recurring_schedule(session, 9999)
    assert result is False


async def test_get_all_active_recurring_excludes_inactive_students(session):
    """Расписание деактивированного ученика не должно генерировать уроки."""
    s = await _student(session)
    await crud.create_recurring_schedule(session, s.id, 3, 14, 0)
    await crud.deactivate_student(session, s.id)
    await session.flush()
    schedules = await crud.get_all_active_recurring_schedules(session)
    assert all(sc.student_id != s.id for sc in schedules)


async def test_get_recurring_schedules_ordered_by_day_and_time(session):
    s = await _student(session)
    await crud.create_recurring_schedule(session, s.id, 4, 18, 0)
    await crud.create_recurring_schedule(session, s.id, 1, 10, 0)
    await crud.create_recurring_schedule(session, s.id, 1, 9, 0)
    await session.flush()
    schedules = await crud.get_recurring_schedules_by_student(session, s.id)
    days = [sc.day_of_week for sc in schedules]
    # Должны быть отсортированы по дню недели
    assert days == sorted(days)
