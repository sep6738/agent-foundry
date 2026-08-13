"""Executable skill runner with path confinement and timeouts."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

from agent_backend.app.skills.registry import Skill


class SkillRunner:
    def run_script(
        self,
        skill: Skill,
        script_name: str,
        args: list[str] | None = None,
        timeout_seconds: int = 30,
    ) -> dict[str, Any]:
        if not skill.meta.source_path:
            return {"ok": False, "error": "skill has no source path"}
        skill_dir = Path(skill.meta.source_path).resolve().parent
        script = (skill_dir / "scripts" / script_name).resolve()
        if not script.is_relative_to(skill_dir):
            return {"ok": False, "error": "script escapes skill directory"}
        if not script.is_file():
            return {"ok": False, "error": f"script not found: {script_name}"}
        if script.suffix != ".py":
            return {"ok": False, "error": "only .py skill scripts are supported"}
        try:
            completed = subprocess.run(
                [sys.executable, str(script), *(args or [])],
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                cwd=skill_dir,
            )
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": "skill script timed out"}
        except OSError as exc:
            return {"ok": False, "error": str(exc)}
        output = completed.stdout.strip()
        if completed.returncode != 0:
            return {
                "ok": False,
                "error": completed.stderr.strip() or f"exit code {completed.returncode}",
                "output": output,
            }
        return {"ok": True, "output": output, "stderr": completed.stderr.strip()}
