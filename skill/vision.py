from __future__ import annotations

import math
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any


PLAN_ID = "plan_001"
MAX_ROOMS = 200
MAX_OPENINGS = 100
SOURCE_TYPES = {
    "explicit_area_label",
    "explicit_dimension_line",
    "explicit_plan_label",
    "explicit_scale",
    "derived_from_explicit_dimensions",
    "visually_detected_symbol",
    "not_found",
}
FORBIDDEN_SOURCE_TYPES = {
    "guessed",
    "assumed_standard",
    "estimated_from_appearance",
    "inferred_without_measurement",
    "estimate_document",
    "user_correction",
}

MEASUREMENT_LIMITS = {
    "floor_area_m2": Decimal("100000"),
    "length_m": Decimal("10000"),
    "width_m": Decimal("10000"),
    "perimeter_m": Decimal("10000"),
    "height_m": Decimal("100"),
}


class GeometryValidationError(ValueError):
    def __init__(self, errors: list[dict[str, str]]):
        super().__init__("Результат Vision-субагента не соответствует схеме геометрии.")
        self.errors = errors


def decimal_text(value: Decimal | str | int | float | None) -> str | None:
    if value is None:
        return None
    number = value if isinstance(value, Decimal) else Decimal(str(value))
    if number == 0:
        return "0"
    return format(number.normalize(), "f")


def review_number(value: str | None) -> str:
    if value is None:
        return "—"
    number = Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return format(number, "f").replace(".", ",")


def _error(errors: list[dict[str, str]], path: str, reason: str) -> None:
    errors.append({"path": path, "reason": reason})


def _exact_object(
    value: Any,
    required: set[str],
    path: str,
    errors: list[dict[str, str]],
) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        _error(errors, path, "must be an object")
        return None
    for key in sorted(set(value) - required):
        _error(errors, f"{path}.{key}" if path else key, "unknown field")
    for key in sorted(required - set(value)):
        _error(errors, f"{path}.{key}" if path else key, "required field is missing")
    return value


def _bounded_text(
    value: Any,
    path: str,
    errors: list[dict[str, str]],
    *,
    maximum: int,
    allow_empty: bool = True,
    nullable: bool = False,
) -> str | None:
    if nullable and value is None:
        return None
    if not isinstance(value, str):
        _error(errors, path, "must be a string")
        return None
    if len(value) > maximum or (not allow_empty and not value.strip()):
        _error(errors, path, f"must contain {'1 to ' if not allow_empty else 'at most '}{maximum} characters")
        return None
    return value.strip() if not allow_empty else value


def _string_list(
    value: Any,
    path: str,
    errors: list[dict[str, str]],
    *,
    maximum_items: int,
) -> list[str]:
    if not isinstance(value, list):
        _error(errors, path, "must be an array")
        return []
    if len(value) > maximum_items:
        _error(errors, path, f"must contain at most {maximum_items} items")
    clean: list[str] = []
    for index, item in enumerate(value[:maximum_items]):
        text = _bounded_text(item, f"{path}[{index}]", errors, maximum=1000)
        if text is not None:
            clean.append(text)
    return clean


def _finite_decimal(
    value: Any,
    path: str,
    errors: list[dict[str, str]],
    *,
    maximum: Decimal,
) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        _error(errors, path, "must be a finite positive number or null")
        return None
    if isinstance(value, float) and not math.isfinite(value):
        _error(errors, path, "must be finite")
        return None
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        _error(errors, path, "must be a finite positive number or null")
        return None
    if not number.is_finite() or number <= 0 or number > maximum:
        _error(errors, path, f"must be greater than 0 and at most {maximum}")
        return None
    return decimal_text(number)


def _measurement(
    value: Any,
    path: str,
    errors: list[dict[str, str]],
    *,
    maximum: Decimal,
) -> dict[str, Any]:
    required = {"value", "confidence", "source_type", "evidence_text"}
    item = _exact_object(value, required, path, errors)
    if item is None:
        return {"value": None, "confidence": 0, "source_type": "not_found", "evidence_text": ""}

    number = _finite_decimal(item.get("value"), f"{path}.value", errors, maximum=maximum)
    confidence = item.get("confidence")
    if (
        isinstance(confidence, bool)
        or not isinstance(confidence, (int, float))
        or not math.isfinite(confidence)
        or not 0 <= confidence <= 1
    ):
        _error(errors, f"{path}.confidence", "must be a finite number between 0 and 1")
        confidence = 0
    source_type = item.get("source_type")
    if source_type in FORBIDDEN_SOURCE_TYPES:
        _error(errors, f"{path}.source_type", f"forbidden source_type: {source_type}")
    elif source_type not in SOURCE_TYPES:
        _error(errors, f"{path}.source_type", "unsupported source_type")
    evidence = _bounded_text(item.get("evidence_text"), f"{path}.evidence_text", errors, maximum=500)
    evidence = evidence if evidence is not None else ""

    # Отсутствующее значение должно быть явно признано отсутствующим. Иначе
    # модель могла бы оставить value=null, но сохранить видимость уверенного замера.
    if number is None:
        if confidence != 0 or source_type != "not_found" or evidence != "":
            _error(errors, path, "null value requires confidence=0, source_type=not_found and empty evidence_text")
    elif source_type == "not_found":
        _error(errors, path, "non-null value cannot use source_type=not_found")
    return {
        "value": number,
        "confidence": float(confidence) if isinstance(confidence, (int, float)) else 0,
        "source_type": source_type if isinstance(source_type, str) else "",
        "evidence_text": evidence,
    }


def _opening(
    value: Any,
    path: str,
    errors: list[dict[str, str]],
) -> dict[str, Any] | None:
    item = _exact_object(value, {"element_id", "width_m", "height_m"}, path, errors)
    if item is None:
        return None
    element_id = _bounded_text(item.get("element_id"), f"{path}.element_id", errors, maximum=200, allow_empty=False)
    width = _measurement(item.get("width_m"), f"{path}.width_m", errors, maximum=Decimal("100"))
    height = _measurement(item.get("height_m"), f"{path}.height_m", errors, maximum=Decimal("100"))
    if element_id is None:
        return None
    return {"element_id": element_id, "width_m": width, "height_m": height}


def validate_analysis(value: Any, expected_plan_id: str = PLAN_ID) -> dict[str, Any]:
    errors: list[dict[str, str]] = []
    required = {
        "schema_version",
        "plan_id",
        "image_quality",
        "object_name_suggestion",
        "rooms",
        "general_warnings",
    }
    root = _exact_object(value, required, "", errors)
    if root is None:
        raise GeometryValidationError(errors)

    if root.get("schema_version") != 1 or type(root.get("schema_version")) is not int:
        _error(errors, "schema_version", "must equal integer 1")
    if root.get("plan_id") != expected_plan_id:
        _error(errors, "plan_id", "must match the imported plan_id")

    quality_raw = _exact_object(root.get("image_quality"), {"usable", "issues"}, "image_quality", errors)
    if quality_raw is None:
        quality = {"usable": False, "issues": []}
    else:
        usable = quality_raw.get("usable")
        if type(usable) is not bool:
            _error(errors, "image_quality.usable", "must be a boolean")
            usable = False
        quality = {
            "usable": usable,
            "issues": _string_list(quality_raw.get("issues"), "image_quality.issues", errors, maximum_items=100),
        }
    suggestion = _bounded_text(
        root.get("object_name_suggestion"),
        "object_name_suggestion",
        errors,
        maximum=200,
        nullable=True,
    )
    general_warnings = _string_list(
        root.get("general_warnings"), "general_warnings", errors, maximum_items=200
    )

    rooms_raw = root.get("rooms")
    if not isinstance(rooms_raw, list):
        _error(errors, "rooms", "must be an array")
        rooms_raw = []
    elif not 1 <= len(rooms_raw) <= MAX_ROOMS:
        _error(errors, "rooms", f"must contain 1 to {MAX_ROOMS} rooms")

    clean_rooms: list[dict[str, Any]] = []
    source_ids: set[str] = set()
    for room_index, raw_room in enumerate(rooms_raw[:MAX_ROOMS]):
        path = f"rooms[{room_index}]"
        room_required = {
            "source_room_id",
            "name",
            "floor_area_m2",
            "length_m",
            "width_m",
            "perimeter_m",
            "height_m",
            "doors",
            "windows",
            "warnings",
        }
        room = _exact_object(raw_room, room_required, path, errors)
        if room is None:
            continue
        source_room_id = _bounded_text(
            room.get("source_room_id"), f"{path}.source_room_id", errors, maximum=200, allow_empty=False
        )
        name = _bounded_text(room.get("name"), f"{path}.name", errors, maximum=200, allow_empty=False)
        if source_room_id in source_ids:
            _error(errors, f"{path}.source_room_id", "must be unique")
        elif source_room_id is not None:
            source_ids.add(source_room_id)

        measurements = {
            field: _measurement(room.get(field), f"{path}.{field}", errors, maximum=limit)
            for field, limit in MEASUREMENT_LIMITS.items()
        }
        collections: dict[str, list[dict[str, Any]]] = {"doors": [], "windows": []}
        for collection in ("doors", "windows"):
            raw_items = room.get(collection)
            if not isinstance(raw_items, list):
                _error(errors, f"{path}.{collection}", "must be an array")
                continue
            if len(raw_items) > MAX_OPENINGS:
                _error(errors, f"{path}.{collection}", f"must contain at most {MAX_OPENINGS} items")
            local_ids: set[str] = set()
            for item_index, raw_item in enumerate(raw_items[:MAX_OPENINGS]):
                opening = _opening(raw_item, f"{path}.{collection}[{item_index}]", errors)
                if opening is None:
                    continue
                if opening["element_id"] in local_ids:
                    _error(
                        errors,
                        f"{path}.{collection}[{item_index}].element_id",
                        "must be unique within the room collection",
                    )
                local_ids.add(opening["element_id"])
                collections[collection].append(opening)
        warnings = _string_list(room.get("warnings"), f"{path}.warnings", errors, maximum_items=100)
        if source_room_id is not None and name is not None:
            clean_rooms.append(
                {
                    "source_room_id": source_room_id,
                    "name": name,
                    **measurements,
                    **collections,
                    "warnings": warnings,
                }
            )

    if errors:
        errors.sort(key=lambda item: (item["path"], item["reason"]))
        raise GeometryValidationError(errors)
    return {
        "schema_version": 1,
        "plan_id": expected_plan_id,
        "image_quality": quality,
        "object_name_suggestion": suggestion,
        "rooms": clean_rooms,
        "general_warnings": general_warnings,
    }


def _opening_conflicts(rooms: list[dict[str, Any]], collection: str) -> list[dict[str, Any]]:
    seen: dict[str, tuple[str | None, str | None, str]] = {}
    conflicts: list[dict[str, Any]] = []
    for room in rooms:
        for opening in room[collection]:
            current = (opening["width_m"], opening["height_m"], room["room_id"])
            previous = seen.get(opening["element_id"])
            if previous and previous[:2] != current[:2]:
                conflicts.append(
                    {
                        "type": "opening_dimension_conflict",
                        "collection": collection,
                        "element_id": opening["element_id"],
                        "room_ids": [previous[2], current[2]],
                        "dimensions": [
                            {"width_m": previous[0], "height_m": previous[1]},
                            {"width_m": current[0], "height_m": current[1]},
                        ],
                    }
                )
            else:
                seen[opening["element_id"]] = current
    return conflicts


def refresh_geometry_derived(geometry: dict[str, Any]) -> dict[str, Any]:
    """Recalculate derivable room fields and rebuild missing/conflict lists."""
    missing: list[dict[str, str]] = []
    conflicts: list[dict[str, Any]] = []
    rooms = geometry["rooms"]
    for room in rooms:
        room_id = room["room_id"]
        for field in MEASUREMENT_LIMITS:
            if room[field] is None:
                missing.append({"room_id": room_id, "field": field})
        for collection in ("doors", "windows"):
            for opening in room[collection]:
                for dimension in ("width_m", "height_m"):
                    if opening[dimension] is None:
                        missing.append(
                            {
                                "room_id": room_id,
                                "field": f"{collection}.{opening['element_id']}.{dimension}",
                            }
                        )

        length = room["length_m"]
        width = room["width_m"]
        if length is not None and width is not None:
            length_d, width_d = Decimal(length), Decimal(width)
            checks = (
                ("floor_area_m2", length_d * width_d),
                ("perimeter_m", Decimal(2) * (length_d + width_d)),
            )
            for field, calculated in checks:
                reported = room[field]
                measurement = room.get("measurements", {}).get(field, {})
                # Явную подпись с плана не затираем расчётом. Пересчитываются только
                # пустые поля и значения, которые изначально тоже были производными.
                if reported is None or measurement.get("source_type") == "derived_from_explicit_dimensions":
                    value = decimal_text(calculated)
                    room[field] = value
                    room.setdefault("measurements", {})[field] = {
                        "value": value,
                        "confidence": min(
                            float(room.get("measurements", {}).get("length_m", {}).get("confidence", 0)),
                            float(room.get("measurements", {}).get("width_m", {}).get("confidence", 0)),
                        ),
                        "source_type": "derived_from_explicit_dimensions",
                        "evidence_text": "Рассчитано по длине и ширине помещения.",
                    }
                    reported = value
                if (
                    reported is not None
                    and calculated
                    and abs(Decimal(reported) - calculated) / calculated > Decimal("0.03")
                ):
                    conflicts.append(
                        {
                            "type": "geometry_arithmetic_conflict",
                            "room_id": room_id,
                            "field": field,
                            "reported_value": reported,
                            "calculated_value": decimal_text(calculated),
                        }
                    )

    conflicts.extend(_opening_conflicts(rooms, "doors"))
    conflicts.extend(_opening_conflicts(rooms, "windows"))
    # Выше часть пустых полей могла заполниться расчётом. Если оставить первый
    # список missing, review попросит пользователя исправить уже известное значение.
    missing = []
    for room in rooms:
        room_id = room["room_id"]
        for field in MEASUREMENT_LIMITS:
            if room[field] is None:
                missing.append({"room_id": room_id, "field": field})
        for collection in ("doors", "windows"):
            for opening in room[collection]:
                for dimension in ("width_m", "height_m"):
                    if opening[dimension] is None:
                        missing.append(
                            {
                                "room_id": room_id,
                                "field": f"{collection}.{opening['element_id']}.{dimension}",
                            }
                        )
    geometry["missing_fields"] = missing
    geometry["conflicts"] = conflicts
    return geometry


def canonicalize_geometry(analysis: dict[str, Any], object_name: str) -> dict[str, Any]:
    # room_NNN должен оставаться стабильным при одинаковом ответе Vision:
    # порядок элементов в JSON модели сам по себе на идентификаторы не влияет.
    ordered = sorted(analysis["rooms"], key=lambda item: (item["source_room_id"].casefold(), item["name"].casefold()))
    rooms: list[dict[str, Any]] = []
    missing: list[dict[str, str]] = []
    warnings = list(analysis["general_warnings"])
    conflicts: list[dict[str, Any]] = []
    source_map: dict[str, str] = {}
    for index, room in enumerate(ordered, start=1):
        room_id = f"room_{index:03d}"
        source_map[room["source_room_id"]] = room_id
        canonical = {
            "room_id": room_id,
            "source_room_id": room["source_room_id"],
            "name": room["name"],
            **{field: room[field]["value"] for field in MEASUREMENT_LIMITS},
            "measurements": {field: room[field] for field in MEASUREMENT_LIMITS},
            "doors": [],
            "windows": [],
            "warnings": list(room["warnings"]),
        }
        for field in MEASUREMENT_LIMITS:
            if canonical[field] is None:
                missing.append({"room_id": room_id, "field": field})
        for collection in ("doors", "windows"):
            for opening in room[collection]:
                item = {
                    "element_id": opening["element_id"],
                    "width_m": opening["width_m"]["value"],
                    "height_m": opening["height_m"]["value"],
                    "measurements": {
                        "width_m": opening["width_m"],
                        "height_m": opening["height_m"],
                    },
                }
                canonical[collection].append(item)
                for dimension in ("width_m", "height_m"):
                    if item[dimension] is None:
                        missing.append(
                            {"room_id": room_id, "field": f"{collection}.{opening['element_id']}.{dimension}"}
                        )
        rooms.append(canonical)
        warnings.extend(room["warnings"])

        length = canonical["length_m"]
        width = canonical["width_m"]
        if length is not None and width is not None:
            length_d, width_d = Decimal(length), Decimal(width)
            checks = (
                ("floor_area_m2", length_d * width_d),
                ("perimeter_m", Decimal(2) * (length_d + width_d)),
            )
            for field, calculated in checks:
                reported = canonical[field]
                if reported is not None and calculated and abs(Decimal(reported) - calculated) / calculated > Decimal("0.03"):
                    conflicts.append(
                        {
                            "type": "geometry_arithmetic_conflict",
                            "room_id": room_id,
                            "field": field,
                            "reported_value": reported,
                            "calculated_value": decimal_text(calculated),
                        }
                    )

    conflicts.extend(_opening_conflicts(rooms, "doors"))
    conflicts.extend(_opening_conflicts(rooms, "windows"))
    geometry = {
        "schema_version": 1,
        "plan_id": analysis["plan_id"],
        "object_name": object_name,
        "object_name_suggestion": analysis["object_name_suggestion"],
        "image_quality": analysis["image_quality"],
        "source_room_id_map": source_map,
        "rooms": rooms,
        "warnings": warnings,
        "missing_fields": missing,
        "conflicts": conflicts,
    }
    return refresh_geometry_derived(geometry)


def derived_state_issues(geometry: dict[str, Any]) -> list[dict[str, str]]:
    """Return only internal gaps where inputs exist but a derived value is absent."""
    issues: list[dict[str, str]] = []
    for room in geometry.get("rooms", []):
        # Реально отсутствующие length/width — допустимая неполнота входа.
        # Но при наличии обоих Python обязан был сохранить площадь и периметр.
        if room.get("length_m") is None or room.get("width_m") is None:
            continue
        for field in ("floor_area_m2", "perimeter_m"):
            if room.get(field) is None:
                issues.append({"room_id": str(room.get("room_id")), "field": field})
    return issues


def build_geometry_review(geometry: dict[str, Any]) -> dict[str, Any]:
    unique_doors = {item["element_id"] for room in geometry["rooms"] for item in room["doors"]}
    unique_windows = {item["element_id"] for room in geometry["rooms"] for item in room["windows"]}
    floor_values = [Decimal(room["floor_area_m2"]) for room in geometry["rooms"] if room["floor_area_m2"] is not None]
    rooms = []
    missing_by_room: dict[str, list[str]] = {}
    for item in geometry["missing_fields"]:
        missing_by_room.setdefault(item["room_id"], []).append(item["field"])
    for room in geometry["rooms"]:
        rooms.append(
            {
                "room_id": room["room_id"],
                "name": room["name"],
                **{field: review_number(room[field]) for field in MEASUREMENT_LIMITS},
                "doors": [
                    {
                        "element_id": item["element_id"],
                        "width_m": review_number(item["width_m"]),
                        "height_m": review_number(item["height_m"]),
                    }
                    for item in room["doors"]
                ],
                "windows": [
                    {
                        "element_id": item["element_id"],
                        "width_m": review_number(item["width_m"]),
                        "height_m": review_number(item["height_m"]),
                    }
                    for item in room["windows"]
                ],
                "warnings": room["warnings"],
                "missing_fields": missing_by_room.get(room["room_id"], []),
            }
        )
    return {
        "object_name": geometry["object_name"],
        "image_quality": geometry["image_quality"],
        "rooms": rooms,
        "totals": {
            "rooms_count": len(rooms),
            "floor_area_m2": review_number(decimal_text(sum(floor_values, Decimal(0)))) if len(floor_values) == len(rooms) else "—",
            "unique_doors_count": len(unique_doors),
            "unique_windows_count": len(unique_windows),
        },
        "warnings": geometry["warnings"],
        "missing_fields": geometry["missing_fields"],
        "conflicts": geometry["conflicts"],
    }
