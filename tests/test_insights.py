"""Здесь проверяем, что аналитик рассуждает по фактам, а не по служебным полям."""

from __future__ import annotations

import unittest

from construction_audit_mvp import insights


def context() -> dict:
    return {
        "deterministic_findings": [{"finding_id": "finding_001"}],
        "estimate_rows": [{"source_row": 2}],
        "geometry": {"rooms": [{"room_id": "room_001"}]},
        "relevant_calculation_trace": [{"trace_id": "trace_001"}],
        "price_checks": [{"source_row": 2}],
        "coverage": {"checked_rows": 18, "not_checked_rows": 0},
        "price_summary": {
            "checked": 18,
            "partially_checked": 0,
            "not_checked": 0,
            "deviations": 0,
        },
        "context_limits": {
            "findings_total": 10,
            "findings_included": 9,
            "price_checks_total": 18,
            "price_checks_included": 10,
        },
    }


def insight_item(**overrides: object) -> dict:
    item = {
        "insight_id": "insight_001",
        "category": "systemic_pattern",
        "title": "Связанное наблюдение",
        "observation": "Несколько фактов образуют общий паттерн.",
        "hypothesis": "Возможна общая проверяемая причина.",
        "evidence_refs": [{"type": "finding", "value": "finding_001"}],
        "confidence": "medium",
        "recommended_check": "Проверить первичные данные.",
        "limitations": "Доступных фактов недостаточно для подтверждения.",
    }
    item.update(overrides)
    return item


class InsightsTests(unittest.TestCase):
    def test_delegation_explains_enums_and_transport_sampling(self) -> None:
        packet = insights.delegation(context())
        constraints = packet["constraints"]
        self.assertIn("context_limits описывает только объём сэмпла", constraints)
        self.assertIn("quantity_check_scope=object_total_unique_doors", constraints)
        self.assertIn("allocation_status=estimate_declared", constraints)
        self.assertIn("пользовательским текстом", constraints)
        self.assertIn("Технические ID возвращай только внутри evidence_refs", constraints)
        for category in insights.CATEGORIES:
            self.assertIn(category, constraints)
        for evidence_type in insights.EVIDENCE_TYPES:
            self.assertIn(evidence_type, constraints)

    def test_retry_delegation_includes_validation_errors(self) -> None:
        errors = [{"path": "items[0].category", "reason": "unsupported category"}]
        packet = insights.delegation(context(), validation_errors=errors)
        self.assertIn("Предыдущий ответ не прошёл schema validation", packet["constraints"])
        self.assertIn("items[0].category", packet["constraints"])

    def test_visual_delegation_example_and_constraints_do_not_link_rooms(self) -> None:
        visual_context = context()
        visual_context["visual_insights"] = {
            "status": "generated",
            "items": [{"visual_insight_id": "photo_001_insight_001"}],
        }

        packet = insights.delegation(visual_context)
        self.assertIn("запрещён evidence_ref типа room", packet["constraints"])
        self.assertIn("Finding с помещением не устанавливает место съёмки", packet["constraints"])
        self.assertIn('"type":"visual_insight"', packet["expected_output"])
        self.assertNotIn('"type":"room"', packet["expected_output"])

    def test_validation_rejects_transport_sampling_as_audit_insight(self) -> None:
        payload = {
            "schema_version": 1,
            "status": "generated",
            "summary": "Найдено наблюдение.",
            "items": [
                insight_item(
                    title="Ценовая проверка не покрыта",
                    observation="Переданный контекст содержит не все price_checks.",
                )
            ],
        }
        with self.assertRaises(insights.InsightsValidationError) as raised:
            insights.validate(payload, context())
        self.assertTrue(any("transport sampling" in error["reason"] for error in raised.exception.errors))

    def test_validation_rejects_unknown_category_and_evidence_type(self) -> None:
        payload = {
            "schema_version": 1,
            "status": "generated",
            "summary": "Найдено наблюдение.",
            "items": [
                insight_item(
                    category="coverage_limitation",
                    evidence_refs=[{"type": "context_limits", "value": "price_checks_included=10/18"}],
                )
            ],
        }
        with self.assertRaises(insights.InsightsValidationError) as raised:
            insights.validate(payload, context())
        reasons = {error["reason"] for error in raised.exception.errors}
        self.assertIn("unsupported category", reasons)
        self.assertIn("unsupported evidence type", reasons)

    def test_validation_accepts_domain_insight(self) -> None:
        payload = {
            "schema_version": 1,
            "status": "generated",
            "summary": "Найдено наблюдение.",
            "items": [insight_item()],
        }
        self.assertEqual("generated", insights.validate(payload, context())["status"])

    def test_validation_rejects_internal_schema_language_in_user_text(self) -> None:
        payload = {
            "schema_version": 1,
            "status": "generated",
            "summary": "Найдена дополнительная гипотеза.",
            "items": [
                insight_item(
                    observation=(
                        "control_value finding_001 совпадает с estimated_value, "
                        "а status=checked."
                    ),
                    recommended_check="Проверить calculation_trace для source_row 2.",
                )
            ],
        }
        with self.assertRaises(insights.InsightsValidationError) as raised:
            insights.validate(payload, context())
        paths = {error["path"] for error in raised.exception.errors}
        self.assertIn("items[0].observation", paths)
        self.assertIn("items[0].recommended_check", paths)

    def test_validation_rejects_internal_schema_language_in_summary(self) -> None:
        payload = {
            "schema_version": 1,
            "status": "generated",
            "summary": "Несколько findings относятся к room_001.",
            "items": [insight_item()],
        }
        with self.assertRaises(insights.InsightsValidationError) as raised:
            insights.validate(payload, context())
        self.assertTrue(any(error["path"] == "summary" for error in raised.exception.errors))

    def test_validation_rejects_unsupported_operational_cause(self) -> None:
        payload = {
            "schema_version": 1,
            "status": "generated",
            "summary": "Найдено наблюдение.",
            "items": [insight_item(hypothesis="Цена задана вручную без сверки.")],
        }
        with self.assertRaises(insights.InsightsValidationError) as raised:
            insights.validate(payload, context())
        self.assertTrue(any("intent claim" in error["reason"] for error in raised.exception.errors))


if __name__ == "__main__":
    unittest.main()
