# Расписание ИИТ ЧелГУ

Бэкенд (FastAPI + PostgreSQL) собирает расписание группы на неделю из Excel
и временных изменений. Фронтенд (React, будущий PWA) его показывает и даёт
администратору вносить изменения.

| Документ | О чём |
|---|---|
| [01-context.md](01-context.md) | задача, пользователи, предметная область |
| [02-architecture.md](02-architecture.md) | архитектура, схема БД, API |
| [03-schedule-json.md](03-schedule-json.md) | контракт JSON недели бэкенд → фронтенд |
| [04-current-state.md](04-current-state.md) | что сделано на текущий момент |
| [05-feedback.md](05-feedback.md) | обращения студентов: папки, почта, ответы, планы |
| [06-messages.md](06-messages.md) | сообщения студентам: рассылка, «Ознакомлен», напоминания, push |
| [07-messages-overview.md](07-messages-overview.md) | сообщения студентам простыми словами: как пользоваться студенту, методисту и как настроить |
| [backend/README.md](backend/README.md) | бэкенд: CLI, API, правила временных изменений |
| [frontend/README.md](frontend/README.md) | фронтенд: экраны, админка |

## Что нужно

* Docker Desktop — для базы и API;
* Node.js 18+ — для фронтенда;
* Excel с расписанием в корне репозитория:
  `Расписание_ИИТ_1_сем_26_27_уч_г_РАБОЧИЙ_ВАРИАНТ.xlsx` (в гит не коммитится).

## Первый запуск

```bash
# 1. База и API (из корня репозитория)
docker compose up -d --build
docker compose exec backend python -m alembic upgrade head      # схема БД
docker compose exec backend python -m app.cli seed-semester     # семестр, сетка звонков, форматы пар

# 2. Залить расписание из Excel
docker compose cp "./Расписание_ИИТ_1_сем_26_27_уч_г_РАБОЧИЙ_ВАРИАНТ.xlsx" backend:/tmp/schedule.xlsx
docker compose exec backend python -m app.cli import-excel /tmp/schedule.xlsx
docker compose exec backend python -m app.cli stats             # проверить, что залилось

# 3. Фронтенд
cd frontend
npm install
npm run dev
```

* фронтенд — http://localhost:5173
* API — http://localhost:8000, документация — http://localhost:8000/docs
* админка — меню в шапке → «Администрирование расписания», логин `admin`, пароль `admin`

Данные лежат в docker-томе и переживают `docker compose down`.

## Обычный запуск

```bash
docker compose up -d
cd frontend && npm run dev
```

## После `git pull`

```bash
docker compose up -d --build                                    # если поменялись зависимости бэкенда
docker compose exec backend python -m alembic upgrade head      # если появились миграции
cd frontend && npm install                                      # если поменялся package.json
```

Бэкенд в контейнере запущен без автоперезагрузки: после правок кода бэкенда —
`docker compose restart backend`.

## Если порт 8000 занят

```bash
BACKEND_PORT=8001 docker compose up -d
cd frontend && VITE_API_URL=http://localhost:8001 npm run dev
```

PowerShell: `$env:BACKEND_PORT=8001; docker compose up -d` и
`$env:VITE_API_URL="http://localhost:8001"; npm run dev`.

Postgres снаружи доступен на `localhost:5433` (не 5432 — чтобы не мешать
локально установленному Postgres).

## Переменные окружения (.env)

**Для запуска через Docker `.env` не нужен**: все переменные с значениями по
умолчанию прописаны в `docker-compose.yml`. В гите лежат только шаблоны
`*.env.example`, сами `.env` игнорируются.

| Где | Когда нужен |
|---|---|
| `.env` в корне | чтобы поменять пароль админа или секрет JWT для Docker: `ADMIN_LOGIN`, `ADMIN_PASSWORD`, `JWT_SECRET`, `BACKEND_PORT` — compose подхватит их сам. Почта для обращений: `SMTP_USER`, `SMTP_PASSWORD`, `PUBLIC_APP_URL`; push: `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, `VAPID_SUBJECT` (см. ниже) |
| `backend/.env` | только при запуске бэкенда **без Docker**: `cp backend/.env.example backend/.env` и поправить `DATABASE_URL`. Без `ADMIN_PASSWORD` вход в админку выключен |
| `frontend/.env.local` | только если бэкенд не на `localhost:8000`: `VITE_API_URL=...` |

Перед выкладкой на сервер обязательно задать свои `ADMIN_PASSWORD` и `JWT_SECRET`.

## Почта для обращений (Яндекс)

Без настроек обращения работают, но письма не уходят — их текст пишется
в лог бэкенда.

1. Завести ящик на Яндексе (например, `csu-schedule@yandex.ru`).
2. id.yandex.ru → «Безопасность» → «Пароли приложений» → создать пароль
   для почты. Обычный пароль от ящика SMTP не принимает.
3. В Яндекс Почте: «Настройки» → «Почтовые программы» → включить доступ
   по протоколу IMAP «С сервера imap.yandex.ru» (без этого SMTP отклоняет вход).
4. В `.env` в корне:
   ```
   SMTP_USER=csu-schedule@yandex.ru
   SMTP_PASSWORD=<пароль приложения>
   ```
5. `docker compose up -d` и проверка:
   `docker compose exec backend python -m app.cli send-emails --test you@example.com`
6. В админке → «Обращения» → «Адресаты и почта» вписать email разработчиков,
   методиста и деканата.

Неотправленные письма (SMTP был недоступен) досылаются командой
`docker compose exec backend python -m app.cli send-emails`.

## Push-уведомления о сообщениях

Без ключей сообщения работают, но push не уходят — студент видит их в
разделе «Сообщения».

1. `docker compose exec backend python -m app.cli generate-vapid`
2. Вывод вставить в `.env` в корне (`VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`,
   `VAPID_SUBJECT=mailto:<почта для связи>`), затем `docker compose up -d`.
3. Push работает только по **HTTPS** (локально — на `localhost`). На iPhone —
   только у приложения, добавленного на экран «Домой».

Ключи генерируются один раз: новые ключи отключают все подписки.
Подробно — [06-messages.md](06-messages.md).

## Тесты бэкенда

```bash
docker compose cp "./Расписание_ИИТ_1_сем_26_27_уч_г_РАБОЧИЙ_ВАРИАНТ.xlsx" "backend:/Расписание_ИИТ_1_сем_26_27_уч_г_РАБОЧИЙ_ВАРИАНТ.xlsx"
docker compose exec backend sh -c "pip install -q -r requirements-dev.txt && python -m pytest -q"
```

Тесты работают на отдельной SQLite-базе и рабочую базу не трогают. Сквозные
тесты берут Excel из корня (в контейнере — `/`), без него они пропускаются.
