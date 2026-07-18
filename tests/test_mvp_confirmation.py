"""Подтверждение должно приходить новым сообщением и относиться к свежей ревизии."""

import json

from _mvp_fixtures import (
    ConstructionAuditMVP, call, ctx, price_catalog_response, setup_geometry,
    setup_imported, mvp_api,
)
from construction_audit_mvp import core


def test_cannot_confirm_without_geometry(mvp_api):
    ext = ConstructionAuditMVP(mvp_api)
    call(ext, "create_case", job_id="audit_1", object_name="Офис")
    response = call(ext, "confirm_geometry", ctx("new", "new-msg"), job_id="audit_1", geometry_revision=1, confirmed=True)
    assert response["code"] == "geometry_required"


def test_confirmed_false_is_rejected(mvp_api, tmp_path):
    ext, *_, saved = setup_geometry(mvp_api, tmp_path)
    response = call(ext, "confirm_geometry", ctx("new", "new-msg"), job_id="audit_1", geometry_revision=1, confirmed=False)
    assert response["code"] == "explicit_confirmation_required"


def test_same_task_id_is_rejected(mvp_api, tmp_path):
    ext, *_, saved = setup_geometry(mvp_api, tmp_path)
    response = call(ext, "confirm_geometry", ctx("task-review", "new-msg"), job_id="audit_1", geometry_revision=1, confirmed=True)
    assert response["code"] == "confirmation_requires_new_turn"


def test_same_client_message_id_is_rejected(mvp_api, tmp_path):
    ext, *_, saved = setup_geometry(mvp_api, tmp_path)
    response = call(ext, "confirm_geometry", ctx("new-task", "msg-review"), job_id="audit_1", geometry_revision=1, confirmed=True)
    assert response["code"] == "confirmation_requires_new_turn"


def test_new_turn_is_accepted_and_hash_saved(mvp_api, tmp_path):
    ext, *_, saved = setup_geometry(mvp_api, tmp_path)
    response = call(ext, "confirm_geometry", ctx("new-task", "new-msg"), job_id="audit_1", geometry_revision=1, confirmed=True)
    assert response["ok"]
    manifest = json.loads((mvp_api.root / "state/jobs/audit_1/manifest.json").read_text())
    assert len(manifest["confirmed_geometry_sha256"]) == 64
    assert manifest["geometry_confirmed_revision"] == 1
    assert manifest["geometry_confirmed_at"]
    assert manifest["confirmation_task_id"] == "new-task"
    assert "mapping_generation_token" not in manifest
    assert response["mcp_tool"] == "mcp_construction_prices__get_supported_works"
    catalog = call(ext, "save_price_catalog", job_id="audit_1", catalog_response=price_catalog_response())
    manifest = json.loads((mvp_api.root / "state/jobs/audit_1/manifest.json").read_text())
    assert manifest["mapping_generation_token"]
    assert catalog["mapping_mode"] == "deterministic_exact_match"
    assert catalog["mapping"]["delegation_token"] == manifest["mapping_generation_token"]


def test_deterministic_mapping_exists_only_after_catalog_validation(mvp_api, tmp_path):
    ext, *_, saved = setup_geometry(mvp_api, tmp_path)
    assert "mapping_delegation" not in saved
    response = call(
        ext, "confirm_geometry", ctx("new-task", "new-msg"),
        job_id="audit_1", geometry_revision=1, confirmed=True,
    )
    assert "mapping_delegation" not in response
    catalog = call(ext, "save_price_catalog", job_id="audit_1", catalog_response=price_catalog_response())
    assert catalog["mapping"]
    assert catalog["next_action"] == "run_audit"
    assert "mapping_delegation" not in catalog


def test_stale_revision_is_rejected(mvp_api, tmp_path):
    ext, *_, saved = setup_geometry(mvp_api, tmp_path)
    response = call(ext, "confirm_geometry", ctx("new", "new"), job_id="audit_1", geometry_revision=999, confirmed=True)
    assert response["code"] == "stale_geometry_revision"


def test_repeat_confirmation_is_idempotent(mvp_api, tmp_path):
    ext, *_, saved = setup_geometry(mvp_api, tmp_path)
    first = call(ext, "confirm_geometry", ctx("new", "new"), job_id="audit_1", geometry_revision=1, confirmed=True)
    second = call(ext, "confirm_geometry", ctx("new", "new"), job_id="audit_1", geometry_revision=1, confirmed=True)
    assert first["changed"] is True and second["changed"] is False


def test_geometry_correction_removes_matching_global_warning():
    geometry = {
        "rooms": [{
            "room_id": "room_001",
            "warnings": ["Высота не указана для помещения.", "Проверить окно."],
        }],
        "warnings": [
            "Ceiling height (height_m) not labeled anywhere on the plan.",
            "Shared doors are duplicated for adjacent rooms.",
        ],
    }

    core._remove_stale_geometry_warnings(geometry, [{
        "applied_targets": ["room_001.height_m"],
    }])

    assert geometry["rooms"][0]["warnings"] == ["Проверить окно."]
    assert geometry["warnings"] == ["Shared doors are duplicated for adjacent rooms."]
