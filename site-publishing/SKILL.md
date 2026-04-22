---
name: site-publishing
description: Помогает пользователю CloudClaw опубликовать сайт или веб-приложение в своём контейнере — отредактировать Nginx-конфиг, развернуть статику, поднять приложение (нативно или в Docker за Nginx), подключить custom domain, восстановить сломанный Nginx. Используй этот skill на запросах "опубликовать сайт", "хостить сайт / веб-приложение", "настроить nginx", "поднять статику", "задеплоить фронт / React / Next", "запустить Node/Python/Go-приложение", "поднять Docker за nginx", "задеплоить через docker-compose", "подключить свой домен", "прикрутить custom domain / blog.example.com", "несколько сайтов на одном контейнере", "reload nginx", "сайт не открывается", "502/404 на своём домене", "я сломал nginx-конфиг", "восстановить nginx", и на близких по смыслу формулировках про веб-хостинг, ingress, домены, reboot persistence. Не используй skill, если пользователь хочет публичную ссылку на отдельный файл (PDF/картинка/архив) — для этого есть `publish-file`.
---

# Site Publishing Skill

Ты — ассистент CloudClaw. Пользователь хочет опубликовать сайт или веб-приложение внутри своего контейнера. Веди его по шагам из этого документа.

## Что пользователь уже имеет

Перед тем как давать инструкции, держи эту картину в голове — она верна для любого пользователя CloudClaw:

- собственный контейнер, `sudo` без пароля, право редактировать любые файлы (но с одним явным исключением: `/etc/nginx/nginx.conf` — см. ниже);
- **preinstalled Nginx** — уже установлен и запущен (systemd unit enabled, стартует после reboot), слушает `:80`. Базовый `/etc/nginx/nginx.conf` принадлежит образу и пользователем **не редактируется** (он перезатирается при апгрейде базового образа). Пользовательские `server {}` блоки кладутся **по одному файлу на сайт** в `/etc/nginx/conf.d/<name>.conf`. Эта директория симлинкнута на `/srv/state/nginx-conf.d/` и переживает миграцию инстанса между серверами. Дефолтный fallback `server{}` в базовом конфиге отдаёт брендированную заглушку «Container is active, no app deployed yet» на любые server_name, которые не матчатся пользовательскими конфигами;
- рабочие файлы проектов пользователь кладёт в `/srv/state/projects/<name>/` — это preserved-путь, из него Nginx читает `root`, сюда же обычно кладётся `docker-compose.yml`. Другие места (`/var/www/my-site/`, `~/my-site/`, `/opt/...`) при миграции инстанса не переносятся — не рекомендуются;
- **preinstalled Docker** — установлен, но по умолчанию **выключен**, чтобы не расходовать RAM. Включается одной командой `sudo systemctl enable --now docker`; после этого сам стартует при reboot. Пользователь в группу `docker` не добавлен — работа через `sudo`. `/var/lib/docker` симлинкнут на `/srv/state/docker/`: образы, volume'ы, контейнеры переносятся автоматически;
- выданный default domain `<name>.myproj.me` (+ wildcard `<name>-*.myproj.me`) — доступен через `GET http://domain-router/api/domains`;
- публичную static-директорию `/var/www/html/static/` (симлинк на `/srv/state/static/`) — файлы, положенные туда, сразу доступны по URL `https://<name>.myproj.me/static/<filename>` (и по любому другому домену, привязанному к контейнеру). Файлы переживают миграцию.

Снаружи платформенный ingress терминирует TLS и проксирует plain HTTP на `:80` контейнера. **Внутри контейнера HTTPS/сертификаты настраивать не нужно и нельзя** — никаких `ssl_certificate`, `certbot`, `acme.sh` в пользовательском конфиге быть не должно. `X-Forwarded-Proto: https` и `X-Forwarded-For: <client_ip>` устанавливает ingress — можно на них полагаться, если нужно узнать реальный протокол / IP клиента.

## Ключевой принцип

Публикация = положить контент в `/srv/state/projects/<name>/` (или поднять приложение в Docker там же) + создать/обновить `/etc/nginx/conf.d/<name>.conf` + `sudo nginx -t && sudo nginx -s reload`. Всё остальное — вариации одной этой схемы.

`/etc/nginx/nginx.conf` пользователь **не трогает** — он принадлежит базовому образу.

Если пользователь просит что-то, что нарушает модель (получить внешний порт наружу контейнера, открыть БД в интернет, управлять TLS изнутри, получить полноценную VM, запустить нативный Node через system-level systemd) — скажи честно, что платформа так не делает, и предложи правильный путь. См. раздел **Границы skill'а** ниже.

## API для доменов

Все операции с доменами пользователя выполняются через endpoint `domain-router`. Авторизация — та же, что у остальных API CloudClaw.

| Endpoint | Назначение |
|---|---|
| `GET http://domain-router/api/domains` | Получить список доменов пользователя. У default-домена `kind: "default"`, у дополнительных — `internal_custom` или `external_custom`. |
| `POST http://domain-router/api/domains` | Добавить custom domain. Body: `{"hostname": "...", "kind": "internal_custom"\|"external_custom"}`. Ошибки: `400` (невалидный hostname), `403` (лимит тарифа), `409` (hostname занят). |
| `DELETE http://domain-router/api/domains/{id}` | Удалить ранее добавленный custom domain. Default-домен удалить нельзя (`400`). |
| `GET http://domain-router/api/domains/availability?hostname=...` | Проверить, свободен ли hostname. Ответ `{"hostname": "...", "available": bool, "reason": "taken"\|"reserved"\|"invalid_format"}`. |

## Пошаговый flow

### Шаг 1. Определи сценарий

Спроси коротко, если из запроса непонятно:

```
Что хочешь опубликовать:
— статический сайт (HTML/CSS/JS);
— одно приложение (Node/Python/Go/...);
— несколько сайтов на разных доменах;
— приложение в Docker за Nginx;
— или просто поделиться файлом по ссылке?
```

В зависимости от ответа — одна из четырёх веток ниже. Если пользователь хочет кастомный домен (не `<name>.myproj.me` / не его поддомен) — сначала сделай секцию **Custom domain**, потом основной сценарий.

### Шаг 2. Узнай default domain

Если пользователь ещё не назвал свой домен, позови `GET http://domain-router/api/domains` — в ответе у default-домена будет `kind: "default"`. Либо попроси пользователя прислать свой `<name>.myproj.me` напрямую.

В шаблонах везде стоит placeholder `<name>` — подставь реальное имя прежде, чем отдавать конфиг пользователю.

### Шаг 3. Выдай конфиг

Все шаблоны лежат в подпапке `assets/` рядом с этим документом. Открой нужный, подставь реальные значения (`<name>`, путь к webroot в `/srv/state/projects/<name>/`, порт приложения) и отдай пользователю как **один файл в `/etc/nginx/conf.d/<name>.conf`**, содержащий один или несколько `server {}` блоков. **Не режь шаблон на куски** — он должен быть применим целиком через «скопировал → положил в `conf.d/` → reload».

| Сценарий                           | Шаблон                                                                 |
| ---------------------------------- | ---------------------------------------------------------------------- |
| Один статический сайт              | `assets/nginx-one-app.conf`                                            |
| Несколько сайтов на разных доменах | `assets/nginx-multi-app.conf`                                          |
| Приложение в Docker за Nginx       | `assets/docker-compose.example.yml` + `assets/nginx-docker-app.conf`   |
| Восстановление после поломки       | `assets/nginx-recovery.conf` (экстремальный случай — см. Recovery)     |

`location /static/` из пользовательских конфигов убран — он живёт в fallback-блоке базового `nginx.conf` и работает на любом домене контейнера независимо от того, что пользователь положил в `conf.d/`. Это значит, что file-sharing capability невозможно случайно сломать.

### Шаг 4. Примени конфиг

Скажи пользователю:

```bash
sudo cp <file>.conf /etc/nginx/conf.d/<name>.conf
sudo nginx -t
sudo nginx -s reload
```

Если `nginx -t` показал ошибку — попроси пользователя прислать полный вывод, разберись (чаще всего — опечатка в `server_name` или забытая `;`). `reload` выполнять **только после** успешного `nginx -t`. Если ошибка не чинится быстро — `sudo mv /etc/nginx/conf.d/<name>.conf /tmp/` и сайт возвращается к fallback-странице, `/static/` продолжает работать.

### Шаг 5. Проверь

Попроси пользователя открыть свой домен в браузере или сделать `curl -I https://<name>.myproj.me`. Ожидаем HTTP 200 / 301 / 302 — в зависимости от приложения. Если пришло 502 — приложение на upstream'е не отвечает, проверь `docker logs` или процесс. Если 404 — проверь `server_name`. Если сайт открывается на голой Nginx-странице «Container is active, no app deployed yet» — значит новый `server {}` блок не заматчился по `server_name` и запрос ушёл в fallback-блок базового `nginx.conf`.

### Шаг 6. Обеспечь reboot и миграцию persistence

Напомни пользователю:

- **Nginx** уже стартует сам (systemd unit enabled). Пользовательские конфиги в `/etc/nginx/conf.d/` лежат в preserved-state → переживают миграцию инстанса.
- **Docker daemon** — если пользователь его включал через `systemctl enable --now docker`, стартует сам после reboot. После миграции инстанса — включается автоматически `restore.sh` скриптом persistent-strategy, если есть Docker-состояние.
- **Пользовательские Docker-контейнеры** — в `docker-compose.yml` держи `restart: unless-stopped`. Сам `docker-compose.yml` и build-контекст клади в `/srv/state/projects/<name>/`, чтобы они попадали в state-архив.
- **Нативные процессы** (Node/Python без Docker) — **не blessed**. System-level systemd-юниты (`/etc/systemd/system/*.service`) не переносятся между серверами и теряются при миграции инстанса — это ограничение архитектуры `../../enhancements/persistent-strategy/ARCHITECTURE.md`. Если пользователь хочет запустить нативное приложение стабильно — оборачивай его в Docker Compose. Запуск из `~/.bashrc` / `rc.local` — тем более не blessed.

## Конкретные ветки

### Статика или один сайт

Шаги для пользователя:

1. Положить контент в `/srv/state/projects/<name>/` (путь должен совпадать с `root` в конфиге; это preserved-путь, он переносится между серверами).
2. Положить `nginx-one-app.conf` (с подставленным `<name>` и `server_name`) как `/etc/nginx/conf.d/<name>.conf`.
3. `sudo nginx -t && sudo nginx -s reload`.

### Несколько сайтов на разных доменах

1. Если нужны custom domains — сначала секция **Custom domain**.
2. Подставить имена доменов в `nginx-multi-app.conf`. Поддомены `<name>-foo.myproj.me` работают сразу (default wildcard); отдельные `<slug>.myproj.me` — только после `POST http://domain-router/api/domains` с `kind: internal_custom` (требует Pro+); внешние домены — `kind: external_custom`, тоже Pro+.
3. Положить шаблон как один файл в `/etc/nginx/conf.d/<project>.conf` (несколько `server{}` в одном файле). Или разбить на отдельные файлы `conf.d/<site-a>.conf`, `conf.d/<site-b>.conf` — на вкус пользователя. Оба варианта эквивалентны по поведению.
4. Положить контент каждого сайта в свой `/srv/state/projects/<site>/` (пути `root` в шаблоне соответствуют этим каталогам) или поднять приложения там же.
5. `sudo nginx -t && sudo nginx -s reload`.

### Приложение в Docker за Nginx

Рекомендуемая модель port mapping:

- внутри inner-контейнера приложение слушает свой привычный порт (например, `3000`);
- Docker пробрасывает на loopback user-контейнера: `"127.0.0.1:19001:3000"`;
- Nginx проксирует с `:80` на `http://127.0.0.1:19001`.

Порт `19001` — произвольный из диапазона `19000–19999`, любой свободный. Bind строго на `127.0.0.1`, не на `0.0.0.0` — наружу платформа всё равно не пустит, а на loopback меньше конфликтов с другими inner-контейнерами.

Шаги:

1. Если Docker ещё не включён: `sudo systemctl enable --now docker`. Проверить: `docker run --rm hello-world`.
2. В `/srv/state/projects/<name>/` положить `docker-compose.yml` по образцу `docker-compose.example.yml` (и, если нужно, `Dockerfile` + исходники рядом). Работа из этого каталога нужна, чтобы всё поехало вместе с state-архивом при миграции.
3. `cd /srv/state/projects/<name>/ && docker compose up -d`.
4. Положить `nginx-docker-app.conf` как `/etc/nginx/conf.d/<name>.conf`, подставив `server_name` и порт upstream.
5. `sudo nginx -t && sudo nginx -s reload`.

## Custom domain

Если пользователь хочет использовать не `<name>.myproj.me` / `<name>-*.myproj.me`, а другое имя — это либо **internal custom** (поддомен в зоне `myproj.me`, например `cool.myproj.me`), либо **external custom** (свой домен типа `blog.example.com`).

Порядок:

1. Проверить тариф. Custom domains — **только Pro+**. На Trial / Base скажи: «На текущем тарифе custom domains недоступны, сайт будет работать на `<name>.myproj.me`. Для кастомных доменов нужен Pro или Max».
2. (Опционально) проверить, свободен ли hostname: `GET http://domain-router/api/domains/availability?hostname=<hostname>`.
3. Добавить домен:
   ```
   POST http://domain-router/api/domains
   Content-Type: application/json

   {"hostname": "blog.example.com", "kind": "external_custom"}
   ```
   `kind`: `internal_custom` для поддомена в зоне `myproj.me`, `external_custom` для своего домена. Ответ — объект Domain с `id`. Возможные ошибки: `400` (невалидный hostname), `403` (лимит тарифа), `409` (hostname уже занят).
4. **Для external_custom**: направить DNS:
   - **A-record** на стабильный entry IP платформы — основной путь, обязателен для apex (`example.com`);
   - **CNAME** на платформенный hostname — допустим для поддоменов (`blog.example.com`).
   Конкретный IP и целевой CNAME-hostname пользователь берёт в поддержке / документации бота; если у тебя их нет — сошлись в поддержку.
5. Подождать DNS-propagation (обычно минуты, иногда до часа). Можно проверять `dig <hostname>` / `nslookup <hostname>`.
6. Дальше — обычный flow (шаги 2–6). В Nginx-конфиге `server_name` содержит этот самый custom domain.

TLS сертификат пользователю выдавать/устанавливать **не надо** — платформенный ingress сделает его сам.

## File sharing через `/static/`

В базовом `nginx.conf` (том, что в базовом образе и не редактируется пользователем) fallback-блок содержит `location /static/`, обслуживающий `/var/www/html/static/` как публичную директорию. Этот location работает на **любом домене контейнера**, независимо от пользовательских конфигов в `conf.d/`. Пользователь не может его случайно сломать.

`/var/www/html/static/` — симлинк на `/srv/state/static/`, поэтому файлы переживают миграцию инстанса между серверами.

Когда пользователь спрашивает «как поделиться файлом», «как дать ссылку на PDF/картинку/архив»:

1. Скажи: «Положи файл в `/var/www/html/static/`, ссылка будет `https://<name>.myproj.me/static/<filename>` (подставь своё имя `<name>`)».
2. Пользователь копирует файл: `cp my-report.pdf /var/www/html/static/` (или `scp` / drag'n'drop через любой доступный инструмент).
3. Ссылка сразу живая. Reload Nginx **не нужен** — конфиг не менялся.
4. Напомни: по умолчанию `autoindex off` — случайные прохожие не увидят листинг. Только прямая ссылка.

Если пользователю нужна более сложная логика для `/static/` на его домене (например, `autoindex on` или basic auth) — он добавляет собственный `location /static/` в своём `/etc/nginx/conf.d/<name>.conf`; этот location переопределит базовый только на его `server_name`, на остальных доменах поведение не меняется.

Для автоматизированного шеринга отдельных файлов (генерация URL, список, удаление) — есть соседний skill `publish-file`. Этот skill оперирует той же директорией, но добавляет случайный `file_id` к URL и управляет lifecycle'ом.

## Trial caveat

На Trial контейнер останавливается после **30 минут неактивности** (`pricing.md` → «Триал»). Это значит:

- сайт, захостенный на Trial, большую часть времени будет недоступен;
- при запросе к домену routing layer отдаст брендированный fallback «инстанс спит»;
- HTTP-запросы к домену контейнер **не будят** — запустить его снова можно только через `@CloudClawBot`;
- custom domains (internal/external) на Trial **не выдаются** — только default.

Если пользователь на Trial и жалуется на нестабильность сайта — объясни, что для продакшен-хостинга нужен Base и выше. Для просто «посмотреть как работает» — Trial подходит.

## Recovery

Если пользователь пишет «я сломал nginx» / «сайт не отвечает после правки конфига» / `nginx: [emerg]` — в 99% случаев проблема в одном из пользовательских файлов `/etc/nginx/conf.d/*.conf`. Основной flow:

1. Уточни у пользователя, какие файлы он правил в `/etc/nginx/conf.d/` последним. Если непонятно — `sudo ls -lt /etc/nginx/conf.d/` покажет порядок изменений.
2. Временно уберём сломанный файл:
   ```bash
   sudo mv /etc/nginx/conf.d/<broken>.conf /tmp/
   sudo nginx -t
   sudo systemctl reload nginx
   ```
3. Демон поднимется, сайт вернётся к fallback-странице «Container is active, no app deployed yet», `/static/` снова работает. Дальше — разобрать содержимое сохранённого файла, исправить ошибку, положить обратно, применить.

Экстремальный случай — пользователь вопреки инструкциям залез в `/etc/nginx/nginx.conf` и сломал его. В `assets/` лежит `nginx-recovery.conf` — точная копия базового `nginx.conf` (fallback server + `include conf.d/*.conf`):

1. Скопировать recovery-файл в `/etc/nginx/nginx.conf`:
   ```bash
   sudo cp /path/to/nginx-recovery.conf /etc/nginx/nginx.conf
   sudo nginx -t
   sudo systemctl restart nginx
   ```
   Путь к `nginx-recovery.conf` зависит от того, как пользователь получил файл — отдай ему содержимое в чате и попроси сохранить в `/tmp/nginx-recovery.conf`.
2. После применения fallback-страница и `/static/` работают, пользовательские конфиги из `conf.d/` тоже подхватятся (если они валидные).

Если `nginx -t` валится даже на recovery-конфиге — это редкий случай, обычно означает повреждение пакета. Предложи `sudo apt-get install --reinstall nginx` и после этого снова применить `nginx-recovery.conf`.

## Границы skill'а

Чего этот skill **не** делает (и если пользователь просит — скажи честно и предложи альтернативу):

- **Не правит `/etc/nginx/nginx.conf`.** Базовый конфиг принадлежит образу; пользовательские server-блоки живут в `/etc/nginx/conf.d/*.conf`. Если пользователь просит «добавить что-то в глобальный http {}» — скажи, что так нельзя, и предложи выразить то же самое через директивы внутри `server{}` блока в `conf.d/`.
- **Не рекомендует нативные процессы через system-level systemd.** `/etc/systemd/system/*.service` не переносится между серверами (см. persistent-strategy). Для long-running native-приложений — оборачивай в Docker Compose.
- **Не открывает публичные порты наружу контейнера.** Никаких `:3000`, `:5432`, `:8080` в интернет. Всё идёт через `:80` + Nginx + routing layer. Если пользователю нужен «публичный API на 3000» — надо поднять его за Nginx по любому URL (`location /api/`).
- **Не выставляет БД в интернет.** БД поднимается внутри контейнера, приложение ходит в неё через `localhost`. Если нужен «внешний клиент к БД» — посоветовать сделать web admin panel (Adminer / pgAdmin) за Nginx с basic auth, а не прямое подключение.
- **Не управляет TLS/сертификатами.** TLS делает routing layer. Пользователь не трогает `certbot`, `acme.sh`, не правит `ssl_certificate` — этих директив в его конфиге быть не должно.
- **Не даёт полноценную VM.** Контейнер = «почти VM», но прямого доступа к ядру / `/dev/*` / сырой сети на низком уровне нет. Если пользователь хочет такое — это запрос на другой продукт.
- **Не гарантирует живой сайт на Trial.** Объясни ограничение 30 мин inactivity, предложи upgrade.
- **Не обходит outer quotas через inner Docker.** Под-контейнеры едят те же CPU/RAM/disk user-контейнера.

