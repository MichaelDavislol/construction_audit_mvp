"""Основные результаты аудита: расхождения, граница допуска и понятный итог."""

import copy
import json

from _mvp_fixtures import (
    analysis, call, ctx, finalize, mapping, measurement, price_catalog_response, price_match,
    setup_geometry, setup_imported, mvp_api,
)


def _single_mapping(room="Офис 1", work="Устройство пола", canonical="Устройство пола"):
    value = mapping()
    value["room_matches"] = [next(item for item in value["room_matches"] if item["estimate_room"] == room)]
    value["work_matches"] = [{"source_row": 2, "estimate_work": work, "canonical_work": canonical, "confidence": 1, "reason": "Test mapping."}]
    value["price_matches"] = [price_match(2, work)]
    return value


def _audit_artifact(mvp_api):
    return json.loads(
        (mvp_api.root / "state/jobs/audit_1/output/findings.json").read_text()
    )


def test_overstatement_and_safe_summary(mvp_api, tmp_path):
    rows = [[1, "Офис 1", "Устройство пола", "м²", 30, 1, 30, ""]]
    ext, *_ = setup_geometry(mvp_api, tmp_path, rows, confirm=True)
    response = call(ext, "run_audit", job_id="audit_1", mapping=_single_mapping())
    finding = _audit_artifact(mvp_api)["findings"][0]
    assert finding["type"] == "quantity_overstatement"
    assert finding["financial_impact"]["basis"] == "quantity_difference_at_mcp_unit_price"
    assert finding["financial_impact"]["signed_value"] == "17000"
    assert "контрольного расчётного значения" in finding["safe_summary"]
    assert "подрядчик" not in finding["safe_summary"].casefold()


def test_understatement(mvp_api, tmp_path):
    rows = [[1, "Офис 1", "Устройство пола", "м²", 10, 1, 10, ""]]
    ext, *_ = setup_geometry(mvp_api, tmp_path, rows, confirm=True)
    response = call(ext, "run_audit", job_id="audit_1", mapping=_single_mapping())
    assert _audit_artifact(mvp_api)["findings"][0]["type"] == "quantity_understatement"


def test_quantity_at_exact_tolerance_is_recorded_but_not_a_finding(mvp_api, tmp_path):
    rows = [[17, "Офис 1", "Устройство пола", "м²", 21, 1700, 35700, ""]]
    ext, *_ = setup_geometry(mvp_api, tmp_path, rows, confirm=True)
    response = call(ext, "run_audit", job_id="audit_1", mapping=_single_mapping(), tolerance_percent=5)
    artifact = _audit_artifact(mvp_api)
    check = artifact["quantity_checks"][0]
    assert check["status"] == "below_threshold"
    assert check["deviation_percent"] == "5"
    assert check["comparison_operator"] == ">"
    assert not any(item["type"].startswith("quantity_") for item in artifact["findings"])
    assert response["summary"]["quantity_below_threshold_rows"] == 1
    assert response["summary"]["quantity_deviation_rows"] == 0


def test_mapping_typo_reason_becomes_source_data_info(mvp_api, tmp_path):
    rows = [[3, "Офис 1", "Устройство полла", "м²", 20, 1700, 34000, ""]]
    ext, *_ = setup_geometry(mvp_api, tmp_path, rows, confirm=True)
    value = _single_mapping()
    value["work_matches"][0]["estimate_work"] = "Устройство полла"
    value["work_matches"][0]["reason"] = "Исправлена очевидная опечатка."
    value["price_matches"][0]["estimate_work"] = "Устройство полла"
    call(ext, "run_audit", job_id="audit_1", mapping=value)
    artifact = _audit_artifact(mvp_api)
    info = next(item for item in artifact["warnings"] if item["code"] == "source_work_name_typo")
    assert info["level"] == "info"
    assert info["position"] == "3"


def test_exact_duplicate(mvp_api, tmp_path):
    row = [1, "Офис 1", "Устройство пола", "м²", 20, 1, 20, ""]
    rows = [row, [2] + row[1:]]
    ext, *_ = setup_geometry(mvp_api, tmp_path, rows, confirm=True)
    value = _single_mapping()
    duplicate_row_mapping = copy.deepcopy(value["work_matches"][0])
    duplicate_row_mapping["source_row"] = 3
    value["work_matches"].append(duplicate_row_mapping)
    value["price_matches"].append(price_match(3, "Устройство пола"))
    response = call(ext, "run_audit", job_id="audit_1", mapping=value)
    assert any(item["type"] == "exact_duplicate" for item in _audit_artifact(mvp_api)["findings"])


def test_arithmetic_mismatch(mvp_api, tmp_path):
    rows = [[1, "Офис 1", "Устройство пола", "м²", 20, 2, 10, ""]]
    ext, *_ = setup_geometry(mvp_api, tmp_path, rows, confirm=True)
    response = call(ext, "run_audit", job_id="audit_1", mapping=_single_mapping())
    assert any(item["type"] == "arithmetic_mismatch" for item in _audit_artifact(mvp_api)["findings"])


def test_invalid_quantity_finding(mvp_api, tmp_path):
    rows = [[1, "Офис 1", "Устройство пола", "м²", "bad", 2, 10, ""]]
    ext, *_ = setup_geometry(mvp_api, tmp_path, rows, confirm=True)
    response = call(ext, "run_audit", job_id="audit_1", mapping=_single_mapping())
    assert any(item["type"] == "invalid_quantity" for item in _audit_artifact(mvp_api)["findings"])
    assert response["summary"]["not_checked_rows"] == 1


def test_report_requires_llm_finalization(mvp_api, tmp_path):
    ext, *_ = setup_geometry(mvp_api, tmp_path, confirm=True)
    prepared = call(ext, "run_audit", job_id="audit_1", mapping=mapping())
    assert prepared["status"] == "visual_review_required"
    assert not (mvp_api.root / "state/jobs/audit_1/output/report.html").exists()
    response = finalize(ext)
    assert response["ok"] and response["report_artifact"]["size_bytes"] > 0
    import json
    manifest = json.loads((mvp_api.root / "state/jobs/audit_1/manifest.json").read_text())
    assert manifest["audit_completed"] is True and manifest["report_generated"] is True
    assert response["summary"]["quantity_coverage_percent"] == "100"
    assert response["summary"]["price_coverage_percent"] == "100"


def test_render_audit_summary_replays_saved_result(mvp_api, tmp_path):
    ext, *_ = setup_geometry(mvp_api, tmp_path, confirm=True)
    call(ext, "run_audit", job_id="audit_1", mapping=mapping())
    audited = finalize(ext)
    replayed = call(ext, "render_audit_summary", job_id="audit_1")

    assert replayed["ok"]
    assert replayed["summary"] == audited["summary"]
    assert replayed["report_artifact"] == audited["report_artifact"]
    assert replayed["audit_summary_markdown"] == audited["audit_summary_markdown"]
    assert "После ЛЮБОГО [SYSTEM REMINDER]" in replayed["assistant_instruction"]
    assert "Высокая важность" in replayed["audit_summary_markdown"]
    assert "| Предупреждений |" not in replayed["audit_summary_markdown"]


def test_render_audit_summary_recovers_pending_llm_delegation(mvp_api, tmp_path):
    ext, *_ = setup_geometry(mvp_api, tmp_path, confirm=True)
    call(ext, "run_audit", job_id="audit_1", mapping=mapping())
    prepared = call(ext, "skip_visual_review", job_id="audit_1")

    recovered = call(ext, "render_audit_summary", job_id="audit_1")

    assert recovered["ok"]
    assert recovered["status"] == "llm_insights_required"
    assert recovered["llm_context_sha256"] == prepared["llm_context_sha256"]
    assert recovered["llm_insights_delegation"] == prepared["llm_insights_delegation"]
    assert recovered["next_action"] == "schedule_llm_insights_subagent"


def test_audit_summary_for_three_room_fixture(mvp_api, tmp_path):
    works = [
        ("Грунтовка стен", "м²", 50),
        ("Окраска стен", "м²", 50),
        ("Устройство пола", "м²", 20),
        ("Отделка потолка", "м²", 20),
        ("Монтаж плинтуса", "м", 17.1),
        ("Установка дверей", "шт", 1),
        ("Установка окон", "шт", 1),
    ]
    rows = []
    source_row = 1
    for room_name in ("Офис 1", "Офис 2", "Офис 3"):
        for work_name, unit, quantity in works:
            rows.append([source_row, room_name, work_name, unit, quantity, 1, quantity, ""])
            source_row += 1

    geometry_analysis = analysis()
    room_3 = copy.deepcopy(geometry_analysis["rooms"][0])
    room_3.update({"source_room_id": "source-c", "name": "Офис 3"})
    room_3["doors"][0]["element_id"] = "door-3"
    room_3["windows"][0]["element_id"] = "window-3"
    geometry_analysis["rooms"].append(room_3)
    for room in geometry_analysis["rooms"]:
        room["windows"][0]["height_m"] = measurement(None)

    ext, *_ = setup_imported(mvp_api, tmp_path, rows)
    saved = call(ext, "save_geometry", job_id="audit_1", analysis=geometry_analysis)
    confirmed = call(
        ext, "confirm_geometry", ctx("confirm", "confirm-msg"),
        job_id="audit_1", geometry_revision=saved["geometry_revision"], confirmed=True,
    )
    assert confirmed["ok"]
    catalog = call(ext, "save_price_catalog", job_id="audit_1", catalog_response=price_catalog_response())
    assert catalog["ok"]
    full_mapping = mapping(
        room_matches=[
            {"estimate_room": f"Офис {index}", "model_room_id": f"room_{index:03d}",
             "confidence": 1, "reason": "Exact match."}
            for index in range(1, 4)
        ],
        work_matches=[
            {"source_row": source_row, "estimate_work": row[2], "canonical_work": row[2],
             "confidence": 1, "reason": "Exact match."}
            for source_row, row in enumerate(rows, start=2)
        ],
        price_matches=[
            price_match(source_row, row[2])
            for source_row, row in enumerate(rows, start=2)
        ],
    )
    response = call(ext, "run_audit", job_id="audit_1", mapping=full_mapping)

    assert {key: response["summary"][key] for key in (
        "estimate_rows", "checked_rows", "not_checked_rows", "findings_count", "warnings_count"
    )} == {
        "estimate_rows": 21,
        "checked_rows": 15,
        "not_checked_rows": 6,
        "findings_count": 22,
        "warnings_count": 15,
    }
    response = finalize(ext)
    markdown = response["audit_summary_markdown"]
    assert response["next_action"] == "display_audit_summary_markdown_verbatim"
    assert "Выявлено 22 предварительных расхождений" in markdown
    assert "6 строк требуют проверки специалистом" in markdown
    assert "отсутствуют высоты окон" in markdown
    assert response["report_artifact"]["path"] in markdown
    assert "Всё чисто" not in markdown
    assert "предварительным автоматизированным аудитом" in markdown
