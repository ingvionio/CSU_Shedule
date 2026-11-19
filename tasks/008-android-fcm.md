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

(заполняет исполнитель)
