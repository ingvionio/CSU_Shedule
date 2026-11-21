# 014 — Влить асинхронный master и перевести нашу работу на async

Ветка `feature/notifications`. В рабочей копии **уже идёт слияние**
`origin/master` (`git merge --no-commit`): 29 файлов с конфликтами. Задача —
разрешить конфликты в коде и перевести наш код на асинхронную схему master.
**Не выполняй** `git commit`, `git merge --abort`, `git reset`, `git checkout` —
коммит слияния делает архитектор после приёмки.

## Что пришло из master (сохранить полностью)

Задачи `tasks/006-moodle-session-security.md`, `tasks/007-async-backend.md`,
`tasks/008-product-statistics.md` и следующие — прочитай их отчёты:

- **Асинхронный бэкенд** (Тоха): `AsyncEngine`/`AsyncSession` (`app/core/db.py`),
  `async def` роутеры и сервисы, `httpx.AsyncClient` для Moodle, `aiosmtplib`
  для почты, `webpush_async` (aiohttp) для Web Push, разбор Excel и ZIP — в
  рабочем потоке, `pytest-asyncio` в тестах, `requests` удалён из зависимостей.
- Moodle-сессии с фоновым обработчиком (`app/services/moodle_sessions.py`).
- ЛК продукта: события и статистика (`/statistic`), подпись обращений из Moodle.

Их поведение и тесты не ломать и не упрощать.

## Что наше (перевести на async, сохранить поведение)

Задачи 007–013 этой ветки (`tasks/007-notification-outbox.md` …
`tasks/013-exams-in-schedule.md`) и правки после них:

- outbox: `push_deliveries`, `email_outbox.next_attempt_at`; отдельный процесс
  `python -m app.cli worker` (`app/services/worker.py`) — захват строк
  `FOR UPDATE SKIP LOCKED` с арендой, повторы, отправка вне транзакции,
  параллельная отправка push; шаг `process_schedule_changes`;
- FCM (`app/services/fcm.py`) — **без `requests`**: HTTP через `httpx`
  (асинхронно), OAuth-токен сервисного аккаунта через `google-auth`
  (подпись JWT и обмен на токен — через асинхронный транспорт или вручную
  через `httpx`; таймаут получения токена 45 с — из России
  `oauth2.googleapis.com` отвечает ~20 с). Кэш токена и сброс после 401 —
  как сейчас;
- Web Push в worker'е — через асинхронную отправку master (`webpush_async`),
  классификация результатов `sent/gone/retry/failed` — как в 007;
- почта в worker'е — через асинхронную отправку master (`aiosmtplib`);
- сессия и пересдачи: модели, парсеры (чистые модули, синхронные, вызываются в
  рабочем потоке, как Excel у master), импорт, API `/admin/exams…`,
  события в неделе по `?events=1`;
- уведомления об изменении расписания (`schedule_changes`), запись в той же
  транзакции, что изменение;
- `find_group`/`existing_group_ids` (дубли групп при загрузке), парсер
  понедельных книг с несколькими преподавателями, `schedule_pending` у
  магистров, `week.next` до последней недели с событием.

**Worker** — отдельный процесс, как в 007 (systemd `csu-worker`, не внутри
API). Внутри — `asyncio.run(...)`, своя `AsyncSession`, корректное завершение по
SIGTERM/SIGINT. Параллельная отправка push — `asyncio` (семафор на
`PUSH_CONCURRENCY`) вместо потоков.

## Миграции

Цепочка уже выпрямлена архитектором: `…f2a4b6c8d013 → a7d9e2c4b816 →
f3b5c7d9e124 → f3b5c7d9e024 → f4c6d8e0a135 → f5d7e9a1b246 → f6e8a0b2c357`.
Наши миграции должны работать в асинхронном `migrations/env.py` master.
`alembic heads` — одна голова. Тесты миграций обновить под новую цепочку.

## Фронт

Конфликты в `App.tsx`, `api/types.ts`, `pages/messages/StudentMessages.tsx`:
сохранить обе стороны (статистика/подпись обращений master и наши экзамены,
push в Android, отсутствие плашки и кнопки «Выключить», открытие сообщения
один раз, плавное переключение режимов, клик по паре в неделе).

## Не трогать

Корневые `*.md` (`04-current-state.md`, `README.md` и др.), `DEPLOY.md`,
`backend/README.md`, `frontend/README.md` — конфликты в них разрешит
архитектор, оставь маркеры как есть. `.env`, `backend/secrets`, ключи.

## Проверки

- `backend\.venv\Scripts\python -m pytest -q --tb=short -W error::RuntimeWarning`
  из `backend/` — всё зелёное (тесты обеих сторон; зависимости master уже
  установлены в `.venv`, сети нет);
- `alembic heads` — одна голова;
- `npm test`, `npm run build` во `frontend/`;
- в коде не осталось маркеров конфликтов (кроме перечисленных `*.md`),
  синхронного `Session`/`SessionLocal()` без `async`, `requests`.

## Вопросы к архитектору

(пусто)

## Отчёт

Выполнено 21.11.2026 в рабочей копии текущего слияния, без коммита.

### Что сделано

- Разрешены конфликты исходного кода, зависимостей, шаблона
  `backend/.env.example` и `docker-compose.yml`. Сохранены Moodle-сессии
  master, подпись обращений по Moodle, ЛК продукта и события статистики.
- Наши API, импортёры, группы, календарь, экзамены и запись
  `schedule_changes` переведены на `AsyncSession`. Сохранены атомарность
  импортов и уведомлений, сопоставление разных написаний групп,
  `schedule_pending`, расширенная граница недель и выдача экзаменов только
  при `events=1`. Парсеры остались чистыми синхронными модулями; чтение
  загрузок, Excel и ZIP выполняются в рабочем потоке.
- Worker остаётся отдельным процессом `python -m app.cli worker`.
  CLI запускает асинхронную команду через `asyncio.run` и освобождает движок
  при выходе. Сохранены захват `FOR UPDATE SKIP LOCKED`, аренда,
  защита от устаревшего отправителя, повторы/backoff, TTL и шаг обработки
  изменений расписания. Push отправляется задачами asyncio с семафором
  `PUSH_CONCURRENCY`; ORM и сессия в сетевые задачи не передаются.
  SIGTERM/SIGINT завершают текущий проход и останавливают цикл.
- Web Push использует `webpush_async` и aiohttp с прежней классификацией
  исходов; почта — `aiosmtplib` и тот же outbox-обработчик для worker,
  `send-emails` и `send-emails --test`. Во время отправки транзакция
  закрыта. Событие статистики доставки записывается один раз на получателя
  одной рассылки/напоминания, включая обработку нескольких устройств
  разными пачками worker.
- FCM отправляет HTTP и обменивает подписанный google-auth JWT на OAuth-токен
  через `httpx.AsyncClient`. Таймаут OAuth — 45 секунд; загрузка ключа и
  подпись выполняются в рабочем потоке. Сохранены общий кэш, защита
  параллельного обновления и один немедленный повтор после 401. Прямых
  импортов/зависимости `requests` больше нет.
- Наши тесты переведены на async, API-тесты используют настоящий маршрут
  Moodle с подменой внешней авторизации вместо закрытой регистрации.
  Сохранены проверки обеих веток; проверка ожидания SMTP перенесена на
  отдельный worker. Продуктовая статистика также переведена с синхронных
  функций внутри `run_sync` на прямые асинхронные запросы.
- Во фронте совмещены статистика и наши экзамены, Android push,
  однократная обработка ссылки на сообщение, отсутствие плашки включённых
  уведомлений и кнопки «Выключить». Сохранены переключение режимов и
  действия по паре в сетке недели. Резервная регистрация по ФИО не возвращена.
- Цепочка миграций, подготовленная архитектором, сохранена; обновлено
  ожидание `down_revision` в тесте outbox. Новых миграций не добавлено.

### Файлы

- API: `backend/app/api/v1/{admin,exams,feedback,me,messages,product,public,router}.py`.
- Сервисы: `backend/app/services/{admin_imports,exam_importer,exams,fcm,groups,importer,mailer,messages,overrides,product_stats,push,schedule,schedule_changes,weekly_importer,weeks,worker}.py`.
- Запуск и настройки: `backend/app/cli.py`, `app/core/config.py`,
  `backend/requirements.txt`, `backend/.env.example`, `docker-compose.yml`.
- Тесты: `backend/tests/conftest.py`,
  `test_{exams,exams_in_schedule,fcm,feedback,messages,notification_outbox_migration,notification_worker,product_stats,push,schedule_change_api,schedule_change_imports,schedule_changes,weekly_import}.py`;
  новый `backend/tests/test_async_merge.py`.
- Фронт: `frontend/src/App.tsx`, `api/types.ts`,
  `pages/messages/StudentMessages.tsx`;
  новый `frontend/tests/messages-merge.test.mjs`.

### Проверки

- Из `backend/`: `.venv\Scripts\python -B -X utf8 -m pytest -q --tb=short -W error::RuntimeWarning -p no:cacheprovider --basetemp C:\Users\asala\AppData\Local\Temp\csu-014-FWieg4\pytest-final`
  — **477 passed, 35 skipped, код 0**. Пропуски требуют отсутствующего
  рабочего Excel. Семь предупреждений — DeprecationWarning Alembic и
  библиотек WebSocket; предупреждений о неисполненных coroutine нет.
- Новые регрессии проверяют реальную параллельность и ограничение семафора,
  освобождение соединения при сетевом ожидании, запуск CLI worker,
  асинхронный Web Push и закрытие клиента, HTTP-обмен OAuth с таймаутом 45 с,
  общее обновление токена и запоздалый 401, оба экзаменационных парсера
  в рабочем потоке, цепочку миграций через асинхронное окружение Alembic.
- `.venv\Scripts\python -B -X utf8 -m alembic heads`
  — одна голова **f6e8a0b2c357**.
- Из `frontend/`: `npm test` — **57 passed**. Добавлены проверки
  однократного открытия сообщения, сохранения запроса до входа Moodle
  и отсутствия кнопки отключения/плашки включённого push.
- `npm run build` выполнен в копии фронтенда в системном TEMP, чтобы
  промежуточные файлы оставались вне репозитория. Обе проверки TypeScript
  прошли; штатная загрузка Vite-конфига остановилась в esbuild:
  `Cannot read directory "../../../../..": Access is denied`.
  Конфигурация проекта ради окружения не менялась.
- Production-сборка с тем же содержимым Vite-конфига через
  `vite.build({ ...config, configFile: false })` — **успешна**:
  приложение, страницы download/statistic, PWA/service worker и precache.
  Скрипт повтора: из
  `C:\Users\asala\AppData\Local\Temp\csu-014-FWieg4\frontend`
  — `node build.mjs`. Там же находятся копия исходников, ESM-копия конфига
  и `dist/`; в проекте они не создавались.
- Проверены синтаксис Python и `git diff --check` — без ошибок.
  В коде и конфигурации нет маркеров конфликтов, импортов синхронного
  `Session` или `requests`; все контексты `SessionLocal()` асинхронные.

### Ограничения и замечания архитектору

- Штатный `npm run build` нужно повторить в среде без указанного запрета
  esbuild. Проверка типов и production-сборка через API Vite выполнены.
- При проверке полной цепочки на SQLite обнаружен прежний дефект
  `e8c1b2a3d4f5_moodle_user_fields.py`: миграция ожидает имя UNIQUE
  `users_device_key_hash_key`, которого старая SQLite-схема не создавала.
  Эта миграция не изменялась. Интеграционный тест сначала воспроизводит
  исходную схему с именем ограничения, как в PostgreSQL; затем выполняет
  upgrade до головы, downgrade до `f2a4b6c8d013` и повторный upgrade
  через неизменённый асинхронный `migrations/env.py`.
- Живые PostgreSQL, Moodle, SMTP, FCM/Web Push и Android-устройство
  не использовались. Реальная межпроцессная конкуренция PostgreSQL
  здесь не проверена; проверены SQL блокировок, аренда и асинхронная
  параллельная отправка на изолированных SQLite и подменённых транспортах.
- Новых зависимостей сверх объединения requirements обеих веток нет;
  установки пакетов и обращения к сети не выполнялись. Рабочие
  `.env`, `backend/secrets`, ключи, корневые Markdown, DEPLOY.md и
  README не изменялись. Существовавшие `.claude/` и `_claude_test/`
  не изменялись.
- Конфликты устранены в рабочем дереве; индекс слияния не менялся
  (`git add` не выполнялся). В корневых `04-current-state.md` и
  `README.md` оставлены исходные маркеры для архитектора.
  `commit`, `merge --abort`, `reset` и `checkout` не выполнялись.
