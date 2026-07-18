"""Проверяем geometry от строгой схемы до review, который увидит пользователь."""

import copy
import json

from _mvp_fixtures import analysis, call, measurement, setup_imported, mvp_api


def _save_and_render(ext, payload=None):
    saved = call(ext, "save_geometry", job_id="audit_1", analysis=payload or analysis())
    rendered = call(
        ext,
        "render_geometry_review",
        job_id="audit_1",
        geometry_revision=saved["geometry_revision"],
    )
    return saved, rendered


def test_valid_payload_creates_full_review(mvp_api, tmp_path):
    ext, *_ = setup_imported(mvp_api, tmp_path)
    response, rendered = _save_and_render(ext)
    review = json.loads((mvp_api.root / "state/jobs/audit_1/output/geometry_review.json").read_text())
    assert response["status"] == "geometry_review_required"
    assert len(review["rooms"]) == 2
    assert review["rooms"][0]["doors"][0]["element_id"] == "door-shared"
    assert rendered["review_markdown"]


def test_review_markdown_is_complete_and_actionable(mvp_api, tmp_path):
    ext, *_ = setup_imported(mvp_api, tmp_path)
    saved, rendered = _save_and_render(ext)
    markdown = rendered["review_markdown"]
    instruction = saved["assistant_instruction"]
    review = json.loads((mvp_api.root / "state/jobs/audit_1/output/geometry_review.json").read_text())

    assert saved["next_action"] == "cross_subagent_handoff_barrier_then_render_geometry_review"
    assert "render_geometry_review" in instruction
    assert "не вызывай tools" in instruction.casefold()
    for room in review["rooms"]:
        for value in (
            room["name"], room["floor_area_m2"], room["length_m"],
            room["width_m"], room["perimeter_m"], room["height_m"],
            room["doors"][0]["element_id"], room["windows"][0]["element_id"],
        ):
            assert str(value) in markdown
        assert room["room_id"] not in markdown
    assert "| Помещение | Размеры, м (Д × Ш) | Площадь, м² | Периметр, м | Высота, м |" in markdown
    for section in ("Итоги", "Что нужно уточнить", "Конфликты", "Двери", "Окна"):
        assert section in markdown
    assert not markdown.endswith("?")
    assert "Подтверждаете указанную геометрию?" not in markdown
    assert markdown.splitlines()[-1] == "[ОЖИДАНИЕ НОВОГО СООБЩЕНИЯ ПОЛЬЗОВАТЕЛЯ]"
    assert "отправить отдельное новое входящее сообщение с подтверждением" in markdown
    assert not saved["confirmation_question"].endswith("?")
    assert "Да" not in saved["confirmation_question"]


def test_review_contract_does_not_change_structured_review(mvp_api, tmp_path):
    ext, *_ = setup_imported(mvp_api, tmp_path)
    response = call(ext, "save_geometry", job_id="audit_1", analysis=analysis())
    persisted = json.loads(
        (mvp_api.root / "state/jobs/audit_1/output/geometry_review.json").read_text(encoding="utf-8")
    )

    assert "review" not in response
    assert persisted["rooms"]


def test_render_geometry_review_replays_saved_markdown(mvp_api, tmp_path):
    ext, *_ = setup_imported(mvp_api, tmp_path)
    saved = call(ext, "save_geometry", job_id="audit_1", analysis=analysis())
    replayed = call(
        ext,
        "render_geometry_review",
        job_id="audit_1",
        geometry_revision=saved["geometry_revision"],
    )

    assert replayed["ok"]
    assert replayed["review_markdown"] == call(
        ext, "render_geometry_review", job_id="audit_1", geometry_revision=saved["geometry_revision"]
    )["review_markdown"]
    assert replayed["next_action"] == "display_review_markdown_verbatim"


def test_canonical_room_ids_are_stable(mvp_api, tmp_path):
    ext, *_ = setup_imported(mvp_api, tmp_path)
    call(ext, "save_geometry", job_id="audit_1", analysis=analysis())
    review = json.loads((mvp_api.root / "state/jobs/audit_1/output/geometry_review.json").read_text())
    assert [(r["room_id"], r["name"]) for r in review["rooms"]] == [("room_001", "Офис 1"), ("room_002", "Офис 2")]


def test_missing_confidence_is_rejected(mvp_api, tmp_path):
    ext, *_ = setup_imported(mvp_api, tmp_path)
    value = analysis(); del value["rooms"][0]["height_m"]["confidence"]
    response = call(ext, "save_geometry", job_id="audit_1", analysis=value)
    paths = {item["path"] for item in response["details"]["validation_errors"]}
    assert "rooms[0].height_m.confidence" in paths


def test_null_source_consistency_is_enforced(mvp_api, tmp_path):
    ext, *_ = setup_imported(mvp_api, tmp_path)
    value = analysis(); value["rooms"][0]["height_m"] = {"value": None, "confidence": .5, "source_type": "not_found", "evidence_text": ""}
    response = call(ext, "save_geometry", job_id="audit_1", analysis=value)
    assert response["code"] == "geometry_schema_invalid"


def test_forbidden_sources_are_aggregated(mvp_api, tmp_path):
    ext, *_ = setup_imported(mvp_api, tmp_path)
    value = analysis()
    value["rooms"][0]["height_m"]["source_type"] = "assumed_standard"
    value["rooms"][1]["height_m"]["source_type"] = "estimate_document"
    response = call(ext, "save_geometry", job_id="audit_1", analysis=value)
    assert len(response["details"]["validation_errors"]) >= 2


def test_invalid_payload_preserves_valid_geometry(mvp_api, tmp_path):
    ext, *_ = setup_imported(mvp_api, tmp_path)
    assert call(ext, "save_geometry", job_id="audit_1", analysis=analysis())["ok"]
    path = mvp_api.root / "state/jobs/audit_1/output/geometry.json"
    before = path.read_bytes()
    invalid = analysis(); invalid["rooms"][0]["height_m"]["source_type"] = "guessed"
    response = call(ext, "save_geometry", job_id="audit_1", analysis=invalid)
    assert not response["ok"] and path.read_bytes() == before


def test_second_invalid_attempt_stops_pipeline(mvp_api, tmp_path):
    ext, *_ = setup_imported(mvp_api, tmp_path)
    invalid = analysis(); invalid["rooms"][0]["height_m"]["source_type"] = "guessed"
    assert call(ext, "save_geometry", job_id="audit_1", analysis=invalid)["code"] == "geometry_schema_invalid"
    assert call(ext, "save_geometry", job_id="audit_1", analysis=invalid)["code"] == "geometry_analysis_failed"


def test_missing_geometry_is_kept_missing(mvp_api, tmp_path):
    ext, *_ = setup_imported(mvp_api, tmp_path)
    value = analysis(); value["rooms"][0]["height_m"] = measurement(None)
    call(ext, "save_geometry", job_id="audit_1", analysis=value)
    review = json.loads((mvp_api.root / "state/jobs/audit_1/output/geometry_review.json").read_text())
    assert any(item["field"] == "height_m" for item in review["missing_fields"])
    assert review["rooms"][1]["height_m"] == "—"


def test_review_requests_inputs_and_marks_derived_values_as_calculated(mvp_api, tmp_path):
    ext, *_ = setup_imported(mvp_api, tmp_path)
    value = analysis()
    for field in ("floor_area_m2", "length_m", "width_m", "perimeter_m"):
        value["rooms"][0][field] = measurement(None)

    _, rendered = _save_and_render(ext, value)
    markdown = rendered["review_markdown"]

    assert "| Офис 2 | **нужно уточнить** | рассчитается | рассчитается | 3,00 |" in markdown
    assert (
        "**Офис 2:** укажите длину и ширину; "
        "площадь пола и периметр рассчитаются автоматически."
    ) in markdown
    assert "floor_area_m2" not in markdown
    assert "perimeter_m" not in markdown


def test_review_adds_room_ids_only_for_duplicate_names(mvp_api, tmp_path):
    ext, *_ = setup_imported(mvp_api, tmp_path)
    value = analysis()
    for room in value["rooms"]:
        room["name"] = "Офис"

    _, rendered = _save_and_render(ext, value)
    markdown = rendered["review_markdown"]

    assert "Офис (`room_001`)" in markdown
    assert "Офис (`room_002`)" in markdown


def test_opening_dimension_conflict_is_reported(mvp_api, tmp_path):
    ext, *_ = setup_imported(mvp_api, tmp_path)
    value = analysis(); value["rooms"][0]["doors"][0]["width_m"] = measurement(1.1)
    call(ext, "save_geometry", job_id="audit_1", analysis=value)
    review = json.loads((mvp_api.root / "state/jobs/audit_1/output/geometry_review.json").read_text())
    assert any(item["type"] == "opening_dimension_conflict" for item in review["conflicts"])
