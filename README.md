# Skills

Публичный каталог user-facing skill'ов CloudClaw — Telegram-бота с персонализированными AI-инстансами. Каждый skill лежит в своей папке с исполнимым `SKILL.md`; companion-файлы (например, инструкции для ассистента в другом контексте) — в подпапках рядом.

## skill-creator

Skill'ы здесь создаются и валидируются с помощью `skill-creator` из [`openclaw/openclaw`](https://github.com/openclaw/openclaw/tree/main/skills/skill-creator). Он подключён как git submodule в папку `skill-creator/` с sparse-checkout только на `skills/skill-creator/`.

**После первого клона репы:**

```bash
git submodule update --init skill-creator
cd skill-creator
git sparse-checkout set --no-cone '/skills/skill-creator/'
git read-tree -mu HEAD
cd ..
```

**Актуальная точка входа:** `skill-creator/skills/skill-creator/SKILL.md`.

**Обновление до свежего upstream:**

```bash
cd skill-creator
git fetch origin
git checkout origin/main
cd ..
git add skill-creator
git commit -m "Bump skill-creator to <short-sha>"
```

## Формат SKILL.md

- Обязательный YAML frontmatter с полями `name` (kebab-case) и `description` — в `description` перечисляй триггер-фразы, по которым модель должна автоматически вызвать skill.
- Тело — императив от второго лица («позови endpoint», «выдай конфиг», «дождись подтверждения»).
- Никаких tradeoff'ов, rationale, «почему так» — только рецепт.
- Всё, что можно убрать без потери способности выполнить задачу — убираем. Целевая длина — до 500 строк.

Эталонный пример: [`cloudclaw-migration-import/SKILL.md`](cloudclaw-migration-import/SKILL.md).

## Чего не должно быть в скилле

- Секретов (токенов, API-ключей, credentials) — в рантайме всё берётся из токена юзера на поде.
- Внутренних архитектурных рассуждений, tradeoff'ов, планов развития.
- Ссылок на приватные репо, внутренние дашборды, закрытые вики.
- Design notes в стиле «почему мы так решили», «в будущем перейдём на Z».

Правило: **если это не помогает ассистенту выполнить задачу прямо сейчас — этому не место в `SKILL.md`.**

## Структура папки скилла

```
<skill-name>/
├── SKILL.md                 # основной исполнимый skill (YAML frontmatter + императив)
├── <companion>/             # (опционально) подпапка с companion-скиллом
│   └── SKILL.md
├── scripts/                 # (опционально) исполняемые скрипты
├── references/              # (опционально) reference-доки, которые skill подгружает по мере необходимости
└── assets/                  # (опционально) шаблоны, иконки, фиксированные артефакты
```

Любой файл, до которого дотягивается `SKILL.md` (по пути или по ссылке), должен лежать в папке скилла рядом.

## Соглашение по именам

- Папка скилла — `kebab-case`, по смыслу (`site-publishing`, а не `site-publishing-skill`). Если скилл — одна половина пары, работающая в связке с companion'ом в другом контексте (инстансе, платформе), полезно namespace'нуть имя по продукту — тогда обе половины сразу читаются как пара (`cloudclaw-migration-import` + `cloudclaw-migration-export`).
- Главный файл внутри — всегда `SKILL.md`.
- Companion-скилл для другого контекста — подпапка с собственным `SKILL.md` (пример: `cloudclaw-migration-import/old-instance-export/SKILL.md`).
