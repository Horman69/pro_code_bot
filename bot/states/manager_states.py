from aiogram.fsm.state import State, StatesGroup


class AddStudentStates(StatesGroup):
    """Добавление нового ученика менеджером."""
    waiting_name = State()
    waiting_age = State()
    waiting_payment_type = State()


class AddLessonStates(StatesGroup):
    """Добавление урока вручную."""
    waiting_student = State()
    waiting_date = State()
    waiting_time = State()


class AddPaymentStates(StatesGroup):
    """Приём оплаты — пополнение баланса ученика."""
    waiting_student = State()
    waiting_lessons_count = State()
    waiting_amount = State()


class CancelLessonStates(StatesGroup):
    """Отмена урока менеджером."""
    waiting_lesson = State()
    waiting_reason = State()


class BroadcastStates(StatesGroup):
    """Рассылка сообщения всем родителям."""
    waiting_message = State()
    waiting_confirm = State()


class WriteReportStates(StatesGroup):
    """Написание отчёта о прогрессе ученика по запросу родителя."""
    waiting_report_text = State()


class NewsBroadcastStates(StatesGroup):
    """Рассылка IT-новостей подписчикам."""
    waiting_message = State()
    waiting_confirm = State()


class ReplyToFeedbackStates(StatesGroup):
    """Ответ менеджера на сообщение обратной связи от родителя."""
    waiting_reply_text = State()


class EditStudentStates(StatesGroup):
    """Редактирование данных ученика менеджером."""
    waiting_field = State()
    waiting_value = State()


class RescheduleLessonStates(StatesGroup):
    """Перенос урока на другое время."""
    waiting_student = State()
    waiting_lesson = State()
    waiting_date = State()
    waiting_time = State()


class AddRecurringScheduleStates(StatesGroup):
    """Добавление повторяющегося расписания для ученика."""
    waiting_day = State()
    waiting_time = State()
