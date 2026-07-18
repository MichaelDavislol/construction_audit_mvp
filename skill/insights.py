from __future__ import annotations

import json
import re
from typing import Any

try:
    from . import visual
except ImportError:  # standalone-тесты загружают модуль без package-контекста
    import visual  # type: ignore


SCHEMA_VERSION = 1
MAX_ITEMS = 6
MAX_CONTEXT_CHARS = 10_000
MAX_CONTEXT_FINDINGS = 9
MAX_CONTEXT_PRICE_CHECKS = 10
MAX_CONTEXT_ESTIMATE_ROWS = 10
CATEGORIES = {
    "systemic_pattern",
    "possible_mapping_issue",
    "data_completeness",
    "estimate_structure",
    "possible_cause",
    "recommended_follow_up",
    "visual_observation",
}
CONFIDENCE_LEVELS = {"low", "medium", "high"}
EVIDENCE_TYPES = {"finding", "estimate_row", "room", "trace", "price_check", "visual_insight"}
TRANSPORT_META_CLAIMS = (
    "context_limits",
    "findings_included",
    "price_checks_included",
    "переданный контекст",
    "усечение контекста",
    "усечённый контекст",
    "не все price_checks",
    "context truncation",
    "prompt truncation",
    "transport sample",
)
USER_TEXT_FIELDS = (
    "title", "observation", "hypothesis", "recommended_check", "limitations",
)
INTERNAL_LANGUAGE_RE = re.compile(
    r"\b(?:finding|findings|price[ _-]?checks?|deterministic[ _-]?findings)\b"
    r"|\bstatus\s*="
    r"|\b(?:finding|insight|room|trace|photo)_\d+(?:_insight_\d+)?\b"
    r"|\b[a-z][a-z0-9]*_[a-z0-9_]+\b",
    re.IGNORECASE,
)


class InsightsValidationError(ValueError):
    def __init__(self, errors: list[dict[str, str]]):
        super().__init__("Результат аналитического субагента не соответствует схеме.")
        self.errors = errors


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def build_context_package(
    *,
    manifest: dict[str, Any],
    estimate: dict[str, Any],
    geometry: dict[str, Any],
    mapping: dict[str, Any],
    quantities: dict[str, Any],
    trace: dict[str, Any],
    findings: list[dict[str, Any]],
    warnings: list[dict[str, Any]],
    checked_rows: list[dict[str, Any]],
    not_checked_rows: list[dict[str, Any]],
    price_checks: list[dict[str, Any]],
    price_catalog: dict[str, Any],
    visual_insights: dict[str, Any] | None = None,
    max_context_findings: int = MAX_CONTEXT_FINDINGS,
) -> dict[str, Any]:
    # Аналитику передаём приоритетные находки и связанные строки, а не весь аудит.
    # Полнота при этом остаётся в coverage/price_summary, посчитанных Python.
    selected_findings = sorted(
        findings,
        key=lambda item: (
            0 if item.get("severity") == "high" else 1,
            item.get("source_row") if isinstance(item.get("source_row"), int) else 10**9,
            str(item.get("finding_id") or ""),
        ),
    )[:max(1, min(MAX_CONTEXT_FINDINGS, max_context_findings))]
    visual_projection = (
        visual.compact_for_llm(visual_insights)
        if visual_insights and visual_insights.get("status") != "skipped"
        else None
    )
    finding_source_rows = {
        row
        for finding in selected_findings
        for row in ([finding.get("source_row")] + list(finding.get("source_rows") or []))
        if type(row) is int
    }
    estimate_rows = list(estimate.get("rows", []))
    selected_estimate_rows = [
        row for row in estimate_rows if row.get("source_row") in finding_source_rows
    ][:MAX_CONTEXT_ESTIMATE_ROWS]
    selected_price_checks = [
        check
        for check in price_checks
        if check.get("status") != "checked" or check.get("source_row") in finding_source_rows
    ][:MAX_CONTEXT_PRICE_CHECKS]
    trace_ids = {
        ref
        for finding in selected_findings
        for ref in finding.get("calculation_trace_refs", [])
        if isinstance(ref, str)
    }
    relevant_trace = [
        {
            key: entry.get(key)
            for key in (
                "trace_id", "room_id", "metric", "formula", "inputs", "rounded_result",
                "results",
            )
        }
        for entry in trace.get("entries", [])
        if entry.get("trace_id") in trace_ids
    ]
    finding_room_ids = {
        finding.get("canonical_room_id")
        for finding in selected_findings
        if isinstance(finding.get("canonical_room_id"), str)
    }
    compact_rooms = [
        {
            "room_id": room.get("room_id"),
            "name": room.get("name"),
            "metrics": next(
                (
                    quantity_room.get("metrics", {})
                    for quantity_room in quantities.get("rooms", [])
                    if quantity_room.get("room_id") == room.get("room_id")
                ),
                {},
            ),
        }
        for room in geometry.get("rooms", [])
        if room.get("room_id") in finding_room_ids
    ]
    compact_findings = [
        {
            key: finding.get(key)
            for key in (
                "finding_id", "type", "severity", "source_row", "source_rows",
                "quantity_check_scope", "allocation_status", "canonical_room_id",
                "canonical_room_name", "canonical_work_name", "estimated_value",
                "control_value", "deviation_percent", "unit", "calculation_trace_refs",
            )
        }
        for finding in selected_findings
    ]
    compact_price_checks = [
        {
            key: check.get(key)
            for key in (
                "source_row", "status", "mcp_work_id", "estimate_price", "mcp_price",
            )
        }
        for check in selected_price_checks
    ]
    warning_groups: dict[tuple[Any, Any], list[int]] = {}
    for warning in warnings:
        if warning.get("level") == "info":
            continue
        key = (warning.get("code"), warning.get("metric"))
        source_row = warning.get("source_row")
        rows = warning_groups.setdefault(key, [])
        if isinstance(source_row, int) and source_row not in rows:
            rows.append(source_row)
    user_warnings = [
        {"code": code, "metric": metric, "source_rows": rows[:20], "count": len(rows)}
        for (code, metric), rows in sorted(
            warning_groups.items(), key=lambda item: (str(item[0][0]), str(item[0][1]))
        )
    ]
    package = {
        "schema_version": SCHEMA_VERSION,
        "scope": "construction_audit_mvp_post_check_analysis",
        "object": {
            "name": manifest.get("object_name"),
            "geometry_revision": manifest.get("geometry_revision"),
            "geometry_confirmed": manifest.get("geometry_confirmed"),
            "confirmed_geometry_sha256": manifest.get("confirmed_geometry_sha256"),
        },
        "estimate_rows": [
            {
                "source_row": row.get("source_row"),
                "room": row.get("room"),
                "work_name": row.get("work_name"),
                "unit": row.get("unit"),
                "quantity": row.get("quantity"),
            }
            for row in selected_estimate_rows
        ],
        "geometry": {"rooms": compact_rooms},
        "mapping": {
            key: len(mapping.get(key, []))
            for key in (
                "room_matches", "room_unresolved", "work_matches", "work_unsupported",
                "work_unresolved", "price_matches", "price_unsupported", "price_unresolved",
            )
        },
        "price_summary": {
            "catalog_items": len(price_catalog.get("items", [])),
            "checked": sum(item.get("status") in {"checked", "deviation_found"} for item in price_checks),
            "partially_checked": sum(item.get("status") == "partially_checked" for item in price_checks),
            "not_checked": sum(item.get("status") == "not_checked" for item in price_checks),
            "deviations": sum(
                item.get("status") == "deviation_found" for item in price_checks
            ),
        },
        "price_checks": compact_price_checks,
        "deterministic_findings": compact_findings,
        "warnings": user_warnings,
        "coverage": {
            "checked_rows": len(checked_rows),
            "not_checked_rows": len(not_checked_rows),
        },
        "relevant_calculation_trace": relevant_trace,
        "provenance": {
            "price_catalog_source_tool": manifest.get("price_catalog_source_tool"),
            "price_catalog_source_transport": manifest.get("price_catalog_source_transport"),
        },
    }
    if visual_projection is not None:
        package["visual_insights"] = visual_projection
    return package


def _example_for_context(context: dict[str, Any]) -> dict[str, Any]:
    findings = context.get("deterministic_findings", [])
    visual_items = context.get("visual_insights", {}).get("items", [])
    if visual_items:
        refs = [{"type": "visual_insight", "value": visual_items[0].get("visual_insight_id")}]
        category = "visual_observation"
        observation = "На данном фотокадре есть наблюдение, требующее проверки специалистом."
    elif findings:
        refs = [{"type": "finding", "value": findings[0].get("finding_id")}]
        category = "systemic_pattern"
        observation = "Несколько результатов проверки могут образовывать общий паттерн."
    else:
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "no_useful_observations",
            "summary": "Самостоятельных наблюдений с достаточными основаниями нет.",
            "items": [],
        }
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "generated",
        "summary": "Найдена самостоятельная проверяемая гипотеза.",
        "items": [{
            "insight_id": "insight_001",
            "category": category,
            "title": "Краткий заголовок гипотезы",
            "observation": observation,
            "hypothesis": "Возможное объяснение, сформулированное как гипотеза.",
            "evidence_refs": refs,
            "confidence": "medium",
            "recommended_check": "Что проверить специалисту.",
            "limitations": "Что не позволяет считать гипотезу подтверждённой.",
        }],
    }


def _retry_guidance(validation_errors: list[dict[str, str]]) -> str:
    reasons = {str(error.get("reason") or "") for error in validation_errors}
    guidance: list[str] = []
    if "visual evidence is not linked to rooms" in reasons:
        guidance.append(
            "Для items с фото не называй помещения и не пиши «все помещения», «каждое помещение» "
            "или «по помещениям»: описывай только данный кадр и связанные строки сметы."
        )
    if "must analyze audit evidence, not transport sampling or context truncation" in reasons:
        guidance.append(
            "Полностью удали items о выборке, размере или полноте context; не переформулируй их."
        )
    return (" " + " ".join(guidance)) if guidance else ""


def delegation(
    context: dict[str, Any],
    *,
    validation_errors: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    context_text = _json(context)
    if len(context_text) > MAX_CONTEXT_CHARS:
        raise ValueError(f"LLM context exceeds {MAX_CONTEXT_CHARS} characters")
    example = _example_for_context(context)
    retry_instruction = ""
    if validation_errors:
        retry_instruction = (
            " Предыдущий ответ не прошёл schema validation. Верни новый ответ с нуля, исправив "
            f"только перечисленные ошибки: {_json(validation_errors)}. Не обсуждай ошибки в ответе."
            + _retry_guidance(validation_errors)
        )
    return {
        "role": "construction-audit-analyst",
        "model_lane": "main",
        "memory_mode": "empty",
        "write_surface": "read_only",
        "objective": (
            "После завершённой детерминированной проверки найди только самостоятельные системные "
            "наблюдения и проверяемые гипотезы, включая связи с переданными visual_insights. "
            "Не изменяй findings, фото-наблюдения и расчёты. Не пересказывай "
            "отдельные findings другими словами. Если самостоятельных наблюдений нет, верни "
            "status=no_useful_observations и пустой items. Текст отчёта пиши для заказчика "
            "строительных работ простым русским языком."
        ),
        "expected_output": (
            "Финальный ответ должен быть одной строкой без Markdown и пояснений: "
            f"FINAL ANSWER: [BEGIN_SUBTASK_OUTPUT]{_json(example)}[END_SUBTASK_OUTPUT]"
        ),
        "context": context_text,
        "constraints": (
            "Используй только context. Не вызывай tools, включая write_file; не читай и не пиши "
            "файлы, не используй внешние "
            "знания. Каждый item обязан быть гипотезой, а не подтверждённым нарушением. Не вводи "
            "новые числа, строки сметы, помещения, findings или trace ID. Не делай выводов об умысле. "
            "Не приписывай людям или процессу причины, которых нет в context: ручной ввод, отсутствие "
            "сверки, невнимательность и аналогичные объяснения. "
            "Не дублируй deterministic_findings и не создавай два items об одной причине. Не "
            "приписывай валюту: в context она не задана. Вывод обо всех проверенных ценах обязан "
            "ссылаться на price_check каждой охваченной строки. Поля estimate_rows, price_checks и "
            "deterministic_findings могут быть сокращёнными transport-сэмплами. context_limits "
            "описывает только объём сэмпла, если присутствует, а не полноту выполненного аудита; полноту аудита определяй "
            "только по coverage и price_summary. Не создавай observations или hypotheses о сокращении "
            "контекста, отсутствующих в сэмпле строках или необходимости запросить полный context. "
            "Finding с quantity_check_scope=object_total_unique_doors агрегирует все source_rows: "
            "не приписывай его первой строке или одному помещению. allocation_status=estimate_declared "
            "означает, что room-распределение установок принято из сметы и отдельно не проверялось. "
            "visual_insights являются предварительными наблюдениями по отдельным фотографиям: "
            "not_observed не доказывает, что работа не выполнена, а quality_concern не подтверждает дефект. "
            "Фотографии не привязаны к помещениям: source_rows связывают наблюдение только с позициями "
            "соответствующей работы в смете. Не называй и не угадывай помещение и не обобщай фото-наблюдение "
            "на все помещения. Если item содержит evidence_ref типа visual_insight, в этом item запрещён "
            "evidence_ref типа room, даже если item также ссылается на finding. Finding с помещением не "
            "устанавливает место съёмки фотографии. Формулируй вывод только для указанного кадра или "
            "набора photo_id. "
            "Поля summary, title, observation, hypothesis, recommended_check и limitations являются "
            "пользовательским текстом. В них запрещены внутренние ID, имена полей и enum из context: "
            "например finding_001, room_001, price_check, control_value, source_row, status=checked, "
            "arithmetic_mismatch и calculation_trace. Переводи их смысл на обычный русский: "
            "«выявленное расхождение», «помещение», «сравнение цены», «контрольное значение», "
            "«строка сметы», «основание расчёта». Технические ID возвращай только внутри evidence_refs. "
            f"category — только одно из: {', '.join(sorted(CATEGORIES))}. evidence_refs.type — только "
            f"одно из: {', '.join(sorted(EVIDENCE_TYPES))}. Максимум 6 items. confidence — только low, "
            "medium или high. insight_id последовательно: insight_001, insight_002 и далее. Все "
            "evidence_refs дословно ссылаются на элементы context. Если оснований недостаточно, не "
            "создавай item. Заверши ответ точной "
            "однострочной формой из expected_output, начиная с FINAL ANSWER:. До FINAL ANSWER и после "
            "[END_SUBTASK_OUTPUT] разрешён только whitespace."
            + retry_instruction
        ),
    }


def _text(value: Any, path: str, errors: list[dict[str, str]], *, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        errors.append({"path": path, "reason": f"must be a non-empty string up to {maximum} characters"})
        return ""
    return value.strip()


def validate(value: Any, context: dict[str, Any]) -> dict[str, Any]:
    errors: list[dict[str, str]] = []
    required = {"schema_version", "status", "summary", "items"}
    if not isinstance(value, dict):
        raise InsightsValidationError([{"path": "", "reason": "must be an object"}])
    if set(value) != required:
        errors.append({"path": "", "reason": "must contain only schema_version, status, summary and items"})
    if value.get("schema_version") != SCHEMA_VERSION or type(value.get("schema_version")) is not int:
        errors.append({"path": "schema_version", "reason": f"must equal integer {SCHEMA_VERSION}"})
    status = value.get("status")
    if status not in {"generated", "no_useful_observations"}:
        errors.append({"path": "status", "reason": "unsupported status"})
    summary = _text(value.get("summary"), "summary", errors, maximum=2000)
    raw_items = value.get("items")
    if not isinstance(raw_items, list) or len(raw_items) > MAX_ITEMS:
        errors.append({"path": "items", "reason": f"must be an array up to {MAX_ITEMS} items"})
        raw_items = []
    if status == "generated" and not raw_items:
        errors.append({"path": "items", "reason": "generated status requires at least one item"})
    if status == "no_useful_observations" and raw_items:
        errors.append({"path": "items", "reason": "no_useful_observations requires an empty array"})

    visual_items = context.get("visual_insights", {}).get("items", [])
    visual_source_rows = {
        row
        for item in visual_items
        for row in item.get("source_rows", [])
        if type(row) is int
    }
    # Строки из фото могут не попасть в transport-выборку estimate_rows, но всё
    # равно остаются допустимым evidence: их связь уже проверил visual validator.
    allowed: dict[str, set[Any]] = {
        "finding": {item.get("finding_id") for item in context.get("deterministic_findings", [])},
        "estimate_row": (
            {item.get("source_row") for item in context.get("estimate_rows", [])}
            | visual_source_rows
        ),
        "room": {item.get("room_id") for item in context.get("geometry", {}).get("rooms", [])},
        "trace": {item.get("trace_id") for item in context.get("relevant_calculation_trace", [])},
        "price_check": {item.get("source_row") for item in context.get("price_checks", [])},
        "visual_insight": {
            item.get("visual_insight_id")
            for item in visual_items
        },
    }
    clean_items: list[dict[str, Any]] = []
    seen_meanings: set[str] = set()
    forbidden_claims = (
        "руб.", "рубл", "₽", "доллар", "умышлен", "намеренн", "сознательн",
        "невнимательн", "задан вручную", "задана вручную", "задано вручную",
        "введен вручную", "введена вручную", "введено вручную", "без сверки",
    )
    visual_room_claims = (
        "во всех помещен", "в каждом помещен", "по помещениям", "для каждого помещен",
    )
    room_names = {
        str(item.get("name") or "").strip().casefold()
        for item in context.get("geometry", {}).get("rooms", [])
        if str(item.get("name") or "").strip()
    }
    summary_text = summary.casefold()
    if INTERNAL_LANGUAGE_RE.search(summary):
        errors.append({
            "path": "summary",
            "reason": "must use plain Russian without internal schema identifiers",
        })
    if context.get("visual_insights") and any(
        token in summary_text for token in ("фото", "визуал", "кадр")
    ) and (
        any(token in summary_text for token in visual_room_claims)
        or any(name in summary_text for name in room_names)
    ):
        errors.append({"path": "summary", "reason": "visual evidence is not linked to rooms"})
    item_keys = {
        "insight_id", "category", "title", "observation", "hypothesis",
        "evidence_refs", "confidence", "recommended_check", "limitations",
    }
    for index, raw in enumerate(raw_items):
        path = f"items[{index}]"
        if not isinstance(raw, dict) or set(raw) != item_keys:
            errors.append({"path": path, "reason": "invalid item fields"})
            continue
        insight_id = _text(raw.get("insight_id"), f"{path}.insight_id", errors, maximum=32)
        expected_id = f"insight_{index + 1:03d}"
        if insight_id != expected_id:
            errors.append({"path": f"{path}.insight_id", "reason": f"must equal {expected_id}"})
        category = raw.get("category")
        if category not in CATEGORIES:
            errors.append({"path": f"{path}.category", "reason": "unsupported category"})
        confidence = raw.get("confidence")
        if confidence not in CONFIDENCE_LEVELS:
            errors.append({"path": f"{path}.confidence", "reason": "unsupported confidence"})
        refs = raw.get("evidence_refs")
        clean_refs: list[dict[str, Any]] = []
        seen_refs: set[str] = set()
        if not isinstance(refs, list) or not 1 <= len(refs) <= 20:
            errors.append({"path": f"{path}.evidence_refs", "reason": "must contain 1 to 20 refs"})
            refs = []
        for ref_index, ref in enumerate(refs):
            ref_path = f"{path}.evidence_refs[{ref_index}]"
            if not isinstance(ref, dict) or set(ref) != {"type", "value"}:
                errors.append({"path": ref_path, "reason": "must contain only type and value"})
                continue
            ref_type = ref.get("type")
            ref_value = ref.get("value")
            if ref_type not in EVIDENCE_TYPES:
                errors.append({"path": f"{ref_path}.type", "reason": "unsupported evidence type"})
                continue
            # Ссылка должна существовать в зафиксированном context package.
            # Свободные ID позволили бы модели сослаться на данные, которых она не видела.
            if ref_value not in allowed[ref_type]:
                errors.append({"path": f"{ref_path}.value", "reason": "reference is absent from context"})
                continue
            key = _json(ref)
            if key in seen_refs:
                errors.append({"path": ref_path, "reason": "duplicate reference"})
                continue
            seen_refs.add(key)
            clean_refs.append({"type": ref_type, "value": ref_value})
        clean_item = {
                "insight_id": insight_id,
                "category": category,
                "title": _text(raw.get("title"), f"{path}.title", errors, maximum=200),
                "observation": _text(raw.get("observation"), f"{path}.observation", errors, maximum=2000),
                "hypothesis": _text(raw.get("hypothesis"), f"{path}.hypothesis", errors, maximum=2000),
                "evidence_refs": clean_refs,
                "confidence": confidence,
                "recommended_check": _text(raw.get("recommended_check"), f"{path}.recommended_check", errors, maximum=2000),
                "limitations": _text(raw.get("limitations"), f"{path}.limitations", errors, maximum=2000),
            }
        for field in USER_TEXT_FIELDS:
            if INTERNAL_LANGUAGE_RE.search(str(clean_item.get(field) or "")):
                errors.append({
                    "path": f"{path}.{field}",
                    "reason": "must use plain Russian without internal schema identifiers",
                })
        semantic_text = " ".join(
            str(clean_item.get(key) or "")
            for key in ("title", "observation", "hypothesis", "recommended_check", "limitations")
        ).casefold()
        if any(token in semantic_text for token in forbidden_claims):
            errors.append({"path": path, "reason": "contains unsupported currency or intent claim"})
        if any(token in semantic_text for token in TRANSPORT_META_CLAIMS):
            errors.append({
                "path": path,
                "reason": "must analyze audit evidence, not transport sampling or context truncation",
            })
        if any(ref.get("type") == "visual_insight" for ref in clean_refs) and (
            any(token in semantic_text for token in visual_room_claims)
            or any(name in semantic_text for name in room_names)
        ):
            errors.append({"path": path, "reason": "visual evidence is not linked to rooms"})
        meaning = " ".join(
            " ".join(
                "".join(
                    character
                    for character in str(clean_item.get(key) or "").casefold()
                    if character.isalnum() or character.isspace()
                ).split()
            )
            for key in ("title", "observation", "hypothesis")
        )
        if meaning in seen_meanings:
            errors.append({"path": path, "reason": "duplicates another insight"})
        seen_meanings.add(meaning)
        clean_items.append(clean_item)
    if errors:
        raise InsightsValidationError(errors)
    return {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "summary": summary,
        "items": clean_items,
    }
