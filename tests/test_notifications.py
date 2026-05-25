"""
Тесты сервиса уведомлений — проверяем форматирование сообщений,
обработку ошибок и кэш username бота.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ──────────────────────────────────────────────
# КЭШ USERNAME БОТА
# ──────────────────────────────────────────────

def test_set_and_get_bot_username():
    from bot.services.notifications import set_bot_username, get_bot_username
    set_bot_username("test_school_bot")
    assert get_bot_username() == "test_school_bot"


def test_get_bot_username_empty_by_default():
    from bot.services.notifications import set_bot_username, get_bot_username
    set_bot_username("")
    assert get_bot_username() == ""


# ──────────────────────────────────────────────
# ОТПРАВКА СООБЩЕНИЙ (_send)
# ──────────────────────────────────────────────

async def test_send_returns_true_on_success():
    from bot.services.notifications import _send, set_bot
    mock_bot = AsyncMock()
    mock_bot.send_message = AsyncMock(return_value=MagicMock())
    set_bot(mock_bot)
    result = await _send(12345, "Тест")
    assert result is True
    mock_bot.send_message.assert_called_once_with(12345, "Тест")


async def test_send_returns_false_on_forbidden_error():
    """Пользователь заблокировал бота — _send возвращает False, не падает."""
    from aiogram.exceptions import TelegramForbiddenError
    from bot.services.notifications import _send, set_bot
    mock_bot = AsyncMock()
    mock_bot.send_message.side_effect = TelegramForbiddenError(
        method=MagicMock(), message="Forbidden: bot was blocked by the user"
    )
    set_bot(mock_bot)
    result = await _send(12345, "Тест")
    assert result is False


async def test_send_returns_false_on_generic_error():
    """Любая другая ошибка — тоже False, не крэш."""
    from bot.services.notifications import _send, set_bot
    mock_bot = AsyncMock()
    mock_bot.send_message.side_effect = Exception("Network error")
    set_bot(mock_bot)
    result = await _send(12345, "Тест")
    assert result is False


# ──────────────────────────────────────────────
# УВЕДОМЛЕНИЯ РОДИТЕЛЮ
# ──────────────────────────────────────────────

async def test_notify_parent_lesson_completed_prepaid_shows_balance():
    """Для prepaid: показываем остаток уроков."""
    from bot.services.notifications import notify_parent_lesson_completed, set_bot
    mock_bot = AsyncMock()
    set_bot(mock_bot)
    await notify_parent_lesson_completed(111, "Миша", new_balance=3, payment_type="prepaid")
    call_args = mock_bot.send_message.call_args
    text = call_args[0][1]
    assert "3" in text
    assert "Миша" in text


async def test_notify_parent_lesson_completed_postpaid_no_balance():
    """Для postpaid: баланс не упоминается."""
    from bot.services.notifications import notify_parent_lesson_completed, set_bot
    mock_bot = AsyncMock()
    set_bot(mock_bot)
    await notify_parent_lesson_completed(111, "Миша", new_balance=0, payment_type="postpaid")
    call_args = mock_bot.send_message.call_args
    text = call_args[0][1]
    assert "Миша" in text
    assert "Остаток" not in text


async def test_notify_parent_low_balance_warning():
    """При остатке ≤ 2 — предупреждение о скором окончании."""
    from bot.services.notifications import notify_parent_lesson_completed, set_bot
    mock_bot = AsyncMock()
    set_bot(mock_bot)
    await notify_parent_lesson_completed(111, "Саша", new_balance=2, payment_type="prepaid")
    call_args = mock_bot.send_message.call_args
    text = call_args[0][1]
    assert "мало" in text.lower() or "2" in text


async def test_notify_parent_zero_balance_urgent_message():
    """При нулевом балансе — срочное сообщение."""
    from bot.services.notifications import notify_parent_lesson_completed, set_bot
    mock_bot = AsyncMock()
    set_bot(mock_bot)
    await notify_parent_lesson_completed(111, "Петя", new_balance=0, payment_type="prepaid")
    call_args = mock_bot.send_message.call_args
    text = call_args[0][1]
    assert "закончились" in text.lower() or "0" in text


async def test_notify_parent_reminder_24h_has_confirm_keyboard():
    """Напоминание за 24 часа содержит клавиатуру подтверждения."""
    from bot.services.notifications import notify_parent_reminder_24h, set_bot
    mock_bot = AsyncMock()
    set_bot(mock_bot)
    await notify_parent_reminder_24h(111, "Миша", "25.05 15:00", lesson_id=42)
    call_args = mock_bot.send_message.call_args
    kwargs = call_args[1]
    assert "reply_markup" in kwargs
    assert "Миша" in call_args[0][1]


# ──────────────────────────────────────────────
# УВЕДОМЛЕНИЯ МЕНЕДЖЕРУ
# ──────────────────────────────────────────────

async def test_notify_manager_bug_report_sends_to_manager():
    """Отчёт об ошибке — уходит менеджеру, содержит описание."""
    from bot import config
    from bot.services.notifications import notify_manager_bug_report, set_bot
    mock_bot = AsyncMock()
    set_bot(mock_bot)
    await notify_manager_bug_report(
        user_full_name="Иван Иванов",
        user_info="@ivan",
        description="Кнопка не работает"
    )
    call_args = mock_bot.send_message.call_args
    assert call_args[0][0] == config.MANAGER_TELEGRAM_ID
    text = call_args[0][1]
    assert "Иван Иванов" in text
    assert "@ivan" in text
    assert "Кнопка не работает" in text


async def test_notify_manager_new_parent():
    from bot import config
    from bot.services.notifications import notify_manager_new_parent, set_bot
    mock_bot = AsyncMock()
    set_bot(mock_bot)
    await notify_manager_new_parent("Ольга Смирнова", "Миша")
    call_args = mock_bot.send_message.call_args
    assert call_args[0][0] == config.MANAGER_TELEGRAM_ID
    text = call_args[0][1]
    assert "Ольга Смирнова" in text
    assert "Миша" in text


async def test_notify_manager_lesson_reminder_with_confirmed_status():
    from bot import config
    from bot.services.notifications import notify_manager_lesson_reminder, set_bot
    mock_bot = AsyncMock()
    set_bot(mock_bot)
    await notify_manager_lesson_reminder("Миша", "15:00", parent_confirmed=True)
    text = mock_bot.send_message.call_args[0][1]
    assert "✅" in text


async def test_notify_manager_lesson_reminder_with_no_answer():
    from bot.services.notifications import notify_manager_lesson_reminder, set_bot
    mock_bot = AsyncMock()
    set_bot(mock_bot)
    await notify_manager_lesson_reminder("Миша", "15:00", parent_confirmed=None)
    text = mock_bot.send_message.call_args[0][1]
    assert "❓" in text
