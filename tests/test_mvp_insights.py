"""Финальный аналитик получает ограниченный контекст и обязан ссылаться на факты."""

import json
from pathlib import Path

import pytest

from _mvp_fixtures import call, ctx, mapping, no_useful_insights, setup_geometry, mvp_api
from construction_audit_mvp import insights


def _generated(ref_value="finding_001"):
    return {
        "schema_version": 1,
        "status": "generated",
        "summary": "Есть самостоятельная гипотеза для дополнительной проверки.",
        "items": [
            {
                "insight_id": "insight_001",
                "category": "systemic_pattern",
                "title": "Повторяющийся характер расхождений",
                "observation": "Несколько переданных результатов имеют одинаковое направление.",
                "hypothesis": "Возможна общая причина в исходной методике расчёта.",
                "evidence_refs": [{"type": "finding", "value": ref_value}],
                "confidence": "medium",
                "recommended_check": "Сверить методику по связанным строкам.",
                "limitations": "Гипотеза основана только на переданном контексте.",
            }
        ],
    }


def test_run_audit_prepares_bounded_llm_context_without_report(mvp_api, tmp_path):
    ext, *_ = setup_geometry(mvp_api, tmp_path, confirm=True)
    prepared = call(ext, "run_audit", job_id="audit_1", mapping=mapping())

    assert prepared["status"] == "visual_review_required"
    assert prepared["next_action"] == "await_site_photo_zip_or_skip"
    prepared = call(ext, "skip_visual_review", job_id="audit_1")
    assert prepared["status"] == "llm_insights_required"
    assert prepared["llm_insights_delegation"]["role"] == "construction-audit-analyst"
    assert not (mvp_api.root / "state/jobs/audit_1/output/report.html").exists()
    context = json.loads((mvp_api.root / "state/jobs/audit_1/output/llm_context.json").read_text())
    assert "delegation_token" not in context["mapping"]
    assert context["deterministic_findings"]
    assert len(json.dumps(prepared, ensure_ascii=False, separators=(",", ":"))) <= 14_500
    assert "findings" not in prepared and "price_checks" not in prepared
    assert prepared["llm_insights_delegation"]["expected_output"].startswith(
        "Финальный ответ должен быть одной строкой"
    )
    assert "FINAL ANSWER: [BEGIN_SUBTASK_OUTPUT]" in prepared["llm_insights_delegation"]["expected_output"]
    assert "list_files" in prepared["assistant_instruction"]


def test_finalize_rejects_unknown_evidence_reference(mvp_api, tmp_path):
    ext, *_ = setup_geometry(mvp_api, tmp_path, confirm=True)
    call(ext, "run_audit", job_id="audit_1", mapping=mapping())
    call(ext, "skip_visual_review", job_id="audit_1")

    result = call(
        ext,
        "finalize_audit",
        job_id="audit_1",
        insights_task_id="insights-child",
        llm_insights=_generated("finding_999"),
    )

    assert result["code"] == "llm_insights_schema_invalid"
    assert not (mvp_api.root / "state/jobs/audit_1/output/report.html").exists()


def test_finalize_requires_separate_subagent_result(mvp_api, tmp_path):
    ext, *_ = setup_geometry(mvp_api, tmp_path, confirm=True)
    call(ext, "run_audit", job_id="audit_1", mapping=mapping())
    call(ext, "skip_visual_review", job_id="audit_1")
    result = call(
        ext,
        "finalize_audit",
        ctx("same-task", "msg"),
        job_id="audit_1",
        insights_task_id="same-task",
        llm_insights=no_useful_insights(),
    )
    assert result["code"] == "llm_insights_subagent_required"


def test_generated_hypotheses_are_separate_and_rendered(mvp_api, tmp_path):
    ext, *_ = setup_geometry(mvp_api, tmp_path, confirm=True)
    prepared = call(ext, "run_audit", job_id="audit_1", mapping=mapping())
    prepared = call(ext, "skip_visual_review", job_id="audit_1")
    findings_path = mvp_api.root / "state/jobs/audit_1/output/findings.json"
    deterministic_count = len(json.loads(findings_path.read_text())["findings"])
    result = call(
        ext,
        "finalize_audit",
        job_id="audit_1",
        insights_task_id="insights-child",
        llm_insights=_generated(),
    )

    assert result["status"] == "audit_completed"
    assert len(json.loads(findings_path.read_text())["findings"]) == deterministic_count
    saved_insights = json.loads(
        (mvp_api.root / "state/jobs/audit_1/output/llm_insights.json").read_text()
    )
    assert saved_insights["items"][0]["insight_id"] == "insight_001"
    html = Path(result["report_artifact"]["path"]).read_text(encoding="utf-8")
    assert "Дополнительная гипотеза" in html
    assert "Повторяющийся характер расхождений" in html
    assert "<strong>Вывод:</strong>" in html
    assert "<strong>Что на это указывает:</strong>" in html
    assert "<strong>Что проверить:</strong>" in html
    assert "<summary>Основания и ограничения</summary>" in html


def test_finalize_accepts_one_exact_json_serialization(mvp_api, tmp_path):
    ext, *_ = setup_geometry(mvp_api, tmp_path, confirm=True)
    call(ext, "run_audit", job_id="audit_1", mapping=mapping())
    call(ext, "skip_visual_review", job_id="audit_1")

    result = call(
        ext,
        "finalize_audit",
        job_id="audit_1",
        insights_task_id="insights-child",
        llm_insights=json.dumps(_generated(), ensure_ascii=False, separators=(",", ":")),
    )

    assert result["status"] == "audit_completed"
    saved = json.loads(
        (mvp_api.root / "state/jobs/audit_1/output/llm_insights.json").read_text()
    )
    assert saved["insights_task_id"] == "insights-child"


def test_insights_transport_error_does_not_consume_attempt(mvp_api, tmp_path):
    # Битая JSON-обёртка ещё ничего не говорит о работе аналитика. Сначала пробуем
    # заново извлечь тот же ответ и только потом считаем попытку неудачной.
    ext, *_ = setup_geometry(mvp_api, tmp_path, confirm=True)
    call(ext, "run_audit", job_id="audit_1", mapping=mapping())
    call(ext, "skip_visual_review", job_id="audit_1")

    invalid_transport = call(
        ext,
        "finalize_audit",
        job_id="audit_1",
        insights_task_id="insights-child",
        llm_insights="{not-json",
    )
    assert invalid_transport["code"] == "llm_insights_transport_invalid"
    assert invalid_transport["next_action"] == "reextract_same_subagent_result"
    assert "тем же task ID" in invalid_transport["assistant_instruction"]
    manifest = json.loads(
        (mvp_api.root / "state/jobs/audit_1/manifest.json").read_text()
    )
    assert manifest["llm_insights_attempts"] == 0

    accepted = call(
        ext,
        "finalize_audit",
        job_id="audit_1",
        insights_task_id="insights-child",
        llm_insights=json.dumps(_generated(), ensure_ascii=False),
    )
    assert accepted["status"] == "audit_completed"


def _visual_context():
    return {
        "estimate_rows": [],
        "geometry": {"rooms": [{"room_id": "room_001", "name": "Офис 1"}]},
        "deterministic_findings": [],
        "relevant_calculation_trace": [],
        "price_checks": [],
        "visual_insights": {
            "status": "generated",
            "items": [{
                "visual_insight_id": "photo_001_insight_001",
                "photo_id": "photo_001",
                "source_rows": [15],
            }],
        },
    }


def _visual_hypothesis(observation):
    return {
        "schema_version": 1,
        "status": "generated",
        "summary": "Фото-наблюдение требует проверки аудитором.",
        "items": [{
            "insight_id": "insight_001",
            "category": "visual_observation",
            "title": "Сопоставление фотографии со сметой",
            "observation": observation,
            "hypothesis": "Фотография может относиться к более раннему этапу работ.",
            "evidence_refs": [
                {"type": "visual_insight", "value": "photo_001_insight_001"},
                {"type": "estimate_row", "value": 15},
            ],
            "confidence": "medium",
            "recommended_check": "Проверить результат окраски на объекте.",
            "limitations": "Основание ограничено одной фотографией.",
        }],
    }


def test_visual_hypothesis_keeps_estimate_row_outside_transport_sample():
    result = insights.validate(
        _visual_hypothesis("На фотографии окраска стен не наблюдается."),
        _visual_context(),
    )

    assert result["items"][0]["evidence_refs"][1] == {
        "type": "estimate_row", "value": 15,
    }


def test_visual_hypothesis_cannot_be_generalized_to_rooms():
    with pytest.raises(insights.InsightsValidationError) as exc_info:
        insights.validate(
            _visual_hypothesis("По фотографии окраска отсутствует во всех помещениях."),
            _visual_context(),
        )

    assert any(
        error["reason"] == "visual evidence is not linked to rooms"
        for error in exc_info.value.errors
    )
