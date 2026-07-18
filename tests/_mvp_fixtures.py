"""Заготовки для всего детерминированного контура.

LLM здесь не запускается: её валидный или ошибочный ответ подставляется как обычный
внешний payload. Так мы отдельно проверяем код скилла, не смешивая его ошибки со
случайностью конкретного ответа модели.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from openpyxl import Workbook


from construction_audit_mvp.plugin import ConstructionAuditMVP, register


HEADERS = [
    "№", "Помещение", "Наименование работы", "Единица", "Количество",
    "Цена за единицу", "Стоимость", "Примечание",
]
MCP_ID_BY_WORK = {
    "Грунтовка стен": "wall_priming",
    "Окраска стен": "wall_painting",
    "Устройство пола": "floor_installation",
    "Отделка потолка": "ceiling_finishing",
    "Монтаж плинтуса": "baseboard_installation",
    "Установка окон": "window_installation",
    "Установка дверей": "door_installation",
}


class FakeAPI:
    def __init__(self, root: Path):
        self.root = root
        self.tools = {}
        self.logs = []

    def skill_job_dir(self, job_id: str) -> Path:
        return self.root / "state" / "jobs" / job_id

    def get_runtime_info(self):
        return {"data_dir": str(self.root / "data"), "execution_mode": "in_process"}

    def register_tool(self, name, handler, *, description, schema, timeout_sec=60):
        assert name not in self.tools
        self.tools[name] = {
            "handler": handler, "description": description,
            "schema": schema, "timeout_sec": timeout_sec,
        }

    def log(self, level, message, **fields):
        self.logs.append((level, message, fields))


def ctx(task_id="task-review", client_message_id="msg-review"):
    return SimpleNamespace(task_id=task_id, task_metadata={"client_message_id": client_message_id})


def call(extension, name, context=None, **kwargs):
    context = context or ctx()
    if name == "save_geometry":
        kwargs.setdefault("vision_task_id", "vision-child")
    elif name == "run_audit":
        kwargs.setdefault("mapping_task_id", "mapping-child")
        mapping_payload = kwargs.get("mapping")
        if (
            isinstance(mapping_payload, dict)
            and mapping_payload.get("delegation_token") == "__CURRENT_DELEGATION_TOKEN__"
        ):
            manifest = json.loads(
                (extension.api.skill_job_dir(kwargs["job_id"]) / "manifest.json").read_text()
            )
            if manifest.get("mapping_generation_token"):
                kwargs["mapping"] = {
                    **mapping_payload,
                    "delegation_token": manifest["mapping_generation_token"],
                }
    elif name == "finalize_audit":
        kwargs.setdefault("insights_task_id", "insights-child")
    raw = getattr(extension, name)(context, **kwargs)
    return json.loads(raw)


def no_useful_insights():
    return {
        "schema_version": 1,
        "status": "no_useful_observations",
        "summary": "Самостоятельных наблюдений с достаточными основаниями нет.",
        "items": [],
    }


def finalize(ext, job_id="audit_1", *, llm_insights=None, context=None):
    manifest_path = ext.api.skill_job_dir(job_id) / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("audit_status") == "visual_review_required":
        skipped = call(ext, "skip_visual_review", context, job_id=job_id)
        assert skipped.get("status") == "llm_insights_required", skipped
    return call(
        ext,
        "finalize_audit",
        context,
        job_id=job_id,
        llm_insights=llm_insights or no_useful_insights(),
    )


def run_and_finalize(ext, job_id="audit_1", *, mapping_payload=None, context=None, **kwargs):
    prepared = call(
        ext,
        "run_audit",
        context,
        job_id=job_id,
        mapping=mapping_payload or mapping(),
        **kwargs,
    )
    assert prepared["status"] == "visual_review_required", prepared
    prepared = call(ext, "skip_visual_review", context, job_id=job_id)
    assert prepared.get("status") == "llm_insights_required", prepared
    return finalize(ext, job_id, context=context)


def make_xlsx(base: Path, rows=None, *, sheet="Смета", headers=HEADERS):
    path = base / "task" / "artifacts" / "task-1" / "attachments" / "estimate.xlsx"
    path.parent.mkdir(parents=True, exist_ok=True)
    workbook = Workbook()
    ws = workbook.active
    ws.title = sheet
    ws.append(headers)
    for row in rows or [
        [1, "Офис 1", "Устройство пола", "м²", 20, 100, 2000, ""],
        [2, "Офис 1", "Окраска стен", "м²", 40, 100, 4000, ""],
        [3, "Офис 2", "Установка дверей", "шт", 1, 1000, 1000, ""],
    ]:
        ws.append(row)
    workbook.save(path)
    return path


def make_plan(base: Path, name="plan.png", payload=None):
    path = base / "task" / "artifacts" / "task-1" / "attachments" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    if payload is None:
        payload = b"\x89PNG\r\n\x1a\n" + b"test-plan"
    path.write_bytes(payload)
    return path


def descriptor(path: Path):
    return {
        "attachment_root": "artifact_store",
        "attachment_relpath": f"attachments/{path.name}",
        "attachment_path": str(path),
    }


def measurement(value, source_type="explicit_dimension_line", evidence_text="label", confidence=.95):
    if value is None:
        return {"value": None, "confidence": 0, "source_type": "not_found", "evidence_text": ""}
    return {"value": value, "confidence": confidence, "source_type": source_type, "evidence_text": evidence_text}


def analysis(**overrides):
    value = {
        "schema_version": 1,
        "plan_id": "plan_001",
        "image_quality": {"usable": True, "issues": []},
        "object_name_suggestion": "Офис",
        "rooms": [
            {
                "source_room_id": "source-b",
                "name": "Офис 2",
                "floor_area_m2": measurement(20, "explicit_area_label", "20 м²"),
                "length_m": measurement(5), "width_m": measurement(4),
                "perimeter_m": measurement(18, "derived_from_explicit_dimensions"),
                "height_m": measurement(3),
                "doors": [{"element_id": "door-shared", "width_m": measurement(.9), "height_m": measurement(2.1)}],
                "windows": [{"element_id": "window-2", "width_m": measurement(1.5), "height_m": measurement(1.4)}],
                "warnings": [],
            },
            {
                "source_room_id": "source-a",
                "name": "Офис 1",
                "floor_area_m2": measurement(20, "explicit_area_label", "20 м²"),
                "length_m": measurement(5), "width_m": measurement(4),
                "perimeter_m": measurement(18, "derived_from_explicit_dimensions"),
                "height_m": measurement(3),
                "doors": [{"element_id": "door-shared", "width_m": measurement(.9), "height_m": measurement(2.1)}],
                "windows": [{"element_id": "window-1", "width_m": measurement(1.5), "height_m": measurement(1.4)}],
                "warnings": [],
            },
        ],
        "general_warnings": [],
    }
    value.update(overrides)
    return value


def mapping(**overrides):
    value = {
        "schema_version": 3,
        "delegation_token": "__CURRENT_DELEGATION_TOKEN__",
        "room_matches": [
            {"estimate_room": "Офис 1", "model_room_id": "room_001", "confidence": .99, "reason": "Смысловое совпадение."},
            {"estimate_room": "Офис 2", "model_room_id": "room_002", "confidence": .99, "reason": "Смысловое совпадение."},
        ],
        "room_unresolved": [],
        "work_matches": [
            {"source_row": 2, "estimate_work": "Устройство пола", "canonical_work": "Устройство пола", "confidence": 1, "reason": "Совпадение."},
            {"source_row": 3, "estimate_work": "Окраска стен", "canonical_work": "Окраска стен", "confidence": 1, "reason": "Совпадение."},
            {"source_row": 4, "estimate_work": "Установка дверей", "canonical_work": "Установка дверей", "confidence": 1, "reason": "Совпадение."},
        ],
        "work_unsupported": [],
        "work_unresolved": [],
        "price_matches": [
            {"source_row": 2, "estimate_work": "Устройство пола", "mcp_work_id": "floor_installation", "confidence": 1, "reason": "Совпадение по смыслу, объекту и единице."},
            {"source_row": 3, "estimate_work": "Окраска стен", "mcp_work_id": "wall_painting", "confidence": 1, "reason": "Совпадение по смыслу, объекту и единице."},
            {"source_row": 4, "estimate_work": "Установка дверей", "mcp_work_id": "door_installation", "confidence": 1, "reason": "Совпадение по смыслу, объекту и единице."},
        ],
        "price_unsupported": [],
        "price_unresolved": [],
    }
    value.update(overrides)
    return value


def price_match(source_row, estimate_work, mcp_work_id=None):
    return {
        "source_row": source_row,
        "estimate_work": estimate_work,
        "mcp_work_id": mcp_work_id or MCP_ID_BY_WORK[estimate_work],
        "confidence": 1,
        "reason": "Совпадение по смыслу, объекту и единице.",
    }


def price_catalog_response(**overrides):
    value = {
        "result": [
            {"id": "wall_priming", "name": "Грунтовка стен", "unit": "м²", "price": 120},
            {"id": "wall_painting", "name": "Окраска стен", "unit": "м²", "price": 450},
            {"id": "floor_installation", "name": "Устройство пола", "unit": "м²", "price": 1700},
            {"id": "ceiling_finishing", "name": "Отделка потолка", "unit": "м²", "price": 650},
            {"id": "baseboard_installation", "name": "Монтаж плинтуса", "unit": "м", "price": 350},
            {"id": "window_installation", "name": "Установка окон", "unit": "шт.", "price": 9000},
            {"id": "door_installation", "name": "Установка дверей", "unit": "шт.", "price": 7000},
        ]
    }
    value.update(overrides)
    return value


def setup_imported(api, tmp_path, rows=None, job_id="audit_1"):
    ext = ConstructionAuditMVP(api)
    assert call(ext, "create_case", job_id=job_id, object_name="Офис")["ok"]
    estimate = make_xlsx(tmp_path, rows)
    plan = make_plan(tmp_path)
    response = call(ext, "import_documents", job_id=job_id, estimate=descriptor(estimate), plan=descriptor(plan))
    assert response["ok"], response
    return ext, estimate, plan, response


def setup_geometry(api, tmp_path, rows=None, *, confirm=False):
    ext, estimate, plan, imported = setup_imported(api, tmp_path, rows)
    saved = call(ext, "save_geometry", job_id="audit_1", analysis=analysis())
    assert saved["ok"], saved
    if confirm:
        confirmed = call(
            ext, "confirm_geometry", ctx("task-confirm", "msg-confirm"),
            job_id="audit_1", geometry_revision=saved["geometry_revision"], confirmed=True,
        )
        assert confirmed["ok"], confirmed
        catalog = call(
            ext,
            "save_price_catalog",
            job_id="audit_1",
            catalog_response=price_catalog_response(),
        )
        assert catalog["ok"], catalog
    return ext, estimate, plan, imported, saved


@pytest.fixture
def mvp_api(tmp_path):
    return FakeAPI(tmp_path)
