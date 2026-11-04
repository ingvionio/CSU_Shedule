# ТЗ: Система информирования студентов (рассылка, прочтение, push)

**Версия 0.1 · основание: USM «Рассылка сообщений студентам и контроль прочтения»**

---

## 1. Цель

Дать методисту возможность адресно отправлять сообщения студентам, требовать подтверждения для важных, видеть факт прочтения и напоминать непрочитавшим. Студент получает push-уведомление и видит сообщения внутри приложения.

## 2. Принятые решения

| No | Вопрос | Решение |
|---|---|---|
| 1 | Идентичность студента | **Вариант А**: лёгкий профиль (ФИО + группа) при первом входе, таблица `users`. |
| 2 | Push-уведомления | **Входят в этот этап**: PWA + Web Push (VAPID), иначе рассылка не имеет смысла. |
| 3 | «Напомнить непрочитавшим» | Отдельное **уведомление** тем, у кого `read_at IS NULL` |
| 4 | Поток/направление | Новая колонка `groups.direction` (сейчас направление — только regex в `App.tsx:15-18`) |
| 5 | Пересдачи | Не входят |
| 6 | Сбор данных (ИНН/паспорт) | Не входит |
| | Вход через Moodle | Не входит (таблица `users.moodle_id` предусматривается на будущее) |

## 3. Роли и триггеры

| Роль | Возможности |
|---|---|
| **Методист** (= админ, существующий JWT `core/security.py`) | Создание и отправка сообщений, просмотр прочтений, напоминания. |
| **Студент** | Профиль ФИО+группа, просмотр сообщений, подтверждение «Ознакомлен», подписка на push. |

## 4. Функциональные требования

### 4.1 Идентичность студента (фундамент)

- FR-1.1 Первый вход: экран «ФИО + выбор группы». `POST /auth/student/register` находит существующего по `(full_name, group_id)` или создаёт; выдаёт **студенческий JWT** (`role=student`).
- FR-1.2 Профиль и токен хранятся в `localStorage` (как сейчас группа в `api/cache.ts`).
- FR-1.3 Студенческий токен имеет отдельный `ttl` (например 60 дней; параметр `STUDENT_JWT_TTL_HOURS`). При истечении фронт повторяет register — пользователь тот же, история прочтений сохраняется.
- FR-1.4 Студент-токен **не проходит** в админ.эндпоинты (`require_admin` уже проверяет `role==admin`).
- FR-1.5 Расписание и справочники (`/groups`, `/schedule`, `/time-slots`, `/lesson-types`) **остаются публичными** — приложение не обязано требовать логин для просмотра расписания (текущее поведение не ломается).

### 4.2 Отправка сообщений (методист)

- FR-2.1 Форма: заголовок, текст, важность, адресаты.
- FR-2.2 Адресация: **все / курс / поток / группа / конкретные студенты** (мультивыбор).
- FR-2.3 Важность: `low | normal | high`:
  - `high` — обязательно push + **кнопка «Ознакомлен»**;
  - `normal` — push, подтверждение не требуется;
  - `low` — тихий push, не требует подтверждения, не подсвечивается как просроченное.
- FR-2.4 При отправке бэкенд **материализует получателей** в `message_recipients` (снимок) и рассылает push подписанным.
- FR-2.5 Список сообщений у методиста: заголовок, важность, дата, адресация, **прогресс прочтения** (`прочитали/всего`).

### 4.3 Прочтение и «Ознакомлен»

- FR-3.1 Открытие сообщения студентом → `read_at`.
- FR-3.2 Для `high` дополнительно кнопка «Ознакомлен» → `acknowledged_at`. **Прочитано ≠ ознакомлено** — это два события.
- FR-3.3 Неподтверждённое `high` подсвечивается в списке и считается в badge непрочитанного, пока нет `acknowledged_at`.
- FR-3.4 Методист видит по каждому получателю: ФИО, группа, `read_at`, `acknowledged_at`.
- FR-3.5 Список непрочитавших — фильтр того же списка.

### 4.4 Напоминания

- FR-4.1 Кнопка «Напомнить непрочитавшим» на деталях сообщения → push «Напоминание: сообщение „X“ не прочитано» всем с `read_at IS NULL`; проставляет `reminded_at`.
- FR-4.2 Защита от спама: повторная отправка напоминаний ограничена (не чаще 1 раза в N часов, параметр `REMIND_COOLDOWN_HOURS`, default 6).

### 4.5 Push и PWA

- FR-5.1 Фронтенд становится **PWA**: `vite-plugin-pwa` + Workbox, `manifest.webmanifest`, иконки, standalone.
- FR-5.2 Запрос разрешения на уведомления и подписка `PushManager.subscribe` с VAPID-public; подписка уходит в `POST /me/push-subscriptions`.
- FR-5.3 Service Worker обрабатывает `push` → системное уведомление; `notificationclick` открывает нужное сообщение/приложение.
- FR-5.4 При получении push данные сообщений обновляются (invalidation TanStack Query).
- FR-5.5 VAPID-ключи: генерация, `VAPID_PUBLIC_KEY`/`VAPID_PRIVATE_KEY`/`VAPID_SUBJECT` в окружении бэкенда (+ в `docker-compose.yml`), `VITE_VAPID_PUBLIC_KEY` для фронта.
- FR-5.6 Отписка: удаление подписки через `DELETE /me/push-subscriptions/{id}`; при ошибках доставки — мягкий обработчик, сообщение остаётся в инбоксе.

### 4.6 Поток/направление

- FR-6.1 Миграция: `groups.direction VARCHAR(8) NULL`, бэкфилл из названия (тот же regex `(ПрИ|ПИ|БИ)` из `App.tsx`).
- FR-6.2 Парсер/импорт заполняет `direction` при создании группы.
- FR-6.3 Публичный `GET /directions` — список направлений; адресация потока строится на этом поле.
- FR-6.4 Фронт выбора адресатов и выбора группы переходит с regex на серверное поле.

## 5. Нефункциональные требования

- NFR-1 Безопасность: студенческий JWT подтверждает только `role=student`; `require_admin` (существ. `core/security.py`) не меняется.
- NFR-2 Персональные данные: не более минимально нужных (ФИО, группа); 152-ФЗ-полный учёт — вне границ (см. п.12), но маркируем поле как перс. данные в коде/доке.
- NFR-3 Производительность: создание сообщения — единая транзакция (разрезы + push-очередь вне транзакции); push на больших аудиториях — пакетами/фоновой задачей.
- NFR-4 Доступность: отправка не падает из-за недоступности сервиса push (инбокс сам по себе источник истины).
- NFR-5 Существующие тесты (71) остаются зелёными.

## 6. Модель данных

```sql
users (новая, расширение из 02-architecture.md)
  id serial PK
  full_name  text NOT NULL
  group_id   FK groups ON DELETE SET NULL
  role       text NOT NULL DEFAULT 'student'   -- 'admin'|'student'
  moodle_id  text NULL                         -- на будущее
  created_at timestamptz

messages
  id serial PK
  title      text NOT NULL
  body       text NOT NULL
  importance text NOT NULL DEFAULT 'normal'    -- low|normal|high
  target     jsonb NOT NULL   -- {type:'all'|'course'|'direction'|'group'|'students', ...}
  created_by FK users(id) NULL
  sent_at    timestamptz NOT NULL

message_recipients            -- срез на момент отправки
  id serial PK
  message_id  FK messages ON DELETE CASCADE
  user_id     FK users    ON DELETE CASCADE
  group_id    int NULL    -- снимок группы
  read_at         timestamptz NULL
  acknowledged_at timestamptz NULL
  reminded_at     timestamptz NULL
  UNIQUE(message_id, user_id)

push_subscriptions
  id serial PK
  user_id FK users ON DELETE CASCADE
  endpoint text UNIQUE
  p256dh   text NOT NULL
  auth     text NOT NULL
  user_agent text NULL
  created_at timestamptz

groups: + direction varchar(8) NULL, бэкфилл + индекс
```

Индексы: `message_recipients(user_id, read_at)`, `message_recipients(message_id)`.

## 7. API

### Студент (Bearer JWT role=student)

| Метод | Путь | Назначение |
|---|---|---|
| POST | `/auth/student/register` | `{full_name, group_id}` → токен + профиль (FR-1.1) |
| GET | `/me` | Профиль + `unread_count` |
| GET | `/me/messages` | Инбокс (FR-3.x): список со статусами |
| GET | `/me/messages/{id}` | Сообщение; ставит `read_at` |
| POST | `/me/messages/{id}/acknowledge` | «Ознакомлен» (`high`) |
| POST | `/me/push-subscriptions` | сохранить подписку |
| DELETE | `/me/push-subscriptions/{id}` | отписаться |

### Методист (JWT role=admin)

| Метод | Путь | Назначение |
|---|---|---|
| GET | `/admin/users` | Список студентов (поиск, фильтр курс/группа) — для «конкретные студенты» |
| POST | `/admin/messages` | Создать и отправить (материализация + push) |
| GET | `/admin/messages` | Список + прогресс прочтения |
| GET | `/admin/messages/{id}` | Детали + получатели со статусами |
| POST | `/admin/messages/{id}/remind` | Напомнить непрочитавшим (FR-4.x) |
| DELETE | `/admin/messages/{id}` | Удалить сообщение |

### Публично (добавление)

| GET | `/directions` | Список направлений (FR-6.3) |

## 8. JSON-контракт (фронт ⇄ бэкенд)

```jsonc
// Инбокс, GET /me/messages
{
  "unread_count": 3,
  "messages": [
    {
      "id": 12, "title": "Перенос пары", "body": "...",
      "importance": "high",
      "sent_at": "2026-10-26T09:00:00Z",
      "read_at": null,
      "acknowledged_at": null,
      "requires_ack": true
    }
  ]
}

// Список методиста, GET /admin/messages
{
  "id": 12, "title": "...", "importance": "high",
  "sent_at": "...", "target": {"type": "course", "course": 1},
  "recipients_total": 42, "read_count": 30, "acknowledged_count": 25
}

// POST /admin/messages
{ "title": "...", "body": "...", "importance": "high",
  "target": {"type": "group", "group_id": 3} }

// POST /admin/messages/{id}
// -> recipients: [{user_id, full_name, group_name, read_at, acknowledged_at}]
```

## 9. Фронтенд

- **Студент**: экран входа (ФИО + группа) вместо текущей заставки; вкладка «Сообщения» или колокольчик в шапке с badge `unread_count`; список сообщений; страница сообщения с кнопкой «Ознакомлен» для `high`; офлайн-режим PWA.
- **Методист**: раздел в админке — список сообщений с прогрессом; форма (заголовок/текст/важность/адресаты: курс→поток→группа→студенты); детали с таблицей получателей и «Напомнить непрочитавшим».
- **Общее**: выбор группы/адресации переходит на серверное поле `direction`.

## 10. Окружение и инфраструктура

- `backend/requirements.txt`: + `pywebpush`.
- Админка для VAPID — утилита/док в README (генерация ключей).
- `docker-compose.yml`: + `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, `VAPID_SUBJECT`, (опц.) `STUDENT_JWT_TTL_HOURS`, `REMIND_COOLDOWN_HOURS`.
- `frontend`: `vite-plugin-pwa`, манифест, SW, `VITE_VAPID_PUBLIC_KEY` в `.env`.
- Порты/https: Web Push требует **HTTPS** (production) / localhost (dev) — учесть в README.

## 11. Тестирование

- register студента: создание/повторный вход, разные группы.
- Ролевой контроль: студенческий токен на `/admin/*` → 403; админ на `/me` → 403.
- Материализация: all/course/direction/group/students — корректный состав получателей.
- read/ack: пассивное чтение и активное «Ознакомлен», подсчёт `acknowledged_count`.
- Remind: только `read_at IS NULL`, cooldown-ограничение.
- PWA/Push: подписка, доставка в тестовый endpoint (мок pywebpush), отписка.

## 12. Вне границ этого ТЗ

- Moodle-вход;
- пересдачи;
- сбор данных (ИНН/паспорт);
- черновики сообщений, вложения, ответы/чаты студентов;
- учёт и хранение персональных данных по 152-ФЗ (только минимальный сбор сейчас).

## 13. Этапы реализации (предложение)

1. **Идентичность + мессенджер (без push)**: users, register, messages/recipients, read/ack, админ-раздел, `direction` — сразу с тестами.
2. **Push + PWA**: подписки, SW, доставка, напоминания, cooldown, манифест/иконки.
3. **Полировка**: badge/offline, производительность пакетной отправки, README.