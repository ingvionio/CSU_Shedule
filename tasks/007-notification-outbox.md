# 007 — Надёжная доставка уведомлений: outbox и worker

## Зачем

Сейчас push о сообщениях и письма по обращениям отправляются фоновой задачей
FastAPI (`BackgroundTasks`) сразу после ответа API, один раз:

- push (`app/services/push.py`, `notify_message`) нигде не записывается:
  перезапуск контейнера или временная ошибка push-сервиса — и уведомление
  потеряно навсегда, методист об этом не узнает;
- повторных попыток нет, отправка последовательная внутри процесса API;
- методист видит «Напоминание отправлено: N», даже когда VAPID не настроен
  и не ушло ничего;
- письма лежат в `email_outbox`, но недосланные (`pending`) никто не досылает
  автоматически — только ручной `python -m app.cli send-emails`.

## Решение (принято с Лёшей 19.11.2026)

**Без брокера.** Outbox — сами записи доставки в Postgres, их обрабатывает
отдельный процесс-worker.

- Push: таблица `push_deliveries` — одна строка на (сообщение/напоминание ×
  устройство). Строки создаются **в той же транзакции**, что сообщение или
  напоминание.
- Почта: существующая `email_outbox` (уже пишется в транзакции обращения).
- Worker (`python -m app.cli worker`, отдельный сервис в `docker-compose.yml`)
  раз в несколько секунд забирает готовые к отправке строки через
  `SELECT … FOR UPDATE SKIP LOCKED`, отправляет, повторяет с нарастающей
  задержкой, записывает результат.
- API больше ничего не отправляет сам: `BackgroundTasks` для push и почты
  убираются.

## Требования

### 1. Модель и миграция

Одна миграция Alembic, `down_revision = "f2a4b6c8d013"` (проверь `alembic heads`).

`push_deliveries` (модель в `app/models/push.py`):

| Колонка | Тип | Смысл |
|---|---|---|
| `id` | int PK | |
| `message_id` | FK `messages.id` ON DELETE CASCADE, index | |
| `subscription_id` | FK `push_subscriptions.id` ON DELETE SET NULL, NULL | подписка может быть удалена — строка остаётся для статистики |
| `user_id` | FK `users.id` ON DELETE CASCADE, index | |
| `kind` | varchar(16) | `message` \| `reminder` (CHECK) |
| `status` | varchar(16) | `pending` \| `sent` \| `failed` \| `gone` \| `skipped` (CHECK) |
| `attempts` | smallint, default 0 | |
| `next_attempt_at` | timestamptz NOT NULL | когда строку можно брать в работу |
| `last_error` | varchar(500) NULL | |
| `created_at` | timestamptz | |
| `sent_at` | timestamptz NULL | |

Индекс `(status, next_attempt_at)` для выборки worker'а.

`email_outbox`: добавить `next_attempt_at timestamptz NULL` (+ индекс вместе
со `status`). Для существующих `pending` — NULL означает «можно сразу».

### 2. Запись в outbox (в транзакции)

`app/services/messages.py`:

- `create_message`: если важность не `low` **и** push настроен
  (`push.is_configured()`), то в той же транзакции создать по строке
  `push_deliveries(kind='message', status='pending', next_attempt_at=now)`
  на каждую подписку каждого получателя. Функция больше не возвращает список
  id для push.
- `remind`: так же, `kind='reminder'`, для подписок студентов из `pending`.
  Возвращает число студентов (как сейчас `len(user_ids)`) и число устройств.
- Создание строк — одна функция в `app/services/push.py`
  (например, `enqueue(db, message_id, user_ids, kind, now)`), без commit
  внутри; commit делает вызывающий сервис.
- Досылка новичкам (`attach_recent_messages`) push не создаёт — как сейчас.

`app/api/v1/messages.py` и `app/api/v1/feedback.py`: убрать `BackgroundTasks`
и вызовы `notify_message` / `deliver_by_ids`. `notify_message` и
`deliver_by_ids` удалить, если больше нигде не используются.

### 3. Worker

Новый модуль `app/services/worker.py` (или пакет `app/worker/`) и команда
`python -m app.cli worker`.

Цикл: каждые `WORKER_POLL_SECONDS` (настройка, по умолчанию 2) —
`process_push(db, now)` и `process_email(db, now)`; после пустого прохода спит,
после непустого — сразу следующий. Корректно завершается по SIGTERM/SIGINT
(дорабатывает текущую пачку). Логирует каждую пачку одной строкой
(сколько отправлено / повторов / ошибок).

**Захват строк (общий для push и почты):**
1. `SELECT … WHERE status='pending' AND (next_attempt_at IS NULL OR next_attempt_at <= now) ORDER BY id LIMIT batch FOR UPDATE SKIP LOCKED`
   (`.with_for_update(skip_locked=True)`; на SQLite в тестах это игнорируется — нормально);
2. каждой строке: `attempts += 1`, `next_attempt_at = now + LEASE` (5 минут) — commit.
   Если worker упадёт посреди отправки, строка сама вернётся в работу через 5 минут;
3. отправка — вне транзакции;
4. запись результата — отдельная короткая транзакция.

Так несколько worker'ов не возьмут одну строку, а падение не теряет её.

**Push** (`batch` = `PUSH_BATCH_SIZE`, по умолчанию 100; отправка параллельно
в `ThreadPoolExecutor` на `PUSH_CONCURRENCY` потоков, по умолчанию 8;
работа с БД — только в основном потоке):

- payload строится в момент отправки из `Message` (как `push.payload`,
  `reminder = kind == 'reminder'`);
- сообщение удалено (`deleted_at`) или подписки уже нет → `skipped`;
- VAPID не настроен → `skipped`, `last_error='push не настроен'`;
- строка старше 24 ч (TTL push) → `failed`, `last_error='истёк срок'`;
- успех → `sent`, `sent_at`;
- ответ 404/410 → `gone`, подписка удаляется (строка остаётся, `subscription_id` → NULL);
- ответ 429/5xx, таймаут, сетевые ошибки → `pending`, `next_attempt_at = now + backoff(attempts)`,
  где backoff: 30 с, 2 мин, 10 мин, 30 мин; после `PUSH_MAX_ATTEMPTS`
  (по умолчанию 5) → `failed`;
- другие 4xx → `failed` сразу.

Для этого `app/services/push.py` получает функцию отправки на одно устройство,
которая возвращает результат (`sent` / `gone` / `retry` / `failed` + текст ошибки),
а не бросает исключения. Отправитель передаётся в `process_push` параметром,
чтобы в тестах подменять без сети.

**Почта** (`batch` 20, последовательно): та же схема захвата; дальше логика
`mailer.deliver` — `sent` / повтор с backoff / `failed` после `MAX_ATTEMPTS`;
SMTP не настроен → `skipped` (как сейчас). `send-emails` в CLI остаётся
(ручная досылка и `--test`), использует ту же функцию отправки.

### 4. Настройки и Docker

`app/core/config.py`: `worker_poll_seconds`, `push_batch_size`,
`push_concurrency`, `push_max_attempts` — со значениями по умолчанию выше.
Добавить в `backend/.env.example` с комментариями.

`docker-compose.yml`: сервис `worker` — `build: ./backend`, команда
`python -m app.cli worker`, то же окружение, что у `backend` (вынести общий
`environment` в YAML-якорь `x-backend-env`, чтобы не дублировать),
`depends_on: postgres (healthy)`, `restart: unless-stopped`, тот же volume
`./backend:/app`. Порты не нужны.

### 5. Статистика для методиста

API:
- `AdminMessageOut` (и детали): поле
  `push: {configured: bool, total: int, sent: int, pending: int, failed: int}` —
  по всем строкам `push_deliveries` сообщения (оба вида); `failed` включает
  `failed`, `gone`, `skipped`. `configured` — `push.is_configured()` сейчас.
  Список сообщений — без N+1 (одна агрегирующая выборка на страницу).
- `RemindOut`: `{reminded: int, devices: int, push_configured: bool}`.

Фронт (`frontend/src/api/types.ts`, `frontend/src/pages/admin/AdminMessages.tsx`):
- в деталях сообщения строка «Push: доставлено N из M устройств» и, если есть,
  «ожидают K», «не доставлено L»; при `configured=false` — «Push не настроен:
  студенты увидят сообщение только в приложении»;
- после напоминания: «Напоминание: N студентам, на M устройств.»;
  при `push_configured=false` — «Напоминание записано (N), но push не настроен —
  студенты увидят его только в приложении.»;
- после отправки нового сообщения при `push.configured=false` — то же
  предупреждение в уведомлении формы.

Стили — в `styles.css` рядом с похожими. Фронт ничего не вычисляет, только
показывает поля.

### 6. Тесты (без сети и Docker)

- создание сообщения: строки `push_deliveries` в той же транзакции; при
  ошибке (несуществующая группа) — ни сообщения, ни строк; `low` — строк нет;
  VAPID не настроен — строк нет;
- напоминание создаёт строки `reminder` только для непрочитавших;
- worker, push, с подменённым отправителем: успех; 410 → `gone` и подписка
  удалена; 500 → повтор с `next_attempt_at` в будущем, не берётся раньше
  срока, после лимита `failed`; 400 → `failed`; удалённое сообщение → `skipped`;
  истёкшая строка → `failed`; захваченная строка (lease) не берётся повторно до
  истечения lease и берётся после;
- worker, почта: успех, повтор с backoff, `failed` после лимита, SMTP не
  настроен → `skipped`;
- API: `push` в списке и деталях, `RemindOut` с `devices` и `push_configured`;
- старые тесты `test_push.py` / `test_messages.py` / `test_feedback.py`,
  завязанные на `notify_message` / `deliver_by_ids`, — переписать под новую
  схему, не удалять проверки по смыслу;
- `npm run build` во `frontend/` зелёный.

## Вне задачи

- push в APK (FCM), брокер сообщений;
- закрытие резервной регистрации `/auth/student/register`;
- очистка старых строк `push_deliveries`;
- досылка писем со статусом `skipped`.

## Вопросы к архитектору

(пусто)

## Отчёт

Выполнено 19.11.2026. Изменения оставлены в рабочей копии, коммитов нет.

### Что сделано

- Добавлены `PushDelivery` и миграция `f3b5c7d9e024` от подтверждённой головы
  `f2a4b6c8d013`: внешние ключи, CHECK, индексы, `email_outbox.next_attempt_at`.
  Старые pending-письма сохраняются с NULL и доступны для немедленной отправки.
- Сообщение, получатели и push-доставки записываются одной транзакцией.
  Напоминания создают доставки только непрочитавшим/неподтвердившим;
  отдельно возвращаются числа студентов и устройств. Low, отключённый VAPID
  и досылка новичкам не создают push-доставок.
- Удалены фоновые отправки из API, `notify_message` и `deliver_by_ids`.
  Worker захватывает строки через `FOR UPDATE SKIP LOCKED`, фиксирует попытку
  и lease на 5 минут, отправляет без открытой транзакции, сохраняет результат
  отдельной транзакцией. Устаревший владелец lease не перезаписывает результат
  следующей попытки.
- Push отправляется пулом потоков, в потоки передаются снимки данных без ORM.
  Реализованы TTL, gone с удалением подписки и сохранением статистики,
  skipped, классификация ошибок, backoff и лимит попыток. Почта использует
  такой же захват, backoff и лимит; `send-emails` и `--test` сохранены.
- Добавлены команда `python -m app.cli worker`, завершение по SIGTERM/SIGINT,
  журналирование пачек, настройки и сервис Compose с общим YAML-якорем.
- API возвращает статистику всех доставок сообщения, включая напоминания.
  Список использует одну агрегирующую выборку push и одну общую выборку
  названий групп, без N+1. Фронт показывает статистику и предусмотренные
  предупреждения об отключённом push.

### Файлы

- Модели: `backend/app/models/{push,feedback,__init__}.py`.
- Миграция: `backend/migrations/versions/f3b5c7d9e024_notification_outbox.py`.
- Сервисы: `backend/app/services/{push,messages,mailer,worker}.py`.
- API и схемы: `backend/app/api/v1/{messages,feedback}.py`,
  `backend/app/schemas/message.py`.
- Запуск: `backend/app/cli.py`, `backend/app/core/config.py`,
  `backend/.env.example`, `docker-compose.yml`.
- Фронт: `frontend/src/api/{types,client}.ts`,
  `frontend/src/pages/admin/AdminMessages.tsx`, `frontend/src/styles.css`.
- Тесты: новые `backend/tests/test_notification_worker.py`,
  `backend/tests/test_notification_outbox_migration.py`; обновлены
  `test_push.py`, `test_messages.py`, `test_feedback.py`.
  Тесты обращений переведены на собственные группы и больше не требуют Excel.

### Проверки

- Из `backend/`: `.venv\Scripts\python -m pytest -q` —
  **273 passed, 35 skipped**, ошибок нет. Пропущены прежние проверки,
  требующие отсутствующего рабочего Excel; новые проверки очереди и миграции
  выполнены. Есть предупреждения библиотек и о недоступности записи pytest cache.
- `.venv\Scripts\python -m alembic heads` — единственная голова
  `f3b5c7d9e024`. Проверены upgrade/downgrade на SQLite, сохранение старого
  письма, CHECK, FK и генерация PostgreSQL SQL без подключения к рабочей БД.
- Проверены lease и повтор после его истечения, все задержки backoff,
  лимиты попыток, HTTP 400/403/404/410/429/500/503, сетевые ошибки,
  TTL, отключённые VAPID/SMTP, завершение по сигналу, размер пачки,
  SQL `SKIP LOCKED`, отсутствие N+1 и отличие числа студентов от устройств.
- Compose проверен командой
  `"C:\Program Files\Docker\Docker\resources\cli-plugins\docker-compose.exe" -f docker-compose.yml config --quiet`
  — код 0; контейнеры не запускались. Есть предупреждение доступа к личному
  Docker config, на проверку YAML оно не повлияло.
- В `frontend/` запущен `npm run build`: обе проверки TypeScript прошли,
  штатная загрузка `vite.config.ts` через esbuild завершилась отказом доступа
  к родительскому каталогу (`Cannot read directory "../../..": Access is denied`).
  Конфигурация проекта не менялась ради окружения. Полная production-сборка,
  включая service worker и precache, успешно выполнена с тем же конфигом:

  ```powershell
  node --input-type=module -e 'import config from "./vite.config.ts"; import { build } from "vite"; await build({ ...config, configFile: false });'
  ```

- `git diff --check` — без ошибок.

### Зависимости и запуск

Новых зависимостей нет. В этом окружении отсутствовала `backend/.venv`:
создана на Python 3.12 с `--system-site-packages`; отсутствующие pure Python
пакеты bs4/soupsieve и multipart взяты из другой локальной установки Python.
PyPI недоступен, файлы requirements не менялись. Для воспроизводимого
окружения использовать установку из `requirements-dev.txt`, указанную в AGENTS.md.

После проверки архитектором применить миграцию перед запуском worker:

```powershell
docker compose up -d --build postgres backend
docker compose exec backend python -m alembic upgrade head
docker compose up -d --build worker
docker compose logs -f worker
```

Локальный worker: из `backend/` — `.venv\Scripts\python -m app.cli worker`.
Новые переменные: `WORKER_POLL_SECONDS=2`, `PUSH_BATCH_SIZE=100`,
`PUSH_CONCURRENCY=8`, `PUSH_MAX_ATTEMPTS=5`.

### Ограничения проверки

Штатный `npm run build` необходимо повторить вне ограничения esbuild,
описанного выше. Живая конкуренция нескольких процессов на PostgreSQL,
реальные push/SMTP и остановка контейнера здесь не проверялись; тесты
проверяют SQL захвата, lease, отправку через подмену и обработку сигнала.
При падении после успешной сетевой отправки до записи результата возможна
повторная доставка — это свойство предусмотренной в задаче схемы lease.
Требования не менялись, продуктовых вопросов не возникло.
