from datetime import datetime
from sqlalchemy import (
    BigInteger, Boolean, DateTime, ForeignKey,
    Integer, String, Text, func
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Parent(Base):
    """Родитель — пользователь бота со стороны клиента."""
    __tablename__ = "parents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(20))
    # Уникальный код для реферальных ссылок (UUID без дефисов)
    referral_code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    referred_by_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("parents.id"))
    status: Mapped[str] = mapped_column(String(20), default="active")  # active | blocked
    is_news_subscriber: Mapped[bool] = mapped_column(Boolean, default=False)  # подписка на IT-новости
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())

    students: Mapped[list["Student"]] = relationship("Student", back_populates="parent")
    referrals_made: Mapped[list["Referral"]] = relationship(
        "Referral", foreign_keys="Referral.referrer_id", back_populates="referrer"
    )
    feedbacks: Mapped[list["Feedback"]] = relationship("Feedback", back_populates="parent")


class Student(Base):
    """Ученик — ребёнок, привязанный к родителю."""
    __tablename__ = "students"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    age: Mapped[int | None] = mapped_column(Integer)
    # nullable=True — родитель привязывается позже через инвайт-ссылку
    parent_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("parents.id"), nullable=True)
    lessons_balance: Mapped[int] = mapped_column(Integer, default=0)   # текущий остаток уроков
    lessons_completed: Mapped[int] = mapped_column(Integer, default=0)  # всего проведено
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # prepaid — платит пакетом заранее, postpaid — платит по факту урока
    payment_type: Mapped[str] = mapped_column(String(10), default="prepaid")
    # Токен для инвайт-ссылки (менеджер отправляет родителю)
    invite_token: Mapped[str | None] = mapped_column(String(32), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())

    parent: Mapped["Parent"] = relationship("Parent", back_populates="students")
    lessons: Mapped[list["Lesson"]] = relationship("Lesson", back_populates="student")
    payments: Mapped[list["Payment"]] = relationship("Payment", back_populates="student")


class Lesson(Base):
    """Урок — запись в расписании."""
    __tablename__ = "lessons"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    student_id: Mapped[int] = mapped_column(Integer, ForeignKey("students.id"), nullable=False)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="scheduled")
    # Возможные статусы:
    # scheduled          — запланирован
    # completed          — проведён (менеджер нажал "Проведён")
    # cancelled_parent   — отменён родителем
    # cancelled_teacher  — отменён менеджером
    # no_show            — родитель не пришёл без предупреждения

    # Флаги отправки напоминаний (чтобы не слать дважды)
    reminder_24h_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    reminder_1h_sent: Mapped[bool] = mapped_column(Boolean, default=False)

    # Подтверждение от родителя (True/False/None = не ответил)
    parent_confirmed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    cancellation_reason: Mapped[str | None] = mapped_column(Text)

    # ID события в Google Calendar для синхронизации
    google_event_id: Mapped[str | None] = mapped_column(String(100))

    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())

    student: Mapped["Student"] = relationship("Student", back_populates="lessons")


class Payment(Base):
    """Оплата — пополнение баланса уроков ученика."""
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    student_id: Mapped[int] = mapped_column(Integer, ForeignKey("students.id"), nullable=False)
    lessons_count: Mapped[int] = mapped_column(Integer, nullable=False)  # сколько уроков куплено
    amount: Mapped[int | None] = mapped_column(Integer)  # сумма в рублях (необязательно)
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())

    student: Mapped["Student"] = relationship("Student", back_populates="payments")


class Referral(Base):
    """Реферал — связь между пригласившим и приглашённым родителем."""
    __tablename__ = "referrals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    referrer_id: Mapped[int] = mapped_column(Integer, ForeignKey("parents.id"), nullable=False)
    referred_id: Mapped[int] = mapped_column(Integer, ForeignKey("parents.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    # pending   — друг зарегался, но ещё не оплатил
    # active    — первая оплата прошла, бонусы начали начисляться
    # completed — все milestone пройдены

    # Флаги начисленных бонусов (чтобы не начислить дважды)
    bonus_signup: Mapped[bool] = mapped_column(Boolean, default=False)
    bonus_month_1: Mapped[bool] = mapped_column(Boolean, default=False)
    bonus_month_3: Mapped[bool] = mapped_column(Boolean, default=False)
    bonus_month_6: Mapped[bool] = mapped_column(Boolean, default=False)

    # Дата первой оплаты — от неё считаем месяцы
    first_payment_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())

    referrer: Mapped["Parent"] = relationship(
        "Parent", foreign_keys=[referrer_id], back_populates="referrals_made"
    )
    referred: Mapped["Parent"] = relationship("Parent", foreign_keys=[referred_id])
    bonuses: Mapped[list["ReferralBonus"]] = relationship("ReferralBonus", back_populates="referral")


class ReferralBonus(Base):
    """Начисленный реферальный бонус — история выплат."""
    __tablename__ = "referral_bonuses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    referral_id: Mapped[int] = mapped_column(Integer, ForeignKey("referrals.id"), nullable=False)
    recipient_id: Mapped[int] = mapped_column(Integer, ForeignKey("parents.id"), nullable=False)
    bonus_type: Mapped[str] = mapped_column(String(10))   # lesson | cash
    amount: Mapped[int] = mapped_column(Integer)           # уроки или рубли
    milestone: Mapped[str] = mapped_column(String(20))    # signup | month_1 | month_3 | month_6
    is_paid: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())

    referral: Mapped["Referral"] = relationship("Referral", back_populates="bonuses")


class TrialRequest(Base):
    """Заявка на пробный урок от нового пользователя."""
    __tablename__ = "trial_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    parent_name: Mapped[str] = mapped_column(String(100), nullable=False)
    child_name: Mapped[str] = mapped_column(String(100), nullable=False)
    child_age: Mapped[int | None] = mapped_column(Integer)
    phone: Mapped[str | None] = mapped_column(String(20))
    preferred_time: Mapped[str | None] = mapped_column(String(100))
    referral_code: Mapped[str | None] = mapped_column(String(32))  # код пригласившего родителя
    status: Mapped[str] = mapped_column(String(20), default="pending")
    # pending — ожидает ответа менеджера
    # approved — менеджер одобрил, инвайт отправлен
    # rejected — менеджер отклонил
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())


class Feedback(Base):
    """Обратная связь от родителя менеджеру."""
    __tablename__ = "feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    parent_id: Mapped[int] = mapped_column(Integer, ForeignKey("parents.id"), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())

    parent: Mapped["Parent"] = relationship("Parent", back_populates="feedbacks")


class RecurringSchedule(Base):
    """Шаблон повторяющегося урока — по нему ежедневно создаются уроки на 14 дней вперёд."""
    __tablename__ = "recurring_schedules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    student_id: Mapped[int] = mapped_column(Integer, ForeignKey("students.id"), nullable=False)
    # 0=Пн, 1=Вт, 2=Ср, 3=Чт, 4=Пт, 5=Сб, 6=Вс — как в Python datetime.weekday()
    day_of_week: Mapped[int] = mapped_column(Integer, nullable=False)
    hour: Mapped[int] = mapped_column(Integer, nullable=False)
    minute: Mapped[int] = mapped_column(Integer, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())

    student: Mapped["Student"] = relationship("Student")
