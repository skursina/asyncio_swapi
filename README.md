# Asyncio SWAPI

Асинхронная загрузка данных о персонажах Star Wars из SWAPI в PostgreSQL.

## Технологии

- Python 3.12+
- aiohttp
- asyncio
- SQLAlchemy
- asyncpg
- PostgreSQL
- Docker Compose

## Запуск проекта

### 1. Установить зависимости

```bash
pip install -r requirements.txt
```

### 2. Запустить PostgreSQL
```bash
docker compose up -d
```

### 3. Создать таблицу
```bash
python migrate.py
```

### 4. Загрузить данные
```bash
python load_data.py
```
Программа получает 82 персонажа SWAPI и сохраняет их в PostgreSQL.

### 5. Проверить количество записей
```bash
docker compose exec db psql -U swapi_user -d swapi -c "SELECT count(*) FROM people;"
```
Ожидаемый результат:
```
count
-------
82
```

## Структура проекта
* `models.py` — SQLAlchemy-модель таблицы people
* `migrate.py` — создание таблицы в PostgreSQL
* `load_data.py` — асинхронное получение и сохранение данных
* `docker-compose.yml` — контейнер с PostgreSQL
* `requirements.txt` — зависимости проекта
