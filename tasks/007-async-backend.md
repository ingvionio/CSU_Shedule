# 007 — Асинхронный бэкенд и сетевые клиенты

## Поручение

Проверить подключение к БД и сетевые клиенты. Перевести синхронные операции бэкенда на асинхронные, включая API, фоновые задачи и CLI. Выполнить работу в отдельной ветке и слить её в локальный master.

## Вопросы к архитектору

Нет.

## Отчёт

- В `backend/app/core/db.py` приложение использует `AsyncEngine` и отдельную `AsyncSession` для каждого запроса. PostgreSQL работает через асинхронный psycopg, SQLite — через aiosqlite. В `backend/app/core/config.py` сохранена поддержка существующих URL с `sqlite+pysqlite`.
- Роутеры `backend/app/api/v1/`, сервисы `backend/app/services/`, команды `backend/app/cli.py` и окружение Alembic перешли на асинхронный доступ к БД. Запросная сессия закрывается до фоновой отправки. FastAPI освобождает пул при остановке приложения.
- Moodle использует `httpx.AsyncClient` с отдельными cookies на сеанс. SMTP использует `aiosmtplib`, Web Push — `webpush_async` с клиентом aiohttp. Фоновые задачи возвращают подключение к БД в пул перед сетевым ожиданием. Браузерный клиент уже использовал асинхронный `fetch`.
- Чтение загрузок, разбор Excel и извлечение файлов из ZIP выполняются в рабочем потоке. Тесты проверяют откат ошибочной загрузки, предварительный просмотр и перепривязку домашних заданий.
- В `backend/requirements.txt` добавлены `aiosqlite` и `aiosmtplib`, а `httpx` перенесён из dev-зависимостей в рабочие. `aiohttp`, ранее транзитивная зависимость pywebpush, теперь указан явно. Прямая зависимость от `requests` удалена. Включён extra `sqlalchemy[asyncio]`, FastAPI обновлён до 0.121.0 для `Depends(scope="function")`. Для тестов добавлен `pytest-asyncio`.

### Проверки 20.11.2026

- Полный запуск pytest на отдельной SQLite дал 229 успешных тестов и 35 пропусков. Отдельные проверки подтвердили изоляцию сессий, параллельную работу API при ожидании Moodle и освобождение подключения к БД до ответа SMTP.
- `npm run build` во фронтенде прошёл, включая проверку TypeScript и сборку service worker.
- На отдельной PostgreSQL 17 применены все миграции до `f2a4b6c8d013`, проверены `seed-semester` и `stats`. Через Uvicorn проверены загрузка тестовой книги Excel, параллельное чтение расписания и текущей недели, вход Moodle в mock-режиме. Запрос, ожидающий блокировку в PostgreSQL, оставил другое подключение доступным.
- Команды `init-db`, `seed-semester` и `stats` прошли с SQLite и прежним URL `sqlite+pysqlite`.
- Полная генерация SQL командой `alembic upgrade head --sql` останавливается на обращении к данным в миграции `a41d6c0e2b77`. То же воспроизведено на исходном master. Генерация SQL для последней миграции прошла.
- Moodle, SMTP и Web Push проверены на подменённых ответах. Рабочая книга расписания отсутствовала.

### Команды из backend

```powershell
.venv\Scripts\python -m pip install -r requirements-dev.txt
.venv\Scripts\python -m pytest -q --tb=short -W error::RuntimeWarning
.venv\Scripts\python -m alembic upgrade head
.venv\Scripts\python -m app.cli stats
```

На Windows при запуске Uvicorn с PostgreSQL без `--reload` укажите цикл событий, поддерживаемый psycopg.

```powershell
.venv\Scripts\python -m uvicorn app.main:app --loop asyncio:SelectorEventLoop
```
