"""Импорт принимает нормальные файлы и спокойно отказывает подозрительным."""

import hashlib
import json
import zipfile
from pathlib import Path

from _mvp_fixtures import ConstructionAuditMVP, call, descriptor, make_plan, make_xlsx, mvp_api


def test_imports_xlsx_and_png_and_projects_plan(mvp_api, tmp_path):
    ext = ConstructionAuditMVP(mvp_api)
    call(ext, "create_case", job_id="job", object_name="Офис")
    xlsx, plan = make_xlsx(tmp_path), make_plan(tmp_path)
    response = call(ext, "import_documents", job_id="job", estimate=descriptor(xlsx), plan=descriptor(plan))
    assert response["ok"] and response["estimate"]["rows_count"] == 3
    projection = Path(response["plan"]["source_path"])
    assert projection.is_absolute()
    assert projection.is_file()
    assert projection.parent == (mvp_api.root / "data/uploads/construction_audit_mvp").resolve()


def test_footer_rows_are_skipped(mvp_api, tmp_path):
    rows = [[1, "Офис 1", "Устройство пола", "м²", 20, 1, 20, ""],
            [None, None, "Итого по работам", None, None, None, 20, None],
            [None, None, "Резерв", None, None, None, 2, None]]
    from _mvp_fixtures import setup_imported
    setup_imported(mvp_api, tmp_path, rows)
    normalized = json.loads((mvp_api.root / "state/jobs/audit_1/output/estimate_normalized.json").read_text())
    assert len(normalized["rows"]) == 1


def test_source_xlsx_unchanged_and_no_clean_copy(mvp_api, tmp_path):
    ext = ConstructionAuditMVP(mvp_api)
    call(ext, "create_case", job_id="job", object_name="Офис")
    xlsx, plan = make_xlsx(tmp_path), make_plan(tmp_path)
    before = hashlib.sha256(xlsx.read_bytes()).hexdigest()
    call(ext, "import_documents", job_id="job", estimate=descriptor(xlsx), plan=descriptor(plan))
    assert hashlib.sha256(xlsx.read_bytes()).hexdigest() == before
    assert not list(tmp_path.rglob("*clean*.xlsx"))


def test_missing_total_is_calculated_in_normalized_json(mvp_api, tmp_path):
    from _mvp_fixtures import setup_imported
    setup_imported(mvp_api, tmp_path, [[1, "Офис 1", "Устройство пола", "м²", 2, 10, None, ""]])
    normalized = json.loads((mvp_api.root / "state/jobs/audit_1/output/estimate_normalized.json").read_text())
    assert normalized["rows"][0]["total"] == "20"
    assert normalized["rows"][0]["total_source"] == "calculated_from_quantity_and_price"


def test_corrupted_xlsx_rejected(mvp_api, tmp_path):
    ext = ConstructionAuditMVP(mvp_api)
    call(ext, "create_case", job_id="job", object_name="Офис")
    xlsx, plan = make_xlsx(tmp_path), make_plan(tmp_path)
    xlsx.write_bytes(b"not a zip")
    response = call(ext, "import_documents", job_id="job", estimate=descriptor(xlsx), plan=descriptor(plan))
    assert response["code"] == "invalid_xlsx"


def test_unsafe_attachment_path_rejected(mvp_api, tmp_path):
    ext = ConstructionAuditMVP(mvp_api)
    call(ext, "create_case", job_id="job", object_name="Офис")
    xlsx, plan = make_xlsx(tmp_path), make_plan(tmp_path)
    bad = descriptor(xlsx); bad["attachment_relpath"] = "../estimate.xlsx"
    response = call(ext, "import_documents", job_id="job", estimate=bad, plan=descriptor(plan))
    assert response["code"] == "invalid_attachment"


def test_fake_image_rejected(mvp_api, tmp_path):
    ext = ConstructionAuditMVP(mvp_api)
    call(ext, "create_case", job_id="job", object_name="Офис")
    xlsx, plan = make_xlsx(tmp_path), make_plan(tmp_path, payload=b"fake")
    response = call(ext, "import_documents", job_id="job", estimate=descriptor(xlsx), plan=descriptor(plan))
    assert response["code"] == "invalid_image"


def test_zip_traversal_rejected(mvp_api, tmp_path):
    ext = ConstructionAuditMVP(mvp_api)
    call(ext, "create_case", job_id="job", object_name="Офис")
    xlsx, plan = make_xlsx(tmp_path), make_plan(tmp_path)
    with zipfile.ZipFile(xlsx, "a") as archive:
        archive.writestr("../escape", "bad")
    response = call(ext, "import_documents", job_id="job", estimate=descriptor(xlsx), plan=descriptor(plan))
    assert response["code"] == "unsafe_xlsx_archive"
