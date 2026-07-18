from __future__ import annotations

import json
from base64 import b64encode
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from html import escape
from pathlib import Path
from typing import Any


DISCLAIMER = "Результат является предварительным автоматизированным аудитом и требует проверки специалистом"

QUANTITY_TYPES = {"quantity_overstatement", "quantity_understatement"}
PRICE_TYPES = {"price_overstatement", "price_understatement"}
TOTAL_TYPES = {"total_cost_overstatement", "total_cost_understatement"}
TYPE_LABELS = {
    "quantity_overstatement": "Количество выше контроля",
    "quantity_understatement": "Количество ниже контроля",
    "price_overstatement": "Цена выше MCP",
    "price_understatement": "Цена ниже MCP",
    "total_cost_overstatement": "Стоимость выше контроля MCP",
    "total_cost_understatement": "Стоимость ниже контроля MCP",
    "exact_duplicate": "Возможный дубликат",
    "unit_mismatch": "Несовместимая единица",
    "arithmetic_mismatch": "Несоответствие арифметики строки",
    "invalid_quantity": "Некорректное количество",
    "invalid_price": "Некорректная цена",
    "invalid_total": "Некорректная стоимость",
}
METRIC_LABELS = {
    "floor_area_m2": "Площадь пола",
    "ceiling_area_m2": "Площадь потолка",
    "gross_wall_area_m2": "Площадь стен до вычета проёмов",
    "doors_area_m2": "Площадь дверей",
    "windows_area_m2": "Площадь окон",
    "openings_area_m2": "Площадь проёмов",
    "net_wall_area_m2": "Чистая площадь стен",
    "baseboard_length_m": "Длина плинтуса",
    "door_count": "Количество дверей",
    "window_count": "Количество окон",
}
WORK_METRICS = {
    "Грунтовка стен": "net_wall_area_m2",
    "Окраска стен": "net_wall_area_m2",
    "Устройство пола": "floor_area_m2",
    "Отделка потолка": "ceiling_area_m2",
    "Монтаж плинтуса": "baseboard_length_m",
    "Установка дверей": "door_count",
    "Установка окон": "window_count",
}
CONFIDENCE_LABELS = {
    "low": "низкая — оснований мало",
    "medium": "средняя — гипотезу нужно проверить",
    "high": "высокая — подтверждается несколькими связанными фактами",
}
SEVERITY_LABELS = {"high": "важно", "warning": "внимание"}


def _e(value: Any) -> str:
    if value is None or value == "":
        return "—"
    # В отчёт попадают названия из XLSX, MCP и ответы моделей. Экранировать нужно
    # в одной точке, иначе такое название может стать HTML-разметкой.
    return escape(str(value), quote=True)


def _number(value: Any, *, digits: int = 2) -> str:
    if value is None or value == "":
        return "—"
    try:
        number = Decimal(str(value))
        quantum = Decimal(1).scaleb(-digits)
        rounded = number.quantize(quantum, rounding=ROUND_HALF_UP)
        text = format(rounded, "f")
        whole, _, fraction = text.partition(".")
        sign = ""
        if whole.startswith("-"):
            sign, whole = "−", whole[1:]
        grouped = " ".join(
            reversed([whole[max(0, len(whole) - i - 3):len(whole) - i] for i in range(0, len(whole), 3)])
        )
        fraction = fraction.rstrip("0")
        return f"{sign}{grouped}{',' + fraction if fraction else ''}"
    except (InvalidOperation, ValueError):
        return _e(value)


def _percent(value: Any) -> str:
    return "—" if value in (None, "") else f"{_number(value, digits=1)}%"


def _signed_number(value: Any) -> str:
    if value in (None, ""):
        return "—"
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return _e(value)
    if number > 0:
        return f"+{_number(number)}"
    return _number(number)


def _product(left: Any, right: Any) -> str:
    if left in (None, "") or right in (None, ""):
        return "—"
    try:
        return _number(Decimal(str(left)) * Decimal(str(right)))
    except (InvalidOperation, ValueError):
        return "—"


def _datetime_label(value: Any) -> str:
    if value in (None, ""):
        return "дата не указана"
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return str(value)
    timezone = " UTC" if parsed.utcoffset() is not None and parsed.utcoffset().total_seconds() == 0 else ""
    return parsed.strftime("%d.%m.%Y %H:%M") + timezone


def _is_zero(value: Any) -> bool:
    if value in (None, ""):
        return False
    try:
        return Decimal(str(value)) == 0
    except (InvalidOperation, ValueError):
        return False


def _mapping_method(manifest: dict[str, Any]) -> tuple[str, str]:
    task_id = str(manifest.get("mapping_task_id") or "")
    validated = manifest.get("mapping_validation_status") == "validated"
    validation = (
        " Результат детерминированно проверен по допустимым значениям, покрытию строк и совместимости единиц."
        if validated else ""
    )
    if task_id == "deterministic_mapping":
        return (
            "Точное детерминированное сопоставление",
            "Python сопоставил точные названия и совместимые единицы; mapping-субагент не использовался."
            + validation,
        )
    if task_id:
        return (
            "Mapping-субагент с детерминированной проверкой",
            "Варианты сопоставления выбрал mapping-субагент." + validation,
        )
    return (
        "Способ не указан",
        "В provenance отчёта отсутствует признак способа сопоставления.",
    )


def _price_check_status(item: dict[str, Any]) -> str:
    if item.get("estimate_price") in (None, "") or item.get("mcp_price") in (None, ""):
        return "Цена не проверена"
    if _is_zero(item.get("price_deviation_absolute")):
        return "Цена совпадает"
    return "Есть отклонение цены"


def _total_check_status(item: dict[str, Any], estimate_issues: set[str]) -> str:
    if "arithmetic_mismatch" in estimate_issues:
        return "Ошибка арифметики в смете"
    if item.get("total_cost_impact") in (None, ""):
        return "Стоимость не проверена"
    if _is_zero(item.get("total_cost_impact")):
        return "Стоимость совпадает"
    return "Есть отклонение стоимости"


def _total_comparison(item: dict[str, Any]) -> str:
    if item.get("total_cost_impact") in (None, ""):
        return "Недостаточно данных для сравнения"
    difference = (
        f"{_number(item.get('estimate_total'))} − {_number(item.get('mcp_total'))} "
        f"= {_signed_number(item.get('total_cost_impact'))}"
    )
    if item.get("total_deviation_percent") not in (None, ""):
        return f"{difference}; отклонение {_percent(item.get('total_deviation_percent'))}"
    if _is_zero(item.get("mcp_total")) and not _is_zero(item.get("total_cost_impact")):
        return f"{difference}; процент не рассчитывается, так как контрольная стоимость равна нулю"
    return f"{difference}; процент отклонения не определён"


def _plan_preview_section(manifest: dict[str, Any]) -> str:
    documents = manifest.get("documents") if isinstance(manifest.get("documents"), dict) else {}
    plan = documents.get("plan") if isinstance(documents.get("plan"), dict) else {}
    source_path = plan.get("vision_source_path")
    mime = str(plan.get("mime") or "").lower()
    allowed_mimes = {"image/png", "image/jpeg", "image/webp"}
    if not isinstance(source_path, str) or mime not in allowed_mimes:
        return ""
    try:
        path = Path(source_path)
        if not path.is_file() or path.stat().st_size > 15 * 1024 * 1024:
            return ""
        encoded = b64encode(path.read_bytes()).decode("ascii")
    except OSError:
        return ""
    return f"""<section><h2>Исходный план</h2>
    <details class="plan-preview"><summary>Показать план, по которому подтверждалась геометрия</summary>
    <p class="muted">Исходное изображение встроено в отчёт, поэтому оно останется доступным при переносе HTML-файла.</p>
    <img src="data:{mime};base64,{encoded}" alt="Исходный план объекта"></details></section>"""


def _table(headers: list[str], rows: list[list[Any]], *, class_name: str = "") -> str:
    head = "".join(f"<th>{_e(item)}</th>" for item in headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{_e(item)}</td>" for item in row) + "</tr>"
        for row in rows
    )
    if not rows:
        body = f'<tr><td colspan="{len(headers)}" class="empty">Нет данных</td></tr>'
    class_attr = f' class="{_e(class_name)}"' if class_name else ""
    return f'<div class="table-wrap"><table{class_attr}><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


def _pre(value: Any) -> str:
    return f"<pre>{_e(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))}</pre>"


def _status_label(value: Any) -> str:
    return {
        "completed": "Аудит завершён",
        "completed_partial": "Аудит завершён частично",
        "checked": "Проверено",
        "partially_checked": "Проверено частично",
        "not_checked": "Не проверено",
        "deviation_found": "Есть отклонение",
        "exact_match": "Точное совпадение",
        "below_threshold": "Отклонение ниже порога",
    }.get(str(value), str(value or "—"))


def _finding_kind(finding: dict[str, Any]) -> str:
    kind = finding.get("type")
    if kind in QUANTITY_TYPES:
        return "quantity"
    if kind in PRICE_TYPES:
        return "price"
    if kind in TOTAL_TYPES:
        return "total"
    return "other"


def _finding_basis(
    finding: dict[str, Any],
    mapping: dict[str, Any],
) -> str:
    if finding.get("type") == "arithmetic_mismatch":
        return "Детерминированная проверка: стоимость строки должна равняться количеству × цене за единицу"
    source_rows = set(finding.get("source_rows") or [finding.get("source_row")])
    profile = "price_matches" if _finding_kind(finding) in {"price", "total"} else "work_matches"
    reasons = [
        item.get("reason") for item in mapping.get(profile, [])
        if item.get("source_row") in source_rows and item.get("reason")
    ]
    return "; ".join(dict.fromkeys(reasons)) or "Детерминированная проверка нормализованных данных"


def _recommended_check(finding: dict[str, Any]) -> str:
    if finding.get("quantity_check_scope") == "object_total_unique_doors":
        return (
            "Сверить полный перечень уникальных дверей на плане с суммой всех строк установки; "
            "распределение между помещениями принято из сметы и отдельно не проверялось."
        )
    kind = _finding_kind(finding)
    if kind == "quantity":
        return "Сверить привязку работы к помещению, исходный объём и геометрические размеры."
    if kind == "price":
        return "Проверить состав работы, единицу измерения и применимость позиции MCP."
    if kind == "total":
        return "Пересчитать стоимость строки и проверить использованные количество и цену за единицу."
    if finding.get("type") == "arithmetic_mismatch":
        return "Пересчитать количество × цену за единицу и сверить результат со стоимостью, указанной в смете."
    return "Проверить исходную строку сметы и основание её классификации."


def _formula_label(value: Any) -> str:
    return {
        "(estimate_quantity - control_quantity) * mcp_unit_price":
            "(Количество по смете − контрольное количество) × цена из каталога",
        "(estimate_unit_price - mcp_unit_price) * estimate_quantity":
            "(Цена по смете − цена из каталога) × количество по смете",
        "estimate_total - (estimate_quantity * mcp_unit_price)":
            "Стоимость по смете − (количество по смете × цена из каталога)",
        "(estimate_price - mcp_price) * estimate_quantity":
            "(Цена по смете − цена из каталога) × количество по смете",
        "estimate_total - (estimate_quantity * mcp_price)":
            "Стоимость по смете − (количество по смете × цена из каталога)",
    }.get(str(value), str(value or "—"))


def _trace_label(value: Any, finding: dict[str, Any]) -> str:
    text = str(value)
    parts = text.split(":")
    if len(parts) >= 3 and parts[0] == "room":
        metric = parts[-1]
        room = finding.get("canonical_room_name") or finding.get("original_room_name") or "помещение"
        return f"{METRIC_LABELS.get(metric, metric)} — {room}"
    if len(parts) >= 2 and parts[0] == "object_total":
        return f"Итог по объекту: {METRIC_LABELS.get(parts[-1], parts[-1])}"
    if len(parts) >= 3 and parts[0] == "price" and parts[1] == "row":
        return f"Проверка цены по строке {parts[2]}"
    if len(parts) >= 3 and parts[0] == "quantity_check":
        return "Сравнение количества с установленным порогом"
    return "Детерминированный расчёт Python"


def _trace_unit(metric: Any) -> str:
    value = str(metric or "")
    if value.endswith("_area_m2"):
        return "м²"
    if value == "baseboard_length_m":
        return "м"
    if value in {"door_count", "window_count"}:
        return "шт."
    return ""


def _trace_result(entry: dict[str, Any]) -> str:
    value = entry.get("rounded_result")
    if value in (None, ""):
        return "Не рассчитано"
    unit = _trace_unit(entry.get("metric"))
    result = _number(value)
    return f"{result} {unit}".strip()


def _geometry_trace_expression(entry: dict[str, Any]) -> str:
    metric = str(entry.get("metric") or "")
    inputs = entry.get("inputs") if isinstance(entry.get("inputs"), dict) else {}
    if str(entry.get("trace_id") or "").startswith("object_total:"):
        if metric in {"door_count", "window_count"}:
            identifiers = inputs.get("element_ids") if isinstance(inputs.get("element_ids"), list) else []
            return "Уникальные проёмы: " + (", ".join(str(item) for item in identifiers) or "нет")
        room_values = inputs.get("room_values") if isinstance(inputs.get("room_values"), list) else []
        values = [
            _number(item.get("value"))
            for item in room_values if isinstance(item, dict) and item.get("value") not in (None, "")
        ]
        return "Сумма по помещениям: " + (" + ".join(values) or "нет данных")
    if metric == "floor_area_m2":
        return f"Принято по подтверждённой геометрии: {_number(inputs.get('floor_area_m2'))} м²"
    if metric == "ceiling_area_m2":
        return f"Равна площади пола: {_number(inputs.get('floor_area_m2'))} м²"
    if metric == "gross_wall_area_m2":
        return f"{_number(inputs.get('perimeter_m'))} м × {_number(inputs.get('height_m'))} м"
    if metric in {"doors_area_m2", "windows_area_m2"}:
        collection = "doors" if metric == "doors_area_m2" else "windows"
        openings = inputs.get(collection) if isinstance(inputs.get(collection), list) else []
        parts = [
            f"{_number(item.get('width_m'))} × {_number(item.get('height_m'))}"
            for item in openings if isinstance(item, dict)
        ]
        return " + ".join(parts) if parts else "Проёмы отсутствуют"
    if metric == "openings_area_m2":
        return (
            f"Двери {_number(inputs.get('doors_area_m2'))} м² + "
            f"окна {_number(inputs.get('windows_area_m2'))} м²"
        )
    if metric == "net_wall_area_m2":
        return (
            f"{_number(inputs.get('gross_wall_area_m2'))} м² − "
            f"{_number(inputs.get('openings_area_m2'))} м²"
        )
    if metric == "baseboard_length_m":
        doors = inputs.get("doors") if isinstance(inputs.get("doors"), list) else []
        widths = [
            _number(item.get("width_m"))
            for item in doors if isinstance(item, dict) and item.get("width_m") not in (None, "")
        ]
        deduction = " + ".join(widths) if widths else "0"
        return f"{_number(inputs.get('perimeter_m'))} м − ({deduction}) м"
    if metric in {"door_count", "window_count"}:
        identifiers = inputs.get("element_ids") if isinstance(inputs.get("element_ids"), list) else []
        return "Проёмы: " + (", ".join(str(item) for item in identifiers) or "нет")
    return _formula_label(entry.get("formula"))


def _trace_has_nonzero(value: Any) -> bool:
    if value in (None, ""):
        return False
    try:
        return Decimal(str(value)) != 0
    except (InvalidOperation, ValueError):
        return True


def _quantity_review_rows(
    quantity_checks: list[dict[str, Any]],
    estimate: dict[str, Any],
    mapping: dict[str, Any],
    trace: dict[str, Any],
) -> list[list[Any]]:
    estimate_by_row = {
        item.get("source_row"): item
        for item in estimate.get("rows", [])
        if isinstance(item, dict)
    }
    room_ids = {
        str(item.get("estimate_room") or "").strip().casefold(): item.get("model_room_id")
        for item in mapping.get("room_matches", [])
        if isinstance(item, dict)
    }
    trace_entries = trace.get("entries", []) if isinstance(trace, dict) else []
    geometry_trace = {
        (item.get("room_id"), item.get("metric")): item
        for item in trace_entries
        if isinstance(item, dict) and item.get("metric") in METRIC_LABELS
    }

    rows: list[list[Any]] = []
    rendered_checks: set[str] = set()
    for check in quantity_checks:
        if not isinstance(check, dict):
            continue
        trace_ref = str(check.get("trace_ref") or f"row:{check.get('source_row')}")
        if trace_ref in rendered_checks:
            continue
        rendered_checks.add(trace_ref)

        source_rows = check.get("source_rows") if isinstance(check.get("source_rows"), list) else []
        if not source_rows:
            source_rows = [check.get("source_row")]
        estimate_rows = [estimate_by_row.get(source_row) for source_row in source_rows]
        estimate_rows = [item for item in estimate_rows if isinstance(item, dict)]
        first_estimate = estimate_by_row.get(check.get("source_row"), {})
        if not isinstance(first_estimate, dict):
            first_estimate = {}
        positions = list(dict.fromkeys(
            str(item.get("position")) for item in estimate_rows if item.get("position") not in (None, "")
        ))
        unit = str(first_estimate.get("unit") or "").strip()
        suffix = f" {unit}" if unit else ""
        canonical_work = str(check.get("canonical_work") or check.get("work_name") or "")
        metric = WORK_METRICS.get(canonical_work)
        object_total = canonical_work == "Установка дверей"
        room_name = "Весь объект" if object_total else first_estimate.get("room")
        room_id = None if object_total else room_ids.get(str(room_name or "").strip().casefold())
        geometry_entry = geometry_trace.get((room_id, metric))
        if geometry_entry:
            result = _trace_result(geometry_entry)
            if metric == "floor_area_m2":
                control_calculation = f"Площадь по подтверждённой геометрии = {result}"
            elif metric == "ceiling_area_m2":
                control_calculation = f"Площадь потолка = площадь пола = {result}"
            elif metric in {"door_count", "window_count"}:
                opening = "дверных" if metric == "door_count" else "оконных"
                uniqueness = "уникальных " if object_total else ""
                control_calculation = f"Количество {uniqueness}{opening} проёмов = {result}"
            else:
                control_calculation = f"{_geometry_trace_expression(geometry_entry)} = {result}"
        else:
            control_calculation = (
                "По подтверждённой геометрии: "
                f"{_number(check.get('control_display_value') or check.get('control_value'))}{suffix}"
            )
        comparison = (
            f"{_number(check.get('estimated_value'))} − {_number(check.get('control_value'))} "
            f"= {_signed_number(check.get('deviation_signed'))}{suffix}; "
            f"отклонение {_percent(check.get('deviation_percent'))}; "
            f"порог {_percent(check.get('tolerance_percent'))}"
        )
        rows.append([
            ", ".join(positions) or check.get("source_position"),
            ", ".join(str(item) for item in source_rows if item not in (None, "")),
            room_name,
            check.get("work_name") or canonical_work,
            f"{_number(check.get('estimated_value'))}{suffix}",
            control_calculation,
            comparison,
            _status_label(check.get("status")),
        ])
    return rows


def _audit_progress_rows(
    manifest: dict[str, Any],
    mapping: dict[str, Any],
    summary: dict[str, Any],
    price_catalog: dict[str, Any],
    visual_insights: dict[str, Any],
    llm_insights: dict[str, Any],
) -> list[list[Any]]:
    documents = manifest.get("documents") if isinstance(manifest.get("documents"), dict) else {}
    document_names = [
        item.get("filename") for item in documents.values()
        if isinstance(item, dict) and item.get("filename")
    ]
    unresolved = sum(
        len(mapping.get(key, []))
        for key in ("room_unresolved", "work_unresolved", "price_unresolved")
    )
    unsupported = sum(
        len(mapping.get(key, []))
        for key in ("work_unsupported", "price_unsupported")
    )
    mapping_status = "Выполнен" if not unresolved and not unsupported else "Выполнен частично"
    mapping_method, mapping_method_details = _mapping_method(manifest)
    mapping_result = (
        f"Помещений: {len(mapping.get('room_matches', []))}; "
        f"работ: {len(mapping.get('work_matches', []))}; "
        f"цен: {len(mapping.get('price_matches', []))}. "
        f"Способ: {mapping_method}. {mapping_method_details}"
    )
    if unresolved or unsupported:
        mapping_result += f"; без сопоставления: {unresolved}; не поддерживается: {unsupported}"

    visual_items = visual_insights.get("items", []) if isinstance(visual_insights, dict) else []
    photo_ids = {
        item.get("photo_id") for item in visual_items
        if isinstance(item, dict) and item.get("photo_id")
    }
    if visual_insights.get("status") == "skipped":
        visual_status, visual_result = "Пропущен", "Фотографии не предоставлены"
    else:
        visual_status = "Выполнен"
        visual_result = f"Фотографий: {len(photo_ids)}; наблюдений: {len(visual_items)}"

    insight_items = llm_insights.get("items", []) if isinstance(llm_insights, dict) else []
    insight_result = (
        f"Сформировано гипотез: {len(insight_items)}"
        if insight_items else "Дополнительных обоснованных гипотез не сформировано"
    )
    quantity_not_checked = int(summary.get("quantity_not_checked_rows") or 0)
    price_not_checked = int(summary.get("price_not_checked_rows") or 0)
    return [
        ["Исходные документы", "Получены" if document_names else "Нет данных", ", ".join(document_names) or "Документы не указаны"],
        [
            "Подтверждение геометрии",
            "Подтверждена" if manifest.get("geometry_confirmed") else "Требует внимания",
            (
                f"Подтверждена версия {manifest.get('geometry_confirmed_revision')}"
                if manifest.get("geometry_confirmed") else "Геометрия не подтверждена"
            ),
        ],
        ["Каталог цен", "Получен" if price_catalog.get("items") else "Нет данных", f"Позиций в каталоге: {len(price_catalog.get('items', []))}"],
        ["Сопоставление данных", mapping_status, mapping_result],
        [
            "Проверка количества",
            "Выполнена" if not quantity_not_checked else "Выполнена частично",
            (
                f"Проверено строк: {summary.get('quantity_checked_rows', 0)}; "
                f"с отклонением: {summary.get('quantity_deviation_rows', 0)}; "
                f"не проверено: {quantity_not_checked}"
            ),
        ],
        [
            "Проверка цены и стоимости",
            "Выполнена" if not price_not_checked else "Выполнена частично",
            (
                f"Полностью: {summary.get('price_fully_checked_rows', 0)}; "
                f"частично: {summary.get('price_partially_checked_rows', 0)}; "
                f"с отклонением: {summary.get('price_deviation_rows', 0)}; "
                f"не проверено: {price_not_checked}"
            ),
        ],
        ["Анализ фотографий", visual_status, visual_result],
        ["Дополнительный анализ", "Выполнен", insight_result],
        ["Формирование отчёта", "Выполнено", f"Завершено: {_datetime_label(manifest.get('audit_completed_at'))}"],
    ]


def _calculation_trace_section(trace: dict[str, Any], estimate: dict[str, Any]) -> str:
    entries = trace.get("entries", []) if isinstance(trace, dict) else []
    entries = [item for item in entries if isinstance(item, dict)]
    estimate_by_row = {
        item.get("source_row"): item
        for item in estimate.get("rows", [])
        if isinstance(item, dict) and type(item.get("source_row")) is int
    }

    geometry_by_room: dict[str, list[dict[str, Any]]] = {}
    object_entries: list[dict[str, Any]] = []
    for entry in entries:
        metric = str(entry.get("metric") or "")
        if metric not in METRIC_LABELS:
            continue
        if entry.get("room_id") is None:
            object_entries.append(entry)
            continue
        room_name = str(entry.get("room_name") or "Помещение")
        geometry_by_room.setdefault(room_name, []).append(entry)

    room_sections = []
    for room_name, room_entries in geometry_by_room.items():
        rows = [
            [
                METRIC_LABELS.get(str(entry.get("metric")), entry.get("metric")),
                _geometry_trace_expression(entry),
                _trace_result(entry),
            ]
            for entry in room_entries
        ]
        room_sections.append(
            f"<details><summary>{_e(room_name)}</summary>"
            f"{_table(['Расчёт', 'Как получено', 'Результат'], rows)}</details>"
        )

    object_rows = [
        [
            METRIC_LABELS.get(str(entry.get("metric")), entry.get("metric")),
            _geometry_trace_expression(entry),
            _trace_result(entry),
        ]
        for entry in object_entries
    ]
    object_section = (
        f"<details><summary>Итоги по объекту</summary>"
        f"{_table(['Расчёт', 'Как получено', 'Результат'], object_rows)}</details>"
        if object_rows else ""
    )

    quantity_rows = []
    for entry in entries:
        if entry.get("metric") != "quantity_threshold_check":
            continue
        results = entry.get("results") if isinstance(entry.get("results"), dict) else {}
        if not results.get("threshold_exceeded"):
            continue
        inputs = entry.get("inputs") if isinstance(entry.get("inputs"), dict) else {}
        source_rows = entry.get("source_rows") if isinstance(entry.get("source_rows"), list) else []
        estimate_rows = [estimate_by_row.get(row) for row in source_rows]
        works = list(dict.fromkeys(
            str(item.get("work_name")) for item in estimate_rows if isinstance(item, dict) and item.get("work_name")
        ))
        units = list(dict.fromkeys(
            str(item.get("unit")) for item in estimate_rows if isinstance(item, dict) and item.get("unit")
        ))
        unit = units[0] if len(units) == 1 else ""
        suffix = f" {unit}" if unit else ""
        quantity_rows.append([
            ", ".join(str(row) for row in source_rows) or "—",
            ", ".join(works) or "Проверка количества",
            (
                f"Смета: {_number(inputs.get('estimate_quantity'))}{suffix}; "
                f"контроль: {_number(inputs.get('control_quantity_display'))}{suffix}"
            ),
            (
                f"Отклонение {_percent(results.get('deviation_percent_raw'))}; "
                f"порог {_percent(inputs.get('tolerance_percent'))}"
            ),
        ])

    price_trace_rows = []
    for entry in entries:
        if entry.get("metric") != "price_and_total_check":
            continue
        inputs = entry.get("inputs") if isinstance(entry.get("inputs"), dict) else {}
        results = entry.get("results") if isinstance(entry.get("results"), dict) else {}
        if not (
            _trace_has_nonzero(results.get("unit_price_impact"))
            or _trace_has_nonzero(results.get("total_cost_impact"))
        ):
            continue
        source_row = entry.get("source_row")
        estimate_row = estimate_by_row.get(source_row, {})
        result_parts = []
        if _trace_has_nonzero(results.get("unit_price_impact")):
            result_parts.append(f"влияние цены: {_number(results.get('unit_price_impact'))}")
        if _trace_has_nonzero(results.get("total_cost_impact")):
            result_parts.append(f"разница стоимости: {_number(results.get('total_cost_impact'))}")
        price_trace_rows.append([
            source_row,
            estimate_row.get("work_name") or "Проверка цены и стоимости",
            (
                f"{_number(inputs.get('estimate_quantity'))} × "
                f"{_number(inputs.get('mcp_unit_price'))} = {_number(results.get('mcp_total'))}"
            ),
            (
                f"В смете: {_number(inputs.get('estimate_total'))}; "
                + "; ".join(result_parts)
            ),
        ])

    deviations_html = ""
    if quantity_rows or price_trace_rows:
        deviations_html = "<h4>Расчёты по строкам с отклонениями</h4>"
        if quantity_rows:
            deviations_html += "<h5>Количество</h5>" + _table(
                ["Строки Excel", "Работа", "Сравнение", "Результат"], quantity_rows
            )
        if price_trace_rows:
            deviations_html += "<h5>Цена и стоимость</h5>" + _table(
                ["Строка Excel", "Работа", "Контрольный расчёт", "Результат"], price_trace_rows
            )
    else:
        deviations_html = '<div class="empty-state">Расчётов с отклонениями нет.</div>'

    readable = "".join(room_sections) + object_section + deviations_html
    if not entries:
        readable = '<div class="empty-state">Расчётные данные отсутствуют.</div>'
    return (
        "<details><summary>Расчётные основания (Calculation trace)</summary>"
        '<p class="muted">Формулы ниже построены Python из сохранённых входных данных. '
        "Исходный структурированный trace сохранён без изменений.</p>"
        f"{readable}"
        f"<details><summary>Исходный структурированный trace</summary>{_pre(trace)}</details>"
        "</details>"
    )


def _finding_card(finding: dict[str, Any], mapping: dict[str, Any]) -> str:
    severity = str(finding.get("severity") or "warning")
    kind = _finding_kind(finding)
    source_rows = ", ".join(str(item) for item in finding.get("source_rows", [finding.get("source_row")]))
    source_position = finding.get("source_position")
    row_reference = (
        f"Позиция №{source_position} · строка Excel {source_rows}"
        if source_position not in (None, "") and len(finding.get("source_rows") or [finding.get("source_row")]) == 1
        else f"Строки Excel: {source_rows}"
    )
    if kind == "quantity":
        estimate_label, control_label = "Количество в смете", "Контрольное количество"
        estimated = f"{_number(finding.get('estimated_value'))} {_e(finding.get('unit'))}"
        control = f"{_number(finding.get('control_value'))} {_e(finding.get('unit'))}"
    elif kind == "price":
        estimate_label, control_label = "Цена в смете", "Цена MCP"
        estimated = _number(finding.get("estimated_value"))
        control = _number(finding.get("control_value"))
    elif kind == "total":
        estimate_label, control_label = "Стоимость строки", "Контрольная стоимость"
        estimated = _number(finding.get("estimated_value"))
        control = _number(finding.get("control_value"))
    elif finding.get("type") == "arithmetic_mismatch":
        estimate_label, control_label = "Стоимость в смете", "Количество × цена за единицу"
        estimated = _number(finding.get("estimated_value"))
        control = _number(finding.get("control_value"))
    else:
        estimate_label, control_label = "Значение в смете", "Контрольное значение"
        estimated = _number(finding.get("estimated_value"))
        control = _number(finding.get("control_value"))
    impact = finding.get("financial_impact") or {}
    impact_html = ""
    if impact.get("status") == "calculated":
        impact_html = (
            '<div class="impact"><span>Расчётное влияние</span>'
            f'<strong>{_number(impact.get("signed_value"))}</strong>'
            f'<small>{_e(_formula_label(impact.get("formula")))}</small></div>'
        )
    deviation_label = _percent(finding.get("deviation_percent"))
    if finding.get("deviation_percent") in (None, "") and _is_zero(finding.get("control_value")):
        deviation_label = "не определяется (контроль 0)"
    line_analysis = finding.get("line_cost_analysis") or {}
    line_analysis_html = ""
    if line_analysis.get("status") == "calculated":
        simultaneous_note = (
            '<p><strong>Важно:</strong> одновременно превышены пороги количества и цены.</p>'
            if line_analysis.get("simultaneous_quantity_and_price_deviation") else ""
        )
        line_analysis_html = f"""
        <div class="line-analysis"><h4>Полное отклонение стоимости строки</h4>
        <div class="comparison"><div><span>Стоимость в смете</span><strong>{_number(line_analysis.get('estimate_total'))}</strong></div>
        <div><span>Полная эталонная стоимость</span><strong>{_number(line_analysis.get('reference_total'))}</strong></div>
        <div><span>Полное отклонение</span><strong>{_number(line_analysis.get('full_variance_signed'))} ({_percent(line_analysis.get('full_variance_percent'))})</strong></div></div>
        <p>Вклад количества: <strong>{_number(line_analysis.get('quantity_effect_signed'))}</strong> · вклад цены: <strong>{_number(line_analysis.get('price_effect_signed'))}</strong> · арифметика строки: <strong>{_number(line_analysis.get('arithmetic_effect_signed'))}</strong></p>
        <p class="muted">Полное отклонение = вклад количества + вклад цены + арифметическая разница строки.</p>
        {simultaneous_note}</div>"""
    refs = finding.get("calculation_trace_refs") or []
    trace_text = "; ".join(_trace_label(item, finding) for item in refs) or "—"
    return f"""
    <article class="finding {severity}">
      <div class="finding-head"><div><span class="badge {severity}">{_e(SEVERITY_LABELS.get(severity, severity))}</span>
      <span class="eyebrow">{_e(row_reference)}</span>
      <h3>{_e(TYPE_LABELS.get(str(finding.get('type')), finding.get('type')))}</h3></div>
      <div class="deviation">{_e(deviation_label)}</div></div>
      <p><strong>{_e('Весь объект' if finding.get('quantity_check_scope') == 'object_total_unique_doors' else finding.get('original_room_name'))}</strong> · {_e(finding.get('original_work_name'))}</p>
      <div class="comparison"><div><span>{estimate_label}</span><strong>{estimated}</strong></div>
      <div><span>{control_label}</span><strong>{control}</strong></div>
      <div><span>Абсолютное отклонение</span><strong>{_number(finding.get('deviation_absolute'))}</strong></div></div>
      {impact_html}
      {line_analysis_html}
      <div class="finding-notes"><p><strong>Основание:</strong> {_e(_finding_basis(finding, mapping))}</p>
      <p><strong>Расчёт:</strong> {_e(trace_text)}</p>
      <p><strong>Что проверить:</strong> {_e(_recommended_check(finding))}</p></div>
    </article>"""


def _insights_section(
    value: dict[str, Any],
    geometry: dict[str, Any],
    findings: list[dict[str, Any]],
) -> str:
    if value.get("status") == "no_useful_observations":
        return '<section><h2>Аналитические наблюдения и гипотезы</h2><div class="hypothesis-note">Самостоятельных наблюдений с достаточными основаниями не сформировано.</div></section>'
    cards = []
    room_names = {room.get("room_id"): room.get("name") for room in geometry.get("rooms", [])}
    finding_labels = {}
    for finding in findings:
        position = finding.get("source_position")
        position_text = f"позиция {position}, " if position not in (None, "") else ""
        details = [
            f"{position_text}строка Excel {finding.get('source_row')}",
            str(finding.get("original_room_name") or "").strip(),
            str(finding.get("original_work_name") or "").strip(),
        ]
        finding_labels[finding.get("finding_id")] = " · ".join(item for item in details if item)
    for item in value.get("items", []):
        refs = []
        for ref in item.get("evidence_refs", []):
            ref_type, ref_value = ref.get("type"), ref.get("value")
            if ref_type == "finding":
                refs.append(f"расхождение: {finding_labels.get(ref_value, 'детерминированная проверка')}")
            elif ref_type == "estimate_row":
                refs.append(f"строка сметы {ref_value}")
            elif ref_type == "room":
                refs.append(f"помещение «{room_names.get(ref_value, 'без названия')}»")
            elif ref_type == "price_check":
                refs.append(f"проверка цены по строке {ref_value}")
            elif ref_type == "visual_insight":
                refs.append("наблюдение по фотографии")
            elif ref_type == "trace":
                refs.append("контрольный расчёт")
            else:
                refs.append("детерминированный расчёт")
        refs_text = "; ".join(dict.fromkeys(refs))
        cards.append(
            f"""<article class="insight"><div><span class="badge hypothesis">Дополнительная гипотеза</span>
            <span class="eyebrow">Уверенность: {_e(CONFIDENCE_LABELS.get(item.get('confidence'), item.get('confidence')))}</span></div>
            <h3>{_e(item.get('title'))}</h3>
            <p><strong>Связанные данные отчёта:</strong> {_e(refs_text)}</p>
            <p><strong>Вывод:</strong> {_e(item.get('hypothesis'))}</p>
            <p><strong>Что на это указывает:</strong> {_e(item.get('observation'))}</p>
            <p><strong>Что проверить:</strong> {_e(item.get('recommended_check'))}</p>
            <details><summary>Основания и ограничения</summary>
            <p><strong>Основания:</strong> {_e(refs_text)}</p>
            <p class="muted"><strong>Ограничения:</strong> {_e(item.get('limitations'))}</p></details></article>"""
        )
    return f"""<section><h2>Аналитические наблюдения и гипотезы</h2>
    <div class="hypothesis-note">Этот блок сформирован после расчётов. Он содержит предположения для дополнительной проверки и не подтверждает нарушения. Если формулировка гипотезы расходится с точной привязкой строки, помещения или работы, приоритет имеют детерминированные данные в «Ключевых замечаниях» и строке «Связанные данные отчёта».</div>
    <p>{_e(value.get('summary'))}</p>{''.join(cards)}</section>"""


def _visual_insights_section(value: dict[str, Any]) -> str:
    if value.get("status") == "skipped":
        return """<section><h2>Наблюдения по фотографиям объекта</h2>
        <div class="empty-state">Фотографии объекта не предоставлены.</div></section>"""
    cards: list[str] = []
    status_labels = {
        "observed": "наблюдается",
        "not_observed": "не видно в кадре",
        "not_assessable": "не поддаётся оценке",
        "quality_concern": "обратить внимание",
    }
    for item in value.get("items", []):
        rows = ", ".join(str(row) for row in item.get("source_rows", [])) or "—"
        work = item.get("estimate_work") or "Качество работ"
        cards.append(
            f"""<article class="insight"><div><span class="badge hypothesis">Фото-инсайт</span>
            <span class="eyebrow">{_e(item.get('photo_filename') or item.get('photo_id'))} · {_e(status_labels.get(item.get('status'), item.get('status')))} · уверенность: {_e(item.get('confidence'))}</span></div>
            <h3>{_e(item.get('title'))}</h3><p><strong>Работа:</strong> {_e(work)} · <strong>Строки сметы:</strong> {_e(rows)}</p>
            <p><strong>Наблюдение:</strong> {_e(item.get('observation'))}</p>
            <p><strong>Визуальное основание:</strong> {_e(item.get('evidence_text'))}</p>
            <p><strong>Что проверить аудитору:</strong> {_e(item.get('auditor_check'))}</p>
            <p class="muted"><strong>Ограничения:</strong> {_e(item.get('limitations'))}</p></article>"""
        )
    if not cards:
        cards.append('<div class="empty-state">По предоставленным фотографиям полезных визуальных наблюдений не сформировано.</div>')
    return f"""<section><h2>Наблюдения по фотографиям объекта</h2>
    <div class="notice">Фото-инсайты отражают только видимую часть кадра и не привязаны к помещениям. Строки сметы указывают позиции соответствующей работы, а не место съёмки. Отсутствие результата работы на фотографии не доказывает, что работа не выполнена; решение принимает аудитор.</div>
    {''.join(cards)}</section>"""


def build_report(data: dict[str, Any]) -> str:
    manifest = data["manifest"]
    estimate = data["estimate"]
    geometry = data["geometry"]
    mapping = data["mapping"]
    quantities = data["quantities"]
    trace = data.get("calculation_trace", {"entries": []})
    price_catalog = data["price_catalog"]
    price_checks = data["price_checks"]
    findings = data["findings"]
    warnings = data["warnings"]
    checked_rows = data["checked_rows"]
    not_checked_rows = data["not_checked_rows"]
    quantity_checks = data.get("quantity_checks", [])
    summary = data.get("summary", {})
    llm_insights = data.get("llm_insights", {"status": "no_useful_observations", "items": []})
    visual_insights = data.get("visual_insights", {"status": "skipped", "items": []})

    severity_order = {"high": 0, "warning": 1}
    type_order = {"quantity": 0, "price": 1, "total": 2, "other": 3}
    sorted_findings = sorted(
        findings,
        key=lambda item: (
            severity_order.get(str(item.get("severity")), 9),
            type_order[_finding_kind(item)],
            int(item.get("source_row") or 0),
        ),
    )
    finding_rows = {row for item in findings for row in item.get("source_rows", [item.get("source_row")])}
    clean_rows = [item for item in checked_rows if item.get("source_row") not in finding_rows]

    room_rows = [
        [
            room.get("name"), _number(room.get("floor_area_m2")), _number(room.get("perimeter_m")),
            _number(room.get("height_m")), len(room.get("doors", [])), len(room.get("windows", [])),
            "Требует внимания" if any(item.get("room_id") == room.get("room_id") for item in geometry.get("missing_fields", [])) else "Достаточно данных",
        ]
        for room in geometry.get("rooms", [])
    ]
    quantity_rows = _quantity_review_rows(quantity_checks, estimate, mapping, trace)
    work_by_row = {
        item.get("source_row"): item.get("canonical_work")
        for item in mapping.get("work_matches", [])
    }
    door_estimate_rows = [
        row for row in estimate.get("rows", [])
        if work_by_row.get(row.get("source_row")) == "Установка дверей"
    ]
    door_declared_total = sum(
        (
            Decimal(str(row.get("quantity")))
            for row in door_estimate_rows
            if row.get("quantity") is not None
        ),
        Decimal(0),
    )
    unique_door_total = quantities.get("object_totals", {}).get("door_count")
    door_allocation_rows = [
        [
            row.get("source_row"),
            row.get("room"),
            _number(row.get("quantity")),
            "Принято из сметы; по помещению не проверялось",
        ]
        for row in door_estimate_rows
    ]
    door_allocation_html = ""
    if door_estimate_rows:
        door_allocation_html = f"""
<section><h2>Установка дверей</h2>
<div class="notice">Распределение установок между помещениями принято из сметы и не определяется по плану. Проверено только суммарное количество установок по всем строкам сметы относительно уникальных дверей на плане.</div>
{_table(['Строка','Помещение сметы','Установок по смете','Статус распределения'], door_allocation_rows)}
<p><strong>Сумма установок по смете:</strong> {_number(door_declared_total)} · <strong>Уникальных дверей на плане:</strong> {_number(unique_door_total)}</p>
</section>"""
    estimate_issues_by_row = {
        item.get("source_row"): {
            str(issue.get("type"))
            for issue in item.get("issues", []) if isinstance(issue, dict)
        }
        for item in estimate.get("rows", []) if isinstance(item, dict)
    }
    price_rows = [
        [
            item.get("source_position"), item.get("source_row"), item.get("estimate_work"), item.get("unit"),
            _number(item.get("estimate_price")), _number(item.get("mcp_price")),
            (
                f"({_number(item.get('estimate_price'))} − {_number(item.get('mcp_price'))}) × "
                f"{_number(item.get('quantity'))} = {_signed_number(item.get('unit_price_impact'))}"
                if item.get("unit_price_impact") not in (None, "") else "Недостаточно данных для расчёта"
            ),
            _price_check_status(item),
        ]
        for item in price_checks
    ]
    total_rows = [
        [
            item.get("source_position"), item.get("source_row"), item.get("estimate_work"),
            (
                f"{_number(item.get('quantity'))} × {_number(item.get('estimate_price'))} = "
                f"{_product(item.get('quantity'), item.get('estimate_price'))}; "
                f"в смете указано {_number(item.get('estimate_total'))}"
                if item.get("quantity") not in (None, "") and item.get("estimate_price") not in (None, "")
                else f"В смете указано {_number(item.get('estimate_total'))}"
            ),
            (
                f"{_number(item.get('quantity'))} × {_number(item.get('mcp_price'))} = "
                f"{_number(item.get('mcp_total'))}"
                if item.get("mcp_total") not in (None, "") else "Недостаточно данных для расчёта"
            ),
            _total_comparison(item),
            _total_check_status(item, estimate_issues_by_row.get(item.get("source_row"), set())),
        ]
        for item in price_checks
    ]
    documents = manifest.get("documents", {})
    estimate_doc = documents.get("estimate", {})
    plan_doc = documents.get("plan", {})
    high_count = summary.get("findings_by_severity", {}).get("high", 0)
    warning_count = summary.get("findings_by_severity", {}).get("warning", 0)
    price_result = (
        f"Отклонения цены или стоимости в {summary.get('price_deviation_rows', 0)} строках"
        if summary.get("price_deviation_rows")
        else "По проверенным строкам отклонений цены и стоимости нет"
    )
    progress_rows = _audit_progress_rows(
        manifest, mapping, summary, price_catalog, visual_insights, llm_insights
    )
    _, mapping_method_details = _mapping_method(manifest)
    plan_preview_html = _plan_preview_section(manifest)
    findings_html = "".join(_finding_card(item, mapping) for item in sorted_findings)
    if not findings_html:
        findings_html = '<div class="empty-state">По проверенным строкам предварительных расхождений не выявлено.</div>'

    room_mapping_rows = [
        [item.get("estimate_room"), item.get("model_room_id"), item.get("confidence"), item.get("reason")]
        for item in mapping.get("room_matches", [])
    ]
    work_mapping_rows = [
        [item.get("source_row"), item.get("estimate_work"), item.get("canonical_work"), item.get("confidence"), item.get("reason")]
        for item in mapping.get("work_matches", [])
    ]
    price_mapping_rows = [
        [item.get("source_row"), item.get("estimate_work"), item.get("mcp_work_id"), item.get("confidence"), item.get("reason")]
        for item in mapping.get("price_matches", [])
    ]
    catalog_rows = [
        [item.get("id"), item.get("name"), item.get("unit"), _number(item.get("price"))]
        for item in price_catalog.get("items", [])
    ]
    warning_rows = [
        [item.get("source_row", "—"), item.get("message")]
        for item in warnings if item.get("level") != "info"
    ]
    info_rows = [
        [item.get("source_row", "—"), item.get("message")]
        for item in warnings if item.get("level") == "info"
    ]
    not_checked_table = [
        [item.get("source_row"), item.get("status"), item.get("reason")]
        for item in not_checked_rows
    ]

    return f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Предварительный аудит — {_e(manifest.get('object_name'))}</title>
<style>
:root{{--ink:#182536;--muted:#647286;--line:#d9e0e8;--surface:#f5f7fa;--navy:#173a5e;--red:#a93636;--amber:#9a6500;--blue:#246392;--violet:#68509b}}
*{{box-sizing:border-box}}body{{margin:0;background:#edf1f5;color:var(--ink);font:15px/1.5 system-ui,-apple-system,sans-serif}}
main{{max-width:1180px;margin:0 auto;background:white;min-height:100vh;padding:42px 48px 70px}}h1{{font-size:34px;margin:5px 0 8px;color:var(--navy)}}h2{{margin:42px 0 16px;font-size:24px;color:var(--navy)}}h3{{margin:8px 0;font-size:18px}}p{{margin:7px 0}}.eyebrow{{font-size:12px;text-transform:uppercase;letter-spacing:.07em;color:var(--muted)}}
.lead{{font-size:17px;color:var(--muted)}}.status-line{{display:flex;gap:12px;align-items:center;flex-wrap:wrap}}.status{{background:#dff2e6;color:#17643a;padding:5px 10px;border-radius:999px;font-weight:700}}
.notice,.hypothesis-note{{padding:14px 16px;border-left:4px solid var(--amber);background:#fff7df;margin:18px 0}}.hypothesis-note{{border-color:var(--violet);background:#f5f1ff}}
.kpis{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:28px 0}}.kpi{{padding:17px;border:1px solid var(--line);border-radius:10px;background:var(--surface)}}.kpi span{{display:block;color:var(--muted);font-size:12px}}.kpi strong{{display:block;font-size:25px;margin-top:4px}}.kpi small{{color:var(--muted)}}
.finding,.insight{{border:1px solid var(--line);border-radius:12px;padding:20px;margin:14px 0;background:#fff}}.finding.high{{border-left:5px solid var(--red)}}.finding.warning{{border-left:5px solid var(--amber)}}.finding-head{{display:flex;justify-content:space-between;gap:20px}}.deviation{{font-size:24px;font-weight:700;color:var(--red)}}.badge{{display:inline-block;font-size:11px;font-weight:800;text-transform:uppercase;padding:3px 7px;border-radius:5px;margin-right:8px}}.badge.high{{background:#fae1e1;color:var(--red)}}.badge.warning{{background:#fff0c9;color:var(--amber)}}.badge.hypothesis{{background:#e9e0ff;color:var(--violet)}}
.comparison{{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin:16px 0}}.comparison>div,.impact{{background:var(--surface);padding:12px;border-radius:8px}}.comparison span,.impact span,.impact small{{display:block;color:var(--muted);font-size:12px}}.comparison strong,.impact strong{{font-size:18px}}.impact{{border-left:3px solid var(--blue)}}.finding-notes{{border-top:1px solid var(--line);padding-top:10px}}.insight{{border-left:5px solid var(--violet)}}.muted{{color:var(--muted)}}
.table-wrap{{overflow:auto;margin:10px 0 20px}}table{{border-collapse:collapse;width:100%;font-size:13px}}th,td{{padding:9px 10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}}th{{background:var(--surface);color:#394b60;white-space:nowrap}}.empty,.empty-state{{padding:22px;color:var(--muted);background:var(--surface);border-radius:8px;text-align:center}}
details{{border:1px solid var(--line);border-radius:9px;padding:0 14px;margin:10px 0}}summary{{cursor:pointer;font-weight:700;padding:13px 0;color:var(--navy)}}.plan-preview img{{display:block;max-width:100%;height:auto;margin:12px auto 18px;border:1px solid var(--line);border-radius:8px;background:white}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;background:#172231;color:#eef4fa;padding:14px;border-radius:8px;font-size:12px}}.disclaimer{{margin-top:48px;padding:18px;background:#fff1bd;border:1px solid #e3c35b;font-weight:700}}
@media(max-width:800px){{main{{padding:24px 18px}}.kpis{{grid-template-columns:1fr 1fr}}.comparison{{grid-template-columns:1fr}}}}
</style></head><body><main>
<header><div class="status-line"><span class="status">{_e(_status_label(manifest.get('audit_status')))}</span><span class="eyebrow">Версия геометрии {_e(manifest.get('geometry_revision'))}</span></div>
<h1>Предварительный аудит строительной сметы</h1><p class="lead"><strong>{_e(manifest.get('object_name'))}</strong></p>
<div class="notice">{_e(DISCLAIMER)}.</div></header>

<section><h2>Краткое резюме</h2><div class="kpis">
<div class="kpi"><span>Строк сметы</span><strong>{_e(summary.get('estimate_rows'))}</strong><small>нормализовано</small></div>
<div class="kpi"><span>Охвачено сравнением количества</span><strong>{_percent(summary.get('quantity_coverage_percent'))}</strong><small>{_e(summary.get('quantity_checked_rows'))} проверено · {_e(summary.get('quantity_not_checked_rows'))} не проверено</small></div>
<div class="kpi"><span>Покрытие цены</span><strong>{_percent(summary.get('price_coverage_percent'))}</strong><small>{_e(summary.get('price_fully_checked_rows'))} полностью · {_e(summary.get('price_partially_checked_rows'))} частично</small></div>
<div class="kpi"><span>Первичные замечания</span><strong>{_e(summary.get('findings_count'))}</strong><small>{_e(high_count)} высокой важности · {_e(warning_count)} предупреждений</small></div>
<div class="kpi"><span>Результат количества</span><strong>{_e(summary.get('quantity_deviation_rows'))}</strong><small>{_e(summary.get('quantity_exact_match_rows'))} точных · {_e(summary.get('quantity_below_threshold_rows'))} ниже порога</small></div>
<div class="kpi"><span>Служебные предупреждения</span><strong>{_e(summary.get('warnings_count'))}</strong></div>
<div class="kpi"><span>Цена и стоимость</span><strong>{_e(summary.get('price_deviation_rows'))}</strong><small>{_e(price_result)}</small></div>
<div class="kpi"><span>Геометрия</span><strong>{'Подтверждена' if manifest.get('geometry_confirmed') else 'Не подтверждена'}</strong><small>подтверждённая версия {_e(manifest.get('geometry_confirmed_revision'))}</small></div>
<div class="kpi"><span>Статус</span><strong>{_e(_status_label(summary.get('completion_status')))}</strong><small>{_e(_datetime_label(manifest.get('audit_completed_at')))}</small></div>
</div></section>

<section><h2>Ход проверки</h2>
<p class="muted">Этапы собраны из данных текущего аудита; служебные идентификаторы здесь не показываются.</p>
{_table(['Этап','Статус','Результат'], progress_rows)}</section>

<section><h2>Как читать отчёт</h2><ul>
<li><strong>Ключевые замечания</strong> — основной результат детерминированных проверок Python.</li>
<li><strong>Количество, цена за единицу и стоимость строки проверяются раздельно.</strong> Одна строка может пройти проверку цены, но содержать ошибку количества или арифметики стоимости.</li>
<li><strong>Позиция</strong> — номер позиции внутри сметы; <strong>строка Excel</strong> — фактический номер строки исходного файла.</li>
<li><strong>Аналитические гипотезы</strong> — вторичный материал для эксперта, а не подтверждённые нарушения.</li>
</ul></section>

<section><h2>Ключевые замечания</h2>{findings_html}</section>
{_visual_insights_section(visual_insights)}
{_insights_section(llm_insights, geometry, findings)}
{door_allocation_html}

<section><h2>Раздельная проверка</h2>
<h3>Количество</h3><p class="muted">Для каждой проверяемой работы показаны сметное количество, формула по подтверждённой геометрии и сравнение с порогом.</p>
{_table(['Позиция','Строки Excel','Помещение','Работа','Количество сметы','Контрольный расчёт','Сравнение','Статус'], quantity_rows)}
<h3>Цена за единицу</h3><p class="muted">Статус в этой таблице относится только к цене за единицу и не наследует ошибки количества или стоимости строки.</p>
{_table(['Позиция','Строка Excel','Работа','Единица работы','Цена сметы','Цена по каталогу MCP','Формула влияния цены','Статус'], price_rows)}
<h3>Стоимость строки и арифметика</h3><p class="muted"><strong>Стоимость сметы</strong> сверяется с арифметикой строки. <strong>Контрольная стоимость</strong> равна количеству сметы × цене по каталогу MCP. <strong>Расчётное влияние</strong> показано как разница между ними.</p>
{_table(['Позиция','Строка Excel','Работа','Расчёт по смете','Контрольный расчёт','Сравнение','Статус'], total_rows)}</section>

<section><h2>Геометрия объекта</h2>{_table(['Помещение','Площадь','Периметр','Высота','Дверные проёмы','Окна','Статус данных'], room_rows)}</section>
{plan_preview_html}
<section><details><summary>Строки без отклонений выше установленных порогов ({len(clean_rows)})</summary>
{_table(['Позиция','Строка Excel','Работа','Контрольное значение','Результат количества','Отклонение'], [[item.get('source_position'),item.get('source_row'),item.get('work_name'),('В составе суммы по объекту: смета ' + _number(item.get('aggregate_estimated_value')) + ' · план ' + _number(item.get('control_value'))) if item.get('quantity_check_scope') == 'object_total_unique_doors' else _number(item.get('control_value')),_status_label(item.get('quantity_result')),_percent(item.get('deviation_percent'))] for item in clean_rows])}</details></section>

<section><h2>Ограничения анализа</h2><ul>
<li>Контрольные значения рассчитаны по распознанной и подтверждённой геометрии, но не являются натурным обмером.</li>
<li>Отсутствующие размеры не заменяются предположениями; зависимые проверки остаются непроверенными.</li>
<li>Один межкомнатный дверной проём учитывается в геометрии каждого смежного помещения, но в уникальном итоге объекта дедуплицируется по element_id.</li>
<li>Сметная привязка установки дверей к помещениям принимается как заявленная и отдельно по комнатам не проверяется.</li>
<li>{_e(mapping_method_details)}</li>
<li>Расчётное финансовое влияние является арифметическим ориентиром и не учитывает договорные условия, налоги и дополнительные работы.</li>
<li>Фото-анализ относится только к видимым участкам и не подтверждает выполнение, невыполнение или качество скрытых работ.</li>
</ul></section>

<section><h2>Техническое приложение</h2>
<details><summary>Использованные документы и SHA-256</summary><ul>
<li>XLSX: {_e(estimate_doc.get('filename'))} · {_e(estimate_doc.get('sha256'))}</li>
<li>План: {_e(plan_doc.get('filename'))} · {_e(plan_doc.get('sha256'))}</li></ul></details>
<details><summary>Visual insights</summary>{_pre(visual_insights)}</details>
<details><summary>Подтверждение и provenance</summary>{_pre({'geometry_revision': manifest.get('geometry_revision'), 'geometry_confirmed_revision': manifest.get('geometry_confirmed_revision'), 'confirmed_geometry_sha256': manifest.get('confirmed_geometry_sha256'), 'vision_task_id': manifest.get('vision_task_id'), 'mapping_task_id': manifest.get('mapping_task_id'), 'llm_insights_task_id': manifest.get('llm_insights_task_id'), 'price_catalog_source_tool': manifest.get('price_catalog_source_tool'), 'mapping_sha256': manifest.get('mapping_sha256'), 'llm_context_sha256': manifest.get('llm_context_sha256'), 'llm_insights_sha256': manifest.get('llm_insights_sha256')})}</details>
<details><summary>Mapping помещений</summary>{_table(['Помещение сметы','Geometry ID','Confidence','Основание'], room_mapping_rows)}</details>
<details><summary>Mapping работ для количества</summary>{_table(['Строка','Работа сметы','Canonical work','Confidence','Основание'], work_mapping_rows)}</details>
<details><summary>Mapping с каталогом MCP</summary>{_table(['Строка','Работа сметы','MCP ID','Confidence','Основание'], price_mapping_rows)}</details>
<details><summary>Каталог MCP</summary>{_table(['MCP ID','Название','Единица','Цена'], catalog_rows)}</details>
{_calculation_trace_section(trace, estimate)}
<details><summary>Предупреждения (Warnings)</summary>{_table(['Строка','Сообщение'], warning_rows)}</details>
<details><summary>Служебная информация</summary>{_table(['Строка','Сообщение'], info_rows)}</details>
<details><summary>Unsupported и not checked</summary>{_table(['Строка','Статус','Причина'], not_checked_table)}{_pre({'work_unsupported': mapping.get('work_unsupported', []), 'price_unsupported': mapping.get('price_unsupported', []), 'work_unresolved': mapping.get('work_unresolved', []), 'price_unresolved': mapping.get('price_unresolved', []), 'room_unresolved': mapping.get('room_unresolved', [])})}</details>
<details><summary>Geometry evidence, missing fields и conflicts</summary>{_pre({'rooms': geometry.get('rooms', []), 'missing_fields': geometry.get('missing_fields', []), 'conflicts': geometry.get('conflicts', [])})}</details>
</section>
<p class="disclaimer">{_e(DISCLAIMER)}.</p>
</main></body></html>"""
