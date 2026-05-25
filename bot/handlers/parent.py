import logging
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot import config
from bot.database import crud
from bot.database.session import get_session
from bot.keyboards import parent_kb
from bot.services.notifications import get_bot_username
from bot.states.parent_states import BugReportStates, CancelLessonStates, FeedbackStates

router = Router()
logger = logging.getLogger(__name__)


def _lessons_word(n: int) -> str:
    """Склонение слова 'урок' под число."""
    if 11 <= n % 100 <= 19:
        return "уроков"
    r = n % 10
    if r == 1:
        return "урок"
    if 2 <= r <= 4:
        return "урока"
    return "уроков"


async def _get_parent_or_fail(callback: CallbackQuery, session):
    """Вспомогательная функция — получаем родителя и проверяем что он есть."""
    parent = await crud.get_parent_by_telegram_id(session, callback.from_user.id)
    if not parent:
        await callback.answer("Аккаунт не найден. Напишите /start", show_alert=True)
    return parent


@router.callback_query(F.data == "par:main")
async def parent_main(callback: CallbackQuery, state: FSMContext) -> None:
    """Главное меню родителя — сбрасываем любой активный FSM-флоу."""
    await state.clear()
    async with get_session() as session:
        parent = await _get_parent_or_fail(callback, session)
        if not parent:
            return
        students = await crud.get_students_by_parent(session, parent.id)
        is_subscribed = parent.is_news_subscriber

    await callback.message.edit_text(
        "👤 Личный кабинет",
        reply_markup=parent_kb.parent_main_menu(students, is_subscribed)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("par:cabinet:"))
async def student_cabinet(callback: CallbackQuery) -> None:
    """ЛК конкретного ученика — баланс, расписание."""
    student_id = int(callback.data.split(":")[2])

    async with get_session() as session:
        parent = await _get_parent_or_fail(callback, session)
        if not parent:
            return

        student = await crud.get_student_by_id(session, student_id)
        # Проверяем что этот ученик принадлежит этому родителю
        if not student or student.parent_id != parent.id:
            await callback.answer("Ученик не найден.", show_alert=True)
            return

        balance = student.lessons_balance
        completed = student.lessons_completed

    if student.payment_type == "postpaid":
        # Для постоплаты баланс не показываем
        balance_block = "🔄 <b>Оплата по факту</b>\n<i>Оплачивается после каждого занятия.</i>"
    elif balance == 0:
        balance_block = "🔴 <b>0 уроков</b>\n<i>Для продолжения занятий необходимо пополнить баланс.</i>"
    elif balance <= 2:
        balance_block = (
            f"🟡 <b>{balance}</b> {_lessons_word(balance)}\n"
            f"<i>Баланс заканчивается — рекомендуем пополнить заранее.</i>"
        )
    else:
        balance_block = f"🟢 <b>{balance}</b> {_lessons_word(balance)}"

    text = (
        f"👤 <b>{student.name}</b>\n"
        f"{'─' * 22}\n\n"
        f"📚 Баланс уроков\n"
        f"{balance_block}\n\n"
        f"📊 Проведено занятий: <b>{completed}</b>"
    )

    await callback.message.edit_text(
        text,
        reply_markup=parent_kb.student_cabinet_keyboard(student_id),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("par:schedule:"))
async def student_schedule(callback: CallbackQuery) -> None:
    """Ближайшие уроки ученика."""
    student_id = int(callback.data.split(":")[2])

    async with get_session() as session:
        parent = await _get_parent_or_fail(callback, session)
        if not parent:
            return

        student = await crud.get_student_by_id(session, student_id)
        if not student or student.parent_id != parent.id:
            await callback.answer("Ученик не найден.", show_alert=True)
            return

        lessons = await crud.get_upcoming_lessons(session, student_id)

    if not lessons:
        text = f"📅 Расписание <b>{student.name}</b>\n\nПредстоящих уроков нет."
    else:
        lines = [f"📅 Расписание <b>{student.name}</b>\n"]
        for lesson in lessons:
            dt = lesson.scheduled_at
            lines.append(f"• {dt.strftime('%d.%m.%Y %H:%M')}")
        text = "\n".join(lines)

    await callback.message.edit_text(
        text,
        reply_markup=parent_kb.back_to_cabinet_keyboard(student_id),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("par:history:"))
async def lesson_history(callback: CallbackQuery) -> None:
    """История проведённых уроков."""
    student_id = int(callback.data.split(":")[2])

    async with get_session() as session:
        parent = await _get_parent_or_fail(callback, session)
        if not parent:
            return

        student = await crud.get_student_by_id(session, student_id)
        if not student or student.parent_id != parent.id:
            await callback.answer("Ученик не найден.", show_alert=True)
            return

        lessons = await crud.get_lesson_history(session, student_id)

    if not lessons:
        text = f"📈 История уроков <b>{student.name}</b>\n\nПроведённых уроков пока нет."
    else:
        lines = [f"📈 Последние уроки <b>{student.name}</b>\n"]
        for i, lesson in enumerate(lessons, 1):
            dt = lesson.scheduled_at
            lines.append(f"{i}. {dt.strftime('%d.%m.%Y %H:%M')} ✅")
        text = "\n".join(lines)

    await callback.message.edit_text(
        text,
        reply_markup=parent_kb.back_to_cabinet_keyboard(student_id),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("par:payment_info"))
async def payment_info(callback: CallbackQuery) -> None:
    """Реквизиты для оплаты."""
    # student_id идёт после двоеточия если передан (par:payment_info:{id})
    parts = callback.data.split(":")
    student_id = int(parts[2]) if len(parts) > 2 else None

    text = (
        "💳 <b>Реквизиты для оплаты</b>\n\n"

        "🏦 <b>Банковская карта</b>\n"
        "<code>5536 9139 8877 2220</code>\n"
        "Получатель: <b>Искендеров Р К</b>\n\n"

        "🪙 <b>Криптовалюта (Binance)</b>\n"
        "UID: <code>120859192</code>\n\n"

        "─────────────────────\n"
        "После оплаты напишите менеджеру — он зачислит уроки на баланс."
    )
    keyboard = (
        parent_kb.back_to_cabinet_keyboard(student_id)
        if student_id else parent_kb.back_to_main_keyboard()
    )
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    await callback.answer()


# ──────────────────────────────────────────────
# ПОДТВЕРЖДЕНИЕ / ОТМЕНА УРОКА
# ──────────────────────────────────────────────

async def _check_lesson_ownership(callback_or_message, lesson_id: int, session) -> bool:
    """Проверяем что урок принадлежит ученику этого родителя — защита от подмены lesson_id."""
    from_user_id = callback_or_message.from_user.id
    lesson = await crud.get_lesson_by_id(session, lesson_id)
    if not lesson:
        return False
    parent = await crud.get_parent_by_telegram_id(session, from_user_id)
    if not parent or lesson.student.parent_id != parent.id:
        return False
    return True


@router.callback_query(F.data.startswith("par:confirm:"))
async def confirm_lesson(callback: CallbackQuery) -> None:
    """Родитель подтверждает что придёт на урок."""
    lesson_id = int(callback.data.split(":")[2])

    async with get_session() as session:
        if not await _check_lesson_ownership(callback, lesson_id, session):
            await callback.answer("Нет доступа к этому уроку.", show_alert=True)
            return
        await crud.set_parent_confirmed(session, lesson_id, True)

    await callback.message.edit_text(
        "✅ Отлично! Ждём вас на уроке.",
        reply_markup=parent_kb.back_to_main_keyboard()
    )
    await callback.answer()

    # Уведомляем менеджера что родитель подтвердил
    from bot.services.notifications import notify_manager_lesson_confirmed
    await notify_manager_lesson_confirmed(lesson_id)


@router.callback_query(F.data.startswith("par:cancel:"))
async def cancel_lesson_start(callback: CallbackQuery, state: FSMContext) -> None:
    """Родитель нажал 'Не придём' — предлагаем выбрать причину."""
    lesson_id = int(callback.data.split(":")[2])

    async with get_session() as session:
        if not await _check_lesson_ownership(callback, lesson_id, session):
            await callback.answer("Нет доступа к этому уроку.", show_alert=True)
            return

    await state.update_data(lesson_id=lesson_id)
    await callback.message.edit_text(
        "Что случилось?",
        reply_markup=parent_kb.lesson_cancel_reason_keyboard(lesson_id)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("par:cancel_reason:"))
async def cancel_lesson_quick_reason(callback: CallbackQuery) -> None:
    """Отмена урока с быстрой причиной."""
    parts = callback.data.split(":")
    lesson_id = int(parts[2])
    reason = parts[3]

    async with get_session() as session:
        if not await _check_lesson_ownership(callback, lesson_id, session):
            await callback.answer("Нет доступа к этому уроку.", show_alert=True)
            return
        lesson = await crud.cancel_lesson(session, lesson_id, reason, "parent")
        if not lesson:
            await callback.answer("Урок уже отменён или не найден.", show_alert=True)
            return

    await callback.message.edit_text(
        f"❌ Урок отменён. Причина: {reason}\n\nНадеемся увидеть вас на следующем занятии!",
        reply_markup=parent_kb.back_to_main_keyboard()
    )
    await callback.answer()

    from bot.scheduler.jobs import cancel_lesson_reminders
    cancel_lesson_reminders(lesson_id)

    from bot.services.notifications import notify_manager_lesson_cancelled
    await notify_manager_lesson_cancelled(lesson_id, reason)


@router.callback_query(F.data.startswith("par:cancel_custom:"))
async def cancel_lesson_custom_reason_start(callback: CallbackQuery, state: FSMContext) -> None:
    """Родитель хочет написать свою причину отмены."""
    lesson_id = int(callback.data.split(":")[2])

    async with get_session() as session:
        if not await _check_lesson_ownership(callback, lesson_id, session):
            await callback.answer("Нет доступа к этому уроку.", show_alert=True)
            return

    await state.update_data(lesson_id=lesson_id)
    await state.set_state(CancelLessonStates.waiting_reason)
    await callback.message.edit_text("Напишите причину отмены:")
    await callback.answer()


@router.message(CancelLessonStates.waiting_reason)
async def cancel_lesson_custom_reason(message: Message, state: FSMContext) -> None:
    """Получаем кастомную причину и отменяем урок."""
    data = await state.get_data()
    lesson_id = data["lesson_id"]
    reason = message.text.strip()

    async with get_session() as session:
        lesson = await crud.cancel_lesson(session, lesson_id, reason, "parent")

    await state.clear()

    if not lesson:
        await message.answer(
            "Урок уже был отменён ранее.",
            reply_markup=parent_kb.back_to_main_keyboard()
        )
        return

    await message.answer(
        "❌ Урок отменён. Спасибо что предупредили!",
        reply_markup=parent_kb.back_to_main_keyboard()
    )

    from bot.scheduler.jobs import cancel_lesson_reminders
    cancel_lesson_reminders(lesson_id)

    from bot.services.notifications import notify_manager_lesson_cancelled
    await notify_manager_lesson_cancelled(lesson_id, reason)


# ──────────────────────────────────────────────
# ОБРАТНАЯ СВЯЗЬ
# ──────────────────────────────────────────────

@router.callback_query(F.data.startswith("par:request_report:"))
async def request_progress_report_confirm(callback: CallbackQuery) -> None:
    """Запрашиваем подтверждение перед отправкой запроса отчёта."""
    student_id = int(callback.data.split(":")[2])

    async with get_session() as session:
        parent = await _get_parent_or_fail(callback, session)
        if not parent:
            return
        student = await crud.get_student_by_id(session, student_id)
        if not student or student.parent_id != parent.id:
            await callback.answer("Ученик не найден.", show_alert=True)
            return
        student_name = student.name

    await callback.message.edit_text(
        f"📝 <b>Запросить отчёт о прогрессе?</b>\n\n"
        f"Ученик: <b>{student_name}</b>\n\n"
        f"Преподаватель получит уведомление и подготовит отчёт об успехах вашего ребёнка.",
        reply_markup=parent_kb.confirm_report_request_keyboard(student_id),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("par:confirm_report:"))
async def request_progress_report_send(callback: CallbackQuery) -> None:
    """Подтверждение получено — отправляем запрос менеджеру."""
    student_id = int(callback.data.split(":")[2])

    async with get_session() as session:
        parent = await _get_parent_or_fail(callback, session)
        if not parent:
            return
        student = await crud.get_student_by_id(session, student_id)
        if not student or student.parent_id != parent.id:
            await callback.answer("Ученик не найден.", show_alert=True)
            return
        student_name = student.name
        parent_name = parent.name
        parent_tg_id = parent.telegram_id

    await callback.message.edit_text(
        f"✅ Запрос отправлен!\n\n"
        f"Преподаватель получил уведомление и напишет вам об успехах {student_name} в ближайшее время.",
        reply_markup=parent_kb.back_to_cabinet_keyboard(student_id)
    )
    await callback.answer()

    # Уведомляем менеджера с кнопкой "Написать отчёт"
    from bot.services.notifications import notify_manager_report_requested
    await notify_manager_report_requested(parent_name, student_name, student_id, parent_tg_id)


@router.callback_query(F.data == "par:feedback")
async def feedback_start(callback: CallbackQuery, state: FSMContext) -> None:
    """Начало диалога обратной связи."""
    await state.set_state(FeedbackStates.waiting_message)
    await callback.message.edit_text(
        "💬 <b>Обратная связь</b>\n\n"
        "Напишите ваш вопрос или отзыв — менеджер получит его и ответит:",
        reply_markup=parent_kb.back_to_main_keyboard(),
        parse_mode="HTML"
    )
    await callback.answer()


@router.message(FeedbackStates.waiting_message)
async def feedback_receive(message: Message, state: FSMContext) -> None:
    """Сохраняем обратную связь и уведомляем менеджера."""
    async with get_session() as session:
        parent = await crud.get_parent_by_telegram_id(session, message.from_user.id)
        if not parent:
            await message.answer("Аккаунт не найден. Напишите /start")
            await state.clear()
            return
        feedback = await crud.create_feedback(session, parent.id, message.text.strip())
        feedback_id = feedback.id
        parent_name = parent.name

    await state.clear()
    await message.answer(
        "✅ Сообщение отправлено! Менеджер ответит вам в ближайшее время.",
        reply_markup=parent_kb.back_to_main_keyboard()
    )

    # Уведомляем менеджера
    from bot.services.notifications import notify_manager_feedback
    await notify_manager_feedback(parent_name, message.text.strip(), feedback_id)


# ──────────────────────────────────────────────
# РЕФЕРАЛЬНАЯ ПРОГРАММА
# ──────────────────────────────────────────────

@router.callback_query(F.data == "par:news")
async def news_screen(callback: CallbackQuery) -> None:
    """Экран подписки на IT-новости."""
    async with get_session() as session:
        parent = await _get_parent_or_fail(callback, session)
        if not parent:
            return
        is_subscribed = parent.is_news_subscriber

    if is_subscribed:
        text = (
            "🔔 <b>IT-новости</b>\n\n"
            "Вы подписаны! Мы присылаем самое актуальное из мира IT "
            "для вас и вашего ребёнка.\n\n"
            "Тренды, новые языки программирования, советы как поддержать "
            "интерес ребёнка к технологиям — всё это будет у вас в боте."
        )
    else:
        text = (
            "🔕 <b>IT-новости</b>\n\n"
            "Подпишитесь и получайте самое актуальное из мира IT "
            "для вас и вашего ребёнка:\n\n"
            "• 🚀 Тренды в технологиях\n"
            "• 💡 Советы для родителей детей-программистов\n"
            "• 🎮 Новые способы заинтересовать ребёнка IT\n"
            "• 📚 Полезные ресурсы для обучения\n\n"
            "Только полезный контент, без спама."
        )

    await callback.message.edit_text(
        text,
        reply_markup=parent_kb.news_subscription_keyboard(is_subscribed),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data == "par:news_toggle")
async def news_toggle(callback: CallbackQuery) -> None:
    """Подписаться или отписаться от IT-новостей."""
    async with get_session() as session:
        parent = await _get_parent_or_fail(callback, session)
        if not parent:
            return
        parent_name = parent.name  # сохраняем до закрытия сессии
        new_status = await crud.toggle_news_subscription(session, parent)

    if new_status:
        text = (
            "🔔 <b>Вы подписаны на IT-новости!</b>\n\n"
            "Будем присылать самое интересное и полезное "
            "для вас и вашего ребёнка."
        )
    else:
        text = "🔕 Вы отписались от IT-новостей."

    await callback.message.edit_text(
        text,
        reply_markup=parent_kb.news_subscription_keyboard(new_status),
        parse_mode="HTML"
    )
    await callback.answer("✅ Готово!")

    from bot.services.notifications import notify_manager_news_subscription
    await notify_manager_news_subscription(parent_name, new_status)


@router.callback_query(F.data == "par:referral")
async def referral_info(callback: CallbackQuery) -> None:
    """Экран реферальной программы."""
    async with get_session() as session:
        parent = await _get_parent_or_fail(callback, session)
        if not parent:
            return

        referrals = await crud.get_referrals_by_referrer(session, parent.id)
        active_count = sum(1 for r in referrals if r.status == "active")

    # Определяем статус амбассадора
    if active_count >= 5:
        status = "🥇 Амбассадор"
    elif active_count >= 3:
        status = "🥈 Старший партнёр"
    elif active_count >= 1:
        status = "🥉 Партнёр"
    else:
        status = "👤 Обычный участник"

    bot_username = get_bot_username()
    referral_link = f"https://t.me/{bot_username}?start=ref_{parent.referral_code}"

    text = (
        f"🎁 <b>Партнёрская программа</b>\n\n"
        f"Статус: {status}\n"
        f"Активных рефералов: {active_count}\n\n"
        f"<b>Как это работает:</b>\n"
        f"• Друг записался и оплатил → +1 урок вам\n"
        f"• Учится 1 месяц → ещё +1 урок вам\n"
        f"• Учится 3 месяца → 2 000 руб вам\n"
        f"• Учится 6 месяцев → 2 500 руб вам\n\n"
        f"Ваша ссылка:\n<code>{referral_link}</code>"
    )

    await callback.message.edit_text(
        text,
        reply_markup=parent_kb.referral_keyboard(referral_link),
        parse_mode="HTML"
    )
    await callback.answer()


# ──────────────────────────────────────────────
# СООБЩИТЬ ОБ ОШИБКЕ
# ──────────────────────────────────────────────

@router.callback_query(F.data == "par:bug_report")
async def bug_report_start(callback: CallbackQuery, state: FSMContext) -> None:
    """Начало отчёта об ошибке — просим описать что пошло не так."""
    await state.set_state(BugReportStates.waiting_description)
    await callback.message.edit_text(
        "🐛 <b>Сообщить об ошибке</b>\n\n"
        "Опишите что пошло не так — что вы делали, что ожидали увидеть "
        "и что получилось вместо этого.\n\n"
        "Напишите ваше сообщение:",
        reply_markup=parent_kb.back_to_main_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(BugReportStates.waiting_description)
async def bug_report_received(message: Message, state: FSMContext) -> None:
    """Получили описание ошибки — пересылаем менеджеру."""
    from bot.services.notifications import notify_manager_bug_report

    description = message.text.strip()
    user = message.from_user
    user_info = f"@{user.username}" if user.username else f"tg_id={user.id}"

    await notify_manager_bug_report(user.full_name, user_info, description)

    await state.clear()
    await message.answer(
        "✅ Спасибо! Сообщение об ошибке отправлено.\n\n"
        "Мы разберёмся и исправим это как можно скорее.",
        reply_markup=parent_kb.back_to_main_keyboard(),
    )


@router.callback_query(F.data == "par:referral_history")
async def referral_history(callback: CallbackQuery) -> None:
    """История рефералов родителя."""
    async with get_session() as session:
        parent = await _get_parent_or_fail(callback, session)
        if not parent:
            return
        referrals = await crud.get_referrals_by_referrer(session, parent.id)

    if not referrals:
        text = "📊 История рефералов\n\nВы пока никого не пригласили."
    else:
        lines = ["📊 <b>Ваши рефералы</b>\n"]
        for r in referrals:
            status_icon = {"pending": "⏳", "active": "✅", "completed": "🏆"}.get(r.status, "❓")
            months = ""
            if r.first_payment_at:
                from bot.utils import local_now
                delta = local_now() - r.first_payment_at
                months = f" — {delta.days // 30} мес."
            lines.append(f"{status_icon} {r.referred.name}{months}")
        text = "\n".join(lines)

    await callback.message.edit_text(
        text,
        reply_markup=parent_kb.back_to_main_keyboard(),
        parse_mode="HTML"
    )
    await callback.answer()
