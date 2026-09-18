import asyncio
import aiohttp

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    create_async_engine,
)

from models import SwapiPeople


BASE_URL = "https://swapi-node.vercel.app"
DB_URL = "postgresql+asyncpg://swapi_user:swapi_pass@localhost:5433/swapi"

engine = create_async_engine(DB_URL)


async def fetch_json(session: aiohttp.ClientSession, url: str) -> dict:
    async with session.get(url) as response:
        response.raise_for_status()
        return await response.json()


async def fetch_homeworld(
    session: aiohttp.ClientSession,
    path: str,
) -> str:
    data = await fetch_json(session, f"{BASE_URL}{path}")

    return data["fields"]["name"]


async def fetch_films(
    session: aiohttp.ClientSession,
    paths: list[str],
) -> str:
    if not paths:
        return ""

    tasks = [
        fetch_json(session, f"{BASE_URL}{path}")
        for path in paths
    ]

    films = await asyncio.gather(*tasks)

    titles = [
        film["fields"]["title"]
        for film in films
    ]

    return ", ".join(titles)


async def fetch_starships(
    session: aiohttp.ClientSession,
    paths: list[str],
) -> str:
    if not paths:
        return ""

    tasks = [
        fetch_json(session, f"{BASE_URL}{path}")
        for path in paths
    ]

    starships = await asyncio.gather(*tasks)

    classes = [
        starship["fields"]["starship_class"]
        for starship in starships
    ]

    return ", ".join(classes)


async def fetch_vehicles(
    session: aiohttp.ClientSession,
    paths: list[str],
) -> str:
    if not paths:
        return ""

    tasks = [
        fetch_json(session, f"{BASE_URL}{path}")
        for path in paths
    ]

    vehicles = await asyncio.gather(*tasks)

    names = [
        vehicle["fields"]["name"]
        for vehicle in vehicles
    ]

    return ", ".join(names)


async def build_person(
    session: aiohttp.ClientSession,
    person: dict,
) -> dict:
    fields = person["fields"]

    homeworld = await fetch_homeworld(
        session,
        fields["homeworld"],
    )

    films = await fetch_films(
        session,
        fields["films"],
    )

    starships = await fetch_starships(
        session,
        fields["starships"],
    )

    vehicles = await fetch_vehicles(
        session,
        fields["vehicles"],
    )

    person_id = fields["url"].rstrip("/").split("/")[-1]

    return {
        "id": person_id,
        "birth_year": fields["birth_year"],
        "eye_color": fields["eye_color"],
        "gender": fields["gender"],
        "hair_color": fields["hair_color"],
        "height": fields["height"],
        "mass": fields["mass"],
        "name": fields["name"],
        "skin_color": fields["skin_color"],
        "homeworld": homeworld,
        "films": films,
        "starships": starships,
        "vehicles": vehicles,
    }


async def build_all_people(
    session: aiohttp.ClientSession,
    people: list[dict],
) -> list[dict]:
    tasks = [
        build_person(session, person)
        for person in people
    ]

    return await asyncio.gather(*tasks)


async def save_people(
    session: AsyncSession,
    people_data: list[dict],
) -> None:
    people = [
        SwapiPeople(**person_data)
        for person_data in people_data
    ]

    session.add_all(people)

    await session.commit()


async def fetch_people_page(session: aiohttp.ClientSession, page: int,) -> dict:
    url = f"{BASE_URL}/api/people?page={page}&limit=10"
    return await fetch_json(session, url)


async def fetch_all_people(session: aiohttp.ClientSession,) -> list[dict]:
    tasks = [
        fetch_people_page(session, page)
        for page in range(1, 10)
    ]

    pages = await asyncio.gather(*tasks)
    return pages


def collect_people(pages: list[dict]) -> list[dict]:
    people = []

    for page in pages:
        people.extend(page["results"])

    return people


async def main():

    async with aiohttp.ClientSession() as session:
        pages = await fetch_all_people(session)
        people = collect_people(pages)

        print("Получено персонажей:", len(people))

        prepared_people = await build_all_people(
            session,
            people,
        )

        print("Подготовлено записей:", len(prepared_people))

        print("\nПервая запись:")
        print(prepared_people[0])

        print("\nПоследняя запись:")
        print(prepared_people[-1])

        async with AsyncSession(engine) as session:
            await save_people(session, prepared_people)
            print("\nВсе персонажи сохранены в PostgreSQL")


asyncio.run(main())
