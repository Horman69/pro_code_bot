import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from bot.database.models import Base


@pytest_asyncio.fixture
async def session():
    """Свежая in-memory база на каждый тест — изолировано, без побочных эффектов."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with factory() as s:
        yield s
    await engine.dispose()


class MockScheduler:
    """Заглушка планировщика — перехватывает add_job/remove_job без реальных задач."""

    def __init__(self):
        self.jobs: dict[str, dict] = {}

    def add_job(self, func, trigger, run_date, args, id, replace_existing=False):
        self.jobs[id] = {"func": func, "run_date": run_date, "args": args}

    def remove_job(self, job_id):
        if job_id not in self.jobs:
            raise Exception(f"Задача {job_id} не найдена")
        del self.jobs[job_id]


@pytest.fixture
def mock_scheduler():
    """Устанавливает MockScheduler и сбрасывает его после теста."""
    from bot.scheduler.jobs import set_scheduler
    sched = MockScheduler()
    set_scheduler(sched)
    yield sched
    set_scheduler(None)
