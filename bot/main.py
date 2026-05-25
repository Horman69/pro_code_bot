import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.types import ErrorEvent
from aiogram_sqlite_storage.sqlitestore import SQLStorage

from bot import config
from bot.database.session import init_db
from bot.handlers import common, manager, parent
from bot.scheduler.jobs import set_scheduler
from bot.scheduler.setup import create_scheduler, setup_recurring_jobs
from bot.services.notifications import set_bot, set_bot_username

# Настройка логов — видим что происходит в боте
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def on_error(event: ErrorEvent) -> None:
    """Глобальный обработчик ошибок — логируем всё что не поймали в хэндлерах."""
    logger.exception(
        f"Необработанная ошибка в хэндлере: {event.exception}",
        exc_info=event.exception
    )


async def main() -> None:
    # Проверяем что токен задан
    if not config.BOT_TOKEN:
        raise ValueError("BOT_TOKEN не задан в .env файле")

    bot = Bot(token=config.BOT_TOKEN)
    # SQLStorage сохраняет FSM-состояния на диск — переживают перезапуск бота
    dp = Dispatcher(storage=SQLStorage("data/fsm_states.db"))

    # Регистрируем глобальный обработчик ошибок
    dp.errors.register(on_error)

    # Регистрируем все роутеры в правильном порядке
    # common идёт первым — обрабатывает /start и регистрацию
    dp.include_router(common.router)
    dp.include_router(manager.router)
    dp.include_router(parent.router)

    # Передаём бот-инстанс и username — get_me() вызываем один раз при старте
    set_bot(bot)
    me = await bot.get_me()
    set_bot_username(me.username)

    # Создаём и запускаем планировщик
    scheduler = create_scheduler()
    set_scheduler(scheduler)
    setup_recurring_jobs(scheduler)
    scheduler.start()
    logger.info("Планировщик запущен")

    # Создаём таблицы БД если их нет
    await init_db()
    logger.info("База данных инициализирована")

    # Устанавливаем описание и краткое описание бота (видны в профиле в TG)
    await bot.set_my_short_description(
        "Школа IT для детей от 7 лет — Роблокс, Unity, 3D, AI, Python и не только 🚀"
    )
    await bot.set_my_description(
        "Обучаем детей и подростков от 7 лет IT-направлениям:\n"
        "🎮 Роблокс, Unity — разработка игр\n"
        "🖨 3D моделирование\n"
        "🤖 Искусственный интеллект\n"
        "🖥 Компьютерная грамотность\n"
        "🐍 Python, веб-разработка\n\n"
        "Формат: онлайн, 1 на 1, гибкое расписание.\n"
        "Первый урок — пробный и бесплатный! 🎓\n\n"
        "Нажмите «Старт» чтобы записаться."
    )
    logger.info(f"Бот запускается. Менеджер ID: {config.MANAGER_TELEGRAM_ID}")

    try:
        # Запускаем polling — бот начинает получать обновления
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        scheduler.shutdown()
        await bot.session.close()
        logger.info("Бот остановлен")


if __name__ == "__main__":
    asyncio.run(main())
