import os
import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, List

from backend.src.data_io.file_reader import FileReader
from backend.src.data_io.file_writer import FileWriter


STEP_ORDER: List[str] = [
    "EPIC",
    "FEATURES",
    "STORIES",
    "TEST_PLAN",
    "TEST_CASES",
    "AUTOMATED_TESTS",
]

STEP_FILE_PREFIX: Dict[str, str] = {
    "EPIC": "00_epic",
    "FEATURES": "01_features",
    "STORIES": "02_stories",
    "TEST_PLAN": "03_test_plan",
    "TEST_CASES": "04_test_cases",
    "AUTOMATED_TESTS": "05_automated_tests",
}


def _utc_ts() -> str:
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def _ensure_step(step: str) -> None:
    if step not in STEP_ORDER:
        raise ValueError(f"Invalid step: {step}. Valid steps: {STEP_ORDER}")


def _step_index(step: str) -> int:
    _ensure_step(step)
    return STEP_ORDER.index(step)


class StateStore:
    """
    Lightweight state manager for AI-Driven Test Process Automation.
    """

    def __init__(self, out_dir: Optional[str] = None) -> None:
        backend_src = Path(__file__).resolve().parents[1]  # .../backend/src

        if out_dir:
            p = Path(out_dir)
            self.out_root = (p if p.is_absolute() else (backend_src / p)).resolve()
        else:
            self.out_root = (backend_src / "output").resolve()

        self.out_root.mkdir(parents=True, exist_ok=True)

    def create_trace(self, trace_id: str, epic_title: Optional[str] = None) -> Dict[str, Any]:
        trace_dir = self._trace_dir(trace_id)
        trace_dir.mkdir(parents=True, exist_ok=True)

        now = _utc_ts()
        state: Dict[str, Any] = {
            "trace_id": trace_id,
            "created_at": now,
            "updated_at": now,
            "current_step": "EPIC",
            "confirmed": {},
            "meta": {"epic_title": epic_title} if epic_title else {},
        }

        self.save_state(state)
        return state

    def load_state(self, trace_id: str) -> Dict[str, Any]:
        return FileReader.read_json(str(self._state_path(trace_id)))

    def save_state(self, state: Dict[str, Any]) -> None:
        state["updated_at"] = _utc_ts()
        FileWriter.write_json(state, str(self._state_path(state["trace_id"])), pretty=True)

    def trace_exists(self, trace_id: str) -> bool:
        return self._state_path(trace_id).exists()

    def resolve_next_step(self, state: Dict[str, Any]) -> str:
        confirmed = state.get("confirmed", {}) or {}
        for step in STEP_ORDER:
            if step not in confirmed:
                return step
        return STEP_ORDER[-1]

    def freeze_confirmed(self, state: Dict[str, Any], step: str, artifact: Any, version: int = 1) -> str:
        _ensure_step(step)

        trace_dir = self._trace_dir(state["trace_id"])
        prefix = STEP_FILE_PREFIX[step]

        if step == "AUTOMATED_TESTS" and isinstance(artifact, str):
            filename = f"{prefix}.confirmed.v{version}.spec.ts"
            path = trace_dir / filename
            FileWriter.write_text(artifact, str(path))
        else:
            filename = f"{prefix}.confirmed.v{version}.json"
            path = trace_dir / filename
            FileWriter.write_json(artifact, str(path), pretty=True)

        state.setdefault("confirmed", {})[step] = str(path)
        state["current_step"] = self.resolve_next_step(state)
        self.save_state(state)
        return str(path)

    def get_confirmed(self, state: Dict[str, Any], step: str) -> Optional[Any]:
        _ensure_step(step)
        path = state.get("confirmed", {}).get(step)
        if not path:
            return None

        p = Path(path)
        if not p.exists():
            return None

        if p.suffix.lower() in (".ts", ".txt", ".md"):
            return FileReader.read_text(str(p))
        return FileReader.read_json(str(p))

    def rollback_to(self, state: Dict[str, Any], target_step: str, delete_files: bool = False) -> Dict[str, Any]:
        _ensure_step(target_step)
        confirmed = state.get("confirmed", {}) or {}

        target_idx = _step_index(target_step)
        steps_after = STEP_ORDER[target_idx + 1:]

        for step in steps_after:
            old_path = confirmed.pop(step, None)
            if delete_files and old_path:
                try:
                    Path(old_path).unlink(missing_ok=True)
                except TypeError:
                    if Path(old_path).exists():
                        Path(old_path).unlink()

        if target_step in confirmed:
            state["current_step"] = self.resolve_next_step(state)
        else:
            state["current_step"] = target_step

        self.save_state(state)
        return state

    def _trace_dir(self, trace_id: str) -> Path:
        return self.out_root / trace_id

    def _state_path(self, trace_id: str) -> Path:
        return self._trace_dir(trace_id) / "state.json"
