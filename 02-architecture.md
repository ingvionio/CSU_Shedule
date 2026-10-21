# Архитектура (кратко)

## Общая схема

```
┌───────────────────────────┐      HTTPS / JSON      ┌───────────────────────────────┐
│  Frontend (React, PWA)    │  ────────────────────▶ │  Backend (Python)             │
│  • авторизация            │                        │  • REST API                   │
│  • страница студента      │  ◀──────────────────── │  • сборка расписания недели   │
│  • страница админа        │                        │  • парсер Excel               │
│  • service worker (кэш)   │                        │  • CRUD изменений             │
└───────────────────────────┘                        └──────────────┬────────────────┘
                                                                    │ SQL
                                                     ┌──────────────▼────────────────┐
                                                     │  PostgreSQL                   │
                                                     └───────────────────────────────┘
```

## Стек

| Слой | Технологии |
|---|---|
| Frontend | React + TypeScript, Vite, PWA (vite-plugin-pwa / Workbox), React Router, TanStack Query |
| API | Python 3.12, FastAPI, Pydantic |
| ORM и миграции | SQLAlchemy 2.x, Alembic |
| Парсинг Excel | openpyxl (при необходимости pandas) |
| БД | PostgreSQL 16 |
| Авторизация админа | логин/пароль, JWT |
| Авторизация студента | Moodle (способ уточняется); запасной вариант — выбор группы без входа |
| Запуск | Docker Compose (frontend + backend + postgres) |

## Структура репозитория

```
frontend/
  src/
    pages/
      LoginPage/        # вход студента (Moodle / выбор группы) и админа
      StudentPage/      # неделя / день, текущая неделя, пометки изменений
      AdminPage/        # загрузка Excel, редактор изменений, предпросмотр
    components/         # карточка пары, переключатель недели/дня и т. д.
    api/                # клиент API, типы из контракта JSON
  public/manifest.webmanifest
backend/
  app/
    api/                # роутеры: public (студент), admin, auth
    services/
      schedule.py       # сборка расписания недели (ядро)
      weeks.py          # номер недели, чётность, даты
      importer.py       # загрузка и парсинг Excel → черновик
    models/             # SQLAlchemy-модели
    schemas/            # Pydantic-схемы (контракт JSON)
    core/               # конфиг, БД, авторизация
  migrations/           # Alembic
  tests/
docs/
docker-compose.yml
```

## Фронтенд

- **Маршруты**: `/login`, `/` (студент), `/admin/*` (только для роли admin).
- **Данные**: TanStack Query запрашивает `GET /groups/{id}/schedule?week=N`, кэширует недели; соседние недели можно подгружать заранее.
- **PWA**: манифест (иконка, название, standalone-режим) и service worker. Статика кэшируется; последний ответ расписания сохраняется, чтобы расписание открывалось без сети. При появлении сети данные обновляются.
- **Группа студента** запоминается на устройстве (или приходит из профиля после входа через Moodle).
- Фронт **не вычисляет** расписание: чётность, номер недели, итоговые пары и статусы приходят с бэкенда.

## API

### Авторизация

| Метод | Путь | Назначение |
|---|---|---|
| POST | `/api/v1/auth/admin/login` | Вход админа, выдача JWT (пока один логин/пароль из `.env`) |
| GET | `/api/v1/auth/moodle/login` | Переход на вход через Moodle (после уточнения способа) |
| GET | `/api/v1/auth/moodle/callback` | Возврат из Moodle, создание/обновление пользователя, определение группы |
| GET | `/api/v1/me` | Текущий пользователь, роль, группа |

### Публичное (студент)

| Метод | Путь | Назначение |
|---|---|---|
| GET | `/api/v1/groups` | Список групп (для ручного выбора) |
| GET | `/api/v1/weeks/current` | Номер и чётность текущей недели, даты |
| GET | `/api/v1/groups/{group_id}/schedule?week={n}` | **Расписание группы на неделю** (основной запрос). Без `week` — текущая неделя |

Расписание на день фронт берёт из ответа на неделю (поле `days[]`), отдельный запрос не нужен.

### Админка

| Метод | Путь | Назначение |
|---|---|---|
| GET | `/api/v1/time-slots` | Сетка звонков (публичный: нужен и студенту для сетки недели) |
| GET | `/api/v1/lesson-types` | Список форматов пар (публичный) |
| GET | `/api/v1/admin/catalog` | Предметы, преподаватели, аудитории — подсказки в форме изменения |
| POST | `/api/v1/admin/imports` | Загрузить Excel (курс, семестр) → черновик + отчёт об ошибках парсинга |
| GET | `/api/v1/admin/imports/{id}` | Результат парсинга / предпросмотр |
| POST | `/api/v1/admin/imports/{id}/publish` | Опубликовать загруженное расписание |
| GET/POST/PATCH/DELETE | `/api/v1/admin/lessons` | Постоянные пары (постоянные изменения) |
| POST / DELETE | `/api/v1/admin/overrides` | Временные изменения (отмена, перенос, замена, доп. пара) для группы или потока; `DELETE /{id}?batch=true` — откат для всего потока |
| GET | `/api/v1/admin/groups/{group_id}/schedule/preview?week={n}` | Предпросмотр недели с учётом черновиков |
| POST | `/api/v1/admin/publish` | Опубликовать черновые изменения |

## Время пары и сетка звонков

Сетка звонков — справочник `time_slots`: номер пары (1–8) и её время.

Каждая пара **всегда** хранит `start_time` и `end_time`. Поле `slot` (номер в сетке) заполнено, только если время пары совпадает со временем звонка. Это решает случай пар вне сетки:

| Ситуация | slot | start_time – end_time |
|---|---|---|
| 4-я пара по звонку | 4 | 16:30 – 18:00 |
| Пара в 17:00, вне сетки | null | 17:00 – 18:30 |

Правила:
- в админке время выбирается из сетки (номер пары подставляет время) или вводится вручную — тогда `slot = null`;
- при парсинге Excel номер пары превращается во время по сетке; если в ячейке указано своё время, пара сохраняется вне сетки;
- пары в дне сортируются **по `start_time`**, а не по номеру;
- бэкенд проверяет пересечения по времени: две пары одной группы не могут пересекаться (кроме отменённых/перенесённых).

## Схема БД

```
semesters ──┐
            ├──< lessons >── groups
time_slots ─┤       │
lesson_types┤       │
subjects ───┤       └──< lesson_overrides
teachers ───┤
rooms ──────┘
schedule_imports ──< lessons
users >── groups (опционально)
```

### Таблицы

**semesters** — учебный семестр
| поле | тип | примечание |
|---|---|---|
| id | serial PK | |
| title | text | «Осень 2026» |
| start_date | date | понедельник первой учебной недели |
| end_date | date | |
| first_week_parity | enum(`odd`,`even`) | чётность первой недели, по календарю недель (обычно `odd`) |
| is_active | bool | |

**groups**
| поле | тип | примечание |
|---|---|---|
| id | serial PK | |
| name | text unique | «ИВТ-21» |
| course | smallint | 1–4 |
| moodle_code | text null | обозначение группы в Moodle |

**time_slots** — сетка звонков
| поле | тип |
|---|---|
| number | smallint PK (1–8) |
| start_time | time |
| end_time | time |

**lesson_types** — форматы пар (таблица, а не enum, чтобы добавлять форматы без изменения схемы)
| поле | тип | примечание |
|---|---|---|
| code | text PK | `lecture`, `practice` (позже `lab`, `exam`, …) |
| name | text | «Лекция», «Практика» |

**subjects**, **teachers**, **rooms** — справочники (`id`, `name` / `full_name`), заполняются при парсинге Excel.

**lessons** — постоянное расписание
| поле | тип | примечание |
|---|---|---|
| id | serial PK | |
| semester_id | FK semesters | |
| group_id | FK groups | |
| weekday | smallint | 1 = пн … 6 = сб |
| start_time | time | всегда заполнено |
| end_time | time | всегда заполнено |
| slot | FK time_slots null | номер в сетке звонков; null — пара вне сетки |
| week_parity | enum(`odd`,`even`,`both`) | мигалка |
| subject_id | FK subjects | |
| lesson_type | FK lesson_types | |
| teacher_id | FK teachers null | |
| room_id | FK rooms null | |
| valid_from | date | с какой даты действует |
| valid_to | date null | до какой даты включительно (null — до конца семестра) |
| status | enum(`draft`,`published`) | |
| import_id | FK schedule_imports null | откуда пришла пара |
| created_by, created_at, updated_at | | |

Постоянное изменение = у старой записи ставим `valid_to`, создаём новую с `valid_from`. История сохраняется.

**lesson_overrides** — временные изменения на конкретную дату
| поле | тип | примечание |
|---|---|---|
| id | serial PK | |
| group_id | FK groups | |
| kind | enum(`cancel`,`move`,`replace`,`add`) | |
| date | date | дата, к которой относится изменение |
| lesson_id | FK lessons null | исходная пара (null для `add`) |
| target_date | date null | для `move`: новая дата |
| start_time, end_time | time null | новое время для `move` / `add` / `replace` (null = без изменений) |
| slot | FK time_slots null | номер в сетке для нового времени, если оно по звонку |
| subject_id, lesson_type, teacher_id, room_id | null | новые значения для `replace` / `add` / `move` (null = без изменений) |
| comment | text null | «Преподаватель на конференции» |
| status | enum(`draft`,`published`) | |
| created_by, created_at | | |

**schedule_imports** — загрузки Excel
| поле | тип |
|---|---|
| id | serial PK |
| semester_id | FK |
| course | smallint |
| file_name | text |
| status | enum(`parsed`,`failed`,`published`) |
| errors | jsonb (строки/ячейки, которые не удалось разобрать) |
| uploaded_by, uploaded_at | |

**users**
| поле | тип | примечание |
|---|---|---|
| id | serial PK | |
| login | text unique | |
| password_hash | text null | для админов |
| role | enum(`admin`,`student`) | |
| group_id | FK groups null | |
| moodle_id | text null | id пользователя в Moodle |

## Сборка расписания недели (ядро бэкенда)

`GET /groups/{group_id}/schedule?week=N`:

1. Взять активный семестр; вычислить даты недели: `monday = start_date + (N-1)*7`.
2. Определить чётность недели по `N` и `first_week_parity`.
3. Для каждого дня недели выбрать `lessons` группы, где:
   `weekday` совпадает, `week_parity IN (parity, 'both')`, `valid_from <= date <= coalesce(valid_to, ∞)`, `status = published`.
4. Применить `lesson_overrides` (published) на даты недели:
   - `cancel` → пара остаётся в ответе со статусом `cancelled`;
   - `replace` → поля пары (в т. ч. время) заменяются, статус `changed`, прежние значения кладутся в `change.original`;
   - `move` → в исходную дату пара попадает со статусом `moved_out` (куда перенесли), в `target_date` — со статусом `moved_in` (откуда перенесли). Перенос может пересекать границу недели;
   - `add` → новая пара со статусом `added`.
5. Отсортировать пары дня по `start_time`, отдать JSON (см. `03-schedule-json.md`).

Предпросмотр в админке использует тот же алгоритм, но учитывает и `draft`-записи.

## Парсинг Excel

1. Админ загружает файл и указывает курс.
2. Парсер находит группы, дни, номера пар, чётность, предмет / формат / преподавателя / аудиторию. Номер пары переводится во время по сетке звонков; пара с собственным временем сохраняется вне сетки.
3. Неизвестные преподаватели, аудитории, предметы добавляются в справочники.
4. Результат сохраняется как `lessons` со статусом `draft`, нераспознанные ячейки — в `schedule_imports.errors`.
5. Админ проверяет, правит и публикует; старые постоянные пары этого курса закрываются через `valid_to`.

Правила разбора ячеек описываются по имеющимся Excel-файлам.
