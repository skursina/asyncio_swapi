import asyncio

from sqlalchemy.ext.asyncio import create_async_engine

from models import Base


DB_URL = "postgresql+asyncpg://swapi_user:swapi_pass@localhost:5433/swapi"


async def main():
    engine = create_async_engine(DB_URL)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    await engine.dispose()


asyncio.run(main())
