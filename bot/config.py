import os
from zoneinfo import ZoneInfo
from dotenv import load_dotenv

load_dotenv()

# Токен бота от BotFather
BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")

# Telegram ID и username менеджера
MANAGER_TELEGRAM_ID: int = int(os.getenv("MANAGER_TELEGRAM_ID", "0"))
MANAGER_USERNAME: str = os.getenv("MANAGER_USERNAME", "")

# Путь к базе данных SQLite (потом сменим на PostgreSQL при 50+ учениках)
DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///data/school.db")

# Включить ли интеграцию с Google Calendar
GOOGLE_CALENDAR_ENABLED: bool = os.getenv("GOOGLE_CALENDAR_ENABLED", "false").lower() == "true"
GOOGLE_CALENDAR_ID: str = os.getenv("GOOGLE_CALENDAR_ID", "")
GOOGLE_CREDENTIALS_PATH: str = os.getenv("GOOGLE_CREDENTIALS_PATH", "google_credentials.json")

# Часовой пояс школы — все datetime в боте в этом поясе
TIMEZONE: ZoneInfo = ZoneInfo(os.getenv("TIMEZONE", "Europe/Moscow"))

# Пороги для уведомлений о балансе
LOW_BALANCE_THRESHOLD: int = 2  # предупреждаем когда осталось ≤ 2 уроков

# Реферальные бонусы (в уроках или рублях)
REFERRAL_BONUS_SIGNUP_LESSONS: int = 1      # бонус за первую оплату друга
REFERRAL_BONUS_MONTH_1_LESSONS: int = 1     # бонус за 1 месяц обучения друга
REFERRAL_BONUS_MONTH_3_CASH: int = 2000     # рублей за 3 месяца
REFERRAL_BONUS_MONTH_6_CASH: int = 2500     # рублей за 6 месяцев
