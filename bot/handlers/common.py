import logging
from aiogram import F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot import config
from bot.database import crud
from bot.database.session import get_session
from bot.keyboards import manager_kb, parent_kb
from bot.states.parent_states import RegisterParentStates, TrialSignupStates

router = Router()
logger = logging.getLogger(__name__)


@router.message(Command("info"))
async def cmd_info(message: Message) -> None:
    """Информация о возможностях бота — для родителей и менеджера."""
    if message.from_user.id == config.MANAGER_TELEGRAM_ID:
        text = (
            "📖 <b>Возможности вашей панели управления</b>\n\n"

            "👥 <b>Ученики</b>\n"
            "Добавляйте учеников, отслеживайте баланс уроков и "
            "генерируйте инвайт-ссылки для родителей.\n\n"

            "📅 <b>Расписание</b>\n"
            "Добавляйте уроки — бот автоматически разошлёт напоминания "
            "родителям за 24 часа и за 1 час до занятия.\n\n"

            "✅ <b>Учёт уроков</b>\n"
            "После урока нажмите «Урок проведён» — баланс ученика "
            "спишется автоматически, родитель получит уведомление.\n\n"

            "💰 <b>Оплаты</b>\n"
            "Фиксируйте оплаты и пополняйте баланс уроков. "
            "Бот сам уведомит родителя о зачислении.\n\n"

            "📊 <b>Аналитика</b>\n"
            "Смотрите кто скоро закончит уроки, общую статистику "
            "и задолженности.\n\n"

            "📰 <b>IT-новости</b>\n"
            "Отправляйте полезный контент родителям которые подписались — "
            "укрепляет доверие и лояльность.\n\n"

            "🎁 <b>Реферальная программа</b>\n"
            "Родители приглашают друзей и получают бонусы автоматически. "
            "Вы видите все выплаты в разделе «Оплаты».\n\n"

            "📢 <b>Рассылка</b>\n"
            "Отправьте сообщение всем родителям сразу — "
            "для объявлений, акций, важных новостей."
        )
    else:
        text = (
            "📖 <b>Что умеет этот бот?</b>\n\n"

            "⏰ <b>Напоминания об уроках</b>\n"
            "Бот напомнит вам за 24 часа и за 1 час до занятия. "
            "Можете подтвердить или отменить урок прямо в боте.\n\n"

            "📊 <b>Учёт уроков</b>\n"
            "В личном кабинете всегда видно сколько уроков осталось, "
            "история занятий и расписание на ближайшее время.\n\n"

            "📝 <b>Отчёт о прогрессе</b>\n"
            "Запросите у преподавателя отчёт об успехах ребёнка — "
            "что прошли, что получается, над чем работать.\n\n"

            "💬 <b>Обратная связь</b>\n"
            "Напишите вопрос или пожелание прямо через бот — "
            "ответ придёт сюда же.\n\n"

            "🎁 <b>Реферальная программа</b>\n"
            "Пригласите друга — получите бонусные уроки или деньги на карту. "
            "Чем дольше друг занимается, тем больше ваш бонус.\n\n"

            "📰 <b>IT-новости</b>\n"
            "Подпишитесь и получайте актуальные новости из мира технологий — "
            "без спама, только полезное.\n\n"

            "💳 <b>Оплата</b>\n"
            "Реквизиты для оплаты доступны в разделе «Личный кабинет».\n\n"

            "─────────────────────\n"
            "📬 <b>Куда попадает заявка на пробный урок?</b>\n"
            "Ваша заявка сразу поступает преподавателю. "
            "Он свяжется с вами в течение нескольких часов для согласования даты.\n\n"

            "📞 <b>Как связаться напрямую?</b>\n"
            "Напишите через раздел «Обратная связь» — это самый быстрый способ."
        )

    await message.answer(text, parse_mode="HTML")


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, command: CommandObject) -> None:
    """
    Точка входа для всех пользователей.
    Менеджер → панель управления.
    Родитель с инвайт-токеном → регистрация.
    Уже зарегистрированный родитель → главное меню.
    """
    await state.clear()
    telegram_id = message.from_user.id

    # Менеджер — отдельный флоу
    if telegram_id == config.MANAGER_TELEGRAM_ID:
        await message.answer(
            "👋 Привет! Это панель управления школой.",
            reply_markup=manager_kb.manager_main_menu()
        )
        return

    # command.args — правильный способ получить аргумент после /start в aiogram 3
    deep_arg = command.args  # None если аргумента нет
    referral_code = deep_arg[4:] if deep_arg and deep_arg.startswith("ref_") else None
    invite_token = deep_arg if deep_arg and not deep_arg.startswith("ref_") else None

    async with get_session() as session:
        parent = await crud.get_parent_by_telegram_id(session, telegram_id)

        if parent:
            # Родитель уже есть — проверяем инвайт-токен (добавление нового ученика)
            if invite_token:
                student = await crud.get_student_by_invite_token(session, invite_token)
                if student and student.parent_id is None:
                    await crud.link_parent_to_student(session, student, parent)
                    students = await crud.get_students_by_parent(session, parent.id)
                    await message.answer(
                        f"✅ Ученик <b>{student.name}</b> привязан к вашему аккаунту!",
                        reply_markup=parent_kb.parent_main_menu(students, parent.is_news_subscriber),
                        parse_mode="HTML"
                    )
                    return

            # Реферальная ссылка для уже зарегистрированного — просто меню
            students = await crud.get_students_by_parent(session, parent.id)
            if not students:
                from aiogram.types import InlineKeyboardButton
                from aiogram.utils.keyboard import InlineKeyboardBuilder
                builder = InlineKeyboardBuilder()
                builder.row(InlineKeyboardButton(
                    text="✍️ Написать менеджеру",
                    url=f"https://t.me/{config.MANAGER_USERNAME}"
                ))
                await message.answer(
                    "👋 Добро пожаловать! Ваш аккаунт привязан, "
                    "но ученики пока не добавлены.\n\n"
                    "Напишите менеджеру — он всё настроит:",
                    reply_markup=builder.as_markup()
                )
                return
            await message.answer(
                f"👋 Привет, {parent.name}!",
                reply_markup=parent_kb.parent_main_menu(students, parent.is_news_subscriber)
            )
            return

        # Новый пользователь — сохраняем реферальный код если пришёл по ссылке
        if referral_code:
            await state.update_data(referral_code=referral_code)
            # Уведомляем менеджера о переходе по реферальной ссылке
            referrer = await crud.get_parent_by_referral_code(session, referral_code)
            if referrer:
                visitor_name = message.from_user.full_name or "Без имени"
                from bot.services.notifications import notify_manager_referral_visit
                await notify_manager_referral_visit(visitor_name, referrer.name)

        # Новый пользователь без инвайт-токена — показываем лендинг школы
        if not invite_token:
            await message.answer(
                "👋 Привет! Добро пожаловать в школу программирования!\n\n"
                "Мы обучаем детей и подростков <b>от 7 лет</b> IT-направлениям — "
                "индивидуально, в удобном темпе.\n\n"
                "🎮 Роблокс (Lua)\n"
                "🎮 Unity (разработка игр)\n"
                "🖨 3D моделирование\n"
                "🖥 Компьютерная грамотность\n"
                "🤖 Искусственный интеллект\n"
                "🐍 Python, веб и другое\n\n"
                "🎓 Индивидуальные занятия 1 на 1\n"
                "⏱ Гибкое расписание\n"
                "💻 Практика с первого урока\n\n"
                "Что хотите сделать?",
                reply_markup=parent_kb.welcome_keyboard(),
                parse_mode="HTML"
            )
            return

        # Проверяем инвайт-токен
        student = await crud.get_student_by_invite_token(session, invite_token)
        if not student:
            await message.answer(
                "❌ Ссылка недействительна или уже была использована.\n"
                "Запросите новую ссылку у преподавателя."
            )
            return

        # Сохраняем токен и имя ученика в FSM — пригодятся при регистрации
        await state.update_data(invite_token=invite_token, student_name=student.name)
        await state.set_state(RegisterParentStates.waiting_name)
        await message.answer(
            f"👋 Добро пожаловать!\n\n"
            f"Вы регистрируетесь как родитель ученика <b>{student.name}</b>.\n\n"
            f"Как вас зовут? (Имя и Фамилия)",
            parse_mode="HTML"
        )


@router.message(RegisterParentStates.waiting_name)
async def register_name(message: Message, state: FSMContext) -> None:
    """Получаем имя родителя при регистрации."""
    name = message.text.strip()
    if len(name) < 2:
        await message.answer("Пожалуйста, введите настоящее имя.")
        return

    await state.update_data(parent_name=name)
    await state.set_state(RegisterParentStates.waiting_phone)
    await message.answer(
        f"Отлично, {name.split()[0]}! 📱\n\n"
        "Введите ваш номер телефона:",
        reply_markup=parent_kb.skip_back_keyboard("par:main")
    )


@router.callback_query(RegisterParentStates.waiting_phone, F.data == "action:skip")
async def register_phone_skip(callback: CallbackQuery, state: FSMContext) -> None:
    """Пропускаем телефон."""
    await _finish_registration(callback.message, state, phone=None)
    await callback.answer()


@router.message(RegisterParentStates.waiting_phone)
async def register_phone(message: Message, state: FSMContext) -> None:
    """Получаем телефон и завершаем регистрацию."""
    await _finish_registration(message, state, phone=message.text.strip())


async def _finish_registration(message, state: FSMContext, phone: str | None) -> None:
    """Общая логика завершения регистрации — вызывается из текста и из кнопки пропуска."""
    data = await state.get_data()
    invite_token = data["invite_token"]
    parent_name = data["parent_name"]
    referral_code = data.get("referral_code")
    telegram_id = message.chat.id  # работает и для Message и для CallbackQuery.message

    async with get_session() as session:
        student = await crud.get_student_by_invite_token(session, invite_token)
        if not student:
            await state.clear()
            await message.answer("❌ Ссылка уже недействительна. Запросите новую у преподавателя.")
            return

        existing = await crud.get_parent_by_telegram_id(session, telegram_id)
        if existing:
            parent = existing
        else:
            # Если referral_code нет в FSM — ищем в TrialRequest (FSM был очищен после заявки)
            if not referral_code:
                trial = await crud.get_trial_by_telegram_id(session, telegram_id)
                if trial:
                    referral_code = trial.referral_code

            referrer_id = None
            if referral_code:
                referrer = await crud.get_parent_by_referral_code(session, referral_code)
                if referrer and referrer.telegram_id != telegram_id:
                    referrer_id = referrer.id

            parent = await crud.create_parent(
                session,
                telegram_id=telegram_id,
                name=parent_name,
                phone=phone,
                referred_by_id=referrer_id,
            )

            # Создаём реферальную связь чтобы milestone-чекер мог начислять бонусы
            if referrer_id:
                await crud.create_referral(session, referrer_id, parent.id)

        await crud.link_parent_to_student(session, student, parent)
        students = await crud.get_students_by_parent(session, parent.id)
        student_name = student.name
        is_subscribed = parent.is_news_subscriber  # сохраняем до закрытия сессии

    await state.clear()

    from bot.services.notifications import notify_manager_new_parent
    await notify_manager_new_parent(parent_name, student_name)

    await message.answer(
        f"✅ Регистрация завершена!\n\n"
        f"Теперь вы будете получать уведомления об уроках {student_name}.",
        reply_markup=parent_kb.parent_main_menu(students, is_subscribed)
    )
    logger.info(f"Новый родитель зарегистрирован: {parent_name} (tg_id={telegram_id})")


# ──────────────────────────────────────────────
# ЛЕНДИНГ — ЗАПИСЬ НА ПРОБНЫЙ УРОК
# ──────────────────────────────────────────────

@router.callback_query(F.data == "trial:about")
async def trial_about(callback: CallbackQuery) -> None:
    """Информация о школе для нового пользователя."""
    await callback.message.edit_text(
        "🏫 <b>О школе программирования</b>\n\n"
        "Обучаем детей и подростков <b>от 7 лет</b> IT-направлениям — "
        "индивидуально, онлайн, в удобное время.\n\n"
        "<b>Направления:</b>\n"
        "🎮 Роблокс (Lua) — создаём игры в Roblox Studio\n"
        "🎮 Unity — разработка игр на C#\n"
        "🖨 3D моделирование — Blender и другие инструменты\n"
        "🖥 Компьютерная грамотность — основы ПК и интернета\n"
        "🤖 Искусственный интеллект — как работает AI и нейросети\n"
        "🐍 Python — программирование и первые проекты\n"
        "🌐 Веб-разработка — HTML, CSS, JavaScript\n\n"
        "<b>Формат занятий:</b>\n"
        "• Онлайн, 1 на 1 с преподавателем\n"
        "• 1–2 раза в неделю по 60 минут\n"
        "• Гибкое расписание под вас\n"
        "• Стоимость: от 1 000 руб/урок\n\n"
        "Первый урок — <b>пробный и бесплатный</b>! "
        "Познакомимся, оценим уровень ребёнка и выберем направление 🎯",
        reply_markup=parent_kb.welcome_keyboard(),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data == "trial:cancel")
async def trial_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    """Отмена записи на пробный урок с любого шага."""
    await state.clear()
    await callback.message.edit_text(
        "Хорошо! Возвращайтесь когда будете готовы 😊\n\n"
        "Первый урок всегда бесплатный — мы вас ждём!",
        reply_markup=parent_kb.welcome_keyboard()
    )
    await callback.answer()


@router.callback_query(F.data == "trial:start")
async def trial_start(callback: CallbackQuery, state: FSMContext) -> None:
    """Начало записи на пробный урок."""
    await state.set_state(TrialSignupStates.waiting_parent_name)
    await callback.message.edit_text(
        "📝 <b>Запись на пробный урок</b>\n\n"
        "Шаг 1 из 4\n\n"
        "Как вас зовут? (Имя и Фамилия)",
        reply_markup=parent_kb.trial_cancel_keyboard(),
        parse_mode="HTML"
    )
    await callback.answer()


@router.message(TrialSignupStates.waiting_parent_name)
async def trial_parent_name(message: Message, state: FSMContext) -> None:
    name = message.text.strip()
    if len(name) < 2:
        await message.answer("Пожалуйста, введите ваше настоящее имя:")
        return
    await state.update_data(parent_name=name)
    await state.set_state(TrialSignupStates.waiting_child_name)
    await message.answer(
        "📝 <b>Запись на пробный урок</b>\n\n"
        "Шаг 2 из 4\n\n"
        "Как зовут вашего ребёнка?",
        parse_mode="HTML"
    )


@router.message(TrialSignupStates.waiting_child_name)
async def trial_child_name(message: Message, state: FSMContext) -> None:
    await state.update_data(child_name=message.text.strip())
    await state.set_state(TrialSignupStates.waiting_child_age)
    await message.answer(
        "📝 <b>Запись на пробный урок</b>\n\n"
        "Шаг 3 из 4\n\n"
        "Сколько лет ребёнку?",
        reply_markup=parent_kb.skip_back_keyboard("trial:start"),
        parse_mode="HTML"
    )


@router.callback_query(TrialSignupStates.waiting_child_age, F.data == "action:skip")
async def trial_child_age_skip(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(child_age=None)
    await _ask_trial_phone(callback.message, state)
    await callback.answer()


@router.message(TrialSignupStates.waiting_child_age)
async def trial_child_age(message: Message, state: FSMContext) -> None:
    try:
        age = int(message.text.strip())
    except ValueError:
        await message.answer(
            "Введите возраст числом:",
            reply_markup=parent_kb.skip_back_keyboard("trial:start")
        )
        return
    await state.update_data(child_age=age)
    await _ask_trial_phone(message, state)


async def _ask_trial_phone(message, state: FSMContext) -> None:
    await state.set_state(TrialSignupStates.waiting_phone)
    await message.answer(
        "📝 <b>Запись на пробный урок</b>\n\n"
        "Шаг 4 из 4\n\n"
        "Ваш номер телефона для связи:",
        reply_markup=parent_kb.skip_back_keyboard("trial:start"),
        parse_mode="HTML"
    )


@router.callback_query(TrialSignupStates.waiting_phone, F.data == "action:skip")
async def trial_phone_skip(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(phone=None)
    await _ask_trial_time(callback.message, state)
    await callback.answer()


@router.message(TrialSignupStates.waiting_phone)
async def trial_phone(message: Message, state: FSMContext) -> None:
    await state.update_data(phone=message.text.strip())
    await _ask_trial_time(message, state)


async def _ask_trial_time(message, state: FSMContext) -> None:
    await state.set_state(TrialSignupStates.waiting_preferred_time)
    await message.answer(
        "🕐 Какое время вам удобно для занятий?",
        reply_markup=parent_kb.trial_time_keyboard()
    )


@router.callback_query(TrialSignupStates.waiting_preferred_time, F.data.startswith("trial:time:"))
async def trial_time_selected(callback: CallbackQuery, state: FSMContext) -> None:
    """Получили время — сохраняем заявку и уведомляем менеджера."""
    preferred_time = callback.data.split("trial:time:")[1]
    await state.update_data(preferred_time=preferred_time)
    data = await state.get_data()

    async with get_session() as session:
        # Не создаём повторную заявку если предыдущая ещё не обработана
        existing = await crud.get_pending_trial_by_telegram_id(session, callback.from_user.id)
        if existing:
            await state.clear()
            await callback.message.edit_text(
                "⏳ Ваша заявка уже отправлена и ожидает рассмотрения.\n\n"
                "Мы свяжемся с вами в ближайшее время!"
            )
            await callback.answer()
            return

        trial = await crud.create_trial_request(
            session,
            telegram_id=callback.from_user.id,
            parent_name=data["parent_name"],
            child_name=data["child_name"],
            child_age=data.get("child_age"),
            phone=data.get("phone"),
            preferred_time=preferred_time,
            referral_code=data.get("referral_code"),  # сохраняем до очистки FSM
        )
        trial_id = trial.id

    await state.clear()

    await callback.message.edit_text(
        "✅ <b>Заявка отправлена!</b>\n\n"
        f"Спасибо, {data['parent_name'].split()[0]}!\n\n"
        "Мы свяжемся с вами в ближайшее время и согласуем удобную дату пробного урока. "
        "Пробный урок — бесплатный знакомственный! 🎓",
        parse_mode="HTML"
    )
    await callback.answer()

    # Уведомляем менеджера с кнопками Одобрить/Отклонить
    from bot.services.notifications import notify_manager_trial_request
    await notify_manager_trial_request(trial_id, data)
    logger.info(f"Новая заявка на пробный урок: {data['parent_name']}, ребёнок {data['child_name']}")
