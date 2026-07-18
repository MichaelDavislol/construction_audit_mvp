"""Публичный набор tools — это контракт с runtime, поэтому проверяем его отдельно."""

import inspect

from construction_audit_mvp import plugin
from _mvp_fixtures import FakeAPI


EXPECTED = {
    "create_case",
    "import_documents",
    "import_plan",
    "save_geometry",
    "confirm_geometry",
    "save_price_catalog",
    "generate_estimate",
    "render_geometry_review",
    "run_audit",
    "skip_visual_review",
    "import_site_photos",
    "save_visual_analysis",
    "finalize_audit",
    "render_audit_summary",
}


def test_registers_exactly_fourteen_tools(tmp_path):
    api = FakeAPI(tmp_path)
    plugin.register(api)
    assert set(api.tools) == EXPECTED
    assert len(api.tools) == 14


def test_short_names_and_strict_root_schemas(tmp_path):
    api = FakeAPI(tmp_path)
    plugin.register(api)
    assert all(len(name) <= 24 for name in api.tools)
    assert all(item["schema"]["additionalProperties"] is False for item in api.tools.values())


def test_save_geometry_uses_nested_object_not_analysis_json(tmp_path):
    api = FakeAPI(tmp_path)
    plugin.register(api)
    properties = api.tools["save_geometry"]["schema"]["properties"]
    assert properties["analysis"]["type"] == "object"
    assert "analysis_json" not in properties


def test_payload_and_trace_arguments_are_required_by_public_schemas(tmp_path):
    api = FakeAPI(tmp_path)
    plugin.register(api)
    assert set(api.tools["save_geometry"]["schema"]["required"]) == {
        "job_id", "vision_task_id", "analysis",
    }
    assert set(api.tools["run_audit"]["schema"]["required"]) == {
        "job_id", "mapping_task_id", "mapping",
    }


def test_run_audit_uses_profile_mapping_schema(tmp_path):
    api = FakeAPI(tmp_path)
    plugin.register(api)
    mapping_schema = api.tools["run_audit"]["schema"]["properties"]["mapping"]
    assert mapping_schema["type"] == "object"
    assert set(mapping_schema["required"]) == {
        "schema_version", "delegation_token", "room_matches", "room_unresolved", "work_matches",
        "work_unsupported", "work_unresolved", "price_matches", "price_unsupported",
        "price_unresolved",
    }
    assert mapping_schema["properties"]["schema_version"]["enum"] == [3]
    assert set(mapping_schema["properties"]["work_matches"]["items"]["required"]) == {
        "source_row", "estimate_work", "canonical_work", "confidence", "reason",
    }
    assert set(mapping_schema["properties"]["price_matches"]["items"]["required"]) == {
        "source_row", "estimate_work", "mcp_work_id", "confidence", "reason",
    }


def test_finalize_audit_uses_structured_insights_schema(tmp_path):
    api = FakeAPI(tmp_path)
    plugin.register(api)
    schema = api.tools["finalize_audit"]["schema"]
    assert set(schema["required"]) == {"job_id", "insights_task_id", "llm_insights"}
    insights = schema["properties"]["llm_insights"]
    structured, serialized = insights["anyOf"]
    assert structured["additionalProperties"] is False
    assert structured["properties"]["status"]["enum"] == ["generated", "no_useful_observations"]
    assert serialized == {
        "type": "string", "minLength": 2, "maxLength": plugin.core.MAX_SUBAGENT_JSON_CHARS,
    }


def test_visual_analysis_schema_accepts_structured_or_serialized_json(tmp_path):
    api = FakeAPI(tmp_path)
    plugin.register(api)
    analysis = api.tools["save_visual_analysis"]["schema"]["properties"]["analysis"]
    structured, serialized = analysis["anyOf"]
    assert structured["additionalProperties"] is False
    assert structured["properties"]["photo_id"]["pattern"] == "^photo_[0-9]{3}$"
    assert serialized["type"] == "string"


def test_price_catalog_schema_preserves_mcp_result_wrapper(tmp_path):
    api = FakeAPI(tmp_path)
    plugin.register(api)
    schema = api.tools["save_price_catalog"]["schema"]["properties"]["catalog_response"]
    assert schema["type"] == "object"
    assert schema["required"] == ["result"]
    assert schema["properties"]["result"]["type"] == "array"
    assert schema["properties"]["result"]["items"]["additionalProperties"] is True


def test_handlers_request_ctx_first(tmp_path):
    api = FakeAPI(tmp_path)
    plugin.register(api)
    for item in api.tools.values():
        assert next(iter(inspect.signature(item["handler"]).parameters)) == "ctx"
