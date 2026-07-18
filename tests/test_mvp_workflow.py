"""Короткий smoke-test всего пути от документов до итогового HTML."""

import hashlib
from pathlib import Path

from _mvp_fixtures import (
    ConstructionAuditMVP, analysis, call, ctx, descriptor, finalize, make_plan, make_xlsx,
    mapping, price_catalog_response, mvp_api,
)


def test_complete_two_turn_workflow(mvp_api, tmp_path):
    # Review и подтверждение специально разделены: иначе агент подтвердил бы сам себя.
    ext = ConstructionAuditMVP(mvp_api)
    assert call(ext, "create_case", job_id="audit_1", object_name="Офис")["next_action"] == "import_documents"
    estimate, plan = make_xlsx(tmp_path), make_plan(tmp_path)
    imported = call(ext, "import_documents", job_id="audit_1", estimate=descriptor(estimate), plan=descriptor(plan))
    assert imported["next_action"] == "schedule_vision_subagent"
    saved = call(ext, "save_geometry", ctx("task-review", "msg-review"), job_id="audit_1", analysis=analysis())
    assert saved["geometry_revision"] == 1 and saved["confirmation_question"]
    reviewed = call(ext, "render_geometry_review", job_id="audit_1", geometry_revision=1)
    assert "Офис 1" in reviewed["review_markdown"]
    same_task = call(ext, "confirm_geometry", ctx("task-review", "new-msg"), job_id="audit_1", geometry_revision=1, confirmed=True)
    assert same_task["code"] == "confirmation_requires_new_turn"
    same_message = call(ext, "confirm_geometry", ctx("new-task", "msg-review"), job_id="audit_1", geometry_revision=1, confirmed=True)
    assert same_message["code"] == "confirmation_requires_new_turn"
    confirmed = call(ext, "confirm_geometry", ctx("new-task", "new-msg"), job_id="audit_1", geometry_revision=1, confirmed=True)
    assert confirmed["next_action"] == "call_mcp_construction_prices__get_supported_works"
    catalog = call(ext, "save_price_catalog", job_id="audit_1", catalog_response=price_catalog_response())
    assert catalog["next_action"] == "run_audit"
    assert catalog["mapping_mode"] == "deterministic_exact_match"
    assert "mapping_delegation" not in catalog
    audited = call(
        ext, "run_audit", ctx("audit-task", "audit-msg"), job_id="audit_1",
        mapping=catalog["mapping"], mapping_task_id=catalog["mapping_task_id"],
    )
    assert audited["status"] == "visual_review_required"
    assert audited["next_action"] == "await_site_photo_zip_or_skip"
    audited = call(ext, "skip_visual_review", job_id="audit_1")
    assert audited["status"] == "llm_insights_required"
    assert audited["next_action"] == "schedule_llm_insights_subagent"
    audited = finalize(ext, context=ctx("finalize-task", "finalize-msg"))
    report = Path(audited["report_artifact"]["path"])
    assert audited["status"] == "audit_completed" and report.is_file()
    assert hashlib.sha256(report.read_bytes()).hexdigest() == audited["report_artifact"]["sha256"]


def test_run_audit_before_confirmation_is_blocked(mvp_api, tmp_path):
    ext = ConstructionAuditMVP(mvp_api)
    call(ext, "create_case", job_id="audit_1", object_name="Офис")
    estimate, plan = make_xlsx(tmp_path), make_plan(tmp_path)
    call(ext, "import_documents", job_id="audit_1", estimate=descriptor(estimate), plan=descriptor(plan))
    call(ext, "save_geometry", job_id="audit_1", analysis=analysis())
    assert call(ext, "run_audit", job_id="audit_1", mapping=mapping())["code"] == "geometry_confirmation_required"
