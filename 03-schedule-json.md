# JSON расписания недели (контракт бэкенд → фронтенд)

## Запрос

```
GET /api/v1/groups/{group_id}/schedule?week={week_number}
```

- `group_id` — id группы (обязательный).
- `week` — номер учебной недели от начала семестра. Если не передан, бэкенд отдаёт текущую неделю.

Бэкенд отдаёт **готовое** расписание: постоянные пары с учётом чётности и сроков действия уже отобраны, временные изменения уже применены. Фронт только отображает.

## Структура ответа

| Поле | Тип | Описание |
|---|---|---|
| `group` | object | `id`, `name`, `course` |
| `week.number` | int | номер недели от начала семестра |
| `week.parity` | `"odd"` \| `"even"` | нечётная / чётная (мигалка) |
| `week.start_date`, `week.end_date` | `YYYY-MM-DD` | понедельник и воскресенье |
| `week.is_current` | bool | это текущая неделя |
| `week.prev`, `week.next` | int \| null | соседние недели в пределах семестра (null — за пределами) |
| `generated_at` | ISO datetime | время сборки ответа |
| `days[]` | array | дни недели пн–сб, **включая дни без пар** (`lessons: []`) |
| `days[].date` | `YYYY-MM-DD` | |
| `days[].weekday` | int | 1 = пн … 6 = сб |
| `days[].is_today` | bool | |
| `days[].lessons[]` | array | пары дня, **отсортированы по `start_time`** |

### Пара (`lessons[]`)

| Поле | Тип | Описание |
|---|---|---|
| `id` | string | стабильный id элемента: `l-{lesson_id}` для постоянной пары, `o-{override_id}` для добавленной/перенесённой |
| `start_time`, `end_time` | `HH:MM` | время пары — заполнено всегда |
| `slot` | int \| null | номер пары в сетке звонков (1–8). `null` — пара вне сетки (например, 17:00) |
| `subject` | string | предмет |
| `type` | object | формат: `{ "code": "lecture", "name": "Лекция" }`. Сейчас `lecture` и `practice`, позже добавятся другие — фронт должен показывать `name` и не падать на незнакомом `code` |
| `room` | string \| null | аудитория |
| `teacher` | string \| null | ФИО преподавателя |
| `status` | enum | см. ниже |
| `change` | object \| null | детали изменения, `null` для `regular` |

Отображение времени: если `slot` есть — «4 пара, 16:30–18:00», если `null` — просто «17:00–18:30».

### Значения `status`

| status | Что показать студенту |
|---|---|
| `regular` | обычная пара |
| `changed` | пара состоится, но изменены аудитория / преподаватель / формат / время — пометка «изменено», в `change.original` прежние значения |
| `cancelled` | пара отменена (показывать зачёркнутой) |
| `moved_out` | пара перенесена **с этого** времени — в `change.moved_to` куда |
| `moved_in` | пара перенесена **на это** время — в `change.moved_from` откуда |
| `added` | дополнительная пара — пометка «новое» |

### Объект `change`

| Поле | Тип | Когда заполнено |
|---|---|---|
| `override_id` | int | всегда: id изменения, по нему админка откатывает его (`DELETE /admin/overrides/{id}`) |
| `kind` | `"cancel"` \| `"replace"` \| `"move"` \| `"add"` | всегда |
| `comment` | string \| null | причина от админа |
| `original` | object \| null | для `changed`: прежние значения изменённых полей |
| `moved_to` | `{date, slot, start_time, end_time}` \| null | для `moved_out` |
| `moved_from` | `{date, slot, start_time, end_time}` \| null | для `moved_in` |

## Пример

Неделя 7 (нечётная), группа ИВТ-21. Во вторник одна пара заменена по аудитории, одна отменена; в среду пара перенесена на пятницу в 17:00 (вне сетки); в четверг дополнительная пара.

```json
{
  "group": { "id": 5, "name": "ИВТ-21", "course": 2 },
  "week": {
    "number": 7,
    "parity": "odd",
    "start_date": "2026-10-12",
    "end_date": "2026-10-18",
    "is_current": true,
    "prev": 6,
    "next": 8
  },
  "generated_at": "2026-10-13T09:15:00+05:00",
  "days": [
    {
      "date": "2026-10-12",
      "weekday": 1,
      "is_today": false,
      "lessons": [
        {
          "id": "l-101",
          "start_time": "08:30",
          "end_time": "10:00",
          "slot": 1,
          "subject": "Математический анализ",
          "type": { "code": "lecture", "name": "Лекция" },
          "room": "А-301",
          "teacher": "Иванов И. И.",
          "status": "regular",
          "change": null
        },
        {
          "id": "l-102",
          "start_time": "10:10",
          "end_time": "11:40",
          "slot": 2,
          "subject": "Математический анализ",
          "type": { "code": "practice", "name": "Практика" },
          "room": "Б-214",
          "teacher": "Петрова А. С.",
          "status": "regular",
          "change": null
        }
      ]
    },
    {
      "date": "2026-10-13",
      "weekday": 2,
      "is_today": true,
      "lessons": [
        {
          "id": "l-110",
          "start_time": "10:10",
          "end_time": "11:40",
          "slot": 2,
          "subject": "Программирование",
          "type": { "code": "practice", "name": "Практика" },
          "room": "В-105",
          "teacher": "Сидоров П. А.",
          "status": "changed",
          "change": {
            "override_id": 41,
            "kind": "replace",
            "comment": "Аудитория на ремонте",
            "original": { "room": "В-201" },
            "moved_to": null,
            "moved_from": null
          }
        },
        {
          "id": "l-111",
          "start_time": "12:10",
          "end_time": "13:40",
          "slot": 3,
          "subject": "Физика",
          "type": { "code": "lecture", "name": "Лекция" },
          "room": "А-101",
          "teacher": "Кузнецов В. Н.",
          "status": "cancelled",
          "change": {
            "override_id": 42,
            "kind": "cancel",
            "comment": "Преподаватель на конференции",
            "original": null,
            "moved_to": null,
            "moved_from": null
          }
        }
      ]
    },
    {
      "date": "2026-10-14",
      "weekday": 3,
      "is_today": false,
      "lessons": [
        {
          "id": "l-120",
          "start_time": "08:30",
          "end_time": "10:00",
          "slot": 1,
          "subject": "Английский язык",
          "type": { "code": "practice", "name": "Практика" },
          "room": "Г-12",
          "teacher": "Смирнова Е. В.",
          "status": "moved_out",
          "change": {
            "override_id": 44,
            "kind": "move",
            "comment": null,
            "original": null,
            "moved_to": { "date": "2026-10-16", "slot": null, "start_time": "17:00", "end_time": "18:30" },
            "moved_from": null
          }
        }
      ]
    },
    {
      "date": "2026-10-15",
      "weekday": 4,
      "is_today": false,
      "lessons": [
        {
          "id": "o-45",
          "start_time": "16:30",
          "end_time": "18:00",
          "slot": 4,
          "subject": "Дискретная математика",
          "type": { "code": "practice", "name": "Практика" },
          "room": "Б-210",
          "teacher": "Орлов Д. М.",
          "status": "added",
          "change": {
            "override_id": 45,
            "kind": "add",
            "comment": "Отработка",
            "original": null,
            "moved_to": null,
            "moved_from": null
          }
        }
      ]
    },
    {
      "date": "2026-10-16",
      "weekday": 5,
      "is_today": false,
      "lessons": [
        {
          "id": "l-130",
          "start_time": "12:10",
          "end_time": "13:40",
          "slot": 3,
          "subject": "Базы данных",
          "type": { "code": "lecture", "name": "Лекция" },
          "room": "А-205",
          "teacher": "Волков С. Г.",
          "status": "regular",
          "change": null
        },
        {
          "id": "o-44",
          "start_time": "17:00",
          "end_time": "18:30",
          "slot": null,
          "subject": "Английский язык",
          "type": { "code": "practice", "name": "Практика" },
          "room": "Г-12",
          "teacher": "Смирнова Е. В.",
          "status": "moved_in",
          "change": {
            "override_id": 44,
            "kind": "move",
            "comment": null,
            "original": null,
            "moved_to": null,
            "moved_from": { "date": "2026-10-14", "slot": 1, "start_time": "08:30", "end_time": "10:00" }
          }
        }
      ]
    },
    {
      "date": "2026-10-17",
      "weekday": 6,
      "is_today": false,
      "lessons": []
    }
  ]
}
```

## Вспомогательные ответы

`GET /api/v1/weeks/current`

```json
{
  "number": 7,
  "parity": "odd",
  "start_date": "2026-10-12",
  "end_date": "2026-10-18",
  "semester": { "id": 1, "title": "Осень 2026", "total_weeks": 18 }
}
```

`GET /api/v1/groups`

```json
[
  { "id": 1, "name": "ИВТ-11", "course": 1 },
  { "id": 5, "name": "ИВТ-21", "course": 2 }
]
```

## Правила для фронта

- Расписание на день — это элемент `days[]` с нужной датой, отдельного запроса нет.
- Переключение недель — по `week.prev` / `week.next`.
- Пары выводить в том порядке, в котором они пришли (уже отсортированы по времени).
- Номер пары показывать, только если `slot` не `null`; время показывать всегда.
- Пометку изменения показывать для любого `status`, кроме `regular`.
- Отменённые и перенесённые (`cancelled`, `moved_out`) пары не удалять из списка, а показывать с пометкой — студент должен видеть, что пары не будет.
- Последний полученный JSON сохраняется для офлайн-режима PWA; при показе из кэша можно выводить `generated_at` («обновлено в …»).
