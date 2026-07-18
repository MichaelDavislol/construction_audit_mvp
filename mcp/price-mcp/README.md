# price-mcp

Локальный MCP-сервер каталога строительных работ и цен для Construction Audit MVP.

## Запуск

Требования: Python 3.12+ и `uv`.

```bash
uv sync
uv run python server.py
```

Сервер запускается на `http://127.0.0.1:8888/mcp` с transport `streamable-http` и публикует один tool:

```text
get_supported_works
```

В Ouroboros задайте server ID `construction_prices`, transport `streamable_http` и URL `http://127.0.0.1:8888/mcp`. Получившееся runtime-имя должно быть:

```text
mcp_construction_prices__get_supported_works
```

## Каталог

Данные находятся в `prices.json`. Текущая demo-версия содержит семь видов работ: грунтовку и окраску стен, устройство пола, отделку потолка, монтаж плинтуса, установку окон и дверей.

Цены являются демонстрационными справочными значениями. Валюта намеренно не указана. Для реального применения замените каталог данными из подтверждённого источника и повторно проверьте единицы измерения.
