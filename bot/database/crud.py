import uuid
from datetime import datetime, timedelta
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from bot.database.models import (
    Feedback, Lesson, Parent, Payment,
    RecurringSchedule, Referral, ReferralBonus, Student, TrialRequest
)
from bot.utils import local_now


# ──────────────────────────────────────────────
# РОДИТЕЛИ
# ──────────────────────────────────────────────

async def get_parent_by_telegram_id(session: AsyncSession, telegram_id: int) -> Parent | None:
    result = await session.execute(
        select(Parent).where(Parent.telegram_id == telegram_id)
    )
    return result.scalar_one_or_none()


async def get_parent_by_referral_code(session: AsyncSession, code: str) -> Parent | None:
    result = await session.execute(
        select(Parent).where(Parent.referral_code == code)
    )
    return result.scalar_one_or_none()


async def create_parent(
    session: AsyncSession,
    telegram_id: int,
    name: str,
    phone: str | None = None,
    referred_by_id: int | None = None,
) -> Parent:
    parent = Parent(
        telegram_id=telegram_id,
        name=name,
        phone=phone,
        referral_code=uuid.uuid4().hex,  # уникальный код для реферальных ссылок
        referred_by_id=referred_by_id,
    )
    session.add(parent)
    await session.flush()  # получаем id до commit
    return parent


async def get_all_parents(session: AsyncSession) -> list[Parent]:
    result = await session.execute(
        select(Parent).where(Parent.status == "active").order_by(Parent.name)
    )
    return list(result.scalars().all())


# ──────────────────────────────────────────────
# УЧЕНИКИ
# ──────────────────────────────────────────────

async def create_student(
    session: AsyncSession,
    name: str,
    age: int | None = None,
    payment_type: str = "prepaid",
) -> Student:
    """Создаём ученика без родителя — родитель привяжется через инвайт-ссылку."""
    student = Student(
        name=name,
        age=age,
        payment_type=payment_type,
        invite_token=uuid.uuid4().hex,  # токен для ссылки которую менеджер шлёт родителю
    )
    session.add(student)
    await session.flush()
    return student


async def get_student_by_invite_token(session: AsyncSession, token: str) -> Student | None:
    result = await session.execute(
        select(Student).where(Student.invite_token == token)
    )
    return result.scalar_one_or_none()


async def link_parent_to_student(session: AsyncSession, student: Student, parent: Parent) -> None:
    """Привязываем родителя к ученику после перехода по инвайт-ссылке."""
    student.parent_id = parent.id
    student.invite_token = None  # токен одноразовый — сбрасываем после использования


async def get_students_by_parent(session: AsyncSession, parent_id: int) -> list[Student]:
    result = await session.execute(
        select(Student)
        .where(Student.parent_id == parent_id)
        .where(Student.is_active == True)
    )
    return list(result.scalars().all())


async def get_all_students(session: AsyncSession) -> list[Student]:
    """Все активные ученики с родителями — для панели менеджера."""
    result = await session.execute(
        select(Student)
        .options(selectinload(Student.parent))
        .where(Student.is_active == True)
        .order_by(Student.name)
    )
    return list(result.scalars().all())


async def get_student_by_id(session: AsyncSession, student_id: int) -> Student | None:
    result = await session.execute(
        select(Student)
        .options(selectinload(Student.parent))
        .where(Student.id == student_id)
    )
    return result.scalar_one_or_none()


async def add_lessons_to_balance(
    session: AsyncSession,
    student: Student,
    count: int,
    amount: int | None = None,
    note: str | None = None,
) -> Payment:
    """Пополнение баланса после оплаты. Для postpaid баланс не трогаем — долг считается отдельно."""
    if student.payment_type == "prepaid":
        student.lessons_balance += count
    payment = Payment(
        student_id=student.id,
        lessons_count=count,
        amount=amount,
        note=note,
    )
    session.add(payment)
    return payment


async def deactivate_student(session: AsyncSession, student_id: int) -> Student | None:
    """Мягкое удаление ученика — скрываем из списков, история сохраняется."""
    student = await get_student_by_id(session, student_id)
    if not student:
        return None
    student.is_active = False
    return student


async def get_postpaid_debt(session: AsyncSession, student_id: int) -> int:
    """Долг postpaid-ученика: проведено уроков минус оплачено."""
    from sqlalchemy import func
    paid_result = await session.execute(
        select(func.coalesce(func.sum(Payment.lessons_count), 0))
        .where(Payment.student_id == student_id)
    )
    total_paid = paid_result.scalar() or 0
    comp_result = await session.execute(
        select(Student.lessons_completed).where(Student.id == student_id)
    )
    total_completed = comp_result.scalar() or 0
    return max(0, total_completed - total_paid)


async def get_postpaid_students_with_debt(session: AsyncSession) -> list[tuple]:
    """Postpaid-ученики у которых есть неоплаченные проведённые уроки."""
    from sqlalchemy import func
    paid_subq = (
        select(Payment.student_id, func.sum(Payment.lessons_count).label("total_paid"))
        .group_by(Payment.student_id)
        .subquery()
    )
    result = await session.execute(
        select(Student, func.coalesce(paid_subq.c.total_paid, 0).label("total_paid"))
        .outerjoin(paid_subq, Student.id == paid_subq.c.student_id)
        .where(Student.is_active == True)
        .where(Student.payment_type == "postpaid")
        .where(Student.lessons_completed > func.coalesce(paid_subq.c.total_paid, 0))
        .order_by(Student.name)
    )
    rows = result.all()
    return [(student, student.lessons_completed - int(paid)) for student, paid in rows]


async def get_students_with_low_balance(session: AsyncSession, threshold: int = 2) -> list[Student]:
    """Ученики у которых осталось мало уроков — только prepaid, postpaid не считаем."""
    result = await session.execute(
        select(Student)
        .options(selectinload(Student.parent))
        .where(Student.is_active == True)
        .where(Student.payment_type == "prepaid")
        .where(Student.lessons_balance <= threshold)
        .where(Student.lessons_balance > 0)
    )
    return list(result.scalars().all())


# ──────────────────────────────────────────────
# УРОКИ
# ──────────────────────────────────────────────

async def create_lesson(
    session: AsyncSession,
    student_id: int,
    scheduled_at: datetime,
    google_event_id: str | None = None,
) -> Lesson:
    lesson = Lesson(
        student_id=student_id,
        scheduled_at=scheduled_at,
        google_event_id=google_event_id,
    )
    session.add(lesson)
    await session.flush()
    return lesson


async def get_lesson_by_id(session: AsyncSession, lesson_id: int) -> Lesson | None:
    result = await session.execute(
        select(Lesson)
        .options(selectinload(Lesson.student).selectinload(Student.parent))
        .where(Lesson.id == lesson_id)
    )
    return result.scalar_one_or_none()


async def get_lessons_today(session: AsyncSession) -> list[Lesson]:
    """Все уроки на сегодня — для утреннего отчёта менеджеру."""
    today_start = local_now().replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = today_start + timedelta(days=1)
    result = await session.execute(
        select(Lesson)
        .options(selectinload(Lesson.student).selectinload(Student.parent))
        .where(Lesson.scheduled_at >= today_start)
        .where(Lesson.scheduled_at < today_end)
        .where(Lesson.status == "scheduled")
        .order_by(Lesson.scheduled_at)
    )
    return list(result.scalars().all())


async def get_upcoming_lessons(session: AsyncSession, student_id: int, limit: int = 5) -> list[Lesson]:
    """Ближайшие уроки ученика — для ЛК родителя."""
    result = await session.execute(
        select(Lesson)
        .where(Lesson.student_id == student_id)
        .where(Lesson.status == "scheduled")
        .where(Lesson.scheduled_at >= local_now())
        .order_by(Lesson.scheduled_at)
        .limit(limit)
    )
    return list(result.scalars().all())


async def get_completable_lessons(session: AsyncSession, student_id: int, limit: int = 10) -> list[Lesson]:
    """Уроки доступные для отметки как проведённые — включает прошедшие за последние 24 часа."""
    lookback = local_now() - timedelta(hours=24)
    result = await session.execute(
        select(Lesson)
        .where(Lesson.student_id == student_id)
        .where(Lesson.status == "scheduled")
        .where(Lesson.scheduled_at >= lookback)
        .order_by(Lesson.scheduled_at)
        .limit(limit)
    )
    return list(result.scalars().all())


async def get_lessons_week(session: AsyncSession) -> list[Lesson]:
    """Уроки на ближайшие 7 дней — для расписания менеджера."""
    now = local_now()
    week_end = now + timedelta(days=7)
    result = await session.execute(
        select(Lesson)
        .options(selectinload(Lesson.student).selectinload(Student.parent))
        .where(Lesson.status == "scheduled")
        .where(Lesson.scheduled_at >= now)
        .where(Lesson.scheduled_at < week_end)
        .order_by(Lesson.scheduled_at)
    )
    return list(result.scalars().all())


async def get_all_upcoming_lessons(session: AsyncSession, limit: int = 20) -> list[Lesson]:
    """Все запланированные уроки — для переноса урока менеджером."""
    result = await session.execute(
        select(Lesson)
        .options(selectinload(Lesson.student).selectinload(Student.parent))
        .where(Lesson.status == "scheduled")
        .where(Lesson.scheduled_at >= local_now())
        .order_by(Lesson.scheduled_at)
        .limit(limit)
    )
    return list(result.scalars().all())


async def get_lesson_history(session: AsyncSession, student_id: int, limit: int = 10) -> list[Lesson]:
    """История проведённых уроков — для ЛК родителя."""
    result = await session.execute(
        select(Lesson)
        .where(Lesson.student_id == student_id)
        .where(Lesson.status == "completed")
        .order_by(Lesson.scheduled_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def complete_lesson(session: AsyncSession, lesson_id: int) -> Lesson | None:
    """Менеджер отмечает урок как проведённый — списываем урок с баланса."""
    lesson = await get_lesson_by_id(session, lesson_id)
    if not lesson or lesson.status != "scheduled":
        return None

    lesson.status = "completed"

    student = lesson.student
    # Для prepaid списываем урок с баланса, для postpaid только считаем
    if student.payment_type == "prepaid" and student.lessons_balance > 0:
        student.lessons_balance -= 1
    student.lessons_completed += 1

    return lesson


async def cancel_lesson(
    session: AsyncSession,
    lesson_id: int,
    reason: str,
    cancelled_by: str,  # "parent" или "teacher"
) -> Lesson | None:
    lesson = await get_lesson_by_id(session, lesson_id)
    if not lesson or lesson.status != "scheduled":
        return None

    lesson.status = f"cancelled_{cancelled_by}"
    lesson.cancellation_reason = reason
    return lesson


async def mark_reminder_sent(
    session: AsyncSession, lesson_id: int, reminder_type: str
) -> None:
    """Помечаем что напоминание отправлено — чтобы не слать дважды."""
    if reminder_type == "24h":
        await session.execute(
            update(Lesson)
            .where(Lesson.id == lesson_id)
            .values(reminder_24h_sent=True)
        )
    else:
        await session.execute(
            update(Lesson)
            .where(Lesson.id == lesson_id)
            .values(reminder_1h_sent=True)
        )


async def set_parent_confirmed(
    session: AsyncSession, lesson_id: int, confirmed: bool
) -> None:
    await session.execute(
        update(Lesson)
        .where(Lesson.id == lesson_id)
        .values(parent_confirmed=confirmed)
    )


async def reschedule_lesson(
    session: AsyncSession, lesson_id: int, new_scheduled_at: datetime
) -> Lesson | None:
    """Переносим урок — обновляем время и сбрасываем флаги напоминаний."""
    lesson = await get_lesson_by_id(session, lesson_id)
    if not lesson or lesson.status != "scheduled":
        return None
    lesson.scheduled_at = new_scheduled_at
    lesson.reminder_24h_sent = False
    lesson.reminder_1h_sent = False
    lesson.parent_confirmed = None
    return lesson


async def update_student_field(
    session: AsyncSession, student_id: int, field: str, value
) -> Student | None:
    """Обновляем одно поле ученика — для редактирования из панели менеджера."""
    student = await get_student_by_id(session, student_id)
    if not student:
        return None
    setattr(student, field, value)
    return student


# ──────────────────────────────────────────────
# РЕФЕРАЛЫ
# ──────────────────────────────────────────────

async def get_referral_by_referred(session: AsyncSession, referred_id: int) -> Referral | None:
    result = await session.execute(
        select(Referral)
        .options(selectinload(Referral.referrer))
        .where(Referral.referred_id == referred_id)
    )
    return result.scalar_one_or_none()


async def create_referral(
    session: AsyncSession, referrer_id: int, referred_id: int
) -> Referral:
    referral = Referral(referrer_id=referrer_id, referred_id=referred_id)
    session.add(referral)
    await session.flush()
    return referral


async def get_referrals_by_referrer(session: AsyncSession, referrer_id: int) -> list[Referral]:
    result = await session.execute(
        select(Referral)
        .options(selectinload(Referral.referred))
        .where(Referral.referrer_id == referrer_id)
        .order_by(Referral.created_at.desc())
    )
    return list(result.scalars().all())


async def activate_referral(session: AsyncSession, referral: Referral) -> None:
    """Активируем реферала после первой оплаты и фиксируем дату."""
    referral.status = "active"
    referral.first_payment_at = local_now()


async def get_active_referrals_for_milestones(session: AsyncSession) -> list[Referral]:
    """Активные рефералы для проверки milestone — запускается ежедневно."""
    result = await session.execute(
        select(Referral)
        .options(selectinload(Referral.referrer), selectinload(Referral.referred))
        .where(Referral.status == "active")
        .where(Referral.first_payment_at != None)
    )
    return list(result.scalars().all())


async def add_referral_bonus(
    session: AsyncSession,
    referral_id: int,
    recipient_id: int,
    bonus_type: str,
    amount: int,
    milestone: str,
) -> ReferralBonus:
    bonus = ReferralBonus(
        referral_id=referral_id,
        recipient_id=recipient_id,
        bonus_type=bonus_type,
        amount=amount,
        milestone=milestone,
    )
    session.add(bonus)
    return bonus


async def get_unpaid_cash_bonuses(session: AsyncSession) -> list[ReferralBonus]:
    """Кэш-бонусы которые нужно выплатить — для панели менеджера."""
    result = await session.execute(
        select(ReferralBonus)
        .options(selectinload(ReferralBonus.referral))
        .where(ReferralBonus.bonus_type == "cash")
        .where(ReferralBonus.is_paid == False)
        .order_by(ReferralBonus.created_at)
    )
    return list(result.scalars().all())


# ──────────────────────────────────────────────
# ЗАЯВКИ НА ПРОБНЫЙ УРОК
# ──────────────────────────────────────────────

async def create_trial_request(
    session: AsyncSession,
    telegram_id: int,
    parent_name: str,
    child_name: str,
    child_age: int | None,
    phone: str | None,
    preferred_time: str | None,
    referral_code: str | None = None,
) -> TrialRequest:
    trial = TrialRequest(
        telegram_id=telegram_id,
        parent_name=parent_name,
        child_name=child_name,
        child_age=child_age,
        phone=phone,
        preferred_time=preferred_time,
        referral_code=referral_code,
    )
    session.add(trial)
    await session.flush()
    return trial


async def get_trial_request_by_id(session: AsyncSession, trial_id: int) -> TrialRequest | None:
    result = await session.execute(
        select(TrialRequest).where(TrialRequest.id == trial_id)
    )
    return result.scalar_one_or_none()


async def get_pending_trial_by_telegram_id(session: AsyncSession, telegram_id: int) -> TrialRequest | None:
    """Проверяем есть ли уже ожидающая обработки заявка от этого пользователя."""
    result = await session.execute(
        select(TrialRequest)
        .where(TrialRequest.telegram_id == telegram_id)
        .where(TrialRequest.status == "pending")
        .order_by(TrialRequest.created_at.desc())
    )
    return result.scalars().first()


async def get_trial_by_telegram_id(session: AsyncSession, telegram_id: int) -> TrialRequest | None:
    """Последняя одобренная заявка пользователя — для восстановления реферального кода."""
    result = await session.execute(
        select(TrialRequest)
        .where(TrialRequest.telegram_id == telegram_id)
        .where(TrialRequest.referral_code != None)
        .order_by(TrialRequest.created_at.desc())
    )
    return result.scalars().first()


async def update_trial_status(session: AsyncSession, trial_id: int, status: str) -> None:
    await session.execute(
        update(TrialRequest).where(TrialRequest.id == trial_id).values(status=status)
    )


# ──────────────────────────────────────────────
# IT НОВОСТИ — ПОДПИСКА
# ──────────────────────────────────────────────

async def toggle_news_subscription(session: AsyncSession, parent: Parent) -> bool:
    """Переключаем подписку. Возвращает новый статус."""
    parent.is_news_subscriber = not parent.is_news_subscriber
    return parent.is_news_subscriber


async def get_news_subscribers(session: AsyncSession) -> list[Parent]:
    """Все родители подписанные на IT-новости."""
    result = await session.execute(
        select(Parent)
        .where(Parent.is_news_subscriber == True)
        .where(Parent.status == "active")
    )
    return list(result.scalars().all())


async def get_news_subscribers_count(session: AsyncSession) -> int:
    """Количество подписчиков — для статистики менеджера."""
    from sqlalchemy import func
    result = await session.execute(
        select(func.count()).select_from(Parent).where(Parent.is_news_subscriber == True)
    )
    return result.scalar() or 0


# ──────────────────────────────────────────────
# ОБРАТНАЯ СВЯЗЬ
# ──────────────────────────────────────────────

async def create_feedback(
    session: AsyncSession, parent_id: int, message: str
) -> Feedback:
    feedback = Feedback(parent_id=parent_id, message=message)
    session.add(feedback)
    await session.flush()
    return feedback


async def get_unread_feedback(session: AsyncSession) -> list[Feedback]:
    result = await session.execute(
        select(Feedback)
        .options(selectinload(Feedback.parent))
        .where(Feedback.is_read == False)
        .order_by(Feedback.created_at)
    )
    return list(result.scalars().all())


async def mark_feedback_read(session: AsyncSession, feedback_id: int) -> None:
    await session.execute(
        update(Feedback).where(Feedback.id == feedback_id).values(is_read=True)
    )


# ──────────────────────────────────────────────
# ПОВТОРЯЮЩЕЕСЯ РАСПИСАНИЕ
# ──────────────────────────────────────────────

async def create_recurring_schedule(
    session: AsyncSession,
    student_id: int,
    day_of_week: int,
    hour: int,
    minute: int,
) -> RecurringSchedule:
    """Создаём шаблон повторяющегося урока для ученика."""
    schedule = RecurringSchedule(
        student_id=student_id,
        day_of_week=day_of_week,
        hour=hour,
        minute=minute,
    )
    session.add(schedule)
    await session.flush()
    return schedule


async def get_recurring_schedules_by_student(
    session: AsyncSession, student_id: int
) -> list[RecurringSchedule]:
    """Все активные повторяющиеся расписания ученика."""
    result = await session.execute(
        select(RecurringSchedule)
        .where(RecurringSchedule.student_id == student_id)
        .where(RecurringSchedule.is_active == True)
        .order_by(RecurringSchedule.day_of_week, RecurringSchedule.hour, RecurringSchedule.minute)
    )
    return list(result.scalars().all())


async def get_all_active_recurring_schedules(session: AsyncSession) -> list[RecurringSchedule]:
    """Все активные шаблоны расписания — только для активных учеников."""
    result = await session.execute(
        select(RecurringSchedule)
        .join(Student, Student.id == RecurringSchedule.student_id)
        .where(RecurringSchedule.is_active == True)
        .where(Student.is_active == True)
        .options(selectinload(RecurringSchedule.student))
    )
    return list(result.scalars().all())


async def delete_recurring_schedule(session: AsyncSession, schedule_id: int) -> bool:
    """Деактивируем шаблон (мягкое удаление)."""
    result = await session.execute(
        update(RecurringSchedule)
        .where(RecurringSchedule.id == schedule_id)
        .values(is_active=False)
    )
    return result.rowcount > 0


async def lesson_exists_at(
    session: AsyncSession, student_id: int, scheduled_at: datetime
) -> bool:
    """Проверяем, что у ученика нет урока в эту же минуту — защита от дублей."""
    result = await session.execute(
        select(Lesson.id)
        .where(Lesson.student_id == student_id)
        .where(Lesson.scheduled_at == scheduled_at)
        .where(Lesson.status != "cancelled_parent")
        .where(Lesson.status != "cancelled_teacher")
        .limit(1)
    )
    return result.scalar_one_or_none() is not None
