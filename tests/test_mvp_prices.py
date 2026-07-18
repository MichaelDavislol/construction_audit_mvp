"""Цена, количество и итоговая стоимость проверяются независимо друг от друга."""

import json
from pathlib import Path

import pytest

from construction_audit_mvp import plugin

from _mvp_fixtures import (
    call,
    ctx,
    finalize,
    mapping,
    price_catalog_response,
    price_match,
    setup_geometry,
    mvp_api,
)


def _confirm_without_catalog(mvp_api, tmp_path, rows=None):
    ext, *_rest, saved = setup_geometry(mvp_api, tmp_path, rows)
    confirmed = call(
        ext,
        "confirm_geometry",
        ctx("confirm-price", "confirm-price-msg"),
        job_id="audit_1",
        geometry_revision=saved["geometry_revision"],
        confirmed=True,
    )
    assert confirmed["mcp_tool"] == "mcp_construction_prices__get_supported_works"
    return ext


@pytest.mark.parametrize(
    ("response", "reason"),
    [
        ([], "must be an object"),
        ({}, "required field is missing"),
        ({"result": {}}, "must be an array"),
        ({"result": [{"id": "x", "name": "Работа", "unit": "м²"}]}, "required field is missing"),
        ({"result": [{"id": "x", "name": "Работа", "unit": "м²", "price": None}]}, "finite non-negative"),
    ],
)
def test_catalog_wrapper_and_items_are_validated(mvp_api, tmp_path, response, reason):
    ext = _confirm_without_catalog(mvp_api, tmp_path)
    result = call(ext, "save_price_catalog", job_id="audit_1", catalog_response=response)
    assert result["code"] == "price_catalog_schema_invalid"
    assert reason in json.dumps(result["details"]["validation_errors"], ensure_ascii=False)


def test_catalog_cannot_be_saved_before_geometry_confirmation(mvp_api, tmp_path):
    ext, *_ = setup_geometry(mvp_api, tmp_path)
    result = call(ext, "save_price_catalog", job_id="audit_1", catalog_response=price_catalog_response())
    assert result["code"] == "geometry_confirmation_required"


def test_duplicate_catalog_ids_are_rejected(mvp_api, tmp_path):
    ext = _confirm_without_catalog(mvp_api, tmp_path)
    item = {"id": "same", "name": "Работа", "unit": "м²", "price": 1}
    result = call(
        ext,
        "save_price_catalog",
        job_id="audit_1",
        catalog_response={"result": [item, {**item, "name": "Другая работа"}]},
    )
    assert result["code"] == "price_catalog_schema_invalid"
    assert result["details"]["validation_errors"][-1]["reason"] == "duplicate id"


def test_result_catalog_is_saved_and_wrapper_is_not_treated_as_array(mvp_api, tmp_path):
    ext = _confirm_without_catalog(mvp_api, tmp_path)
    response = price_catalog_response(extra_wrapper_metadata="ignored")
    saved = call(ext, "save_price_catalog", job_id="audit_1", catalog_response=response)
    artifact = json.loads(
        (mvp_api.root / "state/jobs/audit_1/output/price_catalog.json").read_text()
    )
    assert saved["catalog_items_count"] == len(response["result"])
    assert artifact["items"][0] == {
        "id": "wall_priming", "name": "Грунтовка стен", "unit": "м²", "price": "120",
    }
    assert "result" not in artifact and "extra_wrapper_metadata" not in artifact


def test_geometry_correction_invalidates_saved_catalog_and_mapping_token(mvp_api, tmp_path):
    # После правки высоты старые цены и mapping относятся уже к другой версии
    # расчёта. Оставить их было бы удобнее, но результат перестал бы быть честным.
    ext, *_ = setup_geometry(mvp_api, tmp_path, confirm=True)
    root = mvp_api.root / "state/jobs/audit_1"
    assert (root / "output/price_catalog.json").is_file()
    corrected = call(
        ext,
        "confirm_geometry",
        ctx("price-correction", "price-correction-msg"),
        job_id="audit_1",
        geometry_revision=1,
        confirmed=False,
        corrections=[{
            "target": "rooms",
            "room_ids": ["room_001"],
            "element_ids": "all",
            "field": "height_m",
            "value": 3.2,
        }],
        user_statement="Высота первого офиса 3,2 метра",
    )
    manifest = json.loads((root / "manifest.json").read_text())
    assert corrected["geometry_revision"] == 2
    assert not (root / "output/price_catalog.json").exists()
    assert "price_catalog_sha256" not in manifest
    assert "mapping_generation_token" not in manifest


def test_mapping_schema_returns_only_stable_mcp_id(mvp_api, tmp_path):
    ext = _confirm_without_catalog(mvp_api, tmp_path)
    catalog_response = price_catalog_response()
    catalog_response["result"][1]["name"] = "Нанесение краски на стены"
    saved = call(ext, "save_price_catalog", job_id="audit_1", catalog_response=catalog_response)
    example = saved["mapping_delegation"]["expected_output"]
    assert "mcp_work_id" in example
    assert "mcp_price\"" not in example and "price\":" not in example
    assert "не возвращать, не изменять и не вычислять price" in saved["mapping_delegation"]["constraints"].casefold()


def test_python_reloads_price_by_id_and_calculates_deviations(mvp_api, tmp_path):
    rows = [[1, "Офис 1", "Устройство пола", "м²", 2, 2000, 4000, ""]]
    ext, *_ = setup_geometry(mvp_api, tmp_path, rows, confirm=True)
    value = mapping(
        room_matches=[mapping()["room_matches"][0]],
        work_matches=[mapping()["work_matches"][0]],
        price_matches=[price_match(2, "Устройство пола")],
    )
    call(ext, "run_audit", job_id="audit_1", mapping=value)
    price_artifact = json.loads(
        (mvp_api.root / "state/jobs/audit_1/output/price_checks.json").read_text()
    )
    audit_artifact = json.loads(
        (mvp_api.root / "state/jobs/audit_1/output/findings.json").read_text()
    )
    check = price_artifact["checks"][0]
    assert check["mcp_work_id"] == "floor_installation"
    assert check["mcp_price"] == "1700"
    assert check["quantity"] == "2"
    assert check["mcp_total"] == "3400"
    assert check["price_deviation_absolute"] == "300"
    assert check["total_deviation_absolute"] == "600"
    assert check["unit_price_impact"] == "600"
    assert check["total_cost_impact"] == "600"
    assert check["status"] == "deviation_found"
    finding_types = {item["type"] for item in audit_artifact["findings"]}
    assert "price_overstatement" in finding_types
    assert "total_cost_overstatement" not in finding_types
    price_finding = next(item for item in audit_artifact["findings"] if item["type"] == "price_overstatement")
    assert price_finding["line_cost_analysis"]["full_variance_signed"] == "-30000"
    assert price_artifact["checks"][0] == check


def test_combined_quantity_and_price_error_has_one_price_finding_and_full_decomposition(mvp_api, tmp_path):
    rows = [[7, "Офис 1", "Устройство пола", "м²", 22, 1800, 39600, ""]]
    ext, *_ = setup_geometry(mvp_api, tmp_path, rows, confirm=True)
    value = mapping(
        room_matches=[mapping()["room_matches"][0]],
        work_matches=[mapping()["work_matches"][0]],
        price_matches=[price_match(2, "Устройство пола")],
    )
    call(ext, "run_audit", job_id="audit_1", mapping=value)
    artifact = json.loads(
        (mvp_api.root / "state/jobs/audit_1/output/findings.json").read_text()
    )
    price_findings = [item for item in artifact["findings"] if item["type"].startswith("price_")]
    assert len(price_findings) == 1
    assert not any(item["type"].startswith("total_cost_") for item in artifact["findings"])
    finding = price_findings[0]
    assert finding["source_position"] == "7"
    assert finding["line_cost_analysis"] == {
        "status": "calculated",
        "estimate_total": "39600",
        "reference_total": "34000",
        "full_variance_signed": "5600",
        "full_variance_absolute": "5600",
        "full_variance_percent": "16.47058823529411764705882353",
        "quantity_effect_signed": "3400",
        "price_effect_signed": "2200",
        "arithmetic_effect_signed": "0",
        "decomposition_formula": (
            "estimate_total - control_quantity * mcp_price = "
            "(estimate_quantity - control_quantity) * mcp_price + "
            "(estimate_price - mcp_price) * estimate_quantity + "
            "(estimate_total - estimate_quantity * estimate_price)"
        ),
        "simultaneous_quantity_and_price_deviation": True,
        "total_source": "provided_or_cached",
    }


def test_price_mapping_does_not_require_exact_catalog_name(mvp_api, tmp_path):
    rows = [[1, "Офис 1", "Нанесение краски на стены", "м²", 20, 450, 9000, ""]]
    ext, *_ = setup_geometry(mvp_api, tmp_path, rows, confirm=True)
    value = mapping(
        room_matches=[mapping()["room_matches"][0]],
        work_matches=[{
            "source_row": 2,
            "estimate_work": "Нанесение краски на стены",
            "canonical_work": "Окраска стен",
            "confidence": .9,
            "reason": "Одинаковые действие и объект работы.",
        }],
        price_matches=[price_match(2, "Нанесение краски на стены", "wall_painting")],
    )
    result = call(ext, "run_audit", job_id="audit_1", mapping=value)
    checks = json.loads(
        (mvp_api.root / "state/jobs/audit_1/output/price_checks.json").read_text()
    )["checks"]
    assert result["status"] == "visual_review_required"
    assert checks[0]["mcp_work_id"] == "wall_painting"
    assert checks[0]["mcp_work_name"] == "Окраска стен"


def test_missing_estimate_price_allows_total_check(mvp_api, tmp_path):
    rows = [[1, "Офис 1", "Устройство пола", "м²", 2, None, 3400, ""]]
    ext, *_ = setup_geometry(mvp_api, tmp_path, rows, confirm=True)
    value = mapping(
        room_matches=[mapping()["room_matches"][0]],
        work_matches=[mapping()["work_matches"][0]],
        price_matches=[price_match(2, "Устройство пола")],
    )
    call(ext, "run_audit", job_id="audit_1", mapping=value)
    artifact = json.loads(
        (mvp_api.root / "state/jobs/audit_1/output/findings.json").read_text()
    )
    check = artifact["price_checks"][0]
    assert check["status"] == "partially_checked"
    assert check["estimate_price"] is None and check["mcp_total"] == "3400"
    assert any(item["code"] == "price_check_missing_price" for item in artifact["warnings"])


def test_missing_quantity_keeps_unit_price_check_independent(mvp_api, tmp_path):
    # Без количества нельзя проверить итоговую стоимость, зато сравнить две цены
    # за единицу по-прежнему можно — не теряем полезную часть проверки.
    rows = [[1, "Офис 1", "Устройство пола", "м²", None, 1700, None, ""]]
    ext, *_ = setup_geometry(mvp_api, tmp_path, rows, confirm=True)
    value = mapping(
        room_matches=[mapping()["room_matches"][0]],
        work_matches=[mapping()["work_matches"][0]],
        price_matches=[price_match(2, "Устройство пола")],
    )
    call(ext, "run_audit", job_id="audit_1", mapping=value)
    artifact = json.loads(
        (mvp_api.root / "state/jobs/audit_1/output/findings.json").read_text()
    )
    check = artifact["price_checks"][0]
    assert check["status"] == "partially_checked"
    assert check["mcp_total"] is None and check["price_deviation_absolute"] == "0"
    assert any(item["code"] == "price_check_missing_quantity" for item in artifact["warnings"])


def test_price_unsupported_does_not_disable_geometry_check(mvp_api, tmp_path):
    rows = [[1, "Офис 1", "Устройство пола", "м²", 20, 1700, 34000, ""]]
    ext, *_ = setup_geometry(mvp_api, tmp_path, rows, confirm=True)
    value = mapping(
        room_matches=[mapping()["room_matches"][0]],
        work_matches=[mapping()["work_matches"][0]],
        price_matches=[],
        price_unsupported=[{
            "source_row": 2, "estimate_work": "Устройство пола", "reason": "Нет однозначной позиции MCP.",
        }],
    )
    result = call(ext, "run_audit", job_id="audit_1", mapping=value)
    artifact = json.loads(
        (mvp_api.root / "state/jobs/audit_1/output/findings.json").read_text()
    )
    assert result["summary"]["checked_rows"] == 1
    assert artifact["price_checks"][0]["status"] == "not_checked"
    assert any(item["code"] == "unsupported_price_work" for item in artifact["warnings"])


def test_ambiguous_price_mapping_requires_review_without_report(mvp_api, tmp_path):
    rows = [[1, "Офис 1", "Устройство пола", "м²", 20, 1700, 34000, ""]]
    ext, *_ = setup_geometry(mvp_api, tmp_path, rows, confirm=True)
    value = mapping(
        room_matches=[mapping()["room_matches"][0]],
        work_matches=[mapping()["work_matches"][0]],
        price_matches=[],
        price_unresolved=[{
            "source_row": 2,
            "estimate_work": "Устройство пола",
            "candidate_mcp_work_ids": ["floor_installation"],
            "reason": "Требуется подтверждение.",
            "requires_human_confirmation": True,
        }],
    )
    result = call(ext, "run_audit", job_id="audit_1", mapping=value)
    assert result["status"] == "mapping_review_required"
    assert result["unresolved"][0]["candidate_mcp_work_ids"] == ["floor_installation"]
    assert not (mvp_api.root / "state/jobs/audit_1/output/report.html").exists()


def test_incompatible_price_unit_is_rejected(mvp_api, tmp_path):
    rows = [[1, "Офис 1", "Устройство пола", "шт", 2, 1700, 3400, ""]]
    ext, *_ = setup_geometry(mvp_api, tmp_path, rows, confirm=True)
    value = mapping(
        room_matches=[mapping()["room_matches"][0]],
        work_matches=[],
        work_unsupported=[{
            "source_row": 2, "estimate_work": "Устройство пола", "reason": "Geometry unit incompatible.",
        }],
        price_matches=[price_match(2, "Устройство пола")],
    )
    result = call(ext, "run_audit", job_id="audit_1", mapping=value)
    assert result["code"] == "mapping_schema_invalid"
    assert "несовместима" in result["details"]["validation_errors"][0]["message"]


def test_report_contains_all_price_check_fields(mvp_api, tmp_path):
    rows = [[1, "Офис 1", "Устройство пола", "м²", 2, 2000, 4000, ""]]
    ext, *_ = setup_geometry(mvp_api, tmp_path, rows, confirm=True)
    value = mapping(
        room_matches=[mapping()["room_matches"][0]],
        work_matches=[mapping()["work_matches"][0]],
        price_matches=[price_match(2, "Устройство пола")],
    )
    result = call(ext, "run_audit", job_id="audit_1", mapping=value)
    result = finalize(ext)
    html = Path(result["report_artifact"]["path"]).read_text(encoding="utf-8")
    for text in (
        "Цена за единицу", "Цена сметы", "Цена MCP", "Количество сметы",
        "Стоимость сметы", "Контрольная стоимость", "Расчётное влияние",
        "Статус", "floor_installation", "Устройство пола",
    ):
        assert text in html


def test_skill_documents_mcp_unavailability_handling():
    skill = Path(plugin.__file__).with_name("SKILL.md").read_text(encoding="utf-8")
    assert "price_catalog_unavailable" in skill
    assert "mcp_construction_prices__get_supported_works" in skill
