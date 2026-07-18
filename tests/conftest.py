"""Подключаем именно тот payload, рядом с которым запускаются тесты."""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path


TESTS_DIR = Path(__file__).resolve().parent


def _load_skill_package():
    # В опубликованном репозитории payload лежит рядом, в каталоге skill/.
    for project_root in (TESTS_DIR.parent, TESTS_DIR.parent.parent):
        if (project_root / "skill").is_dir():
            sys.path.insert(0, str(project_root))
            return importlib.import_module("skill")

    # В рабочей раскладке тесты живут отдельно. Путь задаём явно, без привязки
    # к имени пользователя или конкретному домашнему каталогу.
    configured = os.environ.get("CONSTRUCTION_AUDIT_SKILL_DIR")
    if configured:
        skill_dir = Path(configured).expanduser().resolve()
        if skill_dir.name != "construction_audit_mvp" or not (skill_dir / "plugin.py").is_file():
            raise RuntimeError(
                "CONSTRUCTION_AUDIT_SKILL_DIR должен указывать на каталог construction_audit_mvp"
            )
        sys.path.insert(0, str(skill_dir.parent))
        return importlib.import_module("construction_audit_mvp")

    raise RuntimeError(
        "Не найден каталог skill/. Для отдельного запуска задайте "
        "CONSTRUCTION_AUDIT_SKILL_DIR=/path/to/construction_audit_mvp"
    )


sys.modules.setdefault("construction_audit_mvp", _load_skill_package())
