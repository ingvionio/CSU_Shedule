# 008 — Push в Android-приложении через FCM

Зависит от задачи 007 (outbox и worker): FCM — второй отправитель в том же
worker'е. Начинать после её приёмки, в той же ветке `feature/notifications`
(вся работа над уведомлениями — в ней).

## Зачем

APK (Capacitor) открывает фронт в Android WebView, где нет Web Push
(`PushManager`). Поэтому в Android-приложении уведомлений нет вообще. Решение
(19.11.2026, см. «Принятые решения» в `04-current-state.md`): Android —
Firebase Cloud Messaging; Huawei/Honor без сервисов Google — позже отдельной
задачей; iPhone — только PWA.

## Требования

### 1. Подписки: платформа

Миграция (после миграции задачи 007):

- `push_subscriptions.platform varchar(8) NOT NULL DEFAULT 'web'`,
  CHECK `web | fcm`; существующие строки — `web`;
- `p256dh`, `auth` становятся NULL-абельными (у FCM их нет);
- `endpoint` хранит адрес доставки: URL Web Push для `web`, FCM-токен для
  `fcm` (уникальность остаётся). Комментарий в модели.

API `POST /me/push-subscriptions` принимает один из двух видов тела
(дискриминатор — поле `platform`, по умолчанию `web` — старые клиенты не
ломаются):

```jsonc
{ "endpoint": "https://…", "keys": { "p256dh": "…", "auth": "…" } }   // web, как сейчас
{ "platform": "fcm", "token": "<FCM registration token>" }             // Android
```

Для `fcm`: токен 20–4096 символов, без проверки формата. `push.subscribe`
делает upsert по `endpoint` (токен) и выставляет `platform`.

`GET /push/config` → `{ "public_key": str | null, "fcm": bool }` — `fcm`
означает, что на сервере настроен FCM.

### 2. Отправитель FCM (бэкенд)

Настройка `FCM_CREDENTIALS_FILE` — путь к JSON сервисного аккаунта Firebase
(пусто — FCM выключен). `project_id` берётся из файла. В `.env.example`,
`docker-compose.yml` (обоим сервисам через `x-backend-env`) и в README:
файл кладётся в `backend/secrets/` (папка в `.gitignore`), в контейнере это
`/app/secrets/…`.

Отправка — FCM HTTP v1:
`POST https://fcm.googleapis.com/v1/projects/{project_id}/messages:send`,
OAuth-токен из сервисного аккаунта (scope
`https://www.googleapis.com/auth/firebase.messaging`). Зависимость —
`google-auth` (не `firebase-admin`); HTTP — уже имеющийся `requests`.
OAuth-токен кэшируется в процессе и обновляется по истечении.

Тело сообщения:

```jsonc
{ "message": {
    "token": "<endpoint>",
    "notification": { "title": "…", "body": "…" },          // как push.payload
    "data": { "message_id": "12", "url": "/?message=12", "importance": "high" },  // только строки
    "android": {
      "priority": "HIGH",
      "ttl": "86400s",
      "notification": { "channel_id": "messages", "tag": "message-12" }
    } } }
```

Результат (тот же тип результата, что у Web Push в 007):

| Ответ FCM | Результат |
|---|---|
| 200 | `sent` |
| 404 / `UNREGISTERED`, 403 `SENDER_ID_MISMATCH` | `gone` (подписка удаляется) |
| 400 `INVALID_ARGUMENT` | `failed` (текст ошибки в `last_error`) |
| 429, 5xx, таймаут, сеть | повтор по backoff из 007 |
| 401 (OAuth) | сбросить кэш токена, повтор |

Worker выбирает отправителя по `subscription.platform`.

`push.is_configured()` из 007 разделить по платформам:
`web_configured()` (VAPID) и `fcm_configured()`. При постановке в outbox
строки `push_deliveries` создаются только для подписок, чья платформа
настроена. В статистике методиста `push.configured` = настроена хотя бы одна
платформа; строку предупреждения не менять.

### 3. Android-приложение (фронт)

- Зависимость `@capacitor/push-notifications` (мажорная версия как у
  `@capacitor/core`), `npx cap sync android`.
- `frontend/src/api/push.ts`: если `Capacitor.isNativePlatform()` — нативная
  ветка вместо Web Push, с теми же состояниями `PushState` и тем же
  интерфейсом `usePush()` (экран «Сообщения» не меняется, кроме текстов при
  необходимости):
  - `detect`: `fcm=false` в `/push/config` → `unconfigured`; разрешение
    `denied` → `denied`; есть сохранённый id подписки → `on`, иначе `off`;
  - `enable`: `requestPermissions()` (на Android 13+ системный запрос) →
    `register()` → по событию `registration` отправить токен
    (`platform: 'fcm'`) на бэкенд, сохранить id подписки;
    `registrationError` → понятная ошибка;
  - при каждом запуске приложения, если уведомления включены, —
    `register()` и повторная отправка токена (токен может смениться;
    бэкенд делает upsert);
  - `disable`: `DELETE /me/push-subscriptions/{id}`, `unregister()`.
- Канал уведомлений Android: при старте нативного приложения
  `createChannel({ id: 'messages', name: 'Сообщения', importance: 4 })`.
- Нажатие на уведомление (`pushNotificationActionPerformed`) — открыть
  сообщение так же, как ссылка `/?message=N` из Web Push (переиспользовать
  существующую навигацию, без копии логики).
- Push при открытом приложении (`pushNotificationReceived`) — обновить
  инбокс (invalidate `['inbox']`, как делает `messages-updated` от service
  worker'а), системное уведомление не показывать.
- Android-проект:
  - монохромная иконка уведомления `ic_stat_notify` (белый силуэт на
    прозрачном фоне, из существующего значка) и в `AndroidManifest.xml`
    meta-data `com.google.firebase.messaging.default_notification_icon` и
    `default_notification_channel_id = messages`;
  - разрешение `POST_NOTIFICATIONS` должно оказаться в итоговом манифесте
    (проверить, добавляет ли его плагин; если нет — добавить);
  - `google-services.json` в гит не попадает (`frontend/android/app/` в
    `.gitignore`); без него сборка проходит, push просто не работает (уже
    так в `app/build.gradle`).
- `frontend/README.md`, раздел Android APK: куда положить
  `google-services.json`, что push в APK работает только с ним, и строку
  «нативный push для APK в проекте пока не подключён» заменить.

### 4. Тесты

Без сети: HTTP к FCM и получение OAuth-токена подменяются.

- схема подписки: старое тело web, тело fcm, неверные варианты → 422;
  повторная подписка тем же токеном не дублирует строку;
- `/push/config` с FCM и без;
- outbox: при настроенном только FCM строки создаются только для `fcm`
  подписок и наоборот;
- отправитель FCM: тело запроса (поля, `data` — строки, `channel_id`),
  разбор ответов по таблице выше, обновление OAuth-токена после 401;
- worker выбирает отправителя по платформе;
- `npm run build` и `npx cap sync android` проходят; если в окружении есть
  Android SDK — `npm run build:apk`.

## Ручная проверка (архитектор / Лёша)

Нужны `google-services.json`, ключ сервисного аккаунта и Android-телефон или
эмулятор с Google Play: установить APK → «Сообщения» → включить уведомления
→ из админки отправить сообщение группе → уведомление при свёрнутом и при
закрытом приложении; нажатие открывает сообщение; статистика в админке
«доставлено 1 из 1».

## Вне задачи

- Huawei Push Kit (HMS) для телефонов без сервисов Google — отдельная задача;
- iOS-сборка и APNs (iPhone — только PWA);
- RuStore Push.

## Вопросы к архитектору

(пусто)

## Отчёт

Работа выполнена в `feature/notifications`, без коммитов. Реализация готова;
проверки сборки ограничены недоступной установкой зависимостей (см. ниже).

### Что сделано

- Миграция `f4c6d8e0a135` после `f3b5c7d9e024`: платформа `web/fcm`,
  серверный default `web`, CHECK и nullable-ключи. Старые подписки сохраняются.
  При downgrade FCM-подписки удаляются, история доставок остаётся с NULL.
- API принимает прежнее тело Web Push и новый FCM-токен, проверяет длину,
  повторная подписка сохраняет id. `/push/config` возвращает отдельный `fcm`.
- FCM HTTP v1 с `google-auth` и `requests`: общий для потоков OAuth-кэш,
  обновление по истечении и после 401, один немедленный повтор с новым токеном.
  Реализованы результаты sent/gone/failed/retry по таблице задачи, timeout,
  строковые data, TTL, HIGH, channel_id и tag. Дальнейшие повторы — worker 007.
- Outbox создаётся только для настроенных платформ; worker выбирает отправителя
  для каждой подписки. Статистика configured учитывает хотя бы одну платформу.
  Существующие предупреждения методиста сохранены.
- Нативная ветка `usePush`: разрешения, регистрация, обработка ошибок,
  сохранение id, повторная регистрация при запуске и после входа, отписка.
  Смена токена удаляет прежний id подписки; параллельные регистрации объединены,
  отписка дожидается уже начатого сохранения токена.
- Канал `messages` создаётся при старте; Android 7 продолжает работать при
  UNAVAILABLE для каналов. События Android и service worker используют общий
  обработчик навигации `/?message=N` и обновления инбокса. Foreground-показ
  системных уведомлений выключен через presentationOptions: [].
- Android: подключение push-плагина в Gradle, meta-data и явное разрешение
  POST_NOTIFICATIONS. Белый VectorDrawable `ic_stat_notify` получен из альфа-
  силуэта существующего `iit-shield.png`, без нового рисунка или зависимости.
- Добавлены FCM_CREDENTIALS_FILE в настройки, шаблон окружения и общий
  Compose-якорь. Каталог secrets и google-services.json исключены из Git.
  README бэкенда и фронтенда обновлены по прямому требованию этой задачи.
- Общая тестовая SQLite-база перенесена из репозитория в TemporaryDirectory
  системного temp. Книги и SQLite-файлы новых тестов используют pytest tmp_path.

### Файлы

- `backend/app/models/push.py`, `app/schemas/student.py`,
  `app/api/v1/{me,public}.py`, `app/core/config.py`.
- `backend/app/services/{push,worker}.py`, новый `app/services/fcm.py`.
- `backend/migrations/versions/f4c6d8e0a135_fcm_subscriptions.py`.
- `backend/{requirements.txt,.env.example,.gitignore,README.md}`,
  `docker-compose.yml`.
- `backend/tests/{conftest,test_push}.py`, новые
  `test_fcm.py`, `test_fcm_migration.py`.
- `frontend/src/api/{push,client}.ts`, новый `api/native-push.ts`,
  `src/App.tsx`, `src/pages/messages/StudentMessages.tsx`.
- `frontend/{package.json,capacitor.config.json,README.md}`,
  `frontend/tests/native-push.test.mjs`.
- `frontend/android/{capacitor.settings.gradle,app/capacitor.build.gradle,
  app/.gitignore,app/src/main/AndroidManifest.xml,
  app/src/main/res/drawable/ic_stat_notify.xml}`.

### Проверки

- Бэкенд из `backend/`: `.venv\Scripts\python -m pytest -q` —
  **307 passed, 35 skipped**. Пропущены существующие тесты с отсутствующим
  рабочим Excel. Есть предупреждения библиотек и отказ записи старого pytest
  cache; тестовые БД создавались в системном temp, не в репозитории.
- Отдельный прогон новых FCM, миграции, прежнего Push и worker:
  **72 passed**. HTTP, OAuth и все внешние сервисы подменены; сеть и Docker
  для тестов не использовались.
- Миграция: проверены SQLite upgrade/downgrade с существующей web-подпиской,
  CHECK, уникальность токена, NULL-ключи и сохранение истории доставок;
  PostgreSQL DDL сгенерирован без подключения к рабочей базе.
  `alembic heads`: единственная голова `f4c6d8e0a135`.
- `npm test` во `frontend/`: **20 passed**, включая состояния native,
  разрешения, регистрацию и ошибки, startup, ротацию токена, отписку,
  одновременные регистрации, Android 7, получение и нажатие на уведомление.
- Compose `config --quiet`: код 0; есть предупреждение доступа к личному
  Docker config. Контейнеры и рабочая БД не запускались.
- XML манифеста и VectorDrawable разбирается; `git check-ignore` подтверждает
  исключение обоих секретов. `git diff --check` — без ошибок.

### Зависимости и ограничения окружения

- Добавлены только требуемые зависимости: `google-auth>=2,<3` и
  `@capacitor/push-notifications:^8.0.0` (мажор 8, как у core).
- `npm install @capacitor/push-notifications@^8` запущен; запрос к npm registry
  завершается EACCES, доступа к сети нет. Локального кэша пакета тоже нет.
  В имеющемся node_modules отсутствует весь @capacitor, включая прежний core
  и CLI. `package-lock.json` не подделывался и требует обновления настоящим
  `npm install` в окружении с доступом к registry.
- `npm run build` запущен и остановился на TS2307 для отсутствующих
  @capacitor/core и @capacitor/push-notifications. После явных аннотаций
  callback-типов проверка build:apk сообщает только эти отсутствующие модули.
  Полная проверка типов и production-сборка с установленными пакетами
  остаются невыполненными; заглушки пакетов в проект не добавлялись.
- Выполнена попытка `cap sync android` через npm exec (эквивалент npx);
  CLI отсутствует, загрузка из registry блокируется EACCES. Ссылки на плагин
  в двух генерируемых Gradle-файлах добавлены вручную; их надо подтвердить
  реальным sync после установки. Итоговый merged manifest не получен;
  POST_NOTIFICATIONS явно прописан в манифесте приложения.
- Каталог Android SDK обнаружен. `npm run build:apk` запущен, но остановился
  на том же шаге TypeScript до Gradle. APK и сборка без google-services.json
  не проверены; прежнее условное подключение Google Services в build.gradle
  сохранено.
- Попытка установки `google-auth` через pip также безуспешна (No matching
  distribution found); тесты получения OAuth подменены, как требует задача.
  Для реальной отправки библиотеку нужно установить из requirements.txt.
- Реальной отправки FCM, проверки фонового/закрытого приложения и статистики
  на телефоне не было: нужны ключи Firebase, установленный плагин и устройство.
- Во время работы появились сторонние правки `04-current-state.md`;
  исполнитель этот файл не менял. Исходные `.claude/` и `_claude_test/`
  не использовались и не изменялись.

### Как завершить проверку в окружении с сетью

```powershell
# backend/
.venv\Scripts\python -m pip install -r requirements-dev.txt
.venv\Scripts\python -m pytest -q -o cache_dir="$env:TEMP/csu-pytest-cache"

# frontend/: npm install обновит package-lock.json; затем проверить его дифф
npm install
npm test
npm run build
npx cap sync android
npm run build:apk

# из корня, после настройки Firebase в .env и размещения обоих JSON
docker compose up -d --build postgres backend
docker compose exec backend python -m alembic upgrade head
docker compose up -d --build worker
```

Затем выполнить ручную проверку из задачи. Ключ сервисного аккаунта —
`backend/secrets/firebase-service-account.json`, переменная для контейнеров —
`FCM_CREDENTIALS_FILE=/app/secrets/firebase-service-account.json`.
`google-services.json` приложения — `frontend/android/app/google-services.json`.

При реализации сверены официальные [API Capacitor](https://capacitorjs.com/docs/apis/push-notifications),
[код создания каналов](https://github.com/ionic-team/capacitor-plugins/blob/main/push-notifications/android/src/main/java/com/capacitorjs/plugins/pushnotifications/NotificationChannelManager.java)
и [FCM HTTP v1](https://firebase.google.com/docs/cloud-messaging/send/v1-api).

### Приёмка (архитектор, 20.11.2026)

- Установлены зависимости, `npm test`, `npm run build`, `npx cap sync android`,
  `assembleDebug` и полный pytest (307 passed) — зелёные.
- Живая проверка в эмуляторе Android (Google Play): подписка FCM, доставка при
  свёрнутом и выгруженном приложении, открытие сообщения по нажатию,
  «Ознакомлен», статистика методиста.
- Исправлено: таймаут получения OAuth-токена поднят до 45 с —
  `oauth2.googleapis.com` из России отвечает ~20 с, при 10 с FCM не работал.
