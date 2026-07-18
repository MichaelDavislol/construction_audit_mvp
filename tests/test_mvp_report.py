"""Отчёт должен быть понятным человеку и безопасным для открытия в браузере."""

from pathlib import Path

from construction_audit_mvp import report
from construction_audit_mvp.report import DISCLAIMER
from _mvp_fixtures import call, finalize, mapping, run_and_finalize, setup_geometry, mvp_api


def _report(mvp_api, tmp_path):
    ext, *_ = setup_geometry(mvp_api, tmp_path, confirm=True)
    response = run_and_finalize(ext)
    return response, Path(response["report_artifact"]["path"]).read_text(encoding="utf-8")


def test_report_contains_required_sections(mvp_api, tmp_path):
    _, html = _report(mvp_api, tmp_path)
    for text in ("Краткое резюме", "Ключевые замечания", "Аналитические наблюдения и гипотезы", "Раздельная проверка", "Геометрия объекта", "Техническое приложение", "Mapping помещений", "Расчётные основания (Calculation trace)", "Warnings"):
        assert text in html
    assert DISCLAIMER in html


def test_calculation_trace_is_rendered_as_readable_python_calculations(mvp_api, tmp_path):
    _, html = _report(mvp_api, tmp_path)

    assert "Формулы ниже построены Python" in html
    assert "Площадь стен до вычета проёмов" in html
    assert "Чистая площадь стен" in html
    assert "Длина плинтуса" in html
    assert "Как получено" in html
    assert "Итоги по объекту" in html
    assert "Исходный структурированный trace" in html
    assert "room:room_001:floor_area_m2" in html


def test_calculation_trace_highlights_only_deviation_checks():
    trace = {
        "schema_version": 1,
        "entries": [
            {
                "trace_id": "quantity_check:rows:2",
                "source_rows": [2],
                "metric": "quantity_threshold_check",
                "inputs": {
                    "estimate_quantity": "12",
                    "control_quantity_display": "10",
                    "tolerance_percent": "5",
                },
                "results": {
                    "deviation_percent_raw": "20",
                    "threshold_exceeded": True,
                    "status": "deviation_found",
                },
            },
            {
                "trace_id": "price:row:2:wall_painting",
                "source_row": 2,
                "metric": "price_and_total_check",
                "inputs": {
                    "estimate_quantity": "12",
                    "mcp_unit_price": "450",
                    "estimate_total": "6000",
                },
                "results": {
                    "mcp_total": "5400",
                    "unit_price_impact": "0",
                    "total_cost_impact": "600",
                },
            },
        ],
    }
    estimate = {
        "rows": [{
            "source_row": 2,
            "work_name": "Окраска стен",
            "unit": "м²",
        }],
    }

    html = report._calculation_trace_section(trace, estimate)

    assert "Расчёты по строкам с отклонениями" in html
    assert "Смета: 12 м²; контроль: 10 м²" in html
    assert "Отклонение 20%; порог 5%" in html
    assert "12 × 450 = 5 400" in html
    assert "В смете: 6 000; разница стоимости: 600" in html


def test_report_contains_confirmation_and_revision(mvp_api, tmp_path):
    _, html = _report(mvp_api, tmp_path)
    assert "Подтверждена" in html and "revision" in html


def test_report_escapes_untrusted_text(mvp_api, tmp_path):
    rows = [[1, "Офис 1", "<script>alert(1)</script>", "м²", 30, 1, 30, ""]]
    ext, *_ = setup_geometry(mvp_api, tmp_path, rows, confirm=True)
    value = mapping()
    value["room_matches"] = [value["room_matches"][0]]
    value["work_matches"] = []
    value["work_unsupported"] = [{"source_row": 2, "estimate_work": "<script>alert(1)</script>", "reason": "Unsupported"}]
    value["price_matches"] = []
    value["price_unsupported"] = [{"source_row": 2, "estimate_work": "<script>alert(1)</script>", "reason": "Unsupported"}]
    response = call(ext, "run_audit", job_id="audit_1", mapping=value)
    assert response["status"] == "visual_review_required"
    response = finalize(ext)
    html = Path(response["report_artifact"]["path"]).read_text(encoding="utf-8")
    assert "<script>alert(1)</script>" not in html


def test_tool_result_does_not_return_html(mvp_api, tmp_path):
    response, _ = _report(mvp_api, tmp_path)
    assert "<!doctype html>" not in str(response)
