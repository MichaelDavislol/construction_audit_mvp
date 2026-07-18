"""Несколько проверок границ: пути, повторные job и чистый production payload."""

from pathlib import Path

from construction_audit_mvp import plugin
from _mvp_fixtures import ConstructionAuditMVP, call, mvp_api


def test_unsafe_job_ids_rejected(mvp_api):
    ext = ConstructionAuditMVP(mvp_api)
    for job_id in ("../escape", "a/b", "", "x" * 65):
        assert call(ext, "create_case", job_id=job_id, object_name="Офис")["code"] == "invalid_job_id"


def test_create_case_idempotent_and_conflict_detected(mvp_api):
    ext = ConstructionAuditMVP(mvp_api)
    assert call(ext, "create_case", job_id="job", object_name="Офис")["ok"]
    assert call(ext, "create_case", job_id="job", object_name="Офис")["ok"]
    assert call(ext, "create_case", job_id="job", object_name="Склад")["code"] == "case_conflict"


def test_no_tests_inside_production_skill():
    skill = Path(plugin.__file__).parent
    assert not (skill / "tests").exists()
    assert not list(skill.glob("test_*.py"))


def test_exact_production_files():
    skill = Path(plugin.__file__).parent
    names = {
        path.name for path in skill.iterdir()
        if path.is_file() and not path.name.startswith(".")
    }
    assert names == {
        "SKILL.md", "plugin.py", "core.py", "vision.py", "report.py", "insights.py",
        "visual.py",
    }
