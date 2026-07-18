"""Следы делегаций и SHA нужны, чтобы результат можно было воспроизвести и проверить."""

import json
from pathlib import Path

from construction_audit_mvp import core
from _mvp_fixtures import (
    analysis,
    call,
    ctx,
    descriptor,
    make_plan,
    mapping,
    price_catalog_response,
    setup_geometry,
    setup_imported,
    mvp_api,
)


def _manifest(api, job_id="audit_1"):
    return json.loads((api.root / f"state/jobs/{job_id}/manifest.json").read_text())


def test_canonical_json_fingerprint_is_order_independent():
    assert core.canonical_json_sha256({"b": 2, "a": 1}) == core.canonical_json_sha256({"a": 1, "b": 2})
    assert core.canonical_json_sha256({"a": "1"}) != core.canonical_json_sha256({"a": 1})
    assert core.canonical_json_sha256({"a": 1}) != core.canonical_json_sha256({"a": 1.0})


def test_geometry_object_saves_trace_and_version_fingerprint(mvp_api, tmp_path):
    ext, *_ = setup_imported(mvp_api, tmp_path)
    response = call(
        ext,
        "save_geometry",
        ctx("vision-parent", "vision-message"),
        job_id="audit_1",
        vision_task_id="vision-child",
        analysis=analysis(),
    )
    manifest = _manifest(mvp_api)
    geometry = json.loads((mvp_api.root / "state/jobs/audit_1/output/geometry.json").read_text())

    assert response["status"] == "geometry_review_required"
    assert manifest["vision_task_id"] == "vision-child"
    assert manifest["geometry_sha256"] == core.geometry_sha256(geometry)
    assert manifest["geometry_schema_version"] == 1
    assert manifest["geometry_validation_status"] == "validated"
    assert len(manifest["geometry_sha256"]) == 64


def test_geometry_fingerprint_is_stable_for_same_payload(mvp_api, tmp_path):
    payload = analysis()
    ext, *_ = setup_imported(mvp_api, tmp_path, job_id="audit_1")
    assert call(ext, "save_geometry", job_id="audit_1", vision_task_id="vision-a", analysis=payload)["ok"]
    first = _manifest(mvp_api, "audit_1")["geometry_sha256"]

    ext, *_ = setup_imported(mvp_api, tmp_path, job_id="audit_2")
    assert call(ext, "save_geometry", job_id="audit_2", vision_task_id="vision-b", analysis=payload)["ok"]
    assert _manifest(mvp_api, "audit_2")["geometry_sha256"] == first


def test_vision_task_id_is_trace_only_for_retry(mvp_api, tmp_path):
    ext, *_ = setup_imported(mvp_api, tmp_path)
    invalid = analysis()
    invalid["rooms"][0]["height_m"]["source_type"] = "guessed"

    first = call(ext, "save_geometry", job_id="audit_1", vision_task_id="vision-child", analysis=invalid)
    second = call(ext, "save_geometry", job_id="audit_1", vision_task_id="vision-child", analysis=analysis())

    assert first["code"] == "geometry_schema_invalid"
    assert first["details"]["vision_attempt"] == 1
    assert first["details"]["allowed_next_action"] == "retry_vision"
    assert second["ok"]
    assert _manifest(mvp_api)["vision_task_id"] == "vision-child"


def test_second_geometry_schema_error_stops_pipeline(mvp_api, tmp_path):
    ext, *_ = setup_imported(mvp_api, tmp_path)
    invalid = analysis()
    invalid["rooms"][0]["height_m"]["source_type"] = "guessed"

    first = call(ext, "save_geometry", job_id="audit_1", analysis=invalid)
    second = call(ext, "save_geometry", job_id="audit_1", analysis=invalid)

    assert first["code"] == "geometry_schema_invalid"
    assert second["code"] == "geometry_analysis_failed"
    assert second["details"]["vision_attempt"] == 2
    assert second["details"]["allowed_next_action"] == "stop"


def test_new_plan_import_clears_geometry_fingerprint(mvp_api, tmp_path):
    ext, estimate, *_ = setup_imported(mvp_api, tmp_path)
    assert call(ext, "save_geometry", job_id="audit_1", analysis=analysis())["ok"]
    new_plan = make_plan(tmp_path, name="plan-new.png", payload=b"\x89PNG\r\n\x1a\nchanged-plan")

    response = call(
        ext,
        "import_documents",
        job_id="audit_1",
        estimate=descriptor(estimate),
        plan=descriptor(new_plan),
    )

    manifest = _manifest(mvp_api)
    assert response["ok"]
    assert manifest["vision_attempts"] == 0
    for field in ("vision_task_id", "geometry_sha256", "geometry_validation_status"):
        assert field not in manifest


def test_valid_mapping_saves_trace_and_version_fingerprint(mvp_api, tmp_path):
    ext, *_ = setup_geometry(mvp_api, tmp_path, confirm=True)
    response = call(ext, "run_audit", job_id="audit_1", mapping_task_id="mapping-child", mapping=mapping())
    manifest = _manifest(mvp_api)
    mapping_artifact = json.loads((mvp_api.root / "state/jobs/audit_1/output/mapping.json").read_text())

    assert response["status"] == "visual_review_required"
    assert manifest["mapping_task_id"] == "mapping-child"
    assert manifest["mapping_sha256"] == core.canonical_json_sha256(mapping_artifact)
    assert manifest["mapping_schema_version"] == 3
    assert manifest["mapping_validation_status"] == "validated"
    assert manifest["audit_status"] == "visual_review_required"
    assert "llm_context_sha256" not in manifest


def test_invalid_mapping_is_schema_rejected_without_audit_artifacts(mvp_api, tmp_path):
    ext, *_ = setup_geometry(mvp_api, tmp_path, confirm=True)
    payload = mapping()
    payload["room_matches"][0]["model_room_id"] = "room_999"

    response = call(ext, "run_audit", job_id="audit_1", mapping=payload)

    assert response["code"] == "mapping_schema_invalid"
    assert response["details"]["validation_errors"]
    assert response["details"]["allowed_next_action"] == "rerun_mapping_subagent"
    assert "mapping_sha256" not in _manifest(mvp_api)
    assert not (mvp_api.root / "state/jobs/audit_1/output/report.html").exists()
    assert not (mvp_api.root / "state/jobs/audit_1/output/quantities.json").exists()


def test_unresolved_mapping_saves_fingerprint_and_review_status(mvp_api, tmp_path):
    ext, *_ = setup_geometry(mvp_api, tmp_path, confirm=True)
    payload = mapping()
    item = payload["room_matches"].pop()
    payload["room_unresolved"] = [{
        "estimate_room": item["estimate_room"],
        "candidate_room_ids": ["room_002"],
        "reason": "Неоднозначно",
        "requires_human_confirmation": True,
    }]

    response = call(ext, "run_audit", job_id="audit_1", mapping_task_id="mapping-review", mapping=payload)
    manifest = _manifest(mvp_api)

    assert response["status"] == "mapping_review_required"
    assert manifest["mapping_task_id"] == "mapping-review"
    assert len(manifest["mapping_sha256"]) == 64
    assert manifest["audit_status"] == "mapping_review_required"
    assert not (mvp_api.root / "state/jobs/audit_1/output/report.html").exists()


def test_vision_delegation_context_is_minimal(mvp_api, tmp_path):
    _, _, _, imported = setup_imported(mvp_api, tmp_path)
    packet = imported["vision_delegation"]
    context = json.loads(packet["context"])
    assert set(packet) == {
        "role", "model_lane", "memory_mode", "write_surface", "context",
        "objective", "expected_output", "constraints",
    }
    assert packet["role"] == "construction-plan-vision"
    assert packet["model_lane"] == "main"
    assert packet["memory_mode"] == "empty"
    assert packet["write_surface"] == "read_only"
    assert set(context) == {"plan_id", "image_ref"}
    assert context["plan_id"] == imported["plan"]["plan_id"]
    assert "file_path" not in context
    assert "geometry" not in json.dumps(context, ensure_ascii=False).casefold()
    assert "element_id" in packet["expected_output"]
    assert "image_quality" in packet["expected_output"]
    assert "FINAL ANSWER: [BEGIN_SUBTASK_OUTPUT]" in packet["expected_output"]
    assert "explicit_area_label" in packet["constraints"]
    assert "not_found" in packet["constraints"]


def test_vision_delegation_uses_absolute_upload_projection_path(mvp_api, tmp_path):
    _, _, plan, imported = setup_imported(mvp_api, tmp_path)
    packet = imported["vision_delegation"]
    context = json.loads(packet["context"])
    image_ref = context["image_ref"]
    projection = Path(image_ref)

    assert "attachments" not in packet
    assert image_ref == imported["plan"]["source_path"]
    assert projection.is_absolute()
    assert projection.is_file()
    assert projection.parent == (mvp_api.root / "data/uploads/construction_audit_mvp").resolve()
    assert not image_ref.startswith("uploads/")
    assert image_ref in packet["objective"]
    assert image_ref in packet["constraints"]
    assert str(plan) not in packet["objective"]
    serialized = json.dumps(context, ensure_ascii=False)
    for forbidden in ("artifact_store", "attachments", "task_results/artifacts", "file://"):
        assert forbidden not in serialized
    for forbidden_field in (
        "attachment_path", "attachment_root", "attachment_relpath", "full_path",
    ):
        assert forbidden_field not in context
    assert "view_image(path=context.image_ref)" in packet["constraints"]
    assert "list_files" in packet["constraints"]
    assert "search_code" in packet["constraints"]


def test_mapping_delegation_has_catalog_and_compact_estimate_context(mvp_api, tmp_path):
    ext, *_rest, saved = setup_geometry(mvp_api, tmp_path)
    response = call(
        ext,
        "confirm_geometry",
        ctx("confirm-parent", "confirm-message"),
        job_id="audit_1",
        geometry_revision=saved["geometry_revision"],
        confirmed=True,
    )
    assert response["next_action"] == "call_mcp_construction_prices__get_supported_works"
    catalog_response = price_catalog_response()
    catalog_response["result"][1]["name"] = "Нанесение краски на стены"
    catalog = call(ext, "save_price_catalog", job_id="audit_1", catalog_response=catalog_response)
    packet = catalog["mapping_delegation"]
    context = json.loads(packet["context"])
    assert packet["role"] == "construction-estimate-mapper"
    assert packet["write_surface"] == "read_only"
    assert set(context) == {
        "delegation_token", "canonical_rooms", "estimate_rooms", "estimate_works",
        "supported_works", "mcp_price_catalog",
    }
    assert context["delegation_token"]
    assert "delegation_token" in packet["expected_output"]
    assert "FINAL ANSWER: [BEGIN_SUBTASK_OUTPUT]" in packet["expected_output"]
    assert "дословно и без изменений" in packet["constraints"]
    assert context["canonical_rooms"] and context["estimate_rooms"]
    assert context["estimate_works"] and context["supported_works"] and context["mcp_price_catalog"]
    serialized = json.dumps(context, ensure_ascii=False).casefold()
    assert all(set(item) == {"source_row", "name", "unit"} for item in context["estimate_works"])
    assert all(set(item) == {"id", "name", "unit", "price"} for item in context["mcp_price_catalog"])
    assert "не возвращать, не изменять и не вычислять price" in packet["constraints"].casefold()
    for forbidden in (".xlsx", "quantity", "raw", "finding"):
        assert forbidden not in serialized


def test_mapping_delegation_keeps_same_work_rows_separate(mvp_api, tmp_path):
    rows = [
        [1, "Офис 1", "Установка дверей", "шт.", 1, 1000, 1000, ""],
        [2, "Офис 2", "Установка дверей", "м²", 1, 1000, 1000, ""],
    ]
    ext, *_rest, saved = setup_geometry(mvp_api, tmp_path, rows)
    response = call(
        ext,
        "confirm_geometry",
        ctx("confirm-parent", "confirm-message"),
        job_id="audit_1",
        geometry_revision=saved["geometry_revision"],
        confirmed=True,
    )
    response = call(ext, "save_price_catalog", job_id="audit_1", catalog_response=price_catalog_response())

    assert json.loads(response["mapping_delegation"]["context"])["estimate_works"] == [
        {"source_row": 2, "name": "Установка дверей", "unit": "шт."},
        {"source_row": 3, "name": "Установка дверей", "unit": "м²"},
    ]


def test_mapping_delegation_declares_exact_nested_output_contract(mvp_api, tmp_path):
    ext, *_rest, saved = setup_geometry(mvp_api, tmp_path)
    response = call(
        ext,
        "confirm_geometry",
        ctx("confirm-parent", "confirm-message"),
        job_id="audit_1",
        geometry_revision=saved["geometry_revision"],
        confirmed=True,
    )
    catalog_response = price_catalog_response()
    catalog_response["result"][1]["name"] = "Нанесение краски на стены"
    response = call(ext, "save_price_catalog", job_id="audit_1", catalog_response=catalog_response)
    packet = response["mapping_delegation"]
    expected_output = packet["expected_output"]

    example_text = expected_output.split("FINAL ANSWER: [BEGIN_SUBTASK_OUTPUT]", 1)[1].split(
        "[END_SUBTASK_OUTPUT]", 1
    )[0]
    example = json.loads(example_text)
    assert set(example) == {
        "schema_version", "delegation_token", "room_matches", "room_unresolved",
        "work_matches", "work_unsupported", "work_unresolved", "price_matches",
        "price_unsupported", "price_unresolved",
    }
    assert set(example["room_matches"][0]) == {
        "estimate_room", "model_room_id", "confidence", "reason",
    }
    assert set(example["work_matches"][0]) == {
        "source_row", "estimate_work", "canonical_work", "confidence", "reason",
    }
    assert set(example["price_matches"][0]) == {
        "source_row", "estimate_work", "mcp_work_id", "confidence", "reason",
    }
    assert example["schema_version"] == 3
    assert example["delegation_token"] == json.loads(packet["context"])["delegation_token"]
    for field in (
        "candidate_room_ids", "requires_human_confirmation", "candidate_canonical_works",
        "candidate_mcp_work_ids",
    ):
        assert field in expected_output

    constraints = packet["constraints"]
    assert "canonical_rooms[].room_id" in constraints
    assert "supported_works[].name" in constraints
    assert "mcp_price_catalog[].id" in constraints
    for forbidden_alias in (
        "canonical_room_id", "supported_metric", "supported_name", "estimate_units",
        "matched_unit", "matched_units",
    ):
        assert forbidden_alias in constraints
