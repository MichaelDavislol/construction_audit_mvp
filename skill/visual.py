from __future__ import annotations

import json
import re
from typing import Any


SCHEMA_VERSION = 1
MAX_PHOTOS = 5
MAX_INSIGHTS_PER_PHOTO = 8
MAX_LLM_CONTEXT_ITEMS = 6
INSIGHT_CATEGORIES = {"estimate_comparison", "quality"}
CATEGORY_ALIASES = {"quality_concern": "quality"}
ACCEPTED_INSIGHT_CATEGORIES = INSIGHT_CATEGORIES | set(CATEGORY_ALIASES)
INSIGHT_STATUSES = {"observed", "not_observed", "not_assessable", "quality_concern"}
STATUS_ALIASES = {"observed_present": "observed"}
ACCEPTED_INSIGHT_STATUSES = INSIGHT_STATUSES | set(STATUS_ALIASES)
CONFIDENCE_LEVELS = {"low", "medium", "high"}
NOT_OBSERVED_COMPLETION_CLAIMS = (
    re.compile(
        r"\bне\s+(?:выполн\w*|установ\w*|смонтирован\w*|уложен\w*|окрашен\w*|отделан\w*|заверш\w*|сделан\w*)",
        re.IGNORECASE,
    ),
    re.compile(r"\b(?:работ\w*|покрыти\w*|окраск\w*|отделк\w*)\s+отсутств\w*", re.IGNORECASE),
)
FRAME_SCOPE_MARKERS = (
    "в кадре",
    "на фото",
    "на фотографии",
    "на снимке",
    "в поле зрения",
    "на видимом участке",
    "в видимой части",
)


class VisualValidationError(ValueError):
    def __init__(self, errors: list[dict[str, str]]):
        super().__init__("Результат фото Vision-субагента не соответствует схеме.")
        self.errors = errors


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def delegation(
    photo: dict[str, Any],
    estimate_works: list[dict[str, Any]],
    *,
    validation_errors: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    photo_id = photo["photo_id"]
    image_ref = photo["vision_source_path"]
    context = {
        "schema_version": SCHEMA_VERSION,
        "photo_id": photo_id,
        "image_ref": image_ref,
        "delegation_token": photo["delegation_token"],
        "estimate_works": estimate_works,
    }
    example = {
        "schema_version": SCHEMA_VERSION,
        "photo_id": photo_id,
        "delegation_token": photo["delegation_token"],
        "image_quality": {"usable": True, "issues": []},
        "scene_summary": "Видимый участок объекта.",
        "visual_insights": [
            {
                "visual_insight_id": f"{photo_id}_insight_001",
                "category": "quality",
                "estimate_work": None,
                "source_rows": [],
                "status": "quality_concern",
                "title": "Видимый признак качества",
                "observation": "На фото виден признак для очной проверки.",
                "evidence_text": "Признак различим в кадре.",
                "confidence": "medium",
                "auditor_check": "Проверить на объекте.",
                "limitations": "Только этот кадр.",
            },
        ],
        "limitations": ["Только видимая часть кадра."],
    }
    retry_instruction = ""
    if validation_errors:
        retry_instruction = (
            " Предыдущий ответ не прошёл validation. Создай новый ответ с нуля и исправь все "
            f"перечисленные ошибки: {_json(validation_errors)}. Не обсуждай ошибки в ответе."
        )
    return {
        "role": "construction-site-photo-vision",
        "model_lane": "main",
        "memory_mode": "empty",
        "write_surface": "read_only",
        "objective": (
            "Открой view_image(context.image_ref). Сопоставь видимые работы с "
            "context.estimate_works и отметь признаки качества."
        ),
        "expected_output": (
            "До FINAL ANSWER и после [END_SUBTASK_OUTPUT] разрешён только whitespace. "
            "Верни ровно одну строку без Markdown и пояснений: "
            f"FINAL ANSWER: [BEGIN_SUBTASK_OUTPUT]{_json(example)}[END_SUBTASK_OUTPUT]"
        ),
        "context": _json(context),
        "constraints": (
            "Первый tool: view_image(path=context.image_ref); другие tools запрещены. Не называй комнату. "
            "Для каждой context.estimate_works верни один estimate_comparison в исходном порядке; "
            "estimate_work/source_rows скопируй точно; status: observed|not_observed|not_assessable. "
            "Для not_observed в title/observation пиши «не видно в кадре»; запрещены «не выполнено», "
            "«не установлено» и «отсутствует». Скрытое: not_assessable. Затем максимум один quality "
            "item по примеру; category=quality_concern запрещён. Все поля обязательны. Не измеряй по "
            f"перспективе и не утверждай нарушение. Максимум {MAX_INSIGHTS_PER_PHOTO} items; ID "
            "последовательны. Непригодное фото: usable=false, visual_insights=[]."
            + retry_instruction
        ),
    }


def _error(errors: list[dict[str, str]], path: str, reason: str) -> None:
    errors.append({"path": path, "reason": reason})


def _text(value: Any, path: str, errors: list[dict[str, str]], maximum: int, *, nullable: bool = False) -> str | None:
    if nullable and value is None:
        return None
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        _error(errors, path, f"must be a non-empty string up to {maximum} characters")
        return None
    return value.strip()


def validate(
    value: Any,
    *,
    photo: dict[str, Any],
    estimate_works: list[dict[str, Any]],
) -> dict[str, Any]:
    errors: list[dict[str, str]] = []
    root_keys = {
        "schema_version", "photo_id", "delegation_token", "image_quality",
        "scene_summary", "visual_insights", "limitations",
    }
    if not isinstance(value, dict):
        raise VisualValidationError([{"path": "", "reason": "must be an object"}])
    missing_root_keys = sorted(root_keys - set(value))
    extra_root_keys = sorted(set(value) - root_keys)
    if missing_root_keys:
        _error(errors, "", f"missing fields: {', '.join(missing_root_keys)}")
    if extra_root_keys:
        _error(errors, "", f"unexpected fields: {', '.join(extra_root_keys)}")
    if type(value.get("schema_version")) is not int or value.get("schema_version") != SCHEMA_VERSION:
        _error(errors, "schema_version", f"must equal integer {SCHEMA_VERSION}")
    if value.get("photo_id") != photo.get("photo_id"):
        _error(errors, "photo_id", "must match delegated photo_id")
    if value.get("delegation_token") != photo.get("delegation_token"):
        _error(errors, "delegation_token", "must match delegated token")

    quality = value.get("image_quality")
    if not isinstance(quality, dict) or set(quality) != {"usable", "issues"}:
        _error(errors, "image_quality", "must contain usable and issues")
        quality = {"usable": False, "issues": []}
    usable = quality.get("usable")
    if type(usable) is not bool:
        _error(errors, "image_quality.usable", "must be a boolean")
        usable = False
    issues = quality.get("issues")
    if not isinstance(issues, list) or len(issues) > 20:
        _error(errors, "image_quality.issues", "must be an array up to 20 items")
        issues = []
    clean_issues: list[str] = []
    for index, item in enumerate(issues):
        text = _text(item, f"image_quality.issues[{index}]", errors, 500)
        if text is not None:
            clean_issues.append(text)

    scene_summary = _text(value.get("scene_summary"), "scene_summary", errors, 1000) or ""
    limitations = value.get("limitations")
    if not isinstance(limitations, list) or len(limitations) > 20:
        _error(errors, "limitations", "must be an array up to 20 items")
        limitations = []
    clean_limitations: list[str] = []
    for index, item in enumerate(limitations):
        text = _text(item, f"limitations[{index}]", errors, 500)
        if text is not None:
            clean_limitations.append(text)

    work_by_name = {item["canonical_work"]: item for item in estimate_works}
    raw_insights = value.get("visual_insights")
    if not isinstance(raw_insights, list) or len(raw_insights) > MAX_INSIGHTS_PER_PHOTO:
        _error(errors, "visual_insights", f"must be an array up to {MAX_INSIGHTS_PER_PHOTO} items")
        raw_insights = []
    if not usable and raw_insights:
        _error(errors, "visual_insights", "must be empty when image_quality.usable=false")

    item_keys = {
        "visual_insight_id", "category", "estimate_work", "source_rows", "status",
        "title", "observation", "evidence_text", "confidence", "auditor_check", "limitations",
    }
    clean_insights: list[dict[str, Any]] = []
    seen_estimate_works: set[str] = set()
    comparison_order: list[Any] = []
    category_order: list[Any] = []
    for index, raw in enumerate(raw_insights):
        path = f"visual_insights[{index}]"
        if not isinstance(raw, dict):
            _error(errors, path, "must be an object")
            continue
        normalized_raw = dict(raw)
        normalized_category = CATEGORY_ALIASES.get(
            normalized_raw.get("category"), normalized_raw.get("category")
        )
        normalized_raw["category"] = normalized_category
        # Quality не связывается со строками сметы, поэтому это однозначная
        # безопасная нормализация, а не исправление визуального вывода.
        if normalized_category == "quality" and "source_rows" not in normalized_raw:
            normalized_raw["source_rows"] = []
        missing_item_keys = sorted(item_keys - set(normalized_raw))
        extra_item_keys = sorted(set(normalized_raw) - item_keys)
        if missing_item_keys:
            _error(errors, path, f"missing fields: {', '.join(missing_item_keys)}")
        if extra_item_keys:
            _error(errors, path, f"unexpected fields: {', '.join(extra_item_keys)}")
        if missing_item_keys or extra_item_keys:
            continue
        raw = normalized_raw
        expected_id = f"{photo['photo_id']}_insight_{index + 1:03d}"
        insight_id = _text(raw.get("visual_insight_id"), f"{path}.visual_insight_id", errors, 64) or ""
        if insight_id != expected_id:
            _error(errors, f"{path}.visual_insight_id", f"must equal {expected_id}")
        category = raw.get("category")
        category_order.append(category)
        raw_status = raw.get("status")
        status = STATUS_ALIASES.get(raw_status, raw_status)
        confidence = raw.get("confidence")
        if category not in INSIGHT_CATEGORIES:
            _error(errors, f"{path}.category", "unsupported category")
        if raw_status not in ACCEPTED_INSIGHT_STATUSES:
            _error(errors, f"{path}.status", "unsupported status")
        if confidence not in CONFIDENCE_LEVELS:
            _error(errors, f"{path}.confidence", "unsupported confidence")
        estimate_work = raw.get("estimate_work")
        source_rows = raw.get("source_rows")
        if (
            not isinstance(source_rows, list)
            or any(type(row) is not int for row in source_rows)
            or len(source_rows) != len(set(source_rows))
        ):
            _error(errors, f"{path}.source_rows", "must be an integer array")
            source_rows = []
        if category == "quality":
            if estimate_work is not None or source_rows or status != "quality_concern":
                _error(errors, path, "quality requires estimate_work=null, source_rows=[] and quality_concern")
        else:
            comparison_order.append(estimate_work)
            work = work_by_name.get(estimate_work)
            if work is None:
                _error(errors, f"{path}.estimate_work", "work is absent from delegated estimate context")
            elif estimate_work in seen_estimate_works:
                _error(errors, f"{path}.estimate_work", "duplicate estimate comparison for work")
            # Фото не знает помещение. source_rows здесь только связывают видимую
            # работу со всеми её строками сметы и не задают место съёмки.
            elif sorted(source_rows) != sorted(work["source_rows"]):
                _error(errors, f"{path}.source_rows", "must match all source rows for estimate_work")
            else:
                source_rows = list(work["source_rows"])
            if isinstance(estimate_work, str):
                seen_estimate_works.add(estimate_work)
            if status == "quality_concern":
                _error(errors, f"{path}.status", "estimate comparison cannot use quality_concern")
        title = _text(raw.get("title"), f"{path}.title", errors, 200) or ""
        observation = _text(raw.get("observation"), f"{path}.observation", errors, 1500) or ""
        if status == "not_observed":
            # «Не видно в кадре» нельзя незаметно превратить в «не выполнено»:
            # одна фотография не доказывает состояние работы на всём объекте.
            for field, text in (("title", title), ("observation", observation)):
                if any(pattern.search(text) for pattern in NOT_OBSERVED_COMPLETION_CLAIMS):
                    _error(
                        errors,
                        f"{path}.{field}",
                        "not_observed must describe visibility in the frame, not claim non-completion",
                    )
                if "отсутств" in text.casefold() and not any(
                    marker in text.casefold() for marker in FRAME_SCOPE_MARKERS
                ):
                    _error(
                        errors,
                        f"{path}.{field}",
                        "not_observed absence claim must be explicitly limited to the frame",
                    )
        clean_insights.append({
            "visual_insight_id": insight_id,
            "photo_id": photo["photo_id"],
            "category": category,
            "estimate_work": estimate_work,
            "source_rows": source_rows,
            "status": status,
            "title": title,
            "observation": observation,
            "evidence_text": _text(raw.get("evidence_text"), f"{path}.evidence_text", errors, 1000) or "",
            "confidence": confidence,
            "auditor_check": _text(raw.get("auditor_check"), f"{path}.auditor_check", errors, 1000) or "",
            "limitations": _text(raw.get("limitations"), f"{path}.limitations", errors, 1000) or "",
        })

    # Для demo-MVP сохраняем совместимость с историческими частичными ответами,
    # но не позволяем модели переставлять возвращённые работы. Полнота остаётся
    # строгим prompt-контрактом; её runtime enforcement повысил бы число retry.
    delegated_positions = {
        item["canonical_work"]: index for index, item in enumerate(estimate_works)
    }
    returned_positions = [
        delegated_positions[item]
        for item in comparison_order
        if item in delegated_positions
    ]
    if returned_positions != sorted(returned_positions):
        _error(
            errors,
            "visual_insights",
            "estimate comparisons must follow delegated context order",
        )
    if category_order.count("quality") > 1:
        _error(errors, "visual_insights", "at most one quality item is allowed")
    if "quality" in category_order and category_order[-1] != "quality":
        _error(errors, "visual_insights", "quality item must follow all estimate comparisons")

    if errors:
        raise VisualValidationError(errors)
    return {
        "schema_version": SCHEMA_VERSION,
        "photo_id": photo["photo_id"],
        "image_quality": {"usable": usable, "issues": clean_issues},
        "scene_summary": scene_summary,
        "visual_insights": clean_insights,
        "limitations": clean_limitations,
    }


def aggregate(photos: list[dict[str, Any]], analyses: list[dict[str, Any]]) -> dict[str, Any]:
    by_photo = {item["photo_id"]: item for item in analyses}
    items: list[dict[str, Any]] = []
    photo_summaries: list[dict[str, Any]] = []
    for photo in photos:
        analysis = by_photo.get(photo["photo_id"])
        if analysis is None:
            continue
        photo_summaries.append({
            "photo_id": photo["photo_id"],
            "filename": photo["filename"],
            "sha256": photo["sha256"],
            "image_quality": analysis["image_quality"],
            "scene_summary": analysis["scene_summary"],
            "limitations": analysis["limitations"],
        })
        for item in analysis["visual_insights"]:
            items.append({**item, "photo_filename": photo["filename"]})
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "generated" if items else "no_visual_observations",
        "photos_count": len(photos),
        "analyzed_count": len(analyses),
        "photos": photo_summaries,
        "items": items,
    }


def empty_artifact() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "skipped",
        "photos_count": 0,
        "analyzed_count": 0,
        "photos": [],
        "items": [],
    }


def compact_for_llm(artifact: dict[str, Any]) -> dict[str, Any]:
    all_items = artifact.get("items", [])
    by_photo: dict[str, list[dict[str, Any]]] = {}
    for item in all_items:
        by_photo.setdefault(str(item.get("photo_id") or ""), []).append(item)
    items: list[dict[str, Any]] = []
    selected_ids: set[str] = set()
    # Сначала даём аналитику хотя бы одно наблюдение с каждого фото. Иначе лимит
    # контекста легко заполнится первыми кадрами, а последние исчезнут из анализа.
    for photo_items in by_photo.values():
        candidate = next(
            (item for item in photo_items if item.get("category") == "estimate_comparison"),
            photo_items[0] if photo_items else None,
        )
        if candidate is not None and len(items) < MAX_LLM_CONTEXT_ITEMS:
            items.append(candidate)
            selected_ids.add(str(candidate.get("visual_insight_id") or ""))
    for preferred_category in ("quality", "estimate_comparison"):
        for item in all_items:
            if len(items) >= MAX_LLM_CONTEXT_ITEMS:
                break
            insight_id = str(item.get("visual_insight_id") or "")
            if insight_id in selected_ids or item.get("category") != preferred_category:
                continue
            items.append(item)
            selected_ids.add(insight_id)
    return {
        "status": artifact.get("status"),
        "photos_count": artifact.get("photos_count", 0),
        "items_total": len(all_items),
        "items_included": len(items),
        "photo_ids_included": list(dict.fromkeys(item.get("photo_id") for item in items)),
        "items": [
            {
                "visual_insight_id": item.get("visual_insight_id"),
                "photo_id": item.get("photo_id"),
                "category": item.get("category"),
                "estimate_work": item.get("estimate_work"),
                "source_rows": item.get("source_rows"),
                "status": item.get("status"),
                "title": str(item.get("title") or "")[:200],
                "observation": str(item.get("observation") or "")[:400],
                "confidence": item.get("confidence"),
                "auditor_check": str(item.get("auditor_check") or "")[:300],
                "limitations": str(item.get("limitations") or "")[:300],
            }
            for item in items
        ],
    }
