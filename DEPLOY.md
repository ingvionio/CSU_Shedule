# Выкладка на прод (iit-app.ru)

Как устроен сервер (ответы администратора, 20.11.2026):

| Что | Где |
|---|---|
| ОС | Debian 13, пользователь `antigravity` (sudo без пароля). Docker и Node.js на сервере нет |
| Бэкенд | systemd `csu-backend`: код в `~/csu_schedule/backend`, настройки в его `.env`, Python — venv релиза; uvicorn на `127.0.0.1:8000` |
| Релизы | `~/csu_schedule/releases/<коммит>-<дата>/` — `venv/`, дамп базы |
| База | PostgreSQL 17 на сервере, `127.0.0.1:5432`, база `csu_schedule` |
| Фронт | `/var/www/csu_schedule` (собирается у разработчика) |
| nginx | `/etc/nginx/sites-enabled/csu_schedule`, домены iit-app.ru и illusoryorb.ru, Let's Encrypt |

```
браузер / APK ─HTTPS─► nginx ─► /var/www/csu_schedule
                         └/api─► csu-backend 127.0.0.1:8000 ─► PostgreSQL
                                 csu-worker ─► Web Push / FCM / SMTP
```

IP студентов: uvicorn по умолчанию доверяет заголовкам только от
`127.0.0.1` (это nginx) и берёт из `X-Forwarded-For` правый недоверенный
адрес — настоящий IP. Конфиг nginx для этого менять не нужно.

Файлы в репозитории:

| Файл | Куда на сервере |
|---|---|
| `deploy/systemd/csu-worker.service` | `/etc/systemd/system/csu-worker.service` |
| `deploy/systemd/10-release-venv.conf` | `/etc/systemd/system/csu-backend.service.d/10-release-venv.conf` |
| `deploy/env.additions.example` | новые строки для `~/csu_schedule/backend/.env` |

Ниже `$REL` — имя релиза, `<короткий коммит>-<ГГГГММДД>`, например
`bbf3c3d-20261121`.

## Кто что делает (выкладка уведомлений и сессии, ноябрь 2026)

Выкатывает и собирает APK — **Тоха (sadtowa)**: у него ключ подписи и доступ
к серверу.

| Кто | Что | Раздел |
|---|---|---|
| **Лёша** | передать Тохе `google-services.json` (Firebase, проект `iit-app`) | 0 |
| **Лёша** | передать Тохе ключ Firebase `firebase-service-account.json` — лично, не в общий чат; это секрет | 2.4 |
| **Лёша** | дать адрес почты для `VAPID_SUBJECT` | 2.4 |
| **Тоха** | собрать APK 1.2 своим ключом `csu-release-key.jks` и проверить подпись | 0 |
| **Тоха** | проверить, что `JWT_SECRET` на проде не `change-me`, и что нет групп-дублей | 2.1, 2.4 |
| **Тоха** | бэкап → код и venv → настройки → миграции → `csu-backend` + новый `csu-worker` → сайт с новым APK → nginx | 1–2 |
| **Тоха** | проверка: push в браузер и в APK, экзамены в расписании | 3 |
| **Лёша** | предупредить студентов: обновить приложение со страницы «Скачать для Android» (встанет поверх старого) — старое 1.1.1 работает, но без экзаменов и push | — |

Важно про загрузки после выкладки: каждая применённая загрузка расписания
(семестр, понедельная, сессия) через 2 минуты отправляет студентам этих групп
сообщение и push «Расписание обновлено» — загружать, когда это уместно.

## 0. APK — собирает владелец ключа (sadtowa)

Опубликованные версии приложения (до 1.1.1, `versionCode 3`) подписаны
ключом `csu-release-key.jks` (сертификат `CN=CSU Schedule`). Android ставит
обновление поверх установленного, только если подпись **та же**, а
`versionCode` **больше**. Поэтому APK собирает тот, у кого ключ, — ключ и
пароль никуда не пересылаются.

**Что нужно на машине:** Node.js 22+, JDK 21, Android SDK с платформой API 36
(`ANDROID_HOME` или `sdk.dir` в `frontend/android/local.properties`),
подробнее — [frontend/README.md](frontend/README.md#android-apk).

1. **Код.** Ветка `master`:
   ```bash
   git fetch && git checkout master && git pull
   ```
2. **Firebase.** Взять у Лёши `google-services.json` (проект `iit-app`) и
   положить в `frontend/android/app/`. Без него APK соберётся, но push
   работать не будет. Файл исключён из Git.
3. **Ключ.** Положить `csu-release-key.jks` в `frontend/android/` и создать
   рядом `frontend/android/keystore.properties`:
   ```properties
   storeFile=csu-release-key.jks
   storePassword=ПАРОЛЬ_ХРАНИЛИЩА
   keyAlias=csu-release-key
   keyPassword=ПАРОЛЬ_КЛЮЧА
   ```
   Имя ключа (`keyAlias`) — как при создании; посмотреть:
   `keytool -list -keystore csu-release-key.jks`.
   Формат изменился по сравнению с веткой `feature/apk-build`: читаются только
   эти четыре ключа (`keystore.file`, `keystore.password` и т. п. — нет), и
   паролей по умолчанию в `build.gradle` больше нет. `*.jks` и
   `keystore.properties` исключены из Git — перед любым коммитом проверить,
   что `git status` их не показывает.
4. **Сборка** (PowerShell, из `frontend`). Адрес API передаётся только в эту
   команду — сайт собирается без него:
   ```powershell
   npm.cmd ci
   $env:VITE_API_URL='https://iit-app.ru'; npm.cmd run build:apk:release; Remove-Item Env:VITE_API_URL
   ```
   Без `keystore.properties` сборка остановится с понятной ошибкой.
5. **Проверка** — подпись та же, что у опубликованной версии, версия 1.2:
   ```powershell
   $bt = "$env:LOCALAPPDATA\Android\Sdk\build-tools\36.1.0"
   & "$bt\apksigner.bat" verify --print-certs android\app\build\outputs\apk\release\app-release.apk   # Signer #1 certificate DN: CN=CSU Schedule, …
   & "$bt\aapt2.exe" dump badging android\app\build\outputs\apk\release\app-release.apk | Select-String "^package:"   # versionCode='4' versionName='1.2'
   ```
   Если DN другой — APK подписан не тем ключом, раздавать нельзя.
6. **Готовый файл** — `android/app/build/outputs/apk/release/app-release.apk`;
   он кладётся в сборку сайта в разделе 1 (не секрет, его скачивают студенты).

> Пароль ключа раньше был записан значением по умолчанию в `build.gradle`
> ветки `feature/apk-build`. Если репозиторий публичный, пароли стоит сменить —
> подпись при этом не меняется, обновления продолжат ставиться:
> `keytool -storepasswd -keystore csu-release-key.jks` и
> `keytool -keypasswd -alias csu-release-key -keystore csu-release-key.jks`.

## 1. Подготовка у разработчика

Из корня репозитория, ветка `master` после слияния (Git Bash):

```bash
REL=$(git rev-parse --short master)-$(date +%Y%m%d)
git archive --format=tar.gz -o backend-$REL.tar.gz master backend deploy
```

**Сайт** — собирается **после** APK из раздела 0 и **без** `VITE_API_URL`
(сайт открыт на двух доменах и ходит на `/api` своего домена). `npm run build`
пересобирает `dist`, поэтому APK копируется в него уже после сборки:

```bash
cd frontend
npm ci
npm run build
cp android/app/build/outputs/apk/release/app-release.apk dist/downloads/raspisanie-iit.apk
tar -czf ../frontend-$REL.tar.gz -C dist .
cd ..
```

Отправить на сервер:

```bash
scp backend-$REL.tar.gz frontend-$REL.tar.gz antigravity@iit-app.ru:~/csu_schedule/releases/
```

## 2. На сервере

```bash
REL=…                                   # то же имя, что выше
R=~/csu_schedule/releases/$REL
mkdir -p $R/src
tar -xzf ~/csu_schedule/releases/backend-$REL.tar.gz -C $R/src
```

### 2.1 Бэкап базы

```bash
sudo -u postgres pg_dump -Fc csu_schedule > $R/database-before.dump
pg_restore --list $R/database-before.dump | head      # дамп читается
```

Скопировать дамп **вне сервера** (у себя):
`scp antigravity@iit-app.ru:~/csu_schedule/releases/$REL/database-before.dump .`

Проверить, нет ли групп-дублей с разным написанием («ПрИ-402» и «ПрИ 402»:
бывает, если студент вошёл через Moodle раньше загрузки файла). Пустой
вывод — всё в порядке; иначе — сначала разобраться, не выкатывать:

```bash
sudo -u postgres psql csu_schedule -c "select lower(regexp_replace(name, '[\s_—–-]', '', 'g')) as key, string_agg(name || ' (#' || id || ')', ', ') from groups group by 1 having count(*) > 1;"
```

### 2.2 Новый venv

```bash
python3 -m venv $R/venv
$R/venv/bin/pip install -r $R/src/backend/requirements.txt
```

Если `python3 -m venv` ругается — `sudo apt install python3-venv`.

### 2.3 Код

Сохранить текущий код (для отката) и разложить новый поверх. В архиве нет
`.env` и `secrets/` — их копирование не трогает.

```bash
tar -czf $R/backend-before.tar.gz -C ~/csu_schedule --exclude='__pycache__' backend
cp -a $R/src/backend/. ~/csu_schedule/backend/
```

### 2.4 Настройки — только при первой выкладке push

1. Ключ Firebase передать напрямую на сервер (не через чаты):
   ```bash
   mkdir -p ~/csu_schedule/backend/secrets && chmod 700 ~/csu_schedule/backend/secrets
   # с машины разработчика:
   # scp backend/secrets/firebase-service-account.json antigravity@iit-app.ru:~/csu_schedule/backend/secrets/
   chmod 600 ~/csu_schedule/backend/secrets/firebase-service-account.json
   ```
2. Ключи VAPID — сгенерировать **один раз**:
   ```bash
   cd ~/csu_schedule/backend && $R/venv/bin/python -m app.cli generate-vapid
   ```
3. Дописать в `~/csu_schedule/backend/.env` строки из
   `deploy/env.additions.example` (VAPID, `FCM_CREDENTIALS_FILE`) и
   проверить `CORS_ORIGINS` — там нужен `https://localhost` для
   Android-приложения. **`JWT_SECRET` не менять, `MOODLE_ENCRYPTION_KEY` не
   добавлять** — иначе все студенты разлогинятся.

### 2.5 Миграции

Схема меняется только добавлением (новые таблица и колонки) — старый код с
новой схемой работает, поэтому миграции можно накатывать до перезапуска.

```bash
cd ~/csu_schedule/backend && $R/venv/bin/python -m alembic upgrade head
```

### 2.6 Переключение и worker

```bash
PREV=$(readlink -f ~/csu_schedule/releases/current 2>/dev/null)   # для отката; при первой выкладке пусто
ln -sfn $R ~/csu_schedule/releases/current
```

При **первой** выкладке — поставить systemd-файлы:

```bash
sudo cp /etc/systemd/system/csu-backend.service.d/10-release-venv.conf ~/csu_schedule/releases/10-release-venv.conf.before
sudo cp $R/src/deploy/systemd/10-release-venv.conf /etc/systemd/system/csu-backend.service.d/10-release-venv.conf
sudo cp $R/src/deploy/systemd/csu-worker.service /etc/systemd/system/csu-worker.service
sudo systemctl daemon-reload
sudo systemctl enable csu-worker
```

Каждый раз:

```bash
sudo systemctl restart csu-backend csu-worker
systemctl is-active csu-backend csu-worker
```

### 2.7 Сайт

Распаковать поверх без удаления: остаются `.well-known` (Let's Encrypt) и
старые файлы `assets/` — у открытых вкладок не сломаются ссылки.

```bash
sudo tar -xzf ~/csu_schedule/releases/frontend-$REL.tar.gz -C /var/www/csu_schedule --no-same-owner
```

### 2.8 nginx — один раз

В `/etc/nginx/sites-enabled/csu_schedule`, в **обоих** блоках `server`
с сайтом (iit-app.ru и illusoryorb.ru):

1. `client_max_body_size 20M;` → `client_max_body_size 60M;` — админка
   принимает пачку Excel до 50 МБ, сейчас большие загрузки режет nginx (413).
2. Рядом с `location = /sw.js` добавить:
   ```nginx
   location = /index.html {
       add_header Cache-Control "no-cache";
   }

   location /download/ {
       add_header Cache-Control "no-cache";
       try_files $uri $uri/ /index.html;
   }
   ```
   Иначе после выкладки браузеры какое-то время показывают старую версию
   сайта.

```bash
sudo nginx -t && sudo systemctl reload nginx
```

## 3. Проверка

```bash
curl -s https://iit-app.ru/api/v1/push/config       # public_key не null, "fcm": true
curl -s https://illusoryorb.ru/api/v1/push/config   # то же
journalctl -u csu-worker -n 30 --no-pager          # без ошибок
journalctl -u csu-backend -n 30 --no-pager
```

В админке отправить сообщение себе (группе с одним тестовым студентом):
push приходит в браузер (сайт, «Сообщения» → «Включить») и в APK; в деталях
сообщения — «Push: доставлено N из M», в журнале worker'а — строка
`Push: отправлено …`. Скачать APK со страницы «Скачать для Android» и
проверить, что он ставится **поверх** прежней версии.

## 4. Откат

```bash
sudo systemctl stop csu-worker
if [ -n "$PREV" ]; then
  ln -sfn "$PREV" ~/csu_schedule/releases/current
else
  # откат первой выкладки: вернуть прежний drop-in с путём к старому venv
  sudo cp ~/csu_schedule/releases/10-release-venv.conf.before /etc/systemd/system/csu-backend.service.d/10-release-venv.conf
  sudo systemctl daemon-reload
fi
tar -xzf $R/backend-before.tar.gz -C ~/csu_schedule
sudo systemctl restart csu-backend
```

Базу восстанавливать обычно не нужно (миграции только добавляют). Если всё
же нужно:

```bash
sudo systemctl stop csu-backend csu-worker
sudo -u postgres pg_restore --clean --if-exists -d csu_schedule $R/database-before.dump
sudo systemctl start csu-backend
```

Сайт откатывается распаковкой предыдущего `frontend-….tar.gz`.

## Заметки

- `/docs`, `/redoc`, `/openapi.json` открыты на обоих доменах — решить,
  нужны ли они публично.
- Регулярных бэкапов базы на сервере нет — стоит завести (cron +
  копия вне сервера).
- Тестовые debug-сборки APK студентам не раздавать.
