from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.database.models import Lesson, Student


def welcome_keyboard() -> InlineKeyboardMarkup:
    """Экран приветствия для нового пользователя нашедшего бота."""
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(
        text="🎓 Записаться на пробный урок", callback_data="trial:start"
    ))
    builder.row(InlineKeyboardButton(
        text="📖 Узнать подробнее о школе", callback_data="trial:about"
    ))
    return builder.as_markup()


def trial_cancel_keyboard() -> InlineKeyboardMarkup:
    """Кнопка отмены на первом шаге записи на пробный урок."""
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="❌ Отмена", callback_data="trial:cancel"))
    return builder.as_markup()


def trial_time_keyboard() -> InlineKeyboardMarkup:
    """Выбор удобного времени для пробного урока."""
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🌅 Утро (9:00–12:00)", callback_data="trial:time:утро (9-12)"))
    builder.row(InlineKeyboardButton(text="☀️ День (12:00–16:00)", callback_data="trial:time:день (12-16)"))
    builder.row(InlineKeyboardButton(text="🌆 Вечер (16:00–20:00)", callback_data="trial:time:вечер (16-20)"))
    builder.row(InlineKeyboardButton(text="📅 Обсудим индивидуально", callback_data="trial:time:индивидуально"))
    return builder.as_markup()


def parent_main_menu(students: list[Student], is_subscribed: bool = False) -> InlineKeyboardMarkup:
    """Главное меню родителя. Если детей несколько — показываем выбор."""
    builder = InlineKeyboardBuilder()

    if len(students) == 1:
        builder.row(InlineKeyboardButton(
            text="📊 Личный кабинет", callback_data=f"par:cabinet:{students[0].id}"
        ))
    else:
        for student in students:
            builder.row(InlineKeyboardButton(
                text=f"👤 {student.name}",
                callback_data=f"par:cabinet:{student.id}"
            ))

    # Подписка на IT-новости — статус виден прямо в кнопке
    news_icon = "🔔" if is_subscribed else "🔕"
    news_text = f"{news_icon} IT-новости {'(вкл)' if is_subscribed else '(выкл)'}"
    builder.row(InlineKeyboardButton(text=news_text, callback_data="par:news"))
    builder.row(InlineKeyboardButton(text="💬 Обратная связь", callback_data="par:feedback"))
    builder.row(InlineKeyboardButton(text="🎁 Пригласить друга", callback_data="par:referral"))
    builder.row(InlineKeyboardButton(text="🐛 Сообщить об ошибке", callback_data="par:bug_report"))
    return builder.as_markup()


def student_cabinet_keyboard(student_id: int) -> InlineKeyboardMarkup:
    """ЛК конкретного ученика."""
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(
        text="📅 Расписание", callback_data=f"par:schedule:{student_id}"
    ))
    builder.row(InlineKeyboardButton(
        text="📈 История уроков", callback_data=f"par:history:{student_id}"
    ))
    builder.row(InlineKeyboardButton(
        text="📝 Запросить отчёт о прогрессе", callback_data=f"par:request_report:{student_id}"
    ))
    builder.row(InlineKeyboardButton(
        text="💳 Реквизиты для оплаты", callback_data=f"par:payment_info:{student_id}"
    ))
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="par:main"))
    return builder.as_markup()


def lesson_reminder_keyboard(lesson_id: int) -> InlineKeyboardMarkup:
    """Кнопки в напоминании за 24 часа."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ Придём", callback_data=f"par:confirm:{lesson_id}"),
        InlineKeyboardButton(text="❌ Не придём", callback_data=f"par:cancel:{lesson_id}"),
    )
    return builder.as_markup()


def lesson_cancel_reason_keyboard(lesson_id: int) -> InlineKeyboardMarkup:
    """Быстрый выбор причины отмены."""
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(
        text="🤒 Болеем", callback_data=f"par:cancel_reason:{lesson_id}:болеем"
    ))
    builder.row(InlineKeyboardButton(
        text="📌 Другие дела", callback_data=f"par:cancel_reason:{lesson_id}:другие дела"
    ))
    builder.row(InlineKeyboardButton(
        text="✏️ Своя причина", callback_data=f"par:cancel_custom:{lesson_id}"
    ))
    return builder.as_markup()


def back_to_main_keyboard() -> InlineKeyboardMarkup:
    """Простая кнопка назад в главное меню."""
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="◀️ Главное меню", callback_data="par:main"))
    return builder.as_markup()


def confirm_report_request_keyboard(student_id: int) -> InlineKeyboardMarkup:
    """Подтверждение запроса отчёта о прогрессе."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="✅ Да, отправить", callback_data=f"par:confirm_report:{student_id}"
        ),
        InlineKeyboardButton(
            text="❌ Отмена", callback_data=f"par:cabinet:{student_id}"
        ),
    )
    return builder.as_markup()


def back_to_cabinet_keyboard(student_id: int) -> InlineKeyboardMarkup:
    """Кнопка назад в ЛК ученика — для разделов внутри кабинета."""
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data=f"par:cabinet:{student_id}"))
    return builder.as_markup()


def news_subscription_keyboard(is_subscribed: bool) -> InlineKeyboardMarkup:
    """Экран управления подпиской на IT-новости."""
    builder = InlineKeyboardBuilder()
    if is_subscribed:
        builder.row(InlineKeyboardButton(
            text="🔕 Отписаться", callback_data="par:news_toggle"
        ))
    else:
        builder.row(InlineKeyboardButton(
            text="🔔 Подписаться на новости", callback_data="par:news_toggle"
        ))
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="par:main"))
    return builder.as_markup()


def skip_back_keyboard(back_callback: str = "par:main") -> InlineKeyboardMarkup:
    """Кнопки Пропустить + Назад для текстовых вводов."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="⏭ Пропустить", callback_data="action:skip"),
        InlineKeyboardButton(text="◀️ Назад", callback_data=back_callback),
    )
    return builder.as_markup()


def welcome_to_school_keyboard(invite_link: str) -> InlineKeyboardMarkup:
    """Кнопка для одобренного пользователя — переход в бот по инвайт-ссылке."""
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(
        text="🚀 Войти в личный кабинет",
        url=invite_link
    ))
    return builder.as_markup()


def referral_keyboard(referral_link: str) -> InlineKeyboardMarkup:
    """Экран реферальной программы."""
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(
        text="📤 Поделиться ссылкой",
        url=f"https://t.me/share/url?url={referral_link}&text=Записывайся в школу программирования!"
    ))
    builder.row(InlineKeyboardButton(
        text="📊 История начислений", callback_data="par:referral_history"
    ))
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="par:main"))
    return builder.as_markup()
