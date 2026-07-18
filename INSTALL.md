# Установка Construction Audit MVP в Ouroboros

## Требования

- установленный и запускающийся Ouroboros с поддержкой external extension skills, A2A-субагентов и HTTP MCP client;
- Python runtime для Ouroboros;
- включённый в репозиторий `price-mcp`, запускаемый отдельным процессом на том же компьютере;
- для `price-mcp`: Python 3.12+ и желательно `uv`;
- модели, которым доступны основная (`main`) и облегчённая (`light`) lanes, а также `view_image` для Vision-задач.

`openpyxl` указан в manifest скилла как dependency. Ouroboros устанавливает его в изолированное окружение скилла после успешного review.

## 1. Получить репозиторий

```bash
git clone https://github.com/MichaelDavislol/construction_audit_mvp.git
cd construction_audit_mvp
```

## 2. Скопировать payload

Определите каталог установки Ouroboros. В документации ниже он обозначен как `<OUROBOROS_HOME>` и должен содержать `data/` и `repo/`.

```bash
mkdir -p <OUROBOROS_HOME>/data/skills/external/construction_audit_mvp
cp -R skill/. <OUROBOROS_HOME>/data/skills/external/construction_audit_mvp/
```

После копирования каталог должен выглядеть так:

```text
<OUROBOROS_HOME>/data/skills/external/construction_audit_mvp/
├── SKILL.md
├── plugin.py
├── core.py
├── vision.py
├── visual.py
├── insights.py
└── report.py
```

Не копируйте локальные `.ouroboros_env`, `__pycache__`, `.pyc` или `.DS_Store` из другой установки.

## 3. Поднять price-mcp

Из корня клонированного репозитория:

```bash
cd mcp/price-mcp
uv sync
uv run python server.py
```

Подробности: [инструкция MCP](docs/MCP_SETUP.md). Сервер должен отвечать на:

```text
http://127.0.0.1:8888/mcp
```

Он должен оставаться запущенным всё время, пока выполняется аудит или генерация сметы.

## 4. Настроить MCP в Ouroboros

Откройте **Settings → Advanced → MCP Servers**:

1. включите **Enable MCP client**;
2. добавьте сервер;
3. задайте ID `construction_prices`;
4. выберите transport `streamable_http`;
5. укажите URL `http://127.0.0.1:8888/mcp`;
6. включите сервер;
7. в `allowed_tools` оставьте пустой список либо разрешите `get_supported_works`;
8. сохраните настройки и нажмите проверку/refresh.

Ожидаемое runtime-имя инструмента:

```text
mcp_construction_prices__get_supported_works
```

Если оно отличается, проверьте ID сервера: имя строится из ID, а не из отображаемого названия.

## 5. Review и включение скилла

Откройте **Skills → My skills** и найдите `construction_audit_mvp`.

1. Запустите preflight/review доступным в вашей версии Ouroboros способом.
2. Дождитесь свежего executable verdict.
3. Разрешите запрошенные manifest permissions (`tool`, `fs`) и необходимые extension/MCP grants.
4. Убедитесь, что dependency `openpyxl` установлена без ошибки.
5. Включите скилл.

Любое изменение файла payload меняет content hash. После обновления повторите review; иначе Ouroboros может отказать во включении или выполнении.

## 6. Проверить установку

Начните новый диалог и загрузите один читаемый план. Пример запроса:

> Проведи предварительный аудит по этому плану. Сначала покажи распознанную геометрию для проверки.

Для полной ветки загрузите также XLSX:

> Проверь эту смету по приложенному плану, сравни объёмы и цены и подготовь предварительный отчёт.

Нормальный workflow остановится после показа геометрии и дождётся отдельного подтверждения пользователя. Это защитный механизм, а не ошибка.

Готовые входные файлы для проверки находятся в `examples/medical-office/input/`. Ожидаемые артефакты и метрики описаны в `examples/medical-office/README.md`.

## Обновление

1. Отключите скилл в Ouroboros.
2. Замените семь файлов payload актуальными файлами из `skill/`.
3. Не переносите старое `.ouroboros_env` из репозитория.
4. Повторите review, dependency reconciliation, grants и включение.

Состояние старых jobs хранится вне payload, под `data/state/skills/construction_audit_mvp/jobs/`. Перед несовместимым обновлением сделайте резервную копию этого каталога.

## Удаление

Используйте действие удаления local/external skill в UI Ouroboros. Если удаляете вручную, сначала отключите скилл и сохраните нужные job-артефакты. Payload и job state — разные каталоги; удаление одного не всегда удаляет другой.
