"""Mapping проверяется построчно: похожие названия не дают права склеивать строки."""

import copy
import json

from _mvp_fixtures import (
    analysis, call, ctx, mapping, price_catalog_response, price_match,
    setup_geometry, mvp_api,
)


def test_valid_mapping_runs(mvp_api, tmp_path):
    ext, *_ = setup_geometry(mvp_api, tmp_path, confirm=True)
    response = call(ext, "run_audit", job_id="audit_1", mapping=mapping(), tolerance_percent=5)
    assert response["status"] == "visual_review_required"


def test_mapping_without_delegation_token_is_rejected(mvp_api, tmp_path):
    ext, *_ = setup_geometry(mvp_api, tmp_path, confirm=True)
    value = mapping()
    value.pop("delegation_token")
    response = call(ext, "run_audit", job_id="audit_1", mapping=value)
    assert response["code"] == "mapping_delegation_invalid"
    assert response["details"]["reason"] == "missing_delegation_token"


def test_mapping_with_wrong_delegation_token_is_rejected(mvp_api, tmp_path):
    ext, *_ = setup_geometry(mvp_api, tmp_path, confirm=True)
    response = call(
        ext, "run_audit", job_id="audit_1",
        mapping=mapping(delegation_token="x" * 43),
    )
    assert response["code"] == "mapping_delegation_invalid"
    assert response["details"]["reason"] == "stale_or_foreign_delegation_token"


def test_mapping_token_from_previous_geometry_revision_is_rejected(mvp_api, tmp_path):
    ext, *_ = setup_geometry(mvp_api, tmp_path, confirm=True)
    manifest_path = mvp_api.root / "state/jobs/audit_1/manifest.json"
    stale_token = json.loads(manifest_path.read_text())["mapping_generation_token"]
    saved = call(
        ext, "save_geometry", ctx("second-review", "second-review-msg"),
        job_id="audit_1", analysis=analysis(),
    )
    confirmed = call(
        ext, "confirm_geometry", ctx("second-confirm", "second-confirm-msg"),
        job_id="audit_1", geometry_revision=saved["geometry_revision"], confirmed=True,
    )
    assert confirmed["ok"]
    catalog = call(ext, "save_price_catalog", job_id="audit_1", catalog_response=price_catalog_response())
    assert catalog["ok"]
    response = call(
        ext, "run_audit", job_id="audit_1",
        mapping=mapping(delegation_token=stale_token),
    )
    assert response["code"] == "mapping_delegation_invalid"


def test_unknown_room_id_rejected(mvp_api, tmp_path):
    ext, *_ = setup_geometry(mvp_api, tmp_path, confirm=True)
    value = mapping(); value["room_matches"][0]["model_room_id"] = "room_999"
    assert call(ext, "run_audit", job_id="audit_1", mapping=value)["code"] == "mapping_schema_invalid"


def test_unknown_canonical_work_rejected(mvp_api, tmp_path):
    ext, *_ = setup_geometry(mvp_api, tmp_path, confirm=True)
    value = mapping(); value["work_matches"][0]["canonical_work"] = "Неизвестно"
    assert call(ext, "run_audit", job_id="audit_1", mapping=value)["code"] == "mapping_schema_invalid"


def test_duplicate_mapping_rejected(mvp_api, tmp_path):
    ext, *_ = setup_geometry(mvp_api, tmp_path, confirm=True)
    value = mapping(); value["room_matches"].append(copy.deepcopy(value["room_matches"][0]))
    assert call(ext, "run_audit", job_id="audit_1", mapping=value)["code"] == "mapping_schema_invalid"


def test_unresolved_returns_review_without_report(mvp_api, tmp_path):
    ext, *_ = setup_geometry(mvp_api, tmp_path, confirm=True)
    value = mapping()
    item = value["room_matches"].pop()
    value["room_unresolved"] = [{"estimate_room": item["estimate_room"], "candidate_room_ids": ["room_002"], "reason": "Неоднозначно", "requires_human_confirmation": True}]
    response = call(ext, "run_audit", job_id="audit_1", mapping=value)
    assert response["status"] == "mapping_review_required"
    assert not (mvp_api.root / "state/jobs/audit_1/output/report.html").exists()


def test_incompatible_unit_rejected(mvp_api, tmp_path):
    rows = [[1, "Офис 1", "Устройство пола", "шт", 20, 1, 20, ""]]
    ext, *_ = setup_geometry(mvp_api, tmp_path, rows, confirm=True)
    value = mapping()
    value["room_matches"] = [value["room_matches"][0]]
    value["work_matches"] = [value["work_matches"][0]]
    value["price_matches"] = [value["price_matches"][0]]
    assert call(ext, "run_audit", job_id="audit_1", mapping=value)["code"] == "mapping_schema_invalid"


def test_unsupported_work_becomes_warning(mvp_api, tmp_path):
    rows = [[1, "Офис 1", "Демонтаж перегородок", "м²", 20, 1, 20, ""]]
    ext, *_ = setup_geometry(mvp_api, tmp_path, rows, confirm=True)
    value = mapping()
    value["room_matches"] = [value["room_matches"][0]]
    value["work_matches"] = []
    value["work_unsupported"] = [{"source_row": 2, "estimate_work": "Демонтаж перегородок", "reason": "MVP не поддерживает."}]
    value["price_matches"] = []
    value["price_unsupported"] = [{"source_row": 2, "estimate_work": "Демонтаж перегородок", "reason": "MCP не поддерживает."}]
    response = call(ext, "run_audit", job_id="audit_1", mapping=value)
    artifact = json.loads(
        (mvp_api.root / "state/jobs/audit_1/output/findings.json").read_text()
    )
    assert any(item["code"] == "unsupported_work" for item in artifact["warnings"])


def test_same_work_is_mapped_per_source_row(mvp_api, tmp_path):
    # Название совпадает, единицы — нет. Решение по первой строке нельзя молча
    # распространить на вторую только потому, что обе называются одинаково.
    rows = [
        [1, "Офис 1", "Установка дверей", "шт.", 1, 1000, 1000, ""],
        [2, "Офис 2", "Установка дверей", "м²", 1, 1000, 1000, ""],
    ]
    ext, *_ = setup_geometry(mvp_api, tmp_path, rows, confirm=True)
    value = mapping()
    value["work_matches"] = [
        {"source_row": 2, "estimate_work": "Установка дверей", "canonical_work": "Установка дверей", "confidence": 1, "reason": "Штучная единица."},
    ]
    value["work_unsupported"] = [
        {"source_row": 3, "estimate_work": "Установка дверей", "reason": "Единица м² несовместима со счётом дверей."},
    ]
    value["price_matches"] = [price_match(2, "Установка дверей")]
    value["price_unsupported"] = [
        {"source_row": 3, "estimate_work": "Установка дверей", "reason": "Единица м² несовместима с MCP."},
    ]

    response = call(ext, "run_audit", job_id="audit_1", mapping=value)

    assert response["status"] == "visual_review_required"
    assert response["summary"]["checked_rows"] == 1
    assert response["summary"]["not_checked_rows"] == 1
    artifact = json.loads(
        (mvp_api.root / "state/jobs/audit_1/output/findings.json").read_text()
    )
    assert [item["source_row"] for item in artifact["warnings"] if item["code"] == "unsupported_work"] == [3]
