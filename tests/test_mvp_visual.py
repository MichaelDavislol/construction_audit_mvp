"""Фото необязательны, но если они есть — каждое проходит свою Vision-проверку."""

import json
import zipfile
from pathlib import Path

import pytest

from _mvp_fixtures import (
    call, ctx, descriptor, finalize, mapping, setup_geometry, mvp_api,
)
from construction_audit_mvp import core, plugin, visual


PNG = b"\x89PNG\r\n\x1a\n" + b"site-photo"


def _photo_zip(tmp_path: Path, count: int = 2) -> Path:
    path = tmp_path / "task" / "artifacts" / "task-1" / "attachments" / "photos.zip"
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        for index in range(1, count + 1):
            archive.writestr(f"room_{index}.png", PNG + bytes([index]))
    return path


def _analysis(photo_id, token, *, quality=False):
    if quality:
        insight = {
            "visual_insight_id": f"{photo_id}_insight_001",
            "category": "quality",
            "estimate_work": None,
            "source_rows": [],
            "status": "quality_concern",
            "title": "Видимый зазор у дверного блока",
            "observation": "На фотографии заметен неравномерный зазор.",
            "evidence_text": "Зазор виден вдоль правой стороны дверного полотна.",
            "confidence": "medium",
            "auditor_check": "Проверить дверной блок на объекте.",
            "limitations": "Перспектива фотографии может искажать геометрию.",
        }
    else:
        insight = {
            "visual_insight_id": f"{photo_id}_insight_001",
            "category": "estimate_comparison",
            "estimate_work": "Окраска стен",
            "source_rows": [3],
            "status": "not_observed",
            "title": "Окраска стен не наблюдается",
            "observation": "На видимом участке стены окрашенная поверхность не наблюдается.",
            "evidence_text": "В кадре видна необработанная поверхность стены.",
            "confidence": "high",
            "auditor_check": "Сопоставить фото с зоной работ и сметой.",
            "limitations": "Фото показывает только часть помещения.",
        }
    return {
        "schema_version": 1,
        "photo_id": photo_id,
        "delegation_token": token,
        "image_quality": {"usable": True, "issues": []},
        "scene_summary": "Видна часть помещения.",
        "visual_insights": [insight],
        "limitations": ["Вывод относится только к фотографии."],
    }


def test_zip_photos_are_delegated_per_file_and_rendered(mvp_api, tmp_path):
    ext, *_ = setup_geometry(mvp_api, tmp_path, confirm=True)
    prepared = call(ext, "run_audit", job_id="audit_1", mapping=mapping())
    assert prepared["status"] == "visual_review_required"

    imported = call(
        ext, "import_site_photos", job_id="audit_1", archive=descriptor(_photo_zip(tmp_path))
    )
    assert imported["status"] == "visual_analysis_required"
    assert imported["photos_count"] == 2
    assert len(imported["visual_delegations"]) == 2
    assert all(item["packet"]["role"] == "construction-site-photo-vision" for item in imported["visual_delegations"])

    by_photo = {item["photo_id"]: item["packet"] for item in imported["visual_delegations"]}
    first_context = json.loads(by_photo["photo_001"]["context"])
    second_context = json.loads(by_photo["photo_002"]["context"])
    assert first_context["image_ref"].endswith(".png")
    assert "Окраска стен" in {item["canonical_work"] for item in first_context["estimate_works"]}
    assert all("rooms" not in item for item in first_context["estimate_works"])
    assert next(
        item for item in first_context["estimate_works"]
        if item["canonical_work"] == "Окраска стен"
    )["source_rows"] == [3]

    first = call(
        ext, "save_visual_analysis", ctx("parent", "msg"), job_id="audit_1",
        photo_id="photo_001", photo_task_id="a1b2c3d4",
        analysis=_analysis("photo_001", first_context["delegation_token"]),
    )
    assert first["remaining_count"] == 1
    second = call(
        ext, "save_visual_analysis", ctx("parent", "msg"), job_id="audit_1",
        photo_id="photo_002", photo_task_id="b1c2d3e4",
        analysis=_analysis("photo_002", second_context["delegation_token"], quality=True),
    )
    assert second["status"] == "llm_insights_required"
    assert second["visual_summary"] == {
        "status": "generated", "photos_count": 2, "insights_count": 2,
    }

    artifact = json.loads(
        (mvp_api.root / "state/jobs/audit_1/output/visual_insights.json").read_text()
    )
    assert [item["status"] for item in artifact["items"]] == ["not_observed", "quality_concern"]
    result = finalize(ext, llm_insights={
        "schema_version": 1,
        "status": "generated",
        "summary": "Фото-наблюдение требует проверки аудитором.",
        "items": [{
            "insight_id": "insight_001",
            "category": "visual_observation",
            "title": "Сопоставление фото со сметой",
            "observation": "Окраска стен визуально не наблюдается.",
            "hypothesis": "Фотография может относиться к более раннему этапу работ.",
            "evidence_refs": [{
                "type": "visual_insight", "value": "photo_001_insight_001",
            }],
            "confidence": "medium",
            "recommended_check": "Проверить этап и место съёмки.",
            "limitations": "Основание ограничено одной фотографией.",
        }],
    })
    html = Path(result["report_artifact"]["path"]).read_text(encoding="utf-8")
    assert "Наблюдения по фотографиям объекта" in html
    assert "не привязаны к помещениям" in html
    assert "Окраска стен не наблюдается" in html
    assert "Видимый зазор у дверного блока" in html
    assert "## Наблюдения по фотографиям" in result["audit_summary_markdown"]
    assert "Окраска стен (строки 3)" in result["audit_summary_markdown"]


def test_archive_with_more_than_five_photos_is_rejected(mvp_api, tmp_path):
    ext, *_ = setup_geometry(mvp_api, tmp_path, confirm=True)
    call(ext, "run_audit", job_id="audit_1", mapping=mapping())
    result = call(
        ext, "import_site_photos", job_id="audit_1",
        archive=descriptor(_photo_zip(tmp_path, count=6)),
    )
    assert result["code"] == "invalid_photo_archive"
    assert result["details"]["photos_found"] == 6


def test_visual_analysis_rejects_foreign_token(mvp_api, tmp_path):
    ext, *_ = setup_geometry(mvp_api, tmp_path, confirm=True)
    call(ext, "run_audit", job_id="audit_1", mapping=mapping())
    imported = call(
        ext, "import_site_photos", job_id="audit_1",
        archive=descriptor(_photo_zip(tmp_path, count=1)),
    )
    result = call(
        ext, "save_visual_analysis", job_id="audit_1", photo_id="photo_001",
        photo_task_id="a1b2c3d4", analysis=_analysis("photo_001", "x" * 43),
    )
    assert result["code"] == "visual_analysis_schema_invalid"
    assert result["details"]["photo_id"] == "photo_001"
    assert result["details"]["visual_delegation"]["role"] == "construction-site-photo-vision"


def test_five_photo_packets_fit_transport_budget_and_have_no_rooms(mvp_api, tmp_path):
    ext, *_ = setup_geometry(mvp_api, tmp_path, confirm=True)
    call(ext, "run_audit", job_id="audit_1", mapping=mapping())
    imported = call(
        ext, "import_site_photos", job_id="audit_1",
        archive=descriptor(_photo_zip(tmp_path, count=5)),
    )

    payload = json.dumps(imported, ensure_ascii=False, separators=(",", ":"))
    assert len(payload) <= 14_500
    assert len(imported["visual_delegations"]) == 5
    for item in imported["visual_delegations"]:
        context = json.loads(item["packet"]["context"])
        assert all(set(work) == {"canonical_work", "source_rows"} for work in context["estimate_works"])


def test_observed_present_alias_is_normalized_inside_skill(mvp_api, tmp_path):
    ext, *_ = setup_geometry(mvp_api, tmp_path, confirm=True)
    call(ext, "run_audit", job_id="audit_1", mapping=mapping())
    imported = call(
        ext, "import_site_photos", job_id="audit_1",
        archive=descriptor(_photo_zip(tmp_path, count=1)),
    )
    context = json.loads(imported["visual_delegations"][0]["packet"]["context"])
    value = _analysis("photo_001", context["delegation_token"])
    value["visual_insights"][0]["status"] = "observed_present"

    response = call(
        ext, "save_visual_analysis", job_id="audit_1", photo_id="photo_001",
        photo_task_id="a1b2c3d4", analysis=value,
    )
    assert response["status"] == "llm_insights_required"
    artifact = json.loads(
        (mvp_api.root / "state/jobs/audit_1/output/visual_insights.json").read_text()
    )
    assert artifact["items"][0]["status"] == "observed"


def test_visual_analysis_accepts_one_exact_json_serialization(mvp_api, tmp_path):
    ext, *_ = setup_geometry(mvp_api, tmp_path, confirm=True)
    call(ext, "run_audit", job_id="audit_1", mapping=mapping())
    imported = call(
        ext, "import_site_photos", job_id="audit_1",
        archive=descriptor(_photo_zip(tmp_path, count=1)),
    )
    context = json.loads(imported["visual_delegations"][0]["packet"]["context"])
    value = _analysis("photo_001", context["delegation_token"])

    response = call(
        ext, "save_visual_analysis", job_id="audit_1", photo_id="photo_001",
        photo_task_id="a1b2c3d4",
        analysis=json.dumps(value, ensure_ascii=False, separators=(",", ":")),
    )

    assert response["status"] == "llm_insights_required"
    artifact = json.loads(
        (mvp_api.root / "state/jobs/audit_1/output/visual_photo_analyses.json").read_text()
    )
    assert artifact["items"][0]["photo_task_id"] == "a1b2c3d4"


def test_visual_transport_error_does_not_reject_task_id(mvp_api, tmp_path):
    ext, *_ = setup_geometry(mvp_api, tmp_path, confirm=True)
    call(ext, "run_audit", job_id="audit_1", mapping=mapping())
    imported = call(
        ext, "import_site_photos", job_id="audit_1",
        archive=descriptor(_photo_zip(tmp_path, count=1)),
    )
    context = json.loads(imported["visual_delegations"][0]["packet"]["context"])

    invalid_transport = call(
        ext, "save_visual_analysis", job_id="audit_1", photo_id="photo_001",
        photo_task_id="a1b2c3d4", analysis="{not-json",
    )
    assert invalid_transport["code"] == "visual_analysis_transport_invalid"
    assert invalid_transport["next_action"] == "reextract_same_subagent_result"
    assert "Не запускай нового субагента" in invalid_transport["assistant_instruction"]
    manifest = json.loads(
        (mvp_api.root / "state/jobs/audit_1/manifest.json").read_text()
    )
    assert manifest["visual_rejected_task_ids"] == {}

    accepted = call(
        ext, "save_visual_analysis", job_id="audit_1", photo_id="photo_001",
        photo_task_id="a1b2c3d4",
        analysis=json.dumps(
            _analysis("photo_001", context["delegation_token"]),
            ensure_ascii=False,
        ),
    )
    assert accepted["status"] == "llm_insights_required"


def test_semantically_invalid_visual_json_string_still_rejects_task_id(mvp_api, tmp_path):
    ext, *_ = setup_geometry(mvp_api, tmp_path, confirm=True)
    call(ext, "run_audit", job_id="audit_1", mapping=mapping())
    imported = call(
        ext, "import_site_photos", job_id="audit_1",
        archive=descriptor(_photo_zip(tmp_path, count=1)),
    )
    context = json.loads(imported["visual_delegations"][0]["packet"]["context"])
    invalid = _analysis("photo_001", context["delegation_token"])
    invalid["visual_insights"][0]["title"] = "Окраска стен не выполнена"

    first = call(
        ext, "save_visual_analysis", job_id="audit_1", photo_id="photo_001",
        photo_task_id="a1b2c3d4", analysis=json.dumps(invalid, ensure_ascii=False),
    )
    assert first["code"] == "visual_analysis_schema_invalid"

    repeated = call(
        ext, "save_visual_analysis", job_id="audit_1", photo_id="photo_001",
        photo_task_id="a1b2c3d4",
        analysis=json.dumps(
            _analysis("photo_001", context["delegation_token"]),
            ensure_ascii=False,
        ),
    )
    assert repeated["code"] == "visual_subagent_retry_required"


def test_quality_concern_category_alias_and_missing_rows_are_normalized(mvp_api, tmp_path):
    ext, *_ = setup_geometry(mvp_api, tmp_path, confirm=True)
    analysis_schema = plugin._visual_analysis_schema()
    item_schema = analysis_schema["properties"]["visual_insights"]["items"]
    assert "quality_concern" in item_schema["properties"]["category"]["enum"]
    assert "source_rows" not in item_schema["required"]
    call(ext, "run_audit", job_id="audit_1", mapping=mapping())
    imported = call(
        ext, "import_site_photos", job_id="audit_1",
        archive=descriptor(_photo_zip(tmp_path, count=1)),
    )
    context = json.loads(imported["visual_delegations"][0]["packet"]["context"])
    value = _analysis("photo_001", context["delegation_token"], quality=True)
    value["visual_insights"][0]["category"] = "quality_concern"
    del value["visual_insights"][0]["source_rows"]

    response = call(
        ext, "save_visual_analysis", job_id="audit_1", photo_id="photo_001",
        photo_task_id="a1b2c3d4", analysis=value,
    )

    assert response["status"] == "llm_insights_required"
    artifact = json.loads(
        (mvp_api.root / "state/jobs/audit_1/output/visual_insights.json").read_text()
    )
    assert artifact["items"][0]["category"] == "quality"
    assert artifact["items"][0]["source_rows"] == []


def test_visual_validation_reports_missing_and_unexpected_fields():
    photo = {
        "photo_id": "photo_001",
        "vision_source_path": "/tmp/photo.png",
        "delegation_token": "x" * 43,
    }
    estimate_works = [{"canonical_work": "Окраска стен", "source_rows": [3]}]
    value = _analysis("photo_001", "x" * 43)
    del value["visual_insights"][0]["source_rows"]
    value["visual_insights"][0]["room"] = "Кабинет"

    with pytest.raises(visual.VisualValidationError) as raised:
        visual.validate(value, photo=photo, estimate_works=estimate_works)

    assert {error["reason"] for error in raised.value.errors} == {
        "missing fields: source_rows", "unexpected fields: room",
    }


def test_rejected_visual_task_id_requires_a_new_subagent(mvp_api, tmp_path):
    ext, *_ = setup_geometry(mvp_api, tmp_path, confirm=True)
    call(ext, "run_audit", job_id="audit_1", mapping=mapping())
    imported = call(
        ext, "import_site_photos", job_id="audit_1",
        archive=descriptor(_photo_zip(tmp_path, count=1)),
    )
    context = json.loads(imported["visual_delegations"][0]["packet"]["context"])
    invalid = _analysis("photo_001", context["delegation_token"])
    invalid["visual_insights"][0]["title"] = "Окраска стен не выполнена"

    first = call(
        ext, "save_visual_analysis", job_id="audit_1", photo_id="photo_001",
        photo_task_id="a1b2c3d4", analysis=invalid,
    )
    assert first["code"] == "visual_analysis_schema_invalid"
    assert first["next_action"] == "rerun_visual_subagent"
    assert "Не изменяй и не отправляй analysis повторно" in first["assistant_instruction"]

    repaired_by_parent = _analysis("photo_001", context["delegation_token"])
    repeated = call(
        ext, "save_visual_analysis", job_id="audit_1", photo_id="photo_001",
        photo_task_id="a1b2c3d4", analysis=repaired_by_parent,
    )
    assert repeated["code"] == "visual_subagent_retry_required"
    assert repeated["details"]["allowed_next_action"] == "rerun_visual_subagent"
    assert repeated["next_action"] == "rerun_visual_subagent"

    retried = call(
        ext, "save_visual_analysis", job_id="audit_1", photo_id="photo_001",
        photo_task_id="b1c2d3e4", analysis=repaired_by_parent,
    )
    assert retried["status"] == "llm_insights_required"


def test_llm_visual_sample_covers_each_photo_before_filling_extra_slots():
    # Если лимит контекста тесный, сначала даём аналитику хотя бы один факт с
    # каждого фото. Иначе первые снимки случайно вытеснят последние.
    items = []
    for photo_index in range(1, 6):
        photo_id = f"photo_{photo_index:03d}"
        for insight_index in range(1, 3):
            items.append({
                "visual_insight_id": f"{photo_id}_insight_{insight_index:03d}",
                "photo_id": photo_id,
                "category": "estimate_comparison",
                "estimate_work": "Окраска стен",
                "source_rows": [3],
                "status": "observed",
                "title": "Окраска видна",
                "observation": "Окраска видна в кадре.",
                "confidence": "medium",
                "auditor_check": "Проверить фото.",
                "limitations": "Только видимая часть кадра.",
            })
    compact = visual.compact_for_llm({
        "status": "generated", "photos_count": 5, "items": items,
    })

    assert compact["items_included"] == visual.MAX_LLM_CONTEXT_ITEMS
    assert set(compact["photo_ids_included"]) == {
        "photo_001", "photo_002", "photo_003", "photo_004", "photo_005",
    }


def test_all_supported_photo_works_keep_their_estimate_rows_without_rooms():
    estimate_rows = [
        {"source_row": row, "work_name": work}
        for row, work in enumerate(core.SUPPORTED_WORKS, start=10)
    ]
    work_matches = [
        {"source_row": row["source_row"], "canonical_work": row["work_name"]}
        for row in estimate_rows
    ]
    estimate_works = core._visual_estimate_works(
        {"rows": estimate_rows}, {"work_matches": work_matches},
    )
    expected_rows = {
        row["work_name"]: [row["source_row"]]
        for row in estimate_rows
    }

    assert {item["canonical_work"] for item in estimate_works} == set(core.SUPPORTED_WORKS)
    assert all(item["source_rows"] == expected_rows[item["canonical_work"]] for item in estimate_works)

    photo = {
        "photo_id": "photo_001",
        "vision_source_path": "/tmp/photo.png",
        "delegation_token": "x" * 43,
    }
    packet_context = json.loads(visual.delegation(photo, estimate_works)["context"])
    assert all("rooms" not in item for item in packet_context["estimate_works"])

    value = {
        "schema_version": 1,
        "photo_id": "photo_001",
        "delegation_token": "x" * 43,
        "image_quality": {"usable": True, "issues": []},
        "scene_summary": "На фотографии различимы отделочные работы и заполнение проёмов.",
        "visual_insights": [
            {
                "visual_insight_id": f"photo_001_insight_{index:03d}",
                "category": "estimate_comparison",
                "estimate_work": item["canonical_work"],
                "source_rows": item["source_rows"],
                "status": "observed",
                "title": f"{item['canonical_work']} наблюдается",
                "observation": "Результат работы различим в кадре.",
                "evidence_text": "Видимый элемент или отделочная поверхность.",
                "confidence": "medium",
                "auditor_check": "Проверить результат работы на объекте.",
                "limitations": "Вывод относится только к видимой части фотографии.",
            }
            for index, item in enumerate(estimate_works, start=1)
        ],
        "limitations": ["Фотография не определяет помещение."],
    }
    validated = visual.validate(value, photo=photo, estimate_works=estimate_works)

    assert {
        item["estimate_work"]: item["source_rows"]
        for item in validated["visual_insights"]
    } == expected_rows

    duplicate = json.loads(json.dumps(value, ensure_ascii=False))
    duplicate["visual_insights"][1]["estimate_work"] = estimate_works[0]["canonical_work"]
    duplicate["visual_insights"][1]["source_rows"] = estimate_works[0]["source_rows"]
    with pytest.raises(visual.VisualValidationError):
        visual.validate(duplicate, photo=photo, estimate_works=estimate_works)


def test_five_photo_packets_with_all_supported_works_fit_transport_budget():
    estimate_works = [
        {"canonical_work": work, "source_rows": [row]}
        for row, work in enumerate(core.SUPPORTED_WORKS, start=10)
    ]
    delegations = []
    for index in range(1, 6):
        photo = {
            "photo_id": f"photo_{index:03d}",
            "vision_source_path": "/private/tmp/" + "long_projection_path_" * 8 + ".png",
            "delegation_token": "x" * 43,
        }
        delegations.append({
            "photo_id": photo["photo_id"],
            "packet": visual.delegation(photo, estimate_works),
        })
    response = {
        "status": "visual_analysis_required",
        "photos_count": 5,
        "visual_delegations": delegations,
        "next_action": "schedule_visual_subagents_in_parallel",
        "assistant_instruction": core.VISUAL_DELEGATION_ASSISTANT_INSTRUCTION,
    }

    assert len(core.canonical_json_text(response)) <= core.MAX_VISUAL_DELEGATION_RESPONSE_CHARS
    assert all("запрещены «не выполнено», «не установлено»" in item["packet"]["constraints"] for item in delegations)
