# 009 — Подготовка к выкладке на прод

Ветка `feature/notifications`. Делаем всё, что не зависит от устройства
конкретного сервера (ответы администратора ещё не получены). Прод:
iit-app.ru, nginx на сервере с белым IP, фронт и `/api` на одном домене,
HTTPS на nginx, без Cloudflare (`04-current-state.md`, «Принятые решения»).

Инструкцию по выкладке (`DEPLOY.md`) пишет архитектор — здесь только код
и конфиги.

## Требования

### 1. Настоящий IP посетителя за nginx

Бэкенд считает лимиты по `request.client.host` (вход Moodle, резервная
регистрация, обращения). За nginx это адрес прокси — лимит срабатывает на
весь институт сразу.

- `backend/Dockerfile`: uvicorn с `--proxy-headers`. Доверенные адреса
  прокси — через переменную окружения `FORWARDED_ALLOW_IPS`, которую uvicorn
  читает сам (по умолчанию `127.0.0.1` — для разработки менять не нужно).
- Тест: приложение, запущенное так же, как в Dockerfile (uvicorn
  `ProxyHeadersMiddleware` с теми же параметрами, без сети и Docker), видит
  IP из `X-Forwarded-For` от доверенного прокси и **не** видит его от
  недоверенного. Если проверить через uvicorn в тесте неудобно — опиши в
  «Вопросах», не выдумывай свою реализацию заголовков.

### 2. Переменные, которые не доходят до контейнера

В `x-backend-env` (`docker-compose.yml`) добавить с пустыми значениями по
умолчанию: `MOODLE_ENCRYPTION_KEY`, `MOODLE_BASE_URL` (по умолчанию
`https://eu.iit.csu.ru`). Поведение при пустом ключе не менять (сейчас
ключ выводится из `JWT_SECRET`).

### 3. Боевой compose: `docker-compose.prod.yml`

Отдельный самостоятельный файл (не override), запуск
`docker compose -f docker-compose.prod.yml …`. Отличия от разработки:

- код только из образа: **без** `./backend:/app`; подключается только
  `./backend/secrets:/app/secrets:ro`;
- `postgres`: порты наружу не публикуются; том называется так же —
  `postgres_data` (чтобы при том же имени проекта подхватились данные);
  `restart: unless-stopped`; пароль — `${POSTGRES_PASSWORD:?…}`;
- `backend`: порт только на loopback — `127.0.0.1:${BACKEND_PORT:-8000}:8000`;
  `FORWARDED_ALLOW_IPS: "*"` с комментарием, почему это безопасно только
  при порте на 127.0.0.1 (nginx на хосте приходит из docker-сети);
  `restart: unless-stopped`;
- `worker`: тот же образ, `python -m app.cli worker`, `restart: unless-stopped`;
- обязательные секреты без значений по умолчанию, с понятной ошибкой:
  `JWT_SECRET`, `ADMIN_PASSWORD`, `POSTGRES_PASSWORD`
  (`${VAR:?задайте VAR в .env}`); `DATABASE_URL` собирается из
  `POSTGRES_PASSWORD`;
- `CORS_ORIGINS` по умолчанию `https://iit-app.ru,https://localhost`
  (`https://localhost` — origin Android-приложения Capacitor);
  `PUBLIC_APP_URL` по умолчанию `https://iit-app.ru`;
- остальные переменные — как в `x-backend-env` разработки (VAPID, FCM, SMTP,
  MOODLE_*, лимиты, worker).
- `docker compose -f docker-compose.prod.yml config` с примерным `.env`
  проходит; без `JWT_SECRET` — падает с понятным текстом.

### 4. Шаблон боевого окружения: `deploy/.env.prod.example`

Все переменные боевого compose с комментариями по-русски: что это, как
сгенерировать (`openssl rand -hex 32` для секретов,
`python -m app.cli generate-vapid` для VAPID), что нельзя менять после
запуска (VAPID — иначе пропадут подписки; `JWT_SECRET`/`MOODLE_ENCRYPTION_KEY`
— иначе студенты разлогинятся и сохранённые пароли Moodle не расшифруются).
Никаких настоящих значений.

### 5. Пример конфига nginx: `deploy/nginx/iit-app.ru.conf.example`

- 80 → 301 на https; 443 с путями сертификата Let's Encrypt (плейсхолдеры);
- `root` — плейсхолдер папки со сборкой фронта (`dist`);
- `location /api/` → `proxy_pass http://127.0.0.1:8000;` с заголовками
  `Host`, `X-Real-IP`, `X-Forwarded-For $proxy_add_x_forwarded_for`,
  `X-Forwarded-Proto`; `client_max_body_size` не меньше суммарного лимита
  загрузки Excel (50 МБ) с запасом; таймауты чтения под импорт (120 с);
- не кэшировать: `/sw.js`, `/index.html`, `/manifest.webmanifest`,
  `/download/` (страница скачивания APK) — `Cache-Control: no-cache`;
- `/assets/` — долгий кэш (`immutable`, у файлов хеш в имени);
- `/downloads/*.apk` — `application/vnd.android.package-archive`, `no-cache`;
- SPA: `try_files $uri $uri/ /index.html`; страница `/download/` отдаётся
  из `download/index.html` сборки;
- gzip для текста.

### 6. Release-сборка APK

- `frontend/android/app/build.gradle`: `signingConfigs.release` из файла
  `frontend/android/keystore.properties` (`storeFile`, `storePassword`,
  `keyAlias`, `keyPassword`); если файла нет — release-сборка падает с
  понятным сообщением, debug-сборка работает как раньше.
- `.gitignore` Android: `keystore.properties`, `*.jks`, `*.keystore`.
- `versionCode 2`, `versionName "1.1"`.
- `frontend/package.json`: скрипт `build:apk:release` (build → cap sync →
  `assembleRelease`), рядом с `build:apk`.
- Адрес API для APK — из `frontend/.env.production.local`
  (`VITE_API_URL=https://iit-app.ru`), файл уже игнорируется (`*.local`);
  в репозиторий не добавлять.
- `frontend/README.md`, раздел Android APK: как один раз создать ключ
  (`keytool -genkeypair …`), формат `keystore.properties`, что ключ и пароли
  нужно сохранить навсегда (без них нельзя выпустить обновление), команда
  release-сборки и путь к результату.

### 7. Проверки

- pytest бэкенда, `npm test`, `npm run build` — зелёные;
- `docker compose -f docker-compose.prod.yml config` — как в п. 3;
- `assembleDebug` без `keystore.properties` проходит; `assembleRelease` без
  него падает с понятным сообщением (если Android SDK доступен).

## Вне задачи

- `DEPLOY.md` (пишет архитектор);
- настройка конкретного сервера, смена `JWT_SECRET` на проде (решает Лёша);
- закрытие резервной регистрации.

## Вопросы к архитектору

1. В требованиях одновременно заданы `FORWARDED_ALLOW_IPS="*"` и
   `X-Forwarded-For $proxy_add_x_forwarded_for`. Uvicorn 0.38.0 при доверии
   `*` выбирает первый адрес цепочки: проверено, для
   `203.0.113.99, 198.51.100.42` возвращает `203.0.113.99`. Посетитель
   может сам прислать первый XFF и обойти IP-лимиты даже при loopback-порте.
   Разрешаете заменить заголовок nginx на `$remote_addr` (nginx — первый
   публичный прокси, Cloudflare нет) либо уточнить доверенные адреса?
   Пока конфиги оставлены строго по требованиям, своей обработки XFF нет.
2. `backend/Dockerfile` содержит `COPY . .`, а `backend/.dockerignore`
   не исключает `secrets/`. Значит, при сборке из рабочей папки ключи могут
   попасть в слой образа независимо от read-only-монтирования в compose.
   Разрешаете добавить `secrets/` в `.dockerignore`? Файлы секретов не читал
   и не менял; эту дополнительную проблему не исправлял вне требований.

**Ответы архитектора (20.11.2026):** оба исправления приняты и внесены при
приёмке. 1 — nginx перезаписывает заголовок: `X-Forwarded-For $remote_addr`
(nginx — единственный прокси перед бэкендом). 2 — `secrets/` добавлен в
`backend/.dockerignore`.

## Отчёт

### Сделано

- `backend/Dockerfile`: добавлен `--proxy-headers`, список доверенных прокси
  uvicorn получает из `FORWARDED_ALLOW_IPS`, без собственного разбора заголовков.
- `backend/tests/test_proxy_headers.py`: пять проверок через настоящий
  `uvicorn.Config.load()` и ASGITransport без сети/Docker. Параметры запуска
  берутся из Dockerfile; проверены localhost по умолчанию, недоверенный
  адрес, явно заданный прокси и `*`. До правки Dockerfile тесты падали, после — проходят.
- `docker-compose.yml`: передаются `MOODLE_ENCRYPTION_KEY` и `MOODLE_BASE_URL`.
- `docker-compose.prod.yml`: самостоятельный compose, единый образ backend/worker,
  без исходников в томах; только secrets:ro, Postgres без опубликованных портов,
  прежний том postgres_data, API на loopback, обязательные секреты, restart,
  production CORS/PUBLIC_APP_URL и все переменные dev x-backend-env.
- `deploy/.env.prod.example`: все настраиваемые переменные, русские пояснения,
  генерация секретов/VAPID и предупреждения о постоянстве ключей; настоящих секретов нет.
- `deploy/nginx/iit-app.ru.conf.example`: HTTPS/редирект, API-прокси, 60 МБ/120 с,
  SPA и отдельная download-страница, политики кэширования/APK MIME, gzip.
- `frontend/android/app/build.gradle`: release-подпись из keystore.properties,
  проверка наличия файла/полей/ключа только для release; версия 2 / 1.1.
- `frontend/android/.gitignore`: исключены keystore.properties, *.jks, *.keystore.
- `frontend/package.json`: добавлен build:apk:release.
- `frontend/README.md`: изменён только раздел Android APK согласно явному
  требованию п. 6: production API, создание и хранение ключа, формат настроек,
  команда и путь release APK.

### Проверки

- Бэкенд из backend: `.venv\Scripts\python -B -m pytest -q -p no:cacheprovider
  --basetemp <TEMP>/pytest` — **312 passed, 35 skipped**, 3 предупреждения
  зависимостей. Пропуски — сквозные проверки, которым нужен рабочий Excel.
  После уточнения аннотаций повторно проверен новый модуль: **5 passed**.
- `npm test` из frontend — **20 passed**. Из-за ошибки запуска стандартной
  оболочки использован npm CLI через node с `--script-shell` PowerShell.
- `npm run build` проверен на копии фронтенда в системном TEMP, чтобы
  tsbuildinfo и временный конфиг Vite не создавались в репозитории.
  Обе проверки TypeScript прошли; штатный загрузчик конфига Vite остановился
  на `Cannot read directory "../../../../..": Access is denied`.
  Дополнительно тот же vite.config.ts транспилирован в TEMP и загружен
  через `vite.build({ ...config, configFile: false })`: **успешно**,
  включая download/index.html, manifest и service worker (13 precache entries).
  Штатная команда целиком зелёной в этой среде не подтверждена.
- Production и dev compose: **config --quiet проходит** с отдельным тестовым
  env в TEMP. Для каждого из JWT_SECRET, ADMIN_PASSWORD, POSTGRES_PASSWORD
  проверено отсутствие: код 1 и сообщение `задайте VAR в .env`.
  Дополнительно проверена JSON-модель compose: loopback API, отсутствие
  портов Postgres, только secrets:ro, общий образ, restart всех сервисов,
  передача всех переменных разработки. Использован установленный
  docker-compose.exe (Compose v5.0.1) напрямую: docker compose не находил
  плагин из-за недоступного пользовательского Docker config; DOCKER_CONFIG
  для проверки направлен в TEMP. Docker daemon и сеть не требовались.
- Android: доступны JDK 21, SDK API 36 и локальный Gradle 8.14.3. Проверки
  выполнены на копии проекта без keystore.properties/google-services.json
  в TEMP, с --offline, отдельными кэшами и чтением локального кэша зависимостей.
  `assembleRelease` ожидаемо падает в :app:validateReleaseSigning:
  «Для release-сборки создайте frontend/android/keystore.properties
  (storeFile, storePassword, keyAlias, keyPassword).»
  `assembleDebug` проходит конфигурацию без ключа, доходит до
  :capacitor-android:compileDebugJavaWithJavac и падает на AccessDeniedException
  при доступе к JAR SDK/кэша. Успешная debug-сборка в этой среде не подтверждена.
- `git check-ignore` подтвердил исключения для ключей и .env.production.local;
  `git diff --check` — без ошибок.

### Ограничения и повторная проверка

- Перед приёмкой повторить штатные `npm run build` и `assembleDebug`
  в среде с рабочими правами доступа. Подписанный release с настоящим ключом
  не собирался: ключи не создавались и не запрашивались.
- nginx -t и запуск контейнеров/миграций на сервере не выполнялись.
  Проверена конфигурация Compose, образы не собирались: pip в Dockerfile
  требует сети, которой нет. Доставку SMTP/Web Push/FCM и HTTPS на настоящем
  сервере не проверял; для них нужен доступ к сети и конфигурация сервера.
- Два обнаруженных риска вынесены в «Вопросы к архитектору» выше.
- Новых зависимостей нет. Новые рабочие команды: `npm run build:apk:release`,
  `docker compose -f docker-compose.prod.yml --env-file <подготовленный-env> config`.
- Временные env, копии проектов, артефакты сборок и кэши — только в системном
  TEMP (каталог csu-deploy-009-*). Репозиторные .env, backend/secrets и
  google-services.json не изменялись; .env.production.local не создавался.
  DEPLOY.md и существующие посторонние файлы не менялись. Коммитов нет.

### Приёмка (архитектор, 20.11.2026)

- Внесено по вопросам исполнителя: nginx перезаписывает `X-Forwarded-For`
  (`$remote_addr`); `secrets/` исключён из образа (`backend/.dockerignore`).
- Исправлено: в боевом compose `backend` и `worker` собирали один тег
  одновременно — сборка падала «image already exists». Теперь собирает
  только `backend`, `worker` берёт образ с `pull_policy: never`.
- В шаблон `.env` добавлено: на работающем проде `JWT_SECRET` переносится
  без изменений, `MOODLE_ENCRYPTION_KEY` не задаётся, `POSTGRES_PASSWORD` —
  текущий пароль существующей базы (решение Лёши 20.11.2026).
- Проверено: pytest 312 passed; `npm test`, `npm run build`; `assembleDebug`;
  `assembleRelease` без ключа — понятная ошибка, с одноразовым тестовым
  ключом — подписанный APK (ключ удалён). Боевой compose поднят отдельным
  проектом с тестовыми секретами: API только на 127.0.0.1, у базы портов
  наружу нет, `/health` отвечает, worker работает, в образе нет `secrets/`
  и `.env`; без `JWT_SECRET` — отказ с понятной ошибкой. Тестовый проект
  удалён вместе со своим томом.

### После ответов администратора (21.11.2026)

Прод работает без Docker (systemd + venv релиза, PostgreSQL на сервере),
поэтому `docker-compose.prod.yml`, `deploy/.env.prod.example` и Docker-пример
nginx удалены. Вместо них — `deploy/systemd/` (worker и drop-in бэкенда),
`deploy/env.additions.example` и `DEPLOY.md` под этот сервер. IP посетителя
на проде определяется верно и без правок: uvicorn доверяет только
`127.0.0.1` (nginx) и берёт правый недоверенный адрес из `X-Forwarded-For`.
`versionCode` поднят до 4: опубликован 1.1.1 (versionCode 3), подписанный
ключом `csu-release-key.jks`. Проверено: venv из `requirements.txt` на
Python 3.13 (Debian trixie) ставится, приложение импортируется; правки nginx
проходят `nginx -t` и дают `no-cache` для `index.html` и `/download/`.
