"""Чистая арифметика без файлов и workflow — быстро и по существу."""

from decimal import Decimal

from construction_audit_mvp import core, vision
from _mvp_fixtures import analysis, measurement


def geometry(value=None):
    return vision.canonicalize_geometry(value or analysis(), "Офис")


def test_floor_ceiling_and_gross_walls():
    quantities, _, _ = core.calculate_quantities(geometry())
    metrics = quantities["rooms"][0]["metrics"]
    assert metrics["floor_area_m2"] == "20.00"
    assert metrics["ceiling_area_m2"] == "20.00"
    assert metrics["gross_wall_area_m2"] == "54.00"


def test_openings_and_net_walls():
    quantities, _, _ = core.calculate_quantities(geometry())
    metrics = quantities["rooms"][0]["metrics"]
    assert metrics["doors_area_m2"] == "1.89"
    assert metrics["windows_area_m2"] == "2.10"
    assert metrics["net_wall_area_m2"] == "50.01"


def test_baseboard():
    quantities, _, _ = core.calculate_quantities(geometry())
    assert quantities["rooms"][0]["metrics"]["baseboard_length_m"] == "17.10"


def test_shared_door_deduplicated_in_object_total():
    quantities, trace, _ = core.calculate_quantities(geometry())
    assert quantities["object_totals"]["door_count"] == "1"
    entry = next(item for item in trace["entries"] if item["trace_id"] == "object_total:door_count")
    assert entry["inputs"]["element_ids"] == ["door-shared"]


def test_same_dimensions_different_ids_not_deduplicated():
    value = analysis(); value["rooms"][0]["doors"][0]["element_id"] = "door-2"
    quantities, _, _ = core.calculate_quantities(geometry(value))
    assert quantities["object_totals"]["door_count"] == "2"


def test_partial_missing_window_height_keeps_counts_and_floor():
    value = analysis(); value["rooms"][0]["windows"][0]["height_m"] = measurement(None)
    quantities, _, warnings = core.calculate_quantities(geometry(value))
    room = quantities["rooms"][1]["metrics"]
    assert room["window_count"] == "1" and room["floor_area_m2"] == "20.00"
    assert room["net_wall_area_m2"] is None
    assert any(item["code"] == "missing_geometry" for item in warnings)


def test_decimal_formatting_is_deterministic():
    assert core.display_decimal(Decimal("1.005")) == "1.01"
