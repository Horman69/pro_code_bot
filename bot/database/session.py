from contextlib import asynccontextmanager
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from bot.config import DATABASE_URL
from bot.database.models import Base

# Создаём асинхронный движок SQLAlchemy
engine = create_async_engine(DATABASE_URL, echo=False)

# Фабрика сессий — используем везде в приложении
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def init_db() -> None:
    """Создаёт таблицы если их нет. Данные не трогаем."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


@asynccontextmanager
async def get_session():
    """Контекстный менеджер сессии — гарантирует закрытие и rollback при ошибке."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
