from __future__ import annotations

import importlib
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class FakeAPI:
    def __init__(self) -> None:
        self.tools: list[str] = []

    def register_tool(self, name: str, **_: object) -> None:
        self.tools.append(name)


class RegistrationTest(unittest.TestCase):
    def test_registers_expected_public_tools(self) -> None:
        plugin = importlib.import_module("skill.plugin")
        api = FakeAPI()
        plugin.register(api)

        self.assertEqual(len(api.tools), 14)
        self.assertEqual(len(set(api.tools)), 14)
        self.assertEqual(
            set(api.tools),
            {
                "create_case",
                "import_documents",
                "import_plan",
                "save_geometry",
                "confirm_geometry",
                "render_geometry_review",
                "save_price_catalog",
                "generate_estimate",
                "run_audit",
                "skip_visual_review",
                "import_site_photos",
                "save_visual_analysis",
                "finalize_audit",
                "render_audit_summary",
            },
        )


if __name__ == "__main__":
    unittest.main()
