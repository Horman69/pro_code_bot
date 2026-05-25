from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.database.models import Lesson, Student


def manager_main_menu() -> InlineKeyboardMarkup:
    """Главное меню менеджера."""
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="👥 Ученики", callback_data="mgr:students"))
    builder.row(InlineKeyboardButton(text="📅 Расписание", callback_data="mgr:schedule"))
    builder.row(InlineKeyboardButton(text="💰 Оплаты", callback_data="mgr:payments"))
    builder.row(InlineKeyboardButton(text="📊 Аналитика", callback_data="mgr:analytics"))
    builder.row(InlineKeyboardButton(text="💬 Обратная связь", callback_data="mgr:feedback"))
    builder.row(InlineKeyboardButton(text="📢 Рассылка всем", callback_data="mgr:broadcast"))
    builder.row(InlineKeyboardButton(text="📰 IT-новости подписчикам", callback_data="mgr:news_broadcast"))
    return builder.as_markup()


def students_list_keyboard(students: list[Student]) -> InlineKeyboardMarkup:
    """Список учеников — каждый кнопка с переходом в профиль."""
    builder = InlineKeyboardBuilder()
    for student in students:
        if student.payment_type == "postpaid":
            icon = "🔄"
            balance_label = "по факту"
        elif student.lessons_balance == 0:
            icon = "🔴"
            balance_label = "0 ур."
        elif student.lessons_balance <= 2:
            icon = "🟡"
            balance_label = f"{student.lessons_balance} ур."
        else:
            icon = "🟢"
            balance_label = f"{student.lessons_balance} ур."
        builder.row(InlineKeyboardButton(
            text=f"{icon} {student.name} — {balance_label}",
            callback_data=f"mgr:student:{student.id}"
        ))
    builder.row(InlineKeyboardButton(text="➕ Добавить ученика", callback_data="mgr:add_student"))
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="mgr:main"))
    return builder.as_markup()


def payment_select_student_keyboard(students: list[Student]) -> InlineKeyboardMarkup:
    """Выбор ученика для оплаты — отдельный префикс чтобы не конфликтовать с профилем."""
    builder = InlineKeyboardBuilder()
    for student in students:
        balance_icon = "🔴" if student.lessons_balance == 0 else (
            "🟡" if student.lessons_balance <= 2 else "🟢"
        )
        builder.row(InlineKeyboardButton(
            text=f"{balance_icon} {student.name} — {student.lessons_balance} ур.",
            callback_data=f"mgr:pay_select:{student.id}"
        ))
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="mgr:payments"))
    return builder.as_markup()


def lesson_student_select_keyboard(students: list[Student]) -> InlineKeyboardMarkup:
    """Выбор ученика для добавления урока — отдельный префикс чтобы не открывать профиль."""
    builder = InlineKeyboardBuilder()
    for student in students:
        builder.row(InlineKeyboardButton(
            text=f"👤 {student.name}",
            callback_data=f"mgr:lesson_student:{student.id}"
        ))
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="mgr:schedule"))
    return builder.as_markup()


def student_profile_keyboard(student_id: int) -> InlineKeyboardMarkup:
    """Профиль ученика — действия менеджера."""
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(
        text="✅ Урок проведён", callback_data=f"mgr:complete_lesson:{student_id}"
    ))
    builder.row(InlineKeyboardButton(
        text="💰 Принять оплату", callback_data=f"mgr:payment:{student_id}"
    ))
    builder.row(InlineKeyboardButton(
        text="📅 Добавить урок", callback_data=f"mgr:add_lesson:{student_id}"
    ))
    builder.row(InlineKeyboardButton(
        text="🔗 Инвайт-ссылка", callback_data=f"mgr:invite:{student_id}"
    ))
    builder.row(InlineKeyboardButton(
        text="📆 Повторы", callback_data=f"mgr:recurring:{student_id}"
    ))
    builder.row(InlineKeyboardButton(
        text="✏️ Редактировать", callback_data=f"mgr:edit_student:{student_id}"
    ))
    builder.row(InlineKeyboardButton(
        text="🗑 Удалить ученика", callback_data=f"mgr:delete_student:{student_id}"
    ))
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="mgr:students"))
    return builder.as_markup()


def confirm_delete_student_keyboard(student_id: int) -> InlineKeyboardMarkup:
    """Подтверждение удаления ученика."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"mgr:confirm_delete:{student_id}"),
        InlineKeyboardButton(text="❌ Отмена", callback_data=f"mgr:student:{student_id}"),
    )
    return builder.as_markup()


def lessons_for_complete_keyboard(lessons: list[Lesson]) -> InlineKeyboardMarkup:
    """Выбор урока который нужно отметить как проведённый."""
    builder = InlineKeyboardBuilder()
    for lesson in lessons:
        time_str = lesson.scheduled_at.strftime("%d.%m %H:%M")
        confirmed = "✅" if lesson.parent_confirmed else ("❓" if lesson.parent_confirmed is None else "❌")
        builder.row(InlineKeyboardButton(
            text=f"{time_str} {confirmed}",
            callback_data=f"mgr:do_complete:{lesson.id}"
        ))
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="mgr:students"))
    return builder.as_markup()


def confirm_complete_keyboard(lesson_id: int) -> InlineKeyboardMarkup:
    """Подтверждение что урок проведён."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ Проведён", callback_data=f"mgr:confirm_complete:{lesson_id}"),
        InlineKeyboardButton(text="❌ Не пришли", callback_data=f"mgr:no_show:{lesson_id}"),
    )
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="mgr:students"))
    return builder.as_markup()


def schedule_keyboard() -> InlineKeyboardMarkup:
    """Меню расписания."""
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="📋 Сегодня", callback_data="mgr:today"))
    builder.row(InlineKeyboardButton(text="📅 На неделю", callback_data="mgr:week"))
    builder.row(InlineKeyboardButton(text="➕ Добавить урок", callback_data="mgr:add_lesson:choose"))
    builder.row(InlineKeyboardButton(text="🔄 Перенести урок", callback_data="mgr:reschedule:choose"))
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="mgr:main"))
    return builder.as_markup()


def back_to_main_keyboard() -> InlineKeyboardMarkup:
    """Простая кнопка назад в главное меню."""
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="◀️ Главное меню", callback_data="mgr:main"))
    return builder.as_markup()


def trial_request_keyboard(trial_id: int) -> InlineKeyboardMarkup:
    """Кнопки одобрения или отклонения заявки на пробный урок."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ Одобрить", callback_data=f"mgr:trial_approve:{trial_id}"),
        InlineKeyboardButton(text="❌ Отклонить", callback_data=f"mgr:trial_reject:{trial_id}"),
    )
    return builder.as_markup()


def write_report_keyboard(student_id: int, parent_tg_id: int) -> InlineKeyboardMarkup:
    """Кнопка для менеджера — написать отчёт о прогрессе ученика."""
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(
        text="✍️ Написать отчёт",
        callback_data=f"mgr:write_report:{student_id}:{parent_tg_id}"
    ))
    return builder.as_markup()


def payment_type_keyboard() -> InlineKeyboardMarkup:
    """Выбор типа оплаты при добавлении ученика."""
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(
        text="💳 Пакет уроков (заранее)", callback_data="mgr:ptype:prepaid"
    ))
    builder.row(InlineKeyboardButton(
        text="🔄 По факту урока", callback_data="mgr:ptype:postpaid"
    ))
    return builder.as_markup()


def skip_back_keyboard(back_callback: str) -> InlineKeyboardMarkup:
    """Кнопки Пропустить + Назад — используем вместо /skip команды."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="⏭ Пропустить", callback_data="action:skip"),
        InlineKeyboardButton(text="◀️ Назад", callback_data=back_callback),
    )
    return builder.as_markup()


def only_back_keyboard(back_callback: str) -> InlineKeyboardMarkup:
    """Только кнопка Назад — для текстовых вводов."""
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data=back_callback))
    return builder.as_markup()


def feedback_list_keyboard(feedbacks: list) -> InlineKeyboardMarkup:
    """Список сообщений обратной связи с кнопкой ответа на каждое."""
    builder = InlineKeyboardBuilder()
    for fb in feedbacks:
        builder.row(InlineKeyboardButton(
            text=f"↩️ Ответить {fb.parent.name}",
            callback_data=f"mgr:reply_feedback:{fb.id}"
        ))
    builder.row(InlineKeyboardButton(text="◀️ Главное меню", callback_data="mgr:main"))
    return builder.as_markup()


def reschedule_lessons_keyboard(lessons: list[Lesson]) -> InlineKeyboardMarkup:
    """Выбор урока для переноса."""
    builder = InlineKeyboardBuilder()
    for lesson in lessons:
        time_str = lesson.scheduled_at.strftime("%d.%m %H:%M")
        builder.row(InlineKeyboardButton(
            text=f"📅 {time_str} — {lesson.student.name}",
            callback_data=f"mgr:reschedule_lesson:{lesson.id}"
        ))
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="mgr:schedule"))
    return builder.as_markup()


def edit_student_keyboard(student_id: int) -> InlineKeyboardMarkup:
    """Выбор поля для редактирования ученика."""
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(
        text="✏️ Имя", callback_data=f"mgr:edit_field:{student_id}:name"
    ))
    builder.row(InlineKeyboardButton(
        text="🎂 Возраст", callback_data=f"mgr:edit_field:{student_id}:age"
    ))
    builder.row(InlineKeyboardButton(
        text="💳 Тип оплаты", callback_data=f"mgr:edit_field:{student_id}:payment_type"
    ))
    builder.row(InlineKeyboardButton(
        text="◀️ Назад", callback_data=f"mgr:student:{student_id}"
    ))
    return builder.as_markup()


def payments_menu_keyboard(unpaid: list) -> InlineKeyboardMarkup:
    """Меню оплат — кнопка приёма оплаты и выплаты бонусов если они есть."""
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="➕ Принять оплату", callback_data="mgr:add_payment"))
    if unpaid:
        builder.row(InlineKeyboardButton(
            text=f"💳 Выплатить бонусы ({len(unpaid)})", callback_data="mgr:pay_bonuses"
        ))
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="mgr:main"))
    return builder.as_markup()


def pay_bonuses_keyboard(unpaid: list) -> InlineKeyboardMarkup:
    """Список кэш-бонусов к выплате — кнопка на каждый бонус."""
    builder = InlineKeyboardBuilder()
    for bonus in unpaid:
        builder.row(InlineKeyboardButton(
            text=f"✅ Выплачено {bonus.amount} руб",
            callback_data=f"mgr:bonus_paid:{bonus.id}"
        ))
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="mgr:payments"))
    return builder.as_markup()


_DAYS_RU = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]


def day_of_week_keyboard(student_id: int) -> InlineKeyboardMarkup:
    """Выбор дня недели для повторяющегося расписания."""
    builder = InlineKeyboardBuilder()
    for i, day_name in enumerate(_DAYS_RU):
        builder.button(
            text=day_name,
            callback_data=f"mgr:rec_day:{student_id}:{i}"
        )
    builder.adjust(4, 3)
    builder.row(InlineKeyboardButton(
        text="◀️ Назад", callback_data=f"mgr:recurring:{student_id}"
    ))
    return builder.as_markup()


def recurring_schedule_keyboard(schedules: list, student_id: int) -> InlineKeyboardMarkup:
    """Список повторяющихся расписаний ученика с кнопкой удаления каждого."""
    builder = InlineKeyboardBuilder()
    for s in schedules:
        day_name = _DAYS_RU[s.day_of_week]
        time_str = f"{s.hour:02d}:{s.minute:02d}"
        builder.row(InlineKeyboardButton(
            text=f"🗑 {day_name} {time_str}",
            callback_data=f"mgr:del_recurring:{s.id}:{student_id}"
        ))
    builder.row(InlineKeyboardButton(
        text="➕ Добавить", callback_data=f"mgr:add_recurring:{student_id}"
    ))
    builder.row(InlineKeyboardButton(
        text="◀️ Назад", callback_data=f"mgr:student:{student_id}"
    ))
    return builder.as_markup()


def confirm_broadcast_keyboard() -> InlineKeyboardMarkup:
    """Подтверждение рассылки."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ Отправить всем", callback_data="mgr:broadcast_confirm"),
        InlineKeyboardButton(text="❌ Отменить", callback_data="mgr:main"),
    )
    return builder.as_markup()
