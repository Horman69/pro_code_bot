from aiogram.fsm.state import State, StatesGroup


class RegisterParentStates(StatesGroup):
    """Регистрация родителя при первом входе по инвайт-ссылке."""
    waiting_name = State()
    waiting_phone = State()


class FeedbackStates(StatesGroup):
    """Отправка обратной связи менеджеру."""
    waiting_message = State()


class CancelLessonStates(StatesGroup):
    """Родитель отменяет урок."""
    waiting_reason = State()


class TrialSignupStates(StatesGroup):
    """Запись на пробный урок — для новых пользователей."""
    waiting_parent_name = State()
    waiting_child_name = State()
    waiting_child_age = State()
    waiting_phone = State()
    waiting_preferred_time = State()


class BugReportStates(StatesGroup):
    """Пользователь сообщает об ошибке бота."""
    waiting_description = State()
