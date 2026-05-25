import asyncio
import logging
from datetime import datetime
from aiogram import Bot, F, Router
from bot.utils import local_now
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot import config
from bot.database import crud
from bot.database.session import get_session
from bot.keyboards import manager_kb, parent_kb
from bot.services.notifications import get_bot_username
from bot.states.manager_states import (
    AddLessonStates, AddPaymentStates, AddRecurringScheduleStates, AddStudentStates,
    BroadcastStates, NewsBroadcastStates, WriteReportStates,
    ReplyToFeedbackStates, EditStudentStates, RescheduleLessonStates,
)

router = Router()
logger = logging.getLogger(__name__)


async def _save_prompt(state: FSMContext, msg) -> None:
    """Сохраняем message_id промпта чтобы удалить после завершения флоу."""
    data = await state.get_data()
    ids = data.get("_prompt_ids", [])
    ids.append(msg.message_id)
    await state.update_data(_prompt_ids=ids)


async def _delete_prompts(bot, chat_id: int, state: FSMContext) -> None:
    """Удаляем все накопленные промпт-сообщения бота."""
    data = await state.get_data()
    for msg_id in data.get("_prompt_ids", []):
        try:
            await bot.delete_message(chat_id, msg_id)
        except Exception:
            pass


# ──────────────────────────────────────────────
# ГЛАВНОЕ МЕНЮ
# ──────────────────────────────────────────────

@router.callback_query(F.data == "mgr:main")
async def manager_main(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.edit_text(
        "🎛 Панель управления",
        reply_markup=manager_kb.manager_main_menu()
    )
    await callback.answer()


# ──────────────────────────────────────────────
# УЧЕНИКИ
# ──────────────────────────────────────────────

@router.callback_query(F.data == "mgr:students")
async def students_list(callback: CallbackQuery) -> None:
    """Список всех учеников с балансом."""
    async with get_session() as session:
        students = await crud.get_all_students(session)

    if not students:
        await callback.message.edit_text(
            "Учеников пока нет.\n\nДобавьте первого!",
            reply_markup=manager_kb.students_list_keyboard([])
        )
    else:
        await callback.message.edit_text(
            f"👥 Ученики ({len(students)})\n\n"
            "🟢 норм  🟡 мало  🔴 закончились  🔄 по факту",
            reply_markup=manager_kb.students_list_keyboard(students)
        )
    await callback.answer()


@router.callback_query(F.data.startswith("mgr:student:"))
async def student_profile(callback: CallbackQuery) -> None:
    """Профиль ученика."""
    student_id = int(callback.data.split(":")[2])

    async with get_session() as session:
        student = await crud.get_student_by_id(session, student_id)
        if not student:
            await callback.answer("Ученик не найден.", show_alert=True)
            return
        debt = await crud.get_postpaid_debt(session, student_id) if student.payment_type == "postpaid" else 0

    parent_info = f"{student.parent.name}" if student.parent_id else "Не привязан"

    if student.payment_type == "postpaid":
        if debt > 0:
            balance_line = f"🔄 По факту | ⚠️ Не оплачено: <b>{debt}</b> ур."
        else:
            balance_line = "🔄 По факту | ✅ Всё оплачено"
    else:
        balance_icon = "🔴" if student.lessons_balance == 0 else (
            "🟡" if student.lessons_balance <= 2 else "🟢"
        )
        balance_line = f"{balance_icon} Баланс: <b>{student.lessons_balance}</b> ур."

    text = (
        f"👤 <b>{student.name}</b>\n"
        f"Возраст: {student.age or '—'}\n"
        f"Родитель: {parent_info}\n\n"
        f"{balance_line}\n"
        f"Проведено всего: <b>{student.lessons_completed}</b>"
    )

    await callback.message.edit_text(
        text,
        reply_markup=manager_kb.student_profile_keyboard(student_id),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data == "mgr:add_student")
async def add_student_start(callback: CallbackQuery, state: FSMContext) -> None:
    """Начало добавления нового ученика."""
    await state.set_state(AddStudentStates.waiting_name)
    await callback.message.edit_text("Введите имя ученика:")
    await callback.answer()


@router.message(AddStudentStates.waiting_name)
async def add_student_name(message: Message, state: FSMContext) -> None:
    await state.update_data(student_name=message.text.strip())
    await state.set_state(AddStudentStates.waiting_age)
    await message.answer(
        "Возраст ученика:",
        reply_markup=manager_kb.skip_back_keyboard("mgr:students")
    )


@router.callback_query(AddStudentStates.waiting_age, F.data == "action:skip")
async def add_student_age_skip(callback: CallbackQuery, state: FSMContext) -> None:
    """Пропускаем возраст — переходим к выбору типа оплаты."""
    await state.update_data(age=None)
    await _ask_payment_type(callback.message, state)
    await callback.answer()


@router.message(AddStudentStates.waiting_age)
async def add_student_age(message: Message, state: FSMContext) -> None:
    try:
        age = int(message.text.strip())
    except ValueError:
        await message.answer(
            "Введите число:",
            reply_markup=manager_kb.skip_back_keyboard("mgr:students")
        )
        return
    await state.update_data(age=age)
    await _ask_payment_type(message, state)


async def _ask_payment_type(message, state: FSMContext) -> None:
    """Спрашиваем тип оплаты ученика."""
    await state.set_state(AddStudentStates.waiting_payment_type)
    await message.answer(
        "💳 Как родитель оплачивает занятия?",
        reply_markup=manager_kb.payment_type_keyboard()
    )


@router.callback_query(AddStudentStates.waiting_payment_type, F.data.startswith("mgr:ptype:"))
async def add_student_payment_type(callback: CallbackQuery, state: FSMContext) -> None:
    """Получили тип оплаты — создаём ученика."""
    payment_type = callback.data.split(":")[2]
    await _create_student(callback.message, state, payment_type=payment_type)
    await callback.answer()


async def _create_student(message, state: FSMContext, payment_type: str = "prepaid") -> None:
    """Общая логика создания ученика."""
    data = await state.get_data()
    age = data.get("age")

    async with get_session() as session:
        student = await crud.create_student(
            session, data["student_name"], age, payment_type
        )
        token = student.invite_token
        student_id = student.id

    await state.clear()

    ptype_label = "по факту урока 🔄" if payment_type == "postpaid" else "пакет уроков 💳"
    bot_username = get_bot_username()
    invite_link = f"https://t.me/{bot_username}?start={token}"

    await message.edit_text(
        f"✅ Ученик <b>{data['student_name']}</b> добавлен!\n"
        f"Тип оплаты: {ptype_label}\n\n"
        f"Отправьте родителю ссылку для регистрации:\n"
        f"<code>{invite_link}</code>",
        reply_markup=manager_kb.student_profile_keyboard(student_id),
        parse_mode="HTML"
    )
    logger.info(f"Добавлен новый ученик: {data['student_name']} ({payment_type})")


# ──────────────────────────────────────────────
# ИНВАЙТ-ССЫЛКА
# ──────────────────────────────────────────────

@router.callback_query(F.data.startswith("mgr:invite:"))
async def show_invite_link(callback: CallbackQuery) -> None:
    """Показываем инвайт-ссылку для ученика (если родитель потерял)."""
    student_id = int(callback.data.split(":")[2])

    async with get_session() as session:
        student = await crud.get_student_by_id(session, student_id)

    if not student:
        await callback.answer("Ученик не найден.", show_alert=True)
        return

    if student.parent_id:
        await callback.answer("Родитель уже привязан к этому ученику.", show_alert=True)
        return

    bot_username = get_bot_username()
    invite_link = f"https://t.me/{bot_username}?start={student.invite_token}"

    await callback.message.edit_text(
        f"🔗 Ссылка для родителя <b>{student.name}</b>:\n\n"
        f"<code>{invite_link}</code>",
        reply_markup=manager_kb.back_to_main_keyboard(),
        parse_mode="HTML"
    )
    await callback.answer()


# ──────────────────────────────────────────────
# УДАЛЕНИЕ УЧЕНИКА
# ──────────────────────────────────────────────

@router.callback_query(F.data.startswith("mgr:delete_student:"))
async def delete_student_confirm(callback: CallbackQuery) -> None:
    """Запрашиваем подтверждение перед удалением ученика."""
    student_id = int(callback.data.split(":")[2])

    async with get_session() as session:
        student = await crud.get_student_by_id(session, student_id)

    if not student:
        await callback.answer("Ученик не найден.", show_alert=True)
        return

    await callback.message.edit_text(
        f"🗑 <b>Удалить ученика?</b>\n\n"
        f"Ученик: <b>{student.name}</b>\n"
        f"Баланс: {student.lessons_balance} ур. | Проведено: {student.lessons_completed} ур.\n\n"
        f"История уроков и оплат сохранится, ученик просто пропадёт из всех списков.",
        reply_markup=manager_kb.confirm_delete_student_keyboard(student_id),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("mgr:confirm_delete:"))
async def delete_student_execute(callback: CallbackQuery) -> None:
    """Подтверждение получено — деактивируем ученика."""
    student_id = int(callback.data.split(":")[2])

    async with get_session() as session:
        student = await crud.deactivate_student(session, student_id)
        student_name = student.name if student else "Неизвестно"

    if not student:
        await callback.answer("Ученик не найден.", show_alert=True)
        return

    await callback.message.edit_text(
        f"✅ Ученик <b>{student_name}</b> удалён.\n\n"
        f"История сохранена в базе данных.",
        reply_markup=manager_kb.back_to_main_keyboard(),
        parse_mode="HTML"
    )
    await callback.answer()
    logger.info(f"Ученик деактивирован: {student_name} (id={student_id})")


# ──────────────────────────────────────────────
# УРОКИ — ОТМЕТИТЬ КАК ПРОВЕДЁННЫЙ
# ──────────────────────────────────────────────

@router.callback_query(F.data.startswith("mgr:complete_lesson:"))
async def choose_lesson_to_complete(callback: CallbackQuery) -> None:
    """Выбор урока который нужно отметить."""
    student_id = int(callback.data.split(":")[2])

    async with get_session() as session:
        lessons = await crud.get_completable_lessons(session, student_id)

    if not lessons:
        await callback.answer("Нет уроков для отметки (последние 24ч + будущие).", show_alert=True)
        return

    await callback.message.edit_text(
        "Выберите урок:",
        reply_markup=manager_kb.lessons_for_complete_keyboard(lessons)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("mgr:do_complete:"))
async def confirm_lesson_completion(callback: CallbackQuery) -> None:
    """Подтверждение — урок проведён или нет."""
    lesson_id = int(callback.data.split(":")[2])
    await callback.message.edit_text(
        "Урок состоялся?",
        reply_markup=manager_kb.confirm_complete_keyboard(lesson_id)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("mgr:confirm_complete:"))
async def do_complete_lesson(callback: CallbackQuery) -> None:
    """Менеджер подтверждает что урок проведён — списываем с баланса."""
    lesson_id = int(callback.data.split(":")[2])

    async with get_session() as session:
        lesson = await crud.complete_lesson(session, lesson_id)
        if not lesson:
            await callback.answer("Урок уже отмечен или не найден.", show_alert=True)
            return

        student = lesson.student
        parent = student.parent
        balance = student.lessons_balance
        completed = student.lessons_completed
        student_name = student.name
        payment_type = student.payment_type
        parent_tg_id = parent.telegram_id if parent else None
        debt = await crud.get_postpaid_debt(session, student.id) if payment_type == "postpaid" else 0

    if payment_type == "postpaid":
        balance_line = f"⚠️ Не оплачено: {debt} ур." if debt > 0 else "✅ Всё оплачено"
    else:
        balance_line = f"Остаток: {balance} ур."
    await callback.message.edit_text(
        f"✅ Урок проведён!\n\n"
        f"Ученик: {student_name}\n"
        f"{balance_line} | Проведено: {completed}",
        reply_markup=manager_kb.back_to_main_keyboard()
    )
    await callback.answer()

    # Уведомляем родителя что урок зачтён
    if parent_tg_id:
        from bot.services.notifications import notify_parent_lesson_completed
        await notify_parent_lesson_completed(parent_tg_id, student_name, balance, payment_type)

    logger.info(f"Урок проведён: id={lesson_id}, ученик={student_name}")


@router.callback_query(F.data.startswith("mgr:no_show:"))
async def mark_no_show(callback: CallbackQuery) -> None:
    """Родитель не пришёл без предупреждения."""
    lesson_id = int(callback.data.split(":")[2])

    async with get_session() as session:
        lesson = await crud.cancel_lesson(session, lesson_id, "не пришли без предупреждения", "parent")
        if not lesson:
            await callback.answer("Урок уже отмечен.", show_alert=True)
            return
        student_name = lesson.student.name

    from bot.scheduler.jobs import cancel_lesson_reminders
    cancel_lesson_reminders(lesson_id)

    await callback.message.edit_text(
        f"❌ Отмечено: {student_name} не пришли.",
        reply_markup=manager_kb.back_to_main_keyboard()
    )
    await callback.answer()


# ──────────────────────────────────────────────
# РАСПИСАНИЕ — ДОБАВИТЬ УРОК
# ──────────────────────────────────────────────

@router.callback_query(F.data == "mgr:schedule")
async def schedule_menu(callback: CallbackQuery) -> None:
    await callback.message.edit_text(
        "📅 Расписание",
        reply_markup=manager_kb.schedule_keyboard()
    )
    await callback.answer()


@router.callback_query(F.data == "mgr:today")
async def today_schedule(callback: CallbackQuery) -> None:
    """Уроки на сегодня."""
    async with get_session() as session:
        lessons = await crud.get_lessons_today(session)

    if not lessons:
        text = "📋 Сегодня уроков нет."
    else:
        lines = ["📋 <b>Уроки сегодня:</b>\n"]
        for lesson in lessons:
            time_str = lesson.scheduled_at.strftime("%H:%M")
            confirmed = ""
            if lesson.parent_confirmed is True:
                confirmed = " ✅"
            elif lesson.parent_confirmed is False:
                confirmed = " ❌"
            lines.append(f"• {time_str} — {lesson.student.name}{confirmed}")
        text = "\n".join(lines)

    await callback.message.edit_text(
        text,
        reply_markup=manager_kb.schedule_keyboard(),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data == "mgr:week")
async def week_schedule(callback: CallbackQuery) -> None:
    """Расписание на ближайшие 7 дней."""
    async with get_session() as session:
        lessons = await crud.get_lessons_week(session)

    if not lessons:
        text = "📅 На ближайшие 7 дней уроков нет."
    else:
        lines = ["📅 <b>Расписание на 7 дней:</b>\n"]
        for lesson in lessons:
            dt = lesson.scheduled_at
            confirmed = ""
            if lesson.parent_confirmed is True:
                confirmed = " ✅"
            elif lesson.parent_confirmed is False:
                confirmed = " ❌"
            lines.append(f"• {dt.strftime('%d.%m %H:%M')} — {lesson.student.name}{confirmed}")
        text = "\n".join(lines)

    await callback.message.edit_text(
        text,
        reply_markup=manager_kb.schedule_keyboard(),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("mgr:add_lesson:"))
async def add_lesson_start(callback: CallbackQuery, state: FSMContext) -> None:
    """Начало добавления урока."""
    parts = callback.data.split(":")
    student_id = parts[2] if parts[2] != "choose" else None

    if student_id:
        # Уже знаем ученика — спрашиваем дату
        await state.update_data(student_id=int(student_id))
        await state.set_state(AddLessonStates.waiting_date)
        await callback.message.edit_text(
            "Введите дату урока в формате ДД.ММ.ГГГГ\n\nПример: 25.05.2026",
            reply_markup=manager_kb.only_back_keyboard("mgr:schedule")
        )
    else:
        # Нужно выбрать ученика
        async with get_session() as session:
            students = await crud.get_all_students(session)
        await state.set_state(AddLessonStates.waiting_student)
        await callback.message.edit_text(
            "Выберите ученика:",
            reply_markup=manager_kb.lesson_student_select_keyboard(students)
        )
    await callback.answer()


@router.callback_query(AddLessonStates.waiting_student, F.data.startswith("mgr:lesson_student:"))
async def add_lesson_student_selected(callback: CallbackQuery, state: FSMContext) -> None:
    """Ученик выбран через расписание — запрашиваем дату урока."""
    student_id = int(callback.data.split(":")[2])
    await state.update_data(student_id=student_id)
    await state.set_state(AddLessonStates.waiting_date)
    await callback.message.edit_text(
        "Введите дату урока в формате ДД.ММ.ГГГГ\n\nПример: 25.05.2026",
        reply_markup=manager_kb.only_back_keyboard("mgr:schedule")
    )
    await callback.answer()


@router.message(AddLessonStates.waiting_date)
async def add_lesson_date(message: Message, state: FSMContext) -> None:
    try:
        date = datetime.strptime(message.text.strip(), "%d.%m.%Y")
    except ValueError:
        await message.answer("Неверный формат. Введите дату как ДД.ММ.ГГГГ\nПример: 25.05.2026")
        return

    if date.date() < local_now().date():
        await message.answer(
            "❌ Нельзя добавить урок в прошлом. Введите будущую дату:",
            reply_markup=manager_kb.only_back_keyboard("mgr:schedule")
        )
        return

    await state.update_data(lesson_date=date)
    await state.set_state(AddLessonStates.waiting_time)
    sent = await message.answer(
        "Введите время урока в формате ЧЧ:ММ\nПример: 16:00",
        reply_markup=manager_kb.only_back_keyboard("mgr:schedule")
    )
    await _save_prompt(state, sent)


@router.message(AddLessonStates.waiting_time)
async def add_lesson_time(message: Message, state: FSMContext) -> None:
    """Создаём урок и планируем напоминания."""
    try:
        time = datetime.strptime(message.text.strip(), "%H:%M")
    except ValueError:
        await message.answer("Неверный формат. Введите время как ЧЧ:ММ\nПример: 16:00")
        return

    data = await state.get_data()
    date: datetime = data["lesson_date"]
    student_id: int = data["student_id"]
    scheduled_at = date.replace(hour=time.hour, minute=time.minute, second=0, microsecond=0)

    async with get_session() as session:
        lesson = await crud.create_lesson(session, student_id, scheduled_at)
        lesson_id = lesson.id
        student = await crud.get_student_by_id(session, student_id)
        student_name = student.name

    from bot.scheduler.jobs import schedule_lesson_reminders
    await schedule_lesson_reminders(lesson_id, scheduled_at)

    await _delete_prompts(message.bot, message.chat.id, state)
    await state.clear()
    await message.answer(
        f"✅ Урок добавлен!\n\n"
        f"Ученик: {student_name}\n"
        f"Дата: {scheduled_at.strftime('%d.%m.%Y %H:%M')}\n\n"
        f"Напоминания запланированы автоматически.",
        reply_markup=manager_kb.back_to_main_keyboard()
    )
    logger.info(f"Добавлен урок id={lesson_id} для ученика {student_name} на {scheduled_at}")


# ──────────────────────────────────────────────
# ОПЛАТЫ
# ──────────────────────────────────────────────

@router.callback_query(F.data == "mgr:payments")
async def payments_menu(callback: CallbackQuery) -> None:
    """Меню оплат — кэш-бонусы к выплате и приём оплаты."""
    async with get_session() as session:
        unpaid = await crud.get_unpaid_cash_bonuses(session)

    text = "💰 Оплаты\n"
    if unpaid:
        text += f"\n⚠️ Кэш-бонусов к выплате: {len(unpaid)}"

    await callback.message.edit_text(text, reply_markup=manager_kb.payments_menu_keyboard(unpaid))
    await callback.answer()


@router.callback_query(F.data == "mgr:pay_bonuses")
async def pay_bonuses(callback: CallbackQuery) -> None:
    """Список кэш-бонусов к выплате рефереру."""
    async with get_session() as session:
        unpaid = await crud.get_unpaid_cash_bonuses(session)

    if not unpaid:
        await callback.answer("Кэш-бонусов к выплате нет.", show_alert=True)
        return

    lines = ["💳 <b>Кэш-бонусы к выплате:</b>\n"]
    for bonus in unpaid:
        lines.append(f"• {bonus.amount:,} руб — milestone: {bonus.milestone}".replace(",", " "))

    await callback.message.edit_text(
        "\n".join(lines),
        reply_markup=manager_kb.pay_bonuses_keyboard(unpaid),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("mgr:bonus_paid:"))
async def mark_bonus_paid(callback: CallbackQuery) -> None:
    """Отмечаем кэш-бонус как выплаченный."""
    bonus_id = int(callback.data.split(":")[2])

    async with get_session() as session:
        from sqlalchemy import update
        from bot.database.models import ReferralBonus
        await session.execute(
            update(ReferralBonus).where(ReferralBonus.id == bonus_id).values(is_paid=True)
        )
        unpaid = await crud.get_unpaid_cash_bonuses(session)

    if not unpaid:
        await callback.message.edit_text(
            "✅ Все кэш-бонусы выплачены!",
            reply_markup=manager_kb.back_to_main_keyboard()
        )
        await callback.answer("✅ Выплата зафиксирована")
        return

    # Обновляем список оставшихся бонусов inline
    lines = ["💳 <b>Кэш-бонусы к выплате:</b>\n"]
    for bonus in unpaid:
        lines.append(f"• {bonus.amount:,} руб — milestone: {bonus.milestone}".replace(",", " "))
    await callback.message.edit_text(
        "\n".join(lines),
        reply_markup=manager_kb.pay_bonuses_keyboard(unpaid),
        parse_mode="HTML"
    )
    await callback.answer("✅ Выплата зафиксирована")


@router.callback_query(F.data.startswith("mgr:payment:"))
async def add_payment_from_profile(callback: CallbackQuery, state: FSMContext) -> None:
    """Принять оплату прямо из профиля ученика — студент уже известен."""
    student_id = int(callback.data.split(":")[2])
    await state.update_data(student_id=student_id)
    await state.set_state(AddPaymentStates.waiting_lessons_count)
    await callback.message.edit_text(
        "Сколько уроков куплено?",
        reply_markup=manager_kb.only_back_keyboard(f"mgr:student:{student_id}")
    )
    await callback.answer()


@router.callback_query(F.data == "mgr:add_payment")
async def add_payment_start(callback: CallbackQuery, state: FSMContext) -> None:
    """Начало приёма оплаты."""
    async with get_session() as session:
        students = await crud.get_all_students(session)

    if not students:
        await callback.answer("Сначала добавьте ученика.", show_alert=True)
        return

    await state.set_state(AddPaymentStates.waiting_student)
    await callback.message.edit_text(
        "Выберите ученика для пополнения:",
        reply_markup=manager_kb.payment_select_student_keyboard(students)
    )
    await callback.answer()


# mgr:pay_select: — отдельный префикс чтобы не конфликтовать с хэндлером профиля ученика
@router.callback_query(F.data.startswith("mgr:pay_select:"))
async def add_payment_student_selected(callback: CallbackQuery, state: FSMContext) -> None:
    student_id = int(callback.data.split(":")[2])
    await state.update_data(student_id=student_id)
    await state.set_state(AddPaymentStates.waiting_lessons_count)
    await callback.message.edit_text(
        "Сколько уроков куплено?",
        reply_markup=manager_kb.only_back_keyboard("mgr:payments")
    )
    await callback.answer()


@router.message(AddPaymentStates.waiting_lessons_count)
async def add_payment_lessons(message: Message, state: FSMContext) -> None:
    try:
        count = int(message.text.strip())
        if count <= 0:
            raise ValueError
    except ValueError:
        await message.answer(
            "Введите положительное число:",
            reply_markup=manager_kb.only_back_keyboard("mgr:payments")
        )
        return

    await state.update_data(lessons_count=count)
    await state.set_state(AddPaymentStates.waiting_amount)
    sent = await message.answer(
        "Сумма оплаты в рублях:",
        reply_markup=manager_kb.skip_back_keyboard("mgr:payments")
    )
    await _save_prompt(state, sent)


@router.callback_query(AddPaymentStates.waiting_amount, F.data == "action:skip")
async def add_payment_amount_skip(callback: CallbackQuery, state: FSMContext) -> None:
    """Пропускаем сумму — зачисляем уроки без суммы."""
    await _finalize_payment(callback.message, state, amount=None)
    await callback.answer()


@router.message(AddPaymentStates.waiting_amount)
async def add_payment_amount(message: Message, state: FSMContext) -> None:
    """Завершаем приём оплаты — зачисляем уроки."""
    amount = None
    try:
        amount = int(message.text.strip())
    except ValueError:
        await message.answer(
            "Введите сумму числом:",
            reply_markup=manager_kb.skip_back_keyboard("mgr:payments")
        )
        return
    await _finalize_payment(message, state, amount=amount)


async def _finalize_payment(message, state: FSMContext, amount: int | None) -> None:
    """Общая логика завершения оплаты."""
    await _delete_prompts(message.bot, message.chat.id, state)
    data = await state.get_data()

    async with get_session() as session:
        student = await crud.get_student_by_id(session, data["student_id"])
        await crud.add_lessons_to_balance(
            session, student, data["lessons_count"], amount
        )

        # Если это первая оплата — активируем реферала
        if student.parent_id:
            referral = await crud.get_referral_by_referred(session, student.parent_id)
            if referral and referral.status == "pending" and not referral.bonus_signup:
                await crud.activate_referral(session, referral)
                referral.bonus_signup = True
                # Начисляем бонусные уроки обоим
                await _apply_signup_bonus(session, referral)

        student_name = student.name
        new_balance = student.lessons_balance
        payment_type = student.payment_type
        parent_tg_id = student.parent.telegram_id if student.parent_id else None

    await state.clear()
    if payment_type == "postpaid":
        result_text = (
            f"✅ Оплата зафиксирована!\n\n"
            f"Ученик: {student_name}\n"
            f"Уроков оплачено: {data['lessons_count']} ур."
        )
    else:
        result_text = (
            f"✅ Оплата принята!\n\n"
            f"Ученик: {student_name}\n"
            f"Добавлено: {data['lessons_count']} ур.\n"
            f"Новый баланс: {new_balance} ур."
        )
    await message.answer(result_text, reply_markup=manager_kb.back_to_main_keyboard())

    # Уведомляем родителя о зачислении
    if parent_tg_id:
        from bot.services.notifications import notify_parent_payment_received
        await notify_parent_payment_received(parent_tg_id, student_name, data["lessons_count"], new_balance)

    logger.info(f"Оплата принята: {student_name}, +{data['lessons_count']} уроков")


async def _apply_signup_bonus(session, referral) -> None:
    """Начисляем бонус за первую оплату реферала (+1 урок) и уведомляем родителя."""
    from bot import config as cfg
    from bot.database.models import Parent

    referrer_students = await crud.get_students_by_parent(session, referral.referrer_id)
    if referrer_students:
        referrer_students[0].lessons_balance += cfg.REFERRAL_BONUS_SIGNUP_LESSONS

    await crud.add_referral_bonus(
        session, referral.id, referral.referrer_id,
        "lesson", cfg.REFERRAL_BONUS_SIGNUP_LESSONS, "signup"
    )

    # Уведомляем пригласившего родителя о начислении бонуса
    referrer_tg_id = referral.referrer.telegram_id
    from bot.services.notifications import notify_parent_referral_bonus
    await notify_parent_referral_bonus(
        referrer_tg_id, "lesson", cfg.REFERRAL_BONUS_SIGNUP_LESSONS, "signup"
    )


# ──────────────────────────────────────────────
# ЗАЯВКИ НА ПРОБНЫЙ УРОК
# ──────────────────────────────────────────────

@router.callback_query(F.data.startswith("mgr:trial_approve:"))
async def trial_approve(callback: CallbackQuery) -> None:
    """Менеджер одобряет заявку — создаём ученика и отправляем инвайт-ссылку."""
    trial_id = int(callback.data.split(":")[2])

    async with get_session() as session:
        trial = await crud.get_trial_request_by_id(session, trial_id)
        if not trial or trial.status != "pending":
            await callback.answer("Заявка уже обработана.", show_alert=True)
            return

        # Создаём ученика сразу с именем из заявки
        student = await crud.create_student(session, trial.child_name, trial.child_age)
        token = student.invite_token
        await crud.update_trial_status(session, trial_id, "approved")
        parent_tg_id = trial.telegram_id
        parent_name = trial.parent_name
        child_name = trial.child_name

    bot_username = get_bot_username()
    invite_link = f"https://t.me/{bot_username}?start={token}"

    # Отправляем инвайт-ссылку напрямую пользователю
    try:
        await callback.bot.send_message(
            parent_tg_id,
            f"🎉 <b>Ваша заявка одобрена!</b>\n\n"
            f"Добро пожаловать в школу программирования, {parent_name.split()[0]}!\n\n"
            f"Для доступа к боту и расписанию нажмите кнопку ниже:",
            reply_markup=parent_kb.welcome_to_school_keyboard(invite_link),
            parse_mode="HTML"
        )
        await callback.message.edit_text(
            f"✅ Заявка одобрена!\n\n"
            f"Ученик: {child_name}\n"
            f"Инвайт-ссылка отправлена родителю автоматически.",
            reply_markup=manager_kb.back_to_main_keyboard()
        )
    except Exception:
        await callback.message.edit_text(
            f"✅ Одобрено, но не удалось отправить ссылку (родитель мог заблокировать бота).\n\n"
            f"Ссылка для ручной отправки:\n<code>{invite_link}</code>",
            reply_markup=manager_kb.back_to_main_keyboard(),
            parse_mode="HTML"
        )
    await callback.answer()
    logger.info(f"Заявка на пробный урок одобрена: {child_name}")


@router.callback_query(F.data.startswith("mgr:trial_reject:"))
async def trial_reject(callback: CallbackQuery) -> None:
    """Менеджер отклоняет заявку."""
    trial_id = int(callback.data.split(":")[2])

    async with get_session() as session:
        trial = await crud.get_trial_request_by_id(session, trial_id)
        if not trial or trial.status != "pending":
            await callback.answer("Заявка уже обработана.", show_alert=True)
            return
        await crud.update_trial_status(session, trial_id, "rejected")
        parent_tg_id = trial.telegram_id
        child_name = trial.child_name

    try:
        await callback.bot.send_message(
            parent_tg_id,
            "К сожалению, на данный момент мы не можем принять вашу заявку. "
            "Мы свяжемся с вами как только появится свободное место. 🙏"
        )
    except Exception:
        pass

    await callback.message.edit_text(
        f"❌ Заявка {child_name} отклонена. Родитель уведомлён.",
        reply_markup=manager_kb.back_to_main_keyboard()
    )
    await callback.answer()


# ──────────────────────────────────────────────
# ОТЧЁТ О ПРОГРЕССЕ УЧЕНИКА
# ──────────────────────────────────────────────

@router.callback_query(F.data.startswith("mgr:write_report:"))
async def write_report_start(callback: CallbackQuery, state: FSMContext) -> None:
    """Менеджер нажал 'Написать отчёт' — запрашиваем текст."""
    parts = callback.data.split(":")
    student_id = int(parts[2])
    parent_tg_id = int(parts[3])

    await state.update_data(
        report_student_id=student_id,
        report_parent_tg_id=parent_tg_id,
        _question_msg_id=callback.message.message_id,
    )
    await state.set_state(WriteReportStates.waiting_report_text)

    async with get_session() as session:
        student = await crud.get_student_by_id(session, student_id)
        student_name = student.name if student else "ученик"

    await callback.message.edit_text(
        f"✍️ Написать отчёт о прогрессе <b>{student_name}</b>\n\n"
        f"Опишите что прошли, как успевает, что получается хорошо и над чем работать:",
        reply_markup=manager_kb.only_back_keyboard("mgr:main"),
        parse_mode="HTML"
    )
    await callback.answer()


@router.message(WriteReportStates.waiting_report_text)
async def write_report_send(message: Message, state: FSMContext) -> None:
    """Отправляем готовый отчёт родителю."""
    data = await state.get_data()
    parent_tg_id = data["report_parent_tg_id"]
    student_id = data["report_student_id"]

    async with get_session() as session:
        student = await crud.get_student_by_id(session, student_id)
        student_name = student.name if student else "ученик"

    question_msg_id = data.get("_question_msg_id")
    await _delete_prompts(message.bot, message.chat.id, state)
    await state.clear()

    # Удаляем вопрос-сообщение (было отредактировано через edit_text)
    if question_msg_id:
        try:
            await message.bot.delete_message(message.chat.id, question_msg_id)
        except Exception:
            pass

    try:
        await message.bot.send_message(
            parent_tg_id,
            f"📝 <b>Отчёт о прогрессе — {student_name}</b>\n\n"
            f"{message.text}",
            parse_mode="HTML"
        )
        await message.answer(
            f"✅ Отчёт отправлен родителю {student_name}!",
            reply_markup=manager_kb.back_to_main_keyboard()
        )
    except Exception:
        await message.answer(
            f"❌ Не удалось отправить отчёт. Возможно родитель заблокировал бота.",
            reply_markup=manager_kb.back_to_main_keyboard()
        )
    logger.info(f"Отчёт о прогрессе отправлен: ученик id={student_id}")


# ──────────────────────────────────────────────
# РАССЫЛКА
# ──────────────────────────────────────────────

@router.callback_query(F.data == "mgr:broadcast")
async def broadcast_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(_question_msg_id=callback.message.message_id)
    await state.set_state(BroadcastStates.waiting_message)
    await callback.message.edit_text(
        "📢 Введите сообщение для рассылки всем родителям:"
    )
    await callback.answer()


@router.message(BroadcastStates.waiting_message)
async def broadcast_preview(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    # Удаляем вопрос "Введите сообщение"
    if q_id := data.get("_question_msg_id"):
        try:
            await message.bot.delete_message(message.chat.id, q_id)
        except Exception:
            pass
    await state.update_data(broadcast_text=message.text.strip())
    await state.set_state(BroadcastStates.waiting_confirm)
    await message.answer(
        f"<b>Превью сообщения:</b>\n\n{message.text.strip()}\n\n"
        f"Отправить всем родителям?",
        reply_markup=manager_kb.confirm_broadcast_keyboard(),
        parse_mode="HTML"
    )


@router.callback_query(BroadcastStates.waiting_confirm, F.data == "mgr:broadcast_confirm")
async def broadcast_send(callback: CallbackQuery, state: FSMContext) -> None:
    """Отправляем сообщение всем активным родителям."""
    data = await state.get_data()
    text = data["broadcast_text"]

    if len(text) > 4096:
        await callback.answer("❌ Текст слишком длинный (максимум 4096 символов).", show_alert=True)
        return

    async with get_session() as session:
        parents = await crud.get_all_parents(session)

    sent = 0
    failed = 0
    for parent in parents:
        try:
            await callback.bot.send_message(parent.telegram_id, text)
            sent += 1
        except Exception:
            # Родитель мог заблокировать бота — не падаем, просто считаем
            failed += 1
        # Telegram разрешает ~30 сообщений/сек — выдерживаем лимит
        await asyncio.sleep(0.033)

    await state.clear()
    await callback.message.edit_text(
        f"✅ Рассылка завершена!\n\nОтправлено: {sent}\nОшибок: {failed}",
        reply_markup=manager_kb.back_to_main_keyboard()
    )
    await callback.answer()
    logger.info(f"Рассылка: отправлено {sent}, ошибок {failed}")


# ──────────────────────────────────────────────
# IT-НОВОСТИ — РАССЫЛКА ПОДПИСЧИКАМ
# ──────────────────────────────────────────────

@router.callback_query(F.data == "mgr:news_broadcast")
async def news_broadcast_start(callback: CallbackQuery, state: FSMContext) -> None:
    """Начало рассылки IT-новостей подписчикам."""
    async with get_session() as session:
        count = await crud.get_news_subscribers_count(session)

    if count == 0:
        await callback.answer("Нет подписчиков на IT-новости.", show_alert=True)
        return

    await state.update_data(_question_msg_id=callback.message.message_id)
    await state.set_state(NewsBroadcastStates.waiting_message)
    await callback.message.edit_text(
        f"📰 <b>Рассылка IT-новостей</b>\n\n"
        f"Подписчиков: <b>{count}</b>\n\n"
        f"Введите текст новости (можно с эмодзи, ссылками, форматированием):",
        reply_markup=manager_kb.only_back_keyboard("mgr:main"),
        parse_mode="HTML"
    )
    await callback.answer()


@router.message(NewsBroadcastStates.waiting_message)
async def news_broadcast_preview(message: Message, state: FSMContext) -> None:
    """Превью перед отправкой."""
    data = await state.get_data()
    if q_id := data.get("_question_msg_id"):
        try:
            await message.bot.delete_message(message.chat.id, q_id)
        except Exception:
            pass
    await state.update_data(news_text=message.text.strip())
    await state.set_state(NewsBroadcastStates.waiting_confirm)

    async with get_session() as session:
        count = await crud.get_news_subscribers_count(session)

    await message.answer(
        f"<b>Превью новости:</b>\n\n"
        f"📰 <b>IT-новости для вас и вашего ребёнка</b>\n\n"
        f"{message.text.strip()}\n\n"
        f"─────────────────\n"
        f"Отправить <b>{count}</b> подписчикам?",
        reply_markup=manager_kb.confirm_broadcast_keyboard(),
        parse_mode="HTML"
    )


@router.callback_query(NewsBroadcastStates.waiting_confirm, F.data == "mgr:broadcast_confirm")
async def news_broadcast_send(callback: CallbackQuery, state: FSMContext) -> None:
    """Отправляем новость всем подписчикам."""
    data = await state.get_data()
    text = (
        f"📰 <b>IT-новости для вас и вашего ребёнка</b>\n\n"
        f"{data['news_text']}"
    )

    if len(text) > 4096:
        await callback.answer("❌ Текст слишком длинный (максимум 4096 символов).", show_alert=True)
        return

    async with get_session() as session:
        subscribers = await crud.get_news_subscribers(session)

    sent = 0
    failed = 0
    for parent in subscribers:
        try:
            await callback.bot.send_message(parent.telegram_id, text, parse_mode="HTML")
            sent += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.033)

    await state.clear()
    await callback.message.edit_text(
        f"✅ IT-новость отправлена!\n\nПолучили: {sent}\nОшибок: {failed}",
        reply_markup=manager_kb.back_to_main_keyboard()
    )
    await callback.answer()
    logger.info(f"IT-новости разосланы: {sent} подписчиков, ошибок {failed}")


# ──────────────────────────────────────────────
# ОБРАТНАЯ СВЯЗЬ
# ──────────────────────────────────────────────

@router.callback_query(F.data == "mgr:feedback")
async def view_feedback(callback: CallbackQuery) -> None:
    """Непрочитанные сообщения от родителей — показываем с кнопкой ответа на каждое."""
    async with get_session() as session:
        # Намеренно НЕ помечаем прочитанными при открытии —
        # пометим только когда менеджер действительно ответит
        feedbacks = await crud.get_unread_feedback(session)

    if not feedbacks:
        await callback.message.edit_text(
            "💬 Непрочитанных сообщений нет.",
            reply_markup=manager_kb.back_to_main_keyboard()
        )
    else:
        lines = [f"💬 <b>Обратная связь ({len(feedbacks)})</b>\n"]
        for fb in feedbacks:
            dt = fb.created_at.strftime("%d.%m %H:%M")
            lines.append(f"<b>{fb.parent.name}</b> [{dt}]:\n{fb.message}\n")
        await callback.message.edit_text(
            "\n".join(lines),
            reply_markup=manager_kb.feedback_list_keyboard(feedbacks),
            parse_mode="HTML"
        )
    await callback.answer()


@router.callback_query(F.data.startswith("mgr:reply_feedback:"))
async def reply_feedback_start(callback: CallbackQuery, state: FSMContext) -> None:
    """Менеджер нажал ответить — запрашиваем текст ответа."""
    feedback_id = int(callback.data.split(":")[2])

    async with get_session() as session:
        from sqlalchemy import select as sa_select
        from bot.database.models import Feedback
        from sqlalchemy.orm import selectinload as sil
        result = await session.execute(
            sa_select(Feedback)
            .options(sil(Feedback.parent))
            .where(Feedback.id == feedback_id)
        )
        feedback = result.scalar_one_or_none()

        if not feedback:
            await callback.answer("Сообщение не найдено.", show_alert=True)
            return

        # Помечаем прочитанным в той же сессии — одна атомарная транзакция
        await crud.mark_feedback_read(session, feedback_id)

    await state.update_data(
        reply_parent_tg_id=feedback.parent.telegram_id,
        reply_parent_name=feedback.parent.name,
        _question_msg_id=callback.message.message_id,
    )
    await state.set_state(ReplyToFeedbackStates.waiting_reply_text)
    await callback.message.edit_text(
        f"↩️ Ответ родителю <b>{feedback.parent.name}</b>\n\n"
        f"Сообщение родителя:\n<i>{feedback.message}</i>\n\n"
        f"Введите ваш ответ:",
        reply_markup=manager_kb.only_back_keyboard("mgr:feedback"),
        parse_mode="HTML"
    )
    await callback.answer()


@router.message(ReplyToFeedbackStates.waiting_reply_text)
async def reply_feedback_send(message: Message, state: FSMContext) -> None:
    """Отправляем ответ родителю."""
    data = await state.get_data()
    parent_tg_id = data["reply_parent_tg_id"]
    parent_name = data["reply_parent_name"]

    if q_id := data.get("_question_msg_id"):
        try:
            await message.bot.delete_message(message.chat.id, q_id)
        except Exception:
            pass

    await state.clear()

    try:
        await message.bot.send_message(
            parent_tg_id,
            f"💬 <b>Ответ от школы</b>\n\n{message.text}",
            parse_mode="HTML"
        )
        await message.answer(
            f"✅ Ответ отправлен родителю {parent_name}.",
            reply_markup=manager_kb.back_to_main_keyboard()
        )
    except Exception:
        await message.answer(
            "❌ Не удалось отправить ответ. Возможно родитель заблокировал бота.",
            reply_markup=manager_kb.back_to_main_keyboard()
        )
    logger.info(f"Ответ на обратную связь отправлен родителю {parent_name}")


# ──────────────────────────────────────────────
# АНАЛИТИКА
# ──────────────────────────────────────────────

# ──────────────────────────────────────────────
# РЕДАКТИРОВАНИЕ УЧЕНИКА
# ──────────────────────────────────────────────

@router.callback_query(F.data.startswith("mgr:edit_student:"))
async def edit_student_start(callback: CallbackQuery) -> None:
    """Показываем меню выбора поля для редактирования."""
    student_id = int(callback.data.split(":")[2])

    async with get_session() as session:
        student = await crud.get_student_by_id(session, student_id)

    if not student:
        await callback.answer("Ученик не найден.", show_alert=True)
        return

    ptype = "по факту урока 🔄" if student.payment_type == "postpaid" else "пакет уроков 💳"
    await callback.message.edit_text(
        f"✏️ <b>Редактировать ученика</b>\n\n"
        f"Имя: {student.name}\n"
        f"Возраст: {student.age or '—'}\n"
        f"Тип оплаты: {ptype}\n\n"
        f"Выберите что изменить:",
        reply_markup=manager_kb.edit_student_keyboard(student_id),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("mgr:edit_field:"))
async def edit_student_field(callback: CallbackQuery, state: FSMContext) -> None:
    """Запрашиваем новое значение поля."""
    parts = callback.data.split(":")
    student_id = int(parts[2])
    field = parts[3]

    prompts = {
        "name": "Введите новое имя ученика:",
        "age": "Введите новый возраст (число):",
        "payment_type": None,  # Особый случай — показываем клавиатуру
    }

    await state.update_data(
        edit_student_id=student_id,
        edit_field=field,
        _question_msg_id=callback.message.message_id,
    )

    if field == "payment_type":
        await state.set_state(EditStudentStates.waiting_value)
        await callback.message.edit_text(
            "💳 Выберите новый тип оплаты:",
            reply_markup=manager_kb.payment_type_keyboard()
        )
    else:
        await state.set_state(EditStudentStates.waiting_value)
        await callback.message.edit_text(
            prompts[field],
            reply_markup=manager_kb.only_back_keyboard(f"mgr:edit_student:{student_id}")
        )
    await callback.answer()


@router.callback_query(EditStudentStates.waiting_value, F.data.startswith("mgr:ptype:"))
async def edit_student_payment_type(callback: CallbackQuery, state: FSMContext) -> None:
    """Сохраняем новый тип оплаты."""
    payment_type = callback.data.split(":")[2]
    data = await state.get_data()
    student_id = data["edit_student_id"]

    async with get_session() as session:
        student = await crud.update_student_field(session, student_id, "payment_type", payment_type)
        student_name = student.name if student else "—"

    await state.clear()
    ptype_label = "по факту урока 🔄" if payment_type == "postpaid" else "пакет уроков 💳"
    await callback.message.edit_text(
        f"✅ Тип оплаты обновлён!\n\n"
        f"Ученик: {student_name}\n"
        f"Тип оплаты: {ptype_label}",
        reply_markup=manager_kb.student_profile_keyboard(student_id)
    )
    await callback.answer()
    logger.info(f"Тип оплаты ученика id={student_id} изменён на {payment_type}")


@router.message(EditStudentStates.waiting_value)
async def edit_student_value(message: Message, state: FSMContext) -> None:
    """Сохраняем новое значение текстового поля ученика."""
    data = await state.get_data()
    student_id = data["edit_student_id"]
    field = data["edit_field"]

    # Тип оплаты меняется только через кнопки — текстовый ввод невозможен
    if field == "payment_type":
        await message.answer(
            "Выберите тип оплаты кнопкой:",
            reply_markup=manager_kb.payment_type_keyboard()
        )
        return

    if field == "age":
        try:
            value = int(message.text.strip())
        except ValueError:
            await message.answer(
                "Введите число:",
                reply_markup=manager_kb.only_back_keyboard(f"mgr:edit_student:{student_id}")
            )
            return
    else:
        value = message.text.strip()

    if q_id := data.get("_question_msg_id"):
        try:
            await message.bot.delete_message(message.chat.id, q_id)
        except Exception:
            pass

    async with get_session() as session:
        student = await crud.update_student_field(session, student_id, field, value)
        student_name = student.name if student else "—"

    await state.clear()
    field_labels = {"name": "Имя", "age": "Возраст"}
    await message.answer(
        f"✅ {field_labels.get(field, field)} обновлено!\n\nУченик: {student_name}",
        reply_markup=manager_kb.student_profile_keyboard(student_id)
    )
    logger.info(f"Поле {field} ученика id={student_id} обновлено: {value}")


# ──────────────────────────────────────────────
# ПЕРЕНОС УРОКА
# ──────────────────────────────────────────────

@router.callback_query(F.data == "mgr:reschedule:choose")
async def reschedule_choose_lesson(callback: CallbackQuery, state: FSMContext) -> None:
    """Показываем список ближайших уроков для переноса."""
    async with get_session() as session:
        lessons = await crud.get_all_upcoming_lessons(session)

    if not lessons:
        await callback.answer("Запланированных уроков нет.", show_alert=True)
        return

    await state.set_state(RescheduleLessonStates.waiting_lesson)
    await callback.message.edit_text(
        "Выберите урок для переноса:",
        reply_markup=manager_kb.reschedule_lessons_keyboard(lessons)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("mgr:reschedule_lesson:"))
async def reschedule_lesson_date(callback: CallbackQuery, state: FSMContext) -> None:
    """Урок выбран — запрашиваем новую дату."""
    lesson_id = int(callback.data.split(":")[2])
    await state.update_data(reschedule_lesson_id=lesson_id)
    await state.set_state(RescheduleLessonStates.waiting_date)
    await callback.message.edit_text(
        "Введите новую дату урока в формате ДД.ММ.ГГГГ\n\nПример: 25.05.2026",
        reply_markup=manager_kb.only_back_keyboard("mgr:schedule")
    )
    await callback.answer()


@router.message(RescheduleLessonStates.waiting_date)
async def reschedule_lesson_get_date(message: Message, state: FSMContext) -> None:
    try:
        date = datetime.strptime(message.text.strip(), "%d.%m.%Y")
    except ValueError:
        await message.answer("Неверный формат. Введите дату как ДД.ММ.ГГГГ\nПример: 25.05.2026")
        return

    if date.date() < local_now().date():
        await message.answer(
            "❌ Нельзя перенести урок в прошлое. Введите будущую дату:",
            reply_markup=manager_kb.only_back_keyboard("mgr:schedule")
        )
        return

    await state.update_data(reschedule_date=date)
    await state.set_state(RescheduleLessonStates.waiting_time)
    sent = await message.answer(
        "Введите новое время урока в формате ЧЧ:ММ\nПример: 16:00",
        reply_markup=manager_kb.only_back_keyboard("mgr:schedule")
    )
    await _save_prompt(state, sent)


@router.message(RescheduleLessonStates.waiting_time)
async def reschedule_lesson_execute(message: Message, state: FSMContext) -> None:
    """Сохраняем новое время, отменяем старые напоминания и планируем новые."""
    try:
        time = datetime.strptime(message.text.strip(), "%H:%M")
    except ValueError:
        await message.answer("Неверный формат. Введите время как ЧЧ:ММ\nПример: 16:00")
        return

    data = await state.get_data()
    lesson_id = data["reschedule_lesson_id"]
    date: datetime = data["reschedule_date"]
    new_scheduled_at = date.replace(hour=time.hour, minute=time.minute, second=0, microsecond=0)

    async with get_session() as session:
        lesson = await crud.reschedule_lesson(session, lesson_id, new_scheduled_at)
        if not lesson:
            await message.answer(
                "❌ Урок не найден или уже завершён.",
                reply_markup=manager_kb.back_to_main_keyboard()
            )
            await state.clear()
            return
        student_name = lesson.student.name
        parent = lesson.student.parent
        parent_tg_id = parent.telegram_id if parent else None

    from bot.scheduler.jobs import cancel_lesson_reminders, schedule_lesson_reminders
    cancel_lesson_reminders(lesson_id)
    await schedule_lesson_reminders(lesson_id, new_scheduled_at)

    await _delete_prompts(message.bot, message.chat.id, state)
    await state.clear()

    await message.answer(
        f"✅ Урок перенесён!\n\n"
        f"Ученик: {student_name}\n"
        f"Новое время: {new_scheduled_at.strftime('%d.%m.%Y %H:%M')}\n\n"
        f"Напоминания обновлены автоматически.",
        reply_markup=manager_kb.back_to_main_keyboard()
    )

    if parent_tg_id:
        from bot.services.notifications import notify_parent_lesson_rescheduled
        await notify_parent_lesson_rescheduled(
            parent_tg_id, student_name, new_scheduled_at.strftime("%d.%m.%Y %H:%M")
        )

    logger.info(f"Урок id={lesson_id} перенесён: ученик={student_name}, новое время={new_scheduled_at}")


# ──────────────────────────────────────────────
# ПОВТОРЯЮЩЕЕСЯ РАСПИСАНИЕ
# ──────────────────────────────────────────────

@router.callback_query(F.data.startswith("mgr:recurring:"))
async def recurring_schedule_view(callback: CallbackQuery) -> None:
    """Просмотр повторяющихся расписаний ученика."""
    student_id = int(callback.data.split(":")[2])
    async with get_session() as session:
        student = await crud.get_student_by_id(session, student_id)
        if not student:
            await callback.answer("Ученик не найден.", show_alert=True)
            return
        schedules = await crud.get_recurring_schedules_by_student(session, student_id)

    if schedules:
        text = (
            f"📆 <b>Повторяющееся расписание</b>\n"
            f"Ученик: <b>{student.name}</b>\n\n"
            f"Нажмите на слот чтобы удалить:"
        )
    else:
        text = (
            f"📆 <b>Повторяющееся расписание</b>\n"
            f"Ученик: <b>{student.name}</b>\n\n"
            f"Расписание не настроено. Добавьте первый слот:"
        )

    await callback.message.edit_text(
        text,
        reply_markup=manager_kb.recurring_schedule_keyboard(schedules, student_id),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("mgr:add_recurring:"))
async def add_recurring_start(callback: CallbackQuery, state: FSMContext) -> None:
    """Начало добавления повторяющегося слота — выбор дня недели."""
    student_id = int(callback.data.split(":")[2])
    await state.set_state(AddRecurringScheduleStates.waiting_day)
    await state.update_data(student_id=student_id)
    msg = await callback.message.edit_text(
        "Выберите день недели:",
        reply_markup=manager_kb.day_of_week_keyboard(student_id),
    )
    await _save_prompt(state, msg)
    await callback.answer()


@router.callback_query(AddRecurringScheduleStates.waiting_day, F.data.startswith("mgr:rec_day:"))
async def add_recurring_day_selected(callback: CallbackQuery, state: FSMContext) -> None:
    """Менеджер выбрал день — просим ввести время."""
    parts = callback.data.split(":")
    student_id = int(parts[2])
    day_of_week = int(parts[3])
    await state.update_data(day_of_week=day_of_week)
    await state.set_state(AddRecurringScheduleStates.waiting_time)
    msg = await callback.message.edit_text(
        "Введите время урока в формате ЧЧ:ММ\n\nПример: 15:00",
        reply_markup=manager_kb.only_back_keyboard(f"mgr:recurring:{student_id}"),
    )
    await _save_prompt(state, msg)
    await callback.answer()


@router.message(AddRecurringScheduleStates.waiting_time)
async def add_recurring_time_entered(message: Message, state: FSMContext, bot: Bot) -> None:
    """Получили время — создаём шаблон расписания."""
    text = message.text.strip()
    try:
        t = datetime.strptime(text, "%H:%M")
    except ValueError:
        msg = await message.answer(
            "Неверный формат времени. Введите в формате ЧЧ:ММ, например: 15:00",
            reply_markup=manager_kb.only_back_keyboard("mgr:main"),
        )
        await _save_prompt(state, msg)
        return

    data = await state.get_data()
    student_id = data["student_id"]
    day_of_week = data["day_of_week"]

    await _delete_prompts(bot, message.chat.id, state)
    await message.delete()

    async with get_session() as session:
        student = await crud.get_student_by_id(session, student_id)
        if not student:
            await state.clear()
            await bot.send_message(message.chat.id, "❌ Ученик не найден. Операция отменена.")
            return
        await crud.create_recurring_schedule(session, student_id, day_of_week, t.hour, t.minute)

    from bot.keyboards.manager_kb import _DAYS_RU
    day_name = _DAYS_RU[day_of_week]
    await state.clear()

    async with get_session() as session:
        schedules = await crud.get_recurring_schedules_by_student(session, student_id)

    await bot.send_message(
        message.chat.id,
        f"✅ <b>Расписание добавлено!</b>\n\n"
        f"Ученик: <b>{student.name}</b>\n"
        f"День: <b>{day_name}</b>\n"
        f"Время: <b>{t.hour:02d}:{t.minute:02d}</b>\n\n"
        f"Уроки будут создаваться автоматически каждую ночь на 14 дней вперёд.",
        reply_markup=manager_kb.recurring_schedule_keyboard(schedules, student_id),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("mgr:del_recurring:"))
async def delete_recurring_schedule(callback: CallbackQuery) -> None:
    """Удаляем повторяющийся слот расписания."""
    parts = callback.data.split(":")
    schedule_id = int(parts[2])
    student_id = int(parts[3])

    async with get_session() as session:
        deleted = await crud.delete_recurring_schedule(session, schedule_id)
        schedules = await crud.get_recurring_schedules_by_student(session, student_id)
        student = await crud.get_student_by_id(session, student_id)

    if not deleted:
        await callback.answer("Слот не найден.", show_alert=True)
        return

    text = (
        f"📆 <b>Повторяющееся расписание</b>\n"
        f"Ученик: <b>{student.name}</b>\n\n"
        + ("Нажмите на слот чтобы удалить:" if schedules else "Расписание не настроено. Добавьте первый слот:")
    )
    await callback.message.edit_text(
        text,
        reply_markup=manager_kb.recurring_schedule_keyboard(schedules, student_id),
        parse_mode="HTML",
    )
    await callback.answer("Слот удалён ✅")


# ──────────────────────────────────────────────
# АНАЛИТИКА
# ──────────────────────────────────────────────

@router.callback_query(F.data == "mgr:analytics")
async def analytics(callback: CallbackQuery) -> None:
    """Базовая аналитика по школе."""
    async with get_session() as session:
        students = await crud.get_all_students(session)
        low_balance = await crud.get_students_with_low_balance(session)
        postpaid_debt = await crud.get_postpaid_students_with_debt(session)

    total = len(students)
    prepaid = [s for s in students if s.payment_type != "postpaid"]
    postpaid = [s for s in students if s.payment_type == "postpaid"]
    zero_balance = [s for s in prepaid if s.lessons_balance == 0]
    total_completed = sum(s.lessons_completed for s in students)

    text = (
        f"📊 <b>Аналитика</b>\n\n"
        f"Всего учеников: <b>{total}</b> "
        f"(пакет: {len(prepaid)}, по факту: {len(postpaid)})\n"
        f"Всего уроков проведено: <b>{total_completed}</b>\n"
    )

    if zero_balance:
        text += f"\n🔴 Нет уроков ({len(zero_balance)}):\n"
        for s in zero_balance:
            text += f"• {s.name}\n"

    if low_balance:
        text += f"\n🟡 Заканчиваются уроки ({len(low_balance)}):\n"
        for s in low_balance:
            text += f"• {s.name} — {s.lessons_balance} ур.\n"

    if postpaid_debt:
        text += f"\n⚠️ Не оплачено по факту ({len(postpaid_debt)}):\n"
        for s, debt in postpaid_debt:
            text += f"• {s.name} — {debt} ур.\n"

    await callback.message.edit_text(
        text,
        reply_markup=manager_kb.back_to_main_keyboard(),
        parse_mode="HTML"
    )
    await callback.answer()
