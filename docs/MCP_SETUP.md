# Настройка price-mcp

Construction Audit MVP не содержит встроенного прайс-листа. Каталог работ и цен предоставляет отдельный MCP-сервер `price-mcp`, который необходимо запустить на том же ПК, что и Ouroboros.

## Почему сервер отдельный

Так цены можно обновлять независимо от кода аудита, а скилл получает только явный, сохранённый и проверяемый каталог. Если MCP недоступен, процесс завершается ошибкой `price_catalog_unavailable` и не подставляет цены из памяти модели.

## Требования price-mcp

Фактический проект использует:

- Python `>=3.12`;
- пакет `mcp>=1.27,<2`;
- файл `prices.json` рядом с `server.py`;
- host `127.0.0.1`;
- port `8888`;
- transport `streamable-http`;
- единственный tool `get_supported_works`.

## Установка и запуск

MCP-сервер включён в этот monorepo. Из корня репозитория выполните:

```bash
cd mcp/price-mcp
uv sync
uv run python server.py
```

Если окружение уже подготовлено без `uv`:

```bash
cd mcp/price-mcp
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install "mcp>=1.27,<2"
python server.py
```

Ожидаемое сообщение:

```text
MCP server: http://127.0.0.1:8888/mcp
```

Не закрывайте этот процесс во время работы скилла. Для постоянной эксплуатации настройте пользовательский service manager вашей ОС и запускайте процесс из каталога `price-mcp`, чтобы рядом был доступен `prices.json`.

## Настройка Ouroboros

В **Settings → Advanced → MCP Servers** создайте запись:

| Поле | Значение |
|---|---|
| ID | `construction_prices` |
| Name | `Construction Prices` |
| Enabled | `true` |
| Transport | `streamable_http` |
| URL | `http://127.0.0.1:8888/mcp` |
| Auth token | пусто |
| Allowed tools | пусто либо `get_supported_works` |

Затем включите глобальный MCP client и сохраните настройки.

ID `construction_prices` обязателен: Ouroboros нормализует имя внешнего инструмента по шаблону `mcp_<server_id>__<tool>`. Скилл ожидает ровно:

```text
mcp_construction_prices__get_supported_works
```

## Проверка

Используйте кнопку Test/Refresh в карточке MCP-сервера. Проверка должна обнаружить `get_supported_works` без auth.

Если соединение не устанавливается:

- проверьте, что `server.py` всё ещё запущен;
- убедитесь, что URL заканчивается на `/mcp`;
- убедитесь, что transport в Ouroboros записан как `streamable_http`;
- проверьте, что порт `8888` не занят другим процессом;
- проверьте, что server ID равен `construction_prices`;
- обновите список tools после запуска сервера;
- проверьте, не запрещён ли tool отдельным capability/grant policy.

## Формат prices.json

Сервер возвращает JSON-массив из `prices.json`. Каждая позиция должна иметь стабильный идентификатор работы, каноническое название, единицу измерения и цену в форме, которую ожидает текущая версия скилла. Изменение схемы каталога необходимо проверять вместе с `save_price_catalog` в `core.py`.

Не указывайте валюту в пользовательских результатах, если каталог явно её не подтверждает.
