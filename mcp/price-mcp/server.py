from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP


BASE_DIR = Path(__file__).resolve().parent
PRICES_FILE = BASE_DIR / "prices.json"

HOST = "127.0.0.1"
PORT = 8888


mcp = FastMCP(
    name="Construction Prices",
    instructions=(
        "Справочный MCP-сервер для аудита строительных смет. "
        "Предоставляет перечень поддерживаемых строительных работ, "
        "их единицы измерения и эталонные цены."
    ),
    host=HOST,
    port=PORT,
)


def load_supported_works() -> list[dict[str, Any]]:
    """Загрузить справочник поддерживаемых работ."""

    if not PRICES_FILE.exists():
        raise FileNotFoundError(
            f"Не найден файл справочника: {PRICES_FILE}"
        )

    with PRICES_FILE.open("r", encoding="utf-8") as file:
        data = json.load(file)

    if not isinstance(data, list):
        raise ValueError(
            "prices.json должен содержать JSON-массив"
        )

    return data


@mcp.tool(
    name="get_supported_works",
    description=(
        "Возвращает полный справочник поддерживаемых строительных работ. "
        "Для каждой работы возвращаются стабильный ID, каноническое название, "
        "единица измерения и эталонная цена. "
        "Используй этот инструмент при проверке стоимости работ в смете. "
        "Сопоставь название работы из сметы с позицией справочника по смыслу, "
        "даже если формулировки не совпадают дословно."
    ),
)
def get_supported_works() -> list[dict[str, Any]]:
    return load_supported_works()


if __name__ == "__main__":
    print(f"MCP server: http://{HOST}:{PORT}/mcp")

    mcp.run(
        transport="streamable-http"
    )
