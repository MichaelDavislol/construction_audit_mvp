"""Короткие unit-тесты формулировок, которые Vision имеет право делать по фото."""

from __future__ import annotations

import unittest
from pathlib import Path

from construction_audit_mvp import core, report, visual


def photo() -> dict:
    return {
        "photo_id": "photo_001",
        "vision_source_path": "/tmp/site.jpg",
        "delegation_token": "token_001",
    }


def works() -> list[dict]:
    return [{"canonical_work": "Окраска стен", "source_rows": [2]}]


def payload(*, title: str = "Работа не видна", observation: str = "Результат работы не виден в кадре.") -> dict:
    return {
        "schema_version": 1,
        "photo_id": "photo_001",
        "delegation_token": "token_001",
        "image_quality": {"usable": True, "issues": []},
        "scene_summary": "Видимый участок объекта.",
        "visual_insights": [
            {
                "visual_insight_id": "photo_001_insight_001",
                "category": "estimate_comparison",
                "estimate_work": "Окраска стен",
                "source_rows": [2],
                "status": "not_observed",
                "title": title,
                "observation": observation,
                "evidence_text": "Видимая поверхность стены.",
                "confidence": "medium",
                "auditor_check": "Проверить работу на объекте.",
                "limitations": "Только видимая часть кадра.",
            }
        ],
        "limitations": ["Только видимая часть кадра."],
    }


class VisualTests(unittest.TestCase):
    def test_not_observed_accepts_frame_limited_visibility(self) -> None:
        result = visual.validate(payload(), photo=photo(), estimate_works=works())
        self.assertEqual("not_observed", result["visual_insights"][0]["status"])

    def test_not_observed_rejects_non_completion_claim(self) -> None:
        # «Не видно в кадре» — наблюдение. «Не выполнено» — уже ничем не доказанный вывод.
        value = payload(
            title="Окраска стен не выполнена",
            observation="Финишная окраска стен не выполнена.",
        )
        with self.assertRaises(visual.VisualValidationError) as raised:
            visual.validate(value, photo=photo(), estimate_works=works())
        self.assertTrue(any("non-completion" in error["reason"] for error in raised.exception.errors))

    def test_not_observed_rejects_unscoped_absence(self) -> None:
        value = payload(title="Окраска отсутствует", observation="Окраска отсутствует.")
        with self.assertRaises(visual.VisualValidationError) as raised:
            visual.validate(value, photo=photo(), estimate_works=works())
        self.assertTrue(any("limited to the frame" in error["reason"] for error in raised.exception.errors))

    def test_delegation_forbids_postamble(self) -> None:
        packet = visual.delegation(photo(), works())
        self.assertIn("после [END_SUBTASK_OUTPUT] разрешён только whitespace", packet["expected_output"])
        self.assertIn("не выполнено", packet["constraints"])

    def test_visual_instruction_enforces_sequential_wait_and_save(self) -> None:
        instruction = core.VISUAL_DELEGATION_ASSISTANT_INSTRUCTION
        self.assertIn("Не вызывай wait_tasks, recent_tasks", instruction)
        self.assertIn("только после успешного save", instruction)

    def test_photo_task_id_contract_is_runtime_task_id_shape(self) -> None:
        self.assertIsNotNone(core.SUBAGENT_TASK_ID_RE.fullmatch("80d27745"))
        self.assertIsNone(core.SUBAGENT_TASK_ID_RE.fullmatch("photo-task"))

    def test_report_uses_frame_limited_not_observed_label(self) -> None:
        html = report._visual_insights_section({"status": "generated", "items": [{
            "photo_id": "photo_001",
            "status": "not_observed",
            "category": "estimate_comparison",
            "estimate_work": "Окраска стен",
            "source_rows": [2],
            "title": "Работа не видна",
            "observation": "Результат не виден в кадре.",
            "evidence_text": "Видимая стена.",
            "confidence": "medium",
            "auditor_check": "Проверить на объекте.",
            "limitations": "Только этот кадр.",
        }]})
        self.assertIn("не видно в кадре", html)
        self.assertNotIn("не наблюдается", html)

    def test_markdown_price_finding_does_not_reuse_quantity_unit(self) -> None:
        markdown = core.build_audit_summary_markdown(
            {
                "completion_status": "completed",
                "estimate_rows": 1,
                "checked_rows": 1,
                "not_checked_rows": 0,
                "findings_count": 1,
                "findings_by_severity": {"high": 1, "warning": 0},
            },
            [{
                "source_row": 2,
                "original_room_name": "Кухня",
                "original_work_name": "Окраска стен",
                "type": "price_overstatement",
                "unit": "м²",
                "estimated_value": "135",
                "control_value": "120",
                "deviation_percent": "12.5",
            }],
            [],
            {"rooms": []},
            Path("/tmp/report.html"),
        )
        self.assertIn("| 135 | 120 |", markdown)
        self.assertNotIn("135 м²", markdown)
        self.assertNotIn("120 м²", markdown)


if __name__ == "__main__":
    unittest.main()
