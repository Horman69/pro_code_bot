from datetime import datetime


def local_now() -> datetime:
    """Текущее время в часовом поясе школы без tzinfo — совместимо с SQLite."""
    from bot import config
    return datetime.now(config.TIMEZONE).replace(tzinfo=None)
