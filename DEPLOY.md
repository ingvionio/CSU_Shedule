# Выкладка на прод (iit-app.ru)

Сервер с белым IP: nginx отдаёт собранный фронт и проксирует `/api` на
бэкенд в Docker; HTTPS на nginx; Cloudflare не используется.

```
браузер / APK ──HTTPS──► nginx ──► dist/ (фронт)
                           └─/api─► backend :8000 (127.0.0.1) ──► postgres
                                    worker ──► Web Push / FCM, SMTP
```

> Части, помеченные «⚠ уточнить», зависят от того, как сервер устроен
> сейчас (вопросы администратору отправлены 20.11.2026).

Файлы:

| Файл | Что это |
|---|---|
| `docker-compose.prod.yml` | боевой compose: postgres, backend, worker |
| `deploy/.env.prod.example` | шаблон боевого `.env` (копируется в корень как `.env`) |
| `deploy/nginx/iit-app.ru.conf.example` | пример сайта nginx |
| `backend/secrets/firebase-service-account.json` | ключ Firebase (не в гите) |

Дальше `dc` = `docker compose -f docker-compose.prod.yml`.

## Один раз перед первым запуском

1. **`.env` в корне репозитория на сервере** — из `deploy/.env.prod.example`.
   - **`JWT_SECRET` — перенести текущий с прода, не менять** (решение Лёши
     20.11.2026: на сервере уже свой надёжный секрет). Проверить только,
     что это не `change-me`.
   - **`MOODLE_ENCRYPTION_KEY` на работающем проде не задавать.** Пока он
     пуст, ключ шифрования сохранённых паролей Moodle выводится из
     `JWT_SECRET`; появление отдельного ключа (как и смена `JWT_SECRET`)
     разлогинит всех студентов — сохранённые пароли не расшифруются.
     Задавать его имеет смысл только на новой, пустой установке.
   - `ADMIN_PASSWORD`, `POSTGRES_PASSWORD` — свои значения
     (`openssl rand -hex 32` для новых).
   - ⚠ `POSTGRES_PASSWORD` должен совпадать с паролем существующей базы
     (если базу создавал репозиторный compose — это `postgres`). Сменить
     пароль базы можно отдельно: `ALTER USER postgres PASSWORD '…';`.
   - VAPID: `dc run --rm backend python -m app.cli generate-vapid`.
     **Ключи VAPID после запуска не менять** — все подписки браузеров
     станут недействительными.
   - `FCM_CREDENTIALS_FILE=/app/secrets/firebase-service-account.json`.
2. **Ключ Firebase** — `backend/secrets/firebase-service-account.json`
   (Firebase → Project settings → Service accounts). Передавать только
   напрямую на сервер, не через чаты.
3. **Том базы.** Compose называет том `<папка проекта>_postgres_data`.
   Если прод уже работал на репозиторном `docker-compose.yml`, запускайте
   боевой compose из той же папки — иначе он создаст новую пустую базу.
   Проверить: `docker volume ls | grep postgres_data`. ⚠ уточнить.
4. **nginx** — по образцу `deploy/nginx/iit-app.ru.conf.example`.
   `X-Forwarded-For` в нём **перезаписывается** (`$remote_addr`), не
   дописывается — иначе посетитель подставит свой IP и обойдёт лимиты.
   ⚠ уточнить: текущий конфиг, путь к статике, сертификат.

## Выкладка новой версии

1. **Бэкап базы:**
   ```bash
   dc exec postgres pg_dump -U postgres -Fc csu_schedule > backup-$(date +%F-%H%M).dump
   ```
2. **Код:** `git fetch && git checkout master && git pull` (⚠ уточнить, как
   код попадает на сервер).
3. **Образ и миграции:**
   ```bash
   dc build backend worker
   dc up -d postgres
   dc run --rm backend python -m alembic upgrade head
   ```
4. **Запуск:** `dc up -d backend worker` и `dc ps` — все сервисы `Up`.
5. **Фронт:** `cd frontend && npm ci && npm run build`, содержимое `dist/`
   в папку, которую отдаёт nginx (⚠ уточнить). Без `VITE_API_URL`: фронт и
   API на одном домене.
6. **nginx:** `nginx -t && systemctl reload nginx`.

### Проверка после выкладки

- `curl -s https://iit-app.ru/api/v1/push/config` → `public_key` не `null`,
  `"fcm": true`;
- `dc logs --tail 50 worker` — без ошибок; после отправки сообщения строка
  `Push: отправлено N…`;
- с сервера доходит до Google (для FCM):
  `curl -sS -o /dev/null -w "%{http_code} %{time_total}s\n" -X POST https://oauth2.googleapis.com/token`
  (из России отвечает медленно, ~20 с — это учтено);
- в админке отправить себе сообщение: приходит push в браузер и в APK,
  в деталях сообщения «Push: доставлено N из M».

### Откат

```bash
dc stop backend worker
git checkout <предыдущий коммит>
dc build backend worker
# только если новая схема мешает старому коду — вернуть базу из бэкапа:
dc exec -T postgres pg_restore -U postgres -d csu_schedule --clean --if-exists < backup-….dump
dc up -d backend worker
```

## Android-приложение

Собирается на машине разработчика, не на сервере
([frontend/README.md](frontend/README.md#android-apk)):

1. `frontend/.env.production.local`: `VITE_API_URL=https://iit-app.ru`.
2. `frontend/android/app/google-services.json` — из Firebase.
3. Ключ подписи и `frontend/android/keystore.properties` — создаются один
   раз; **ключ и пароли хранить навсегда**, без них нельзя выпустить
   обновление поверх установленного приложения.
4. `npm run build:apk:release`, затем APK — в `frontend/public/downloads/raspisanie-iit.apk`
   и выложить вместе с фронтом. Перед сборкой увеличить `versionCode`.

Тестовые debug-сборки студентам не раздавать.
