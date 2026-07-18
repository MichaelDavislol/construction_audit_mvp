from __future__ import annotations

import json
from typing import Any, Callable

from . import core, insights, vision, visual


def _json(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


class ConstructionAuditMVP:
    def __init__(self, api: Any):
        self.api = api

    def _call(self, operation: Callable[[], dict[str, Any]]) -> str:
        try:
            return _json({"ok": True, **operation()})
        except core.AuditError as exc:
            payload: dict[str, Any] = {"ok": False, "code": exc.code, "message": exc.message}
            if exc.details:
                payload["details"] = exc.details
                for key in ("next_action", "assistant_instruction"):
                    if key in exc.details:
                        payload[key] = exc.details[key]
            return _json(payload)
        except Exception as exc:
            # Неожиданная ошибка логируется только по типу. Текст exception или
            # traceback могут содержать локальные пути и не должны уходить в tool result.
            logger = getattr(self.api, "log", None)
            if callable(logger):
                try:
                    logger("error", "construction_audit_mvp tool failed", error=type(exc).__name__)
                except TypeError:
                    logger("error", f"construction_audit_mvp tool failed: {type(exc).__name__}")
            return _json({"ok": False, "code": "internal_error", "message": "Внутренняя ошибка construction_audit_mvp."})

    def create_case(self, ctx: Any, *, job_id: str, object_name: str) -> str:
        def operation() -> dict[str, Any]:
            manifest, _ = core.create_case(self.api, job_id, object_name)
            return {
                "job_id": manifest["job_id"],
                "status": "case_created",
                "next_action": "import_documents",
                "alternative_next_action": "import_plan_if_only_plan_was_attached",
            }

        return self._call(operation)

    def import_documents(self, ctx: Any, *, job_id: str, estimate: dict[str, Any], plan: dict[str, Any]) -> str:
        def operation() -> dict[str, Any]:
            _, result = core.import_documents(self.api, job_id, estimate, plan)
            return {"job_id": job_id, **result}

        return self._call(operation)

    def import_plan(self, ctx: Any, *, job_id: str, plan: dict[str, Any]) -> str:
        def operation() -> dict[str, Any]:
            _, result = core.import_plan(self.api, job_id, plan)
            return {"job_id": job_id, **result}

        return self._call(operation)

    def save_geometry(
        self,
        ctx: Any,
        *,
        job_id: str,
        vision_task_id: str,
        analysis: dict[str, Any],
    ) -> str:
        def operation() -> dict[str, Any]:
            _, result = core.save_geometry(self.api, ctx, job_id, vision_task_id, analysis)
            return {"job_id": job_id, **result}

        return self._call(operation)

    def confirm_geometry(
        self,
        ctx: Any,
        *,
        job_id: str,
        geometry_revision: int,
        confirmed: bool,
        corrections: list[dict[str, Any]] | None = None,
        user_statement: str | None = None,
    ) -> str:
        def operation() -> dict[str, Any]:
            _, changed, result = core.confirm_geometry(
                self.api,
                ctx,
                job_id,
                geometry_revision,
                confirmed,
                corrections,
                user_statement,
            )
            if confirmed is False:
                return {"job_id": job_id, **result}
            return {
                "job_id": job_id,
                "changed": changed,
                **result,
            }

        return self._call(operation)

    def save_price_catalog(
        self,
        ctx: Any,
        *,
        job_id: str,
        catalog_response: dict[str, Any],
    ) -> str:
        def operation() -> dict[str, Any]:
            _, result = core.save_price_catalog(self.api, job_id, catalog_response)
            return {"job_id": job_id, **result}

        return self._call(operation)

    def generate_estimate(self, ctx: Any, *, job_id: str) -> str:
        def operation() -> dict[str, Any]:
            _, result = core.generate_estimate(self.api, job_id)
            return {"job_id": job_id, **result}

        return self._call(operation)

    def render_geometry_review(
        self,
        ctx: Any,
        *,
        job_id: str,
        geometry_revision: int,
    ) -> str:
        return self._call(lambda: {"job_id": job_id, **core.render_geometry_review(
            self.api, job_id, geometry_revision
        )})

    def run_audit(
        self,
        ctx: Any,
        *,
        job_id: str,
        mapping_task_id: str,
        mapping: dict[str, Any],
        tolerance_percent: float = 5,
    ) -> str:
        def operation() -> dict[str, Any]:
            _, result = core.run_audit(
                self.api,
                ctx,
                job_id,
                mapping_task_id,
                mapping,
                tolerance_percent,
            )
            return {"job_id": job_id, **result}

        return self._call(operation)

    def skip_visual_review(self, ctx: Any, *, job_id: str) -> str:
        def operation() -> dict[str, Any]:
            _, result = core.skip_visual_review(self.api, job_id)
            return {"job_id": job_id, **result}

        return self._call(operation)

    def import_site_photos(
        self,
        ctx: Any,
        *,
        job_id: str,
        archive: dict[str, Any],
    ) -> str:
        def operation() -> dict[str, Any]:
            _, result = core.import_site_photos(self.api, job_id, archive)
            return {"job_id": job_id, **result}

        return self._call(operation)

    def save_visual_analysis(
        self,
        ctx: Any,
        *,
        job_id: str,
        photo_id: str,
        photo_task_id: str,
        analysis: dict[str, Any] | str,
    ) -> str:
        def operation() -> dict[str, Any]:
            _, result = core.save_visual_analysis(
                self.api, ctx, job_id, photo_id, photo_task_id, analysis
            )
            return {"job_id": job_id, **result}

        return self._call(operation)

    def render_audit_summary(self, ctx: Any, *, job_id: str) -> str:
        return self._call(lambda: {"job_id": job_id, **core.render_audit_summary(self.api, job_id)})

    def finalize_audit(
        self,
        ctx: Any,
        *,
        job_id: str,
        insights_task_id: str,
        llm_insights: dict[str, Any] | str,
    ) -> str:
        def operation() -> dict[str, Any]:
            _, result = core.finalize_audit(
                self.api, ctx, job_id, insights_task_id, llm_insights
            )
            return {"job_id": job_id, **result}

        return self._call(operation)


def _object(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def _object_or_json_string(object_schema: dict[str, Any]) -> dict[str, Any]:
    return {
        "anyOf": [
            object_schema,
            {
                "type": "string",
                "minLength": 2,
                "maxLength": core.MAX_SUBAGENT_JSON_CHARS,
            },
        ]
    }


def _measurement(maximum: float) -> dict[str, Any]:
    return _object(
        {
            "value": {
                "anyOf": [
                    {"type": "number", "exclusiveMinimum": 0, "maximum": maximum},
                    {"type": "null"},
                ]
            },
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "source_type": {"type": "string", "enum": sorted(vision.SOURCE_TYPES)},
            "evidence_text": {"type": "string", "maxLength": 500},
        },
        ["value", "confidence", "source_type", "evidence_text"],
    )


def _analysis_schema() -> dict[str, Any]:
    opening = _object(
        {
            "element_id": {"type": "string", "minLength": 1, "maxLength": 200},
            "width_m": _measurement(100),
            "height_m": _measurement(100),
        },
        ["element_id", "width_m", "height_m"],
    )
    room = _object(
        {
            "source_room_id": {"type": "string", "minLength": 1, "maxLength": 200},
            "name": {"type": "string", "minLength": 1, "maxLength": 200},
            "floor_area_m2": _measurement(100000),
            "length_m": _measurement(10000),
            "width_m": _measurement(10000),
            "perimeter_m": _measurement(10000),
            "height_m": _measurement(100),
            "doors": {"type": "array", "maxItems": 100, "items": opening},
            "windows": {"type": "array", "maxItems": 100, "items": opening},
            "warnings": {
                "type": "array",
                "maxItems": 100,
                "items": {"type": "string", "maxLength": 1000},
            },
        },
        [
            "source_room_id",
            "name",
            "floor_area_m2",
            "length_m",
            "width_m",
            "perimeter_m",
            "height_m",
            "doors",
            "windows",
            "warnings",
        ],
    )
    return _object(
        {
            "schema_version": {"type": "integer", "enum": [1]},
            "plan_id": {"type": "string", "enum": [vision.PLAN_ID]},
            "image_quality": _object(
                {
                    "usable": {"type": "boolean"},
                    "issues": {
                        "type": "array",
                        "maxItems": 100,
                        "items": {"type": "string", "maxLength": 1000},
                    },
                },
                ["usable", "issues"],
            ),
            "object_name_suggestion": {
                "anyOf": [{"type": "string", "maxLength": 200}, {"type": "null"}]
            },
            "rooms": {"type": "array", "minItems": 1, "maxItems": 200, "items": room},
            "general_warnings": {
                "type": "array",
                "maxItems": 200,
                "items": {"type": "string", "maxLength": 1000},
            },
        },
        [
            "schema_version",
            "plan_id",
            "image_quality",
            "object_name_suggestion",
            "rooms",
            "general_warnings",
        ],
    )


def _geometry_correction_schema() -> dict[str, Any]:
    selector = {
        "anyOf": [
            {"type": "string", "enum": ["all"]},
            {
                "type": "array",
                "minItems": 1,
                "maxItems": 200,
                "uniqueItems": True,
                "items": {"type": "string", "minLength": 1, "maxLength": 200},
            },
        ]
    }
    return _object(
        {
            "target": {"type": "string", "enum": ["rooms", "doors", "windows"]},
            "room_ids": selector,
            "element_ids": selector,
            "field": {
                "type": "string",
                "enum": sorted({*vision.MEASUREMENT_LIMITS, "width_m", "height_m"}),
            },
            "value": {
                "anyOf": [
                    {"type": "number", "exclusiveMinimum": 0, "maximum": 100000},
                    {"type": "null"},
                ]
            },
        },
        ["target", "room_ids", "element_ids", "field", "value"],
    )


def _mapping_schema() -> dict[str, Any]:
    confidence = {"type": "number", "minimum": 0, "maximum": 1}
    text = {"type": "string", "minLength": 1, "maxLength": 1000}
    short_text = {"type": "string", "minLength": 1, "maxLength": 200}
    source_row = {"type": "integer", "minimum": 2, "maximum": 1048576}
    room_match = _object(
        {
            "estimate_room": short_text,
            "model_room_id": {
                "anyOf": [
                    {"type": "string", "pattern": "^room_[0-9]{3}$"},
                    {"type": "null"},
                ]
            },
            "confidence": confidence,
            "reason": text,
        },
        ["estimate_room", "model_room_id", "confidence", "reason"],
    )
    room_unresolved = _object(
        {
            "estimate_room": short_text,
            "candidate_room_ids": {
                "type": "array",
                "uniqueItems": True,
                "items": {"type": "string", "pattern": "^room_[0-9]{3}$"},
            },
            "reason": text,
            "requires_human_confirmation": {"type": "boolean"},
        },
        ["estimate_room", "candidate_room_ids", "reason", "requires_human_confirmation"],
    )
    work_match = _object(
        {
            "source_row": source_row,
            "estimate_work": short_text,
            "canonical_work": {"type": "string", "enum": sorted(core.SUPPORTED_WORKS)},
            "confidence": confidence,
            "reason": text,
        },
        ["source_row", "estimate_work", "canonical_work", "confidence", "reason"],
    )
    unsupported = _object(
        {"source_row": source_row, "estimate_work": short_text, "reason": text},
        ["source_row", "estimate_work", "reason"],
    )
    work_unresolved = _object(
        {
            "source_row": source_row,
            "estimate_work": short_text,
            "candidate_canonical_works": {
                "type": "array",
                "uniqueItems": True,
                "items": {"type": "string", "enum": sorted(core.SUPPORTED_WORKS)},
            },
            "reason": text,
            "requires_human_confirmation": {"type": "boolean"},
        },
        [
            "source_row",
            "estimate_work",
            "candidate_canonical_works",
            "reason",
            "requires_human_confirmation",
        ],
    )
    price_match = _object(
        {
            "source_row": source_row,
            "estimate_work": short_text,
            "mcp_work_id": short_text,
            "confidence": confidence,
            "reason": text,
        },
        ["source_row", "estimate_work", "mcp_work_id", "confidence", "reason"],
    )
    price_unresolved = _object(
        {
            "source_row": source_row,
            "estimate_work": short_text,
            "candidate_mcp_work_ids": {
                "type": "array",
                "uniqueItems": True,
                "items": short_text,
            },
            "reason": text,
            "requires_human_confirmation": {"type": "boolean"},
        },
        [
            "source_row",
            "estimate_work",
            "candidate_mcp_work_ids",
            "reason",
            "requires_human_confirmation",
        ],
    )
    return _object(
        {
            "schema_version": {"type": "integer", "enum": [3]},
            "delegation_token": {
                "type": "string",
                "minLength": 32,
                "maxLength": 128,
                "pattern": "^[A-Za-z0-9_-]+$",
            },
            "room_matches": {"type": "array", "maxItems": 500, "items": room_match},
            "room_unresolved": {"type": "array", "maxItems": 500, "items": room_unresolved},
            "work_matches": {"type": "array", "maxItems": 500, "items": work_match},
            "work_unsupported": {"type": "array", "maxItems": 500, "items": unsupported},
            "work_unresolved": {"type": "array", "maxItems": 500, "items": work_unresolved},
            "price_matches": {"type": "array", "maxItems": 500, "items": price_match},
            "price_unsupported": {"type": "array", "maxItems": 500, "items": unsupported},
            "price_unresolved": {"type": "array", "maxItems": 500, "items": price_unresolved},
        },
        [
            "schema_version",
            "delegation_token",
            "room_matches",
            "room_unresolved",
            "work_matches",
            "work_unsupported",
            "work_unresolved",
            "price_matches",
            "price_unsupported",
            "price_unresolved",
        ],
    )


def _price_catalog_response_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "result": {
                "type": "array",
                "maxItems": core.PRICE_CATALOG_MAX_ITEMS,
                "items": {"type": "object", "additionalProperties": True},
            },
            "runtime_text_projection": {
                "type": "string", "minLength": 2, "maxLength": 2000000,
            },
        },
        "required": ["result"],
        "additionalProperties": True,
    }


def _llm_insights_schema() -> dict[str, Any]:
    evidence_ref = _object(
        {
            "type": {"type": "string", "enum": sorted(insights.EVIDENCE_TYPES)},
            "value": {
                "anyOf": [
                    {"type": "string", "minLength": 1, "maxLength": 200},
                    {"type": "integer", "minimum": 2, "maximum": 1048576},
                ]
            },
        },
        ["type", "value"],
    )
    item = _object(
        {
            "insight_id": {"type": "string", "pattern": "^insight_[0-9]{3}$"},
            "category": {"type": "string", "enum": sorted(insights.CATEGORIES)},
            "title": {"type": "string", "minLength": 1, "maxLength": 200},
            "observation": {"type": "string", "minLength": 1, "maxLength": 2000},
            "hypothesis": {"type": "string", "minLength": 1, "maxLength": 2000},
            "evidence_refs": {
                "type": "array", "minItems": 1, "maxItems": 20, "items": evidence_ref,
            },
            "confidence": {"type": "string", "enum": sorted(insights.CONFIDENCE_LEVELS)},
            "recommended_check": {"type": "string", "minLength": 1, "maxLength": 2000},
            "limitations": {"type": "string", "minLength": 1, "maxLength": 2000},
        },
        [
            "insight_id", "category", "title", "observation", "hypothesis",
            "evidence_refs", "confidence", "recommended_check", "limitations",
        ],
    )
    return _object(
        {
            "schema_version": {"type": "integer", "enum": [insights.SCHEMA_VERSION]},
            "status": {
                "type": "string", "enum": ["generated", "no_useful_observations"],
            },
            "summary": {"type": "string", "minLength": 1, "maxLength": 2000},
            "items": {"type": "array", "maxItems": insights.MAX_ITEMS, "items": item},
        },
        ["schema_version", "status", "summary", "items"],
    )


def _visual_analysis_schema() -> dict[str, Any]:
    item = _object(
        {
            "visual_insight_id": {
                "type": "string", "pattern": "^photo_[0-9]{3}_insight_[0-9]{3}$",
            },
            "category": {"type": "string", "enum": sorted(visual.ACCEPTED_INSIGHT_CATEGORIES)},
            "estimate_work": {
                "anyOf": [
                    {"type": "string", "enum": sorted(core.SUPPORTED_WORKS)},
                    {"type": "null"},
                ]
            },
            "source_rows": {
                "type": "array", "uniqueItems": True,
                "items": {"type": "integer", "minimum": 2, "maximum": 1048576},
            },
            "status": {"type": "string", "enum": sorted(visual.ACCEPTED_INSIGHT_STATUSES)},
            "title": {"type": "string", "minLength": 1, "maxLength": 200},
            "observation": {"type": "string", "minLength": 1, "maxLength": 1500},
            "evidence_text": {"type": "string", "minLength": 1, "maxLength": 1000},
            "confidence": {"type": "string", "enum": sorted(visual.CONFIDENCE_LEVELS)},
            "auditor_check": {"type": "string", "minLength": 1, "maxLength": 1000},
            "limitations": {"type": "string", "minLength": 1, "maxLength": 1000},
        },
        [
            "visual_insight_id", "category", "estimate_work", "status",
            "title", "observation", "evidence_text", "confidence", "auditor_check", "limitations",
        ],
    )
    return _object(
        {
            "schema_version": {"type": "integer", "enum": [visual.SCHEMA_VERSION]},
            "photo_id": {"type": "string", "pattern": "^photo_[0-9]{3}$"},
            "delegation_token": {
                "type": "string", "minLength": 32, "maxLength": 128,
                "pattern": "^[A-Za-z0-9_-]+$",
            },
            "image_quality": _object(
                {
                    "usable": {"type": "boolean"},
                    "issues": {
                        "type": "array", "maxItems": 20,
                        "items": {"type": "string", "minLength": 1, "maxLength": 500},
                    },
                },
                ["usable", "issues"],
            ),
            "scene_summary": {"type": "string", "minLength": 1, "maxLength": 1000},
            "visual_insights": {
                "type": "array", "maxItems": visual.MAX_INSIGHTS_PER_PHOTO, "items": item,
            },
            "limitations": {
                "type": "array", "maxItems": 20,
                "items": {"type": "string", "minLength": 1, "maxLength": 500},
            },
        },
        [
            "schema_version", "photo_id", "delegation_token", "image_quality",
            "scene_summary", "visual_insights", "limitations",
        ],
    )


def register(api: Any) -> None:
    extension = ConstructionAuditMVP(api)
    job = {"job_id": {"type": "string", "pattern": "^[A-Za-z0-9_-]{1,64}$"}}
    attachment = _object(
        {
            "attachment_root": {"type": "string", "enum": ["artifact_store"]},
            "attachment_relpath": {"type": "string", "pattern": "^attachments/[^/\\\\]+$", "maxLength": 300},
            "attachment_path": {"type": "string", "minLength": 1, "maxLength": 4096},
        },
        ["attachment_root", "attachment_relpath", "attachment_path"],
    )
    registrations = [
        (
            "create_case",
            "Создаёт изолированный MVP-кейс. Для XLSX + плана вызвать import_documents; если приложен только план — import_plan.",
            _object({**job, "object_name": {"type": "string", "minLength": 1, "maxLength": 200}}, ["job_id", "object_name"]),
            extension.create_case,
        ),
        (
            "import_documents",
            "Импортирует XLSX и план. После успеха ЕДИНСТВЕННОЕ допустимое действие — вызвать schedule_subagent с vision_delegation строго 1:1, затем wait_task. Основному агенту запрещено самому анализировать план или сразу вызывать save_geometry.",
            _object({**job, "estimate": attachment, "plan": attachment}, ["job_id", "estimate", "plan"]),
            extension.import_documents,
        ),
        (
            "import_plan",
            "Изолированная plan-only ветка: импортирует один план без XLSX. После успеха ЕДИНСТВЕННОЕ допустимое действие — вызвать schedule_subagent с vision_delegation строго 1:1, затем wait_task.",
            _object({**job, "plan": attachment}, ["job_id", "plan"]),
            extension.import_plan,
        ),
        (
            "save_geometry",
            "ТОЛЬКО валидирует JSON из успешного wait_task отдельного Vision-субагента: analysis нельзя создавать или исправлять основному агенту, vision_task_id обязан быть ID дочерней задачи. Tool намеренно не возвращает review_markdown. До [SYSTEM REMINDER]/[SUBAGENT_RESULTS] выполнить no-tool handoff-барьер строго по assistant_instruction; после reminder обязательно вызвать render_geometry_review.",
            _object(
                {
                    **job,
                    "vision_task_id": {"type": "string", "minLength": 1, "maxLength": 200},
                    "analysis": _analysis_schema(),
                },
                ["job_id", "vision_task_id", "analysis"],
            ),
            extension.save_geometry,
        ),
        (
            "confirm_geometry",
            "Первое public-tool действие отдельного нового хода после geometry review. При confirmed=true подтверждает текущую revision; следующим действием обязательно вызвать внешний mcp_construction_prices__get_supported_works. При явной пользовательской правке вызвать с confirmed=false, дословным user_statement и детерминированными corrections: tool изменит только выбранные измерения, создаст следующую revision и потребует новый review. Для всех помещений/элементов использовать селектор 'all'. Не запускать Vision, create_case или import_documents для исправлений.",
            _object(
                {
                    **job,
                    "geometry_revision": {"type": "integer", "minimum": 1},
                    "confirmed": {"type": "boolean"},
                    "corrections": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": core.GEOMETRY_CORRECTION_MAX_ITEMS,
                        "items": _geometry_correction_schema(),
                    },
                    "user_statement": {"type": "string", "minLength": 1, "maxLength": 1000},
                },
                ["job_id", "geometry_revision", "confirmed"],
            ),
            extension.confirm_geometry,
        ),
        (
            "save_price_catalog",
            "Принимает object-wrapper успешного mcp_construction_prices__get_supported_works либо его текстовую projection от runtime. Для старой ветки XLSX + план возвращает Mapping как прежде. Для plan-only возвращает предложение генерации сметы и требует дождаться явного согласия пользователя.",
            _object(
                {
                    **job,
                    "catalog_response": _price_catalog_response_schema(),
                },
                ["job_id", "catalog_response"],
            ),
            extension.save_price_catalog,
        ),
        (
            "generate_estimate",
            "Вызывать только после явного согласия пользователя сформировать смету. Детерминированно создаёт XLSX из текущей подтверждённой geometry и сохранённых цен MCP; не использовать LLM для количества, цены или стоимости.",
            _object(job, ["job_id"]),
            extension.generate_estimate,
        ),
        (
            "render_geometry_review",
            "Для исходной Vision-ветки ОБЯЗАТЕЛЬНО вызвать после [SYSTEM REMINDER]/[SUBAGENT_RESULTS], даже если review был в предыдущем assistant draft. Для детерминированной пользовательской correction вызвать сразу с новой revision: субагента и handoff-барьера в этой ветке нет. Затем вывести review_markdown полностью; никогда не писать «показано выше».",
            _object(
                {
                    **job,
                    "geometry_revision": {"type": "integer", "minimum": 1},
                },
                ["job_id", "geometry_revision"],
            ),
            extension.render_geometry_review,
        ),
        (
            "run_audit",
            "Выполняет независимые детерминированные проверки объёмов и стоимости и останавливается на обязательном предложении приложить ZIP с не более чем 5 фотографиями либо явно продолжить без фото. HTML и llm_insights_delegation на этом этапе не создаются.",
            _object(
                {
                    **job,
                    "mapping_task_id": {"type": "string", "minLength": 1, "maxLength": 200},
                    "mapping": _mapping_schema(),
                    "tolerance_percent": {
                        "type": "number",
                        "minimum": 0,
                        "maximum": 100,
                        "default": 5,
                    },
                },
                ["job_id", "mapping_task_id", "mapping"],
            ),
            extension.run_audit,
        ),
        (
            "skip_visual_review",
            "Вызывать только после отдельного явного ответа пользователя «без фото». Сохраняет факт пропуска visual review и возвращает обязательный llm_insights_delegation.",
            _object(job, ["job_id"]),
            extension.skip_visual_review,
        ),
        (
            "import_site_photos",
            "Импортирует один staged ZIP с 1–5 PNG/JPG/JPEG после run_audit. Возвращает компактный immutable schedule_subagent packet для каждой фотографии. Фото не привязываются к помещениям; source_rows обозначают только строки соответствующей работы в смете.",
            _object({**job, "archive": attachment}, ["job_id", "archive"]),
            extension.import_site_photos,
        ),
        (
            "save_visual_analysis",
            "Валидирует JSON одного фото Vision-субагента. Предпочтительно передать точную JSON-строку между runtime-маркерами без json.loads и повторной сборки; structured object остаётся допустимым для совместимости. Также принимается полный неизменённый wait_task envelope с точным FINAL ANSWER. Каждая различимая поддерживаемая работа сохраняется отдельным insight с её source_rows, без привязки к помещению. После последнего фото возвращает обязательный llm_insights_delegation.",
            _object(
                {
                    **job,
                    "photo_id": {"type": "string", "pattern": "^photo_[0-9]{3}$"},
                    "photo_task_id": {"type": "string", "pattern": "^[0-9a-f]{8}$"},
                    "analysis": _object_or_json_string(_visual_analysis_schema()),
                },
                ["job_id", "photo_id", "photo_task_id", "analysis"],
            ),
            extension.save_visual_analysis,
        ),
        (
            "finalize_audit",
            "ТОЛЬКО валидирует JSON из успешного wait_task отдельного аналитического субагента. Предпочтительно передать точную JSON-строку между runtime-маркерами без json.loads и повторной сборки; structured object остаётся допустимым для совместимости. Также принимается полный неизменённый wait_task envelope с точным FINAL ANSWER. Сохраняет гипотезы отдельно от deterministic findings и создаёт итоговый HTML. llm_insights нельзя создавать или исправлять основному агенту.",
            _object(
                {
                    **job,
                    "insights_task_id": {"type": "string", "minLength": 1, "maxLength": 200},
                    "llm_insights": _object_or_json_string(_llm_insights_schema()),
                },
                ["job_id", "insights_task_id", "llm_insights"],
            ),
            extension.finalize_audit,
        ),
        (
            "render_audit_summary",
            "Возобновляет сохранённый llm_insights_required после прерванного хода либо, после завершения, ОБЯЗАТЕЛЬНО повторно возвращает итог после ЛЮБОГО [SYSTEM REMINDER]/[SUBAGENT_RESULTS]. При llm_insights_required запустить возвращённый packet строго 1:1; при audit_completed вывести только audit_summary_markdown полностью.",
            _object(job, ["job_id"]),
            extension.render_audit_summary,
        ),
    ]
    for name, description, schema, handler in registrations:
        api.register_tool(
            name,
            handler=handler,
            description=description,
            schema=schema,
            timeout_sec=30,
        )
