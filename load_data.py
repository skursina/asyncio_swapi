import asyncio
import aiohttp

import logging
from typing import Any

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from models import Base, SwapiPeople

# ─────────────────────── Настройки ───────────────────────

BASE_URL = "https://swapi-node.vercel.app"
DB_URL = "postgresql+asyncpg://swapi_user:swapi_pass@localhost:5433/swapi"

PAGE_SIZE = 10
MAX_CONCURRENT_REQUESTS = 20   # ограничение параллелизма
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=15)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
log = logging.getLogger(__name__)

engine = create_async_engine(DB_URL, echo=False)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


# ─────────────────────── HTTP-слой ───────────────────────

async def fetch_json(
    session: aiohttp.ClientSession,
    url: str,
    sem: asyncio.Semaphore,
) -> dict[str, Any] | None:
    """GET JSON с ограничением параллелизма и обработкой ошибок."""
    async with sem:
        try:
            async with session.get(url, timeout=REQUEST_TIMEOUT) as response:
                response.raise_for_status()
                return await response.json()
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            log.warning("Ошибка запроса %s: %s", url, e)
            return None


# ─────────────── Обогащение связанными данными ───────────────

async def _fetch_many_names(
    session: aiohttp.ClientSession,
    paths: list[str],
    sem: asyncio.Semaphore,
    extractor,                 # функция, достающая нужное поле из ответа
) -> str:
    """Общая логика для films / starships / vehicles."""
    if not paths:
        return ""

    tasks = [
        fetch_json(session, f"{BASE_URL}{path}", sem)
        for path in paths
    ]
    results = await asyncio.gather(*tasks)

    # 1) пропускаем None (ошибки)
    # 2) убираем дубликаты, сохраняя порядок
    names = []
    seen = set()
    for item in results:
        if item is None:
            continue
        value = extractor(item)
        if value and value not in seen:
            seen.add(value)
            names.append(value)

    return ", ".join(names)


async def fetch_homeworld(
    session: aiohttp.ClientSession,
    path: str,
    sem: asyncio.Semaphore,
) -> str:
    data = await fetch_json(session, f"{BASE_URL}{path}", sem)
    if data is None:
        return ""
    return data["fields"]["name"]

async def fetch_films(
    session: aiohttp.ClientSession,
    paths: list[str],
    sem: asyncio.Semaphore,
) -> str:
    return await _fetch_many_names(
        session, paths, sem,
        extractor=lambda d: d["fields"]["title"],
    )


async def fetch_starships(
    session: aiohttp.ClientSession,
    paths: list[str],
    sem: asyncio.Semaphore,
) -> str:
    return await _fetch_many_names(
        session, paths, sem,
        extractor=lambda d: d["fields"]["starship_class"],
    )


async def fetch_vehicles(
    session: aiohttp.ClientSession,
    paths: list[str],
    sem: asyncio.Semaphore,
) -> str:
    return await _fetch_many_names(
        session, paths, sem,
        extractor=lambda d: d["fields"]["name"],
    )


# ─────────────────────── Сборка персонажа ───────────────────────

def _extract_id(url: str) -> str:
    return url.rstrip("/").split("/")[-1]


async def build_person(
    session: aiohttp.ClientSession,
    person: dict[str, Any],
    sem: asyncio.Semaphore,
) -> dict[str, Any]:
    fields = person["fields"]

    # 4 запроса параллельно, а не последовательно
    homeworld, films, starships, vehicles = await asyncio.gather(
        fetch_homeworld(session, fields["homeworld"], sem),
        fetch_films(session, fields.get("films", []), sem),
        fetch_starships(session, fields.get("starships", []), sem),
        fetch_vehicles(session, fields.get("vehicles", []), sem),
    )

    return {
        "id": _extract_id(fields["url"]),
        "birth_year": fields.get("birth_year", ""),
        "eye_color": fields.get("eye_color", ""),
        "gender": fields.get("gender", ""),
        "hair_color": fields.get("hair_color", ""),
        "height": fields.get("height", ""),
        "mass": fields.get("mass", ""),
        "name": fields.get("name", ""),
        "skin_color": fields.get("skin_color", ""),
        "homeworld": homeworld,
        "films": films,
        "starships": starships,
        "vehicles": vehicles,
    }
    

async def build_all_people(
    session: aiohttp.ClientSession,
    people: list[dict[str, Any]],
    sem: asyncio.Semaphore,
) -> list[dict[str, Any]]:
    
    tasks = [build_person(session, p, sem) for p in people]
    
    return await asyncio.gather(*tasks)


# ─────────────────────── Загрузка страниц ───────────────────────

async def fetch_people_page(
    session: aiohttp.ClientSession,
    page: int,
    sem: asyncio.Semaphore,
) -> dict[str, Any] | None:
    url = f"{BASE_URL}/api/people?page={page}&limit={PAGE_SIZE}"
    return await fetch_json(session, url, sem)


async def fetch_all_people(
    session: aiohttp.ClientSession,
    sem: asyncio.Semaphore,
) -> list[dict[str, Any]]:
    """Сначала узнаём первую страницу, потом тянем остальные."""
    first = await fetch_people_page(session, 1, sem)
    if first is None:
        log.error("Не удалось получить первую страницу")
        return []

    total = first.get("count", len(first.get("results", [])))
    total_pages = (total + PAGE_SIZE - 1) // PAGE_SIZE
    log.info("Всего персонажей: %s, страниц: %s", total, total_pages)

    if total_pages <= 1:
        return first.get("results", [])

    tasks = [
        fetch_people_page(session, page, sem)
        for page in range(2, total_pages + 1)
    ]
    rest_pages = await asyncio.gather(*tasks)

    people = list(first.get("results", []))
    for page in rest_pages:
        if page:
            people.extend(page.get("results", []))

    return people


# ─────────────────────── Сохранение в БД ───────────────────────

async def save_people(
    session: AsyncSession,
    people_data: list[dict[str, Any]],
) -> None:
    """Идемпотентный upsert: повторный запуск не падает."""
    if not people_data:
        log.warning("Нет данных для сохранения")
        return

    stmt = insert(SwapiPeople).values(people_data)

    # обновляем все поля, кроме PK, при конфликте по id
    update_cols = {
        col.name: stmt.excluded[col.name]
        for col in SwapiPeople.__table__.columns
        if col.name != "id"
    }

    stmt = stmt.on_conflict_do_update(
        index_elements=[SwapiPeople.id],
        set_=update_cols,
    )

    await session.execute(stmt)
    await session.commit()
    log.info("Сохранено/обновлено записей: %s", len(people_data))


# ─────────────────────── Точка входа ───────────────────────

async def ensure_schema() -> None:
    """Создаём таблицы, если их нет — чтобы скрипт был самодостаточным."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def main() -> None:
    await ensure_schema()

    sem = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)

    async with aiohttp.ClientSession() as http_session:
        people = await fetch_all_people(http_session, sem)
        log.info("Получено персонажей: %s", len(people))

        prepared = await build_all_people(http_session, people, sem)
        log.info("Подготовлено записей: %s", len(prepared))

    async with SessionLocal() as db_session:
        await save_people(db_session, prepared)

    await engine.dispose()
    log.info("Готово")


if __name__ == "__main__":
    asyncio.run(main())
