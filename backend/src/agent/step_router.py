import os 
import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

from typing import Any, Dict, List, Optional

from backend.src.agent.state_store import STEP_ORDER


class StepRouter:
    """
    StepRouter is a lightweight state machine:
      - decide current step (resume)
      - compute previous/next step
      - validate whether a target start step is allowed
    """

    def __init__(self, step_order: Optional[List[str]] = None) -> None:
        self.step_order = step_order or list(STEP_ORDER)

    # ---------- basic step navigation ----------

    def is_valid_step(self, step: str) -> bool:
        return step in self.step_order

    def step_index(self, step: str) -> int:
        if step not in self.step_order:
            raise ValueError(f"Invalid step: {step}. Valid: {self.step_order}")
        return self.step_order.index(step)

    def prev_step(self, step: str) -> Optional[str]:
        i = self.step_index(step)
        return self.step_order[i - 1] if i > 0 else None

    def next_step(self, step: str) -> Optional[str]:
        i = self.step_index(step)
        return self.step_order[i + 1] if i + 1 < len(self.step_order) else None

    # ---------- resume / decide current ----------

    def decide_current_step(self, state: Dict[str, Any]) -> str:
        """
        Decide what step should run next. Priority:
          1) if state.current_step exists and is valid -> use it
          2) otherwise compute first missing step by checking confirmed
        """
        cur = state.get("current_step")
        if isinstance(cur, str) and cur in self.step_order:
            return cur

        confirmed = state.get("confirmed", {}) or {}
        for s in self.step_order:
            if s not in confirmed:
                return s
        return self.step_order[-1]

    # ---------- start-from-middle support ----------

    def can_start_from(self, state: Dict[str, Any], target_step: str) -> Dict[str, Any]:
        """
        Check whether user can start from target_step.

        Rule:
          - allowed if all prerequisite steps BEFORE target_step are confirmed
          - otherwise return missing prerequisites
        """
        if not self.is_valid_step(target_step):
            return {"ok": False, "missing": [], "reason": f"Invalid step: {target_step}"}

        idx = self.step_index(target_step)
        prereq_steps = self.step_order[:idx]
        confirmed = state.get("confirmed", {}) or {}

        missing = [s for s in prereq_steps if s not in confirmed]
        if missing:
            return {
                "ok": False,
                "missing": missing,
                "reason": "Missing prerequisites. Provide/confirm them first.",
            }

        return {"ok": True, "missing": [], "reason": ""}

    def set_start_step(self, state: Dict[str, Any], target_step: str) -> Dict[str, Any]:
        """
        Force state.current_step to target_step ONLY IF prerequisites are satisfied.
        """
        check = self.can_start_from(state, target_step)
        if not check.get("ok"):
            return check

        state["current_step"] = target_step
        return {"ok": True, "missing": [], "reason": ""}

    # ---------- reaction to review actions ----------

    def on_confirm(self, state: Dict[str, Any]) -> str:
        """
        After a step is frozen, the StateStore already sets current_step.
        This method is here for completeness (or future extension).
        """
        return self.decide_current_step(state)

    def on_back(self, state: Dict[str, Any]) -> Optional[str]:
        """
        Compute the previous step to rollback to.
        """
        cur = self.decide_current_step(state)
        return self.prev_step(cur)

    def on_redo(self, state: Dict[str, Any]) -> str:
        """
        Redo stays at current step.
        """
        return self.decide_current_step(state)
