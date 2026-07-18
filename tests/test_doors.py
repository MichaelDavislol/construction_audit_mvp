"""Двери считаются необычно, поэтому держим их правила в одном заметном месте."""

from __future__ import annotations

import unittest

from construction_audit_mvp import core, report


def estimate(quantities: tuple[str, str]) -> dict:
    return {
        "rows": [
            {
                "source_row": 2,
                "room": "Кухня",
                "work_name": "Установка дверей",
                "unit": "шт.",
                "quantity": quantities[0],
                "price": "7000",
                "total": "7000",
                "issues": [],
            },
            {
                "source_row": 3,
                "room": "Коридор",
                "work_name": "Установка дверей",
                "unit": "шт",
                "quantity": quantities[1],
                "price": "7000",
                "total": "7000",
                "issues": [],
            },
        ],
        "warnings": [],
    }


def geometry() -> dict:
    door_1 = {"element_id": "Д-1", "width_m": "0.9", "height_m": "2.1"}
    return {
        "rooms": [
            {
                "room_id": "room_001",
                "name": "Кухня",
                "floor_area_m2": "10",
                "perimeter_m": "14",
                "height_m": "3",
                "doors": [dict(door_1)],
                "windows": [],
            },
            {
                "room_id": "room_002",
                "name": "Коридор",
                "floor_area_m2": "8",
                "perimeter_m": "12",
                "height_m": "3",
                "doors": [
                    dict(door_1),
                    {"element_id": "Д-2", "width_m": "0.9", "height_m": "2.1"},
                ],
                "windows": [],
            },
        ]
    }


def mapping() -> dict:
    return {
        "room_matches": [
            {"estimate_room": "Кухня", "model_room_id": "room_001"},
            {"estimate_room": "Коридор", "model_room_id": "room_002"},
        ],
        "work_matches": [
            {"source_row": 2, "canonical_work": "Установка дверей"},
            {"source_row": 3, "canonical_work": "Установка дверей"},
        ],
        "work_unsupported": [],
    }


class DoorAuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.geometry = geometry()
        self.quantities, self.trace, self.warnings = core.calculate_quantities(self.geometry)

    def run_checks(self, quantities: tuple[str, str]):
        return core.run_checks(
            estimate(quantities),
            self.geometry,
            mapping(),
            self.quantities,
            self.trace,
            core.Decimal("5"),
        )

    def test_shared_door_affects_each_room_but_is_unique_for_object(self) -> None:
        # Для стен дверь нужна в обеих комнатах, но покупать две одинаковые двери не надо.
        by_room = {item["room_id"]: item["metrics"] for item in self.quantities["rooms"]}
        self.assertEqual("1", by_room["room_001"]["door_count"])
        self.assertEqual("2", by_room["room_002"]["door_count"])
        self.assertEqual("2", self.quantities["object_totals"]["door_count"])
        self.assertEqual("40.11", by_room["room_001"]["net_wall_area_m2"])
        self.assertEqual("32.22", by_room["room_002"]["net_wall_area_m2"])
        self.assertEqual("13.10", by_room["room_001"]["baseboard_length_m"])
        self.assertEqual("10.20", by_room["room_002"]["baseboard_length_m"])

    def test_room_allocation_is_not_compared_when_object_total_matches(self) -> None:
        findings, _, checked_rows, not_checked_rows = self.run_checks(("1", "1"))
        self.assertEqual([], findings)
        self.assertEqual([], not_checked_rows)
        self.assertEqual({2, 3}, {item["source_row"] for item in checked_rows})
        self.assertTrue(
            all(item["quantity_check_scope"] == core.DOOR_QUANTITY_SCOPE for item in checked_rows)
        )
        self.assertTrue(
            all(item["allocation_status"] == core.ESTIMATE_DECLARED_ALLOCATION for item in checked_rows)
        )

    def test_object_total_mismatch_creates_one_finding_for_all_door_rows(self) -> None:
        findings, _, checked_rows, _ = self.run_checks(("1", "2"))
        self.assertEqual(1, len(findings))
        finding = findings[0]
        self.assertEqual("Весь объект", finding["canonical_room_name"])
        self.assertEqual([2, 3], finding["source_rows"])
        self.assertEqual("3", finding["estimated_value"])
        self.assertEqual("2", finding["control_value"])
        self.assertEqual(core.DOOR_QUANTITY_SCOPE, finding["quantity_check_scope"])
        self.assertEqual("Все помещения (по смете)", finding["original_room_name"])
        self.assertIn("По строкам 2, 3", finding["safe_summary"])
        summary = core.audit_summary(
            estimate(("1", "2")), findings, [], checked_rows, [], []
        )
        self.assertEqual("3", summary["door_installation_estimate_total"])
        self.assertEqual("2", summary["door_installation_unique_plan_total"])

    def test_vision_packet_requires_shared_boundary_door_in_both_rooms(self) -> None:
        packet = core.vision_delegation("plan_001", "/tmp/plan.jpg")
        self.assertIn("обязательно включи её в doors обоих помещений", packet["constraints"])
        self.assertIn("Не определяй по плану, к какой комнате дверь отнесена в смете", packet["constraints"])

    def test_shared_door_with_conflicting_dimensions_is_blocked(self) -> None:
        invalid = geometry()
        invalid["rooms"][1]["doors"][0]["width_m"] = "0.8"
        with self.assertRaises(core.AuditError) as raised:
            core._require_consistent_shared_doors(invalid)
        self.assertEqual("shared_door_dimension_conflict", raised.exception.code)

    def test_report_explains_estimate_declared_allocation(self) -> None:
        findings, _, checked_rows, _ = self.run_checks(("1", "2"))
        summary = core.audit_summary(
            estimate(("1", "2")), findings, [], checked_rows, [], []
        )
        html = report.build_report(
            {
                "manifest": {"object_name": "Тест", "audit_status": "completed"},
                "estimate": estimate(("1", "2")),
                "geometry": {**self.geometry, "missing_fields": []},
                "mapping": {
                    **mapping(),
                    "price_matches": [],
                    "room_unresolved": [],
                    "work_unresolved": [],
                    "price_unresolved": [],
                    "price_unsupported": [],
                },
                "quantities": self.quantities,
                "calculation_trace": self.trace,
                "findings": findings,
                "warnings": [],
                "checked_rows": checked_rows,
                "not_checked_rows": [],
                "price_catalog": {"items": []},
                "price_checks": [],
                "summary": summary,
                "llm_insights": {
                    "status": "no_useful_observations",
                    "summary": "Нет наблюдений.",
                    "items": [],
                },
            }
        )
        self.assertIn("Распределение установок между помещениями принято из сметы", html)
        self.assertIn("Принято из сметы; по помещению не проверялось", html)
        self.assertIn("Сумма установок по смете:</strong> 3", html)
        self.assertIn("Уникальных дверей на плане:</strong> 2", html)

    def test_clean_door_rows_show_aggregate_control_in_report(self) -> None:
        findings, _, checked_rows, _ = self.run_checks(("1", "1"))
        summary = core.audit_summary(
            estimate(("1", "1")), findings, [], checked_rows, [], []
        )
        html = report.build_report(
            {
                "manifest": {"object_name": "Тест", "audit_status": "completed"},
                "estimate": estimate(("1", "1")),
                "geometry": {**self.geometry, "missing_fields": []},
                "mapping": {
                    **mapping(),
                    "price_matches": [],
                    "room_unresolved": [],
                    "work_unresolved": [],
                    "price_unresolved": [],
                    "price_unsupported": [],
                },
                "quantities": self.quantities,
                "calculation_trace": self.trace,
                "findings": findings,
                "warnings": [],
                "checked_rows": checked_rows,
                "not_checked_rows": [],
                "price_catalog": {"items": []},
                "price_checks": [],
                "summary": summary,
                "llm_insights": {
                    "status": "no_useful_observations",
                    "summary": "Нет наблюдений.",
                    "items": [],
                },
            }
        )
        self.assertIn("В составе суммы по объекту: смета 2 · план 2", html)


if __name__ == "__main__":
    unittest.main()
