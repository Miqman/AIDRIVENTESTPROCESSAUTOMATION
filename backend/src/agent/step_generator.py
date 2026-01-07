import os
import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

import time
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, DefaultDict
from collections import defaultdict

from backend.src.data_io.file_reader import FileReader
from backend.src.llm.copilot_client import CopilotClient


class StepGenerator:
    """
    Generate draft artifacts per step using CopilotClient, based on confirmed context.

    POC design goals:
      - low temp
      - JSON-first outputs (except AUTOMATED_TESTS which can be TS text)
      - minimal context: Epic + direct prerequisites (distilled)
      - prompt files are loaded from backend/src/prompts/
      - robustness: tolerate non-strict JSON and retry/backoff on transient errors

    Enhancement (Scheme-B):
      - TEST_CASES are generated per-story (batched), then merged:
          {"test_cases": [...]}.
        This avoids truncation and makes retries localized.

    Enhancement (Scheme-C):
      - AUTOMATED_TESTS are generated per-story (batched), then merged into one spec.ts
        This avoids truncation for large test suites.
    """

    # Recommended minimal context limits (char-based)
    MAX_EPIC_CHARS = 1800
    MAX_FEATURES_CHARS = 2500
    MAX_STORIES_CHARS = 2800
    MAX_TESTPLAN_CHARS = 2500
    MAX_TESTCASES_CHARS = 3500

    # Per-story context clip (smaller)
    MAX_SINGLE_STORY_CHARS = 1400
    MAX_SINGLE_FEATURE_CHARS = 1200
    MAX_SINGLE_TESTPLAN_CHARS = 1400
    MAX_SINGLE_TESTCASES_CHARS = 4500  # allow a bit more per story for automation

    # TEST_CASES batching controls
    MAX_TESTCASES_PER_STORY = 6          # hard cap to avoid bloat
    DEFAULT_TEST_PRIORITY = "P2"

    # AUTOMATED_TESTS batching controls
    AUTOMATION_MAX_TOKENS_PER_STORY = 3200
    AUTOMATION_TEMPERATURE = 0.1

    # Step -> prompt filenames (system/user)
    PROMPT_FILES: Dict[str, Tuple[str, str]] = {
        "EPIC": ("00_epic.system.txt", "00_epic.user.txt"),
        "FEATURES": ("01_features.system.txt", "01_features.user.txt"),
        "STORIES": ("02_stories.system.txt", "02_stories.user.txt"),
        "TEST_PLAN": ("03_test_plan.system.txt", "03_test_plan.user.txt"),
        "TEST_CASES": ("04_test_cases.system.txt", "04_test_cases.user.txt"),
        "AUTOMATED_TESTS": ("05_automated_tests.system.txt", "05_automated_tests.user.txt"),
    }

    def __init__(
        self,
        copilot: Optional[CopilotClient] = None,
        prompts_dir: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: int = 2048,
        json_retry: int = 1,  # legacy: kept, but we now do robust attempts in _call_json
    ) -> None:
        self.copilot = copilot or CopilotClient(temperature=temperature, max_tokens=max_tokens)
        self.prompts_dir = Path(prompts_dir) if prompts_dir else (Path(__file__).resolve().parents[1] / "prompts")
        self.temperature = float(temperature)
        self.max_tokens = int(max_tokens)
        self.json_retry = int(json_retry)

    # ---------------- Public API ----------------

    def generate_step(
        self,
        step: str,
        state: Dict[str, Any],
        confirmed: Dict[str, Any],
        redo_hint: Optional[str] = None,
    ) -> Any:
        system_prompt, user_template = self._load_prompts(step)

        # Scheme-B: TEST_CASES are generated per story and merged
        if step == "TEST_CASES":
            return self._generate_test_cases_batched(
                system_prompt=system_prompt,
                user_template=user_template,
                state=state,
                confirmed=confirmed,
                redo_hint=redo_hint,
            )

        # Scheme-C: AUTOMATED_TESTS are generated per story and merged into one file
        if step == "AUTOMATED_TESTS":
            return self._generate_automated_tests_batched(
                system_prompt=system_prompt,
                user_template=user_template,
                state=state,
                confirmed=confirmed,
                redo_hint=redo_hint,
            )

        # default flow (single call)
        ctx = self._build_context(step, state, confirmed, redo_hint=redo_hint)
        user_prompt = self._safe_format(user_template, **ctx)
        return self._call_json(system_prompt, user_prompt, step=step)

    # ---------------- Prompt loading ----------------

    def _load_prompts(self, step: str) -> Tuple[str, str]:
        if step not in self.PROMPT_FILES:
            raise ValueError(f"Unknown step for prompts: {step}. Valid: {list(self.PROMPT_FILES.keys())}")

        sys_name, user_name = self.PROMPT_FILES[step]
        sys_path = self.prompts_dir / sys_name
        user_path = self.prompts_dir / user_name

        system_prompt = FileReader.read_text(str(sys_path))
        user_template = FileReader.read_text(str(user_path))
        return system_prompt, user_template

    # ---------------- Context building (minimal) ----------------

    def _build_context(
        self,
        step: str,
        state: Dict[str, Any],
        confirmed: Dict[str, Any],
        redo_hint: Optional[str],
    ) -> Dict[str, Any]:
        trace_id = state.get("trace_id", "")
        meta = state.get("meta", {}) or {}

        epic = confirmed.get("EPIC")
        features = confirmed.get("FEATURES")
        stories = confirmed.get("STORIES")
        test_plan = confirmed.get("TEST_PLAN")
        test_cases = confirmed.get("TEST_CASES")

        epic_text = self._clip_json(epic, self.MAX_EPIC_CHARS)
        features_text = self._clip_json(self._distill_features(features), self.MAX_FEATURES_CHARS)
        stories_text = self._clip_json(self._distill_stories(stories), self.MAX_STORIES_CHARS)
        testplan_text = self._clip_json(self._distill_test_plan(test_plan), self.MAX_TESTPLAN_CHARS)
        testcases_text = self._clip_json(self._distill_test_cases(test_cases), self.MAX_TESTCASES_CHARS)

        return {
            "trace_id": trace_id,
            "meta_json": json.dumps(meta, ensure_ascii=False),
            "redo_hint": redo_hint or "",
            "epic_json": epic_text,
            "features_json": features_text,
            "stories_json": stories_text,
            "test_plan_json": testplan_text,
            "test_cases_json": testcases_text,
        }

    # ---------------- Distillation helpers ----------------

    @staticmethod
    def _unwrap_list(obj: Any, key_candidates: Tuple[str, ...]) -> Any:
        if isinstance(obj, dict):
            for k in key_candidates:
                v = obj.get(k)
                if isinstance(v, list):
                    return v
        return obj

    def _distill_features(self, features: Any) -> Any:
        features_list = self._unwrap_list(features, ("features", "items", "data"))
        if not isinstance(features_list, list):
            return features

        out: List[Dict[str, Any]] = []
        for f in features_list:
            if isinstance(f, dict):
                out.append({
                    "id": f.get("id") or f.get("feature_id"),
                    "name": f.get("name") or f.get("title"),
                    "description": f.get("description") or f.get("summary"),
                })
        return out

    def _distill_stories(self, stories: Any) -> Any:
        stories_list = self._unwrap_list(stories, ("user_stories", "stories", "items", "data"))
        if not isinstance(stories_list, list):
            return stories

        out: List[Dict[str, Any]] = []
        for s in stories_list:
            if isinstance(s, dict):
                out.append({
                    "id": s.get("id") or s.get("story_id"),
                    "feature_id": s.get("feature_id"),
                    "title": s.get("title") or s.get("name"),
                    "acceptance_criteria": s.get("acceptance_criteria") or s.get("ac"),
                })
        return out

    @staticmethod
    def _distill_test_plan(plan: Any) -> Any:
        if not isinstance(plan, dict):
            return plan
        return {
            "scope": plan.get("scope"),
            "in_scope": plan.get("in_scope"),
            "out_of_scope": plan.get("out_of_scope"),
            "test_types": plan.get("test_types"),
            "environments": plan.get("environments"),
            "entry_criteria": plan.get("entry_criteria"),
            "exit_criteria": plan.get("exit_criteria"),
            "risks": plan.get("risks"),
        }

    def _distill_test_cases(self, cases: Any) -> Any:
        cases_list = self._unwrap_list(cases, ("test_cases", "cases", "items", "data"))
        if not isinstance(cases_list, list):
            return cases

        out: List[Dict[str, Any]] = []
        for c in cases_list:
            if isinstance(c, dict):
                out.append({
                    "id": c.get("id") or c.get("tc_id"),
                    "story_id": c.get("story_id"),
                    "title": c.get("title") or c.get("name"),
                    "priority": c.get("priority"),
                    "preconditions": c.get("preconditions"),
                    "steps": c.get("steps"),
                    "expected": c.get("expected") or c.get("expected_results"),
                    "test_data": c.get("test_data"),
                })
        return out

    @staticmethod
    def _clip_json(obj: Any, max_chars: int) -> str:
        try:
            s = json.dumps(obj, ensure_ascii=False, indent=2, default=str)
        except Exception:
            s = str(obj)

        s = (s or "").strip()
        if len(s) <= max_chars:
            return s
        return s[: max(1, max_chars - 3)].rstrip() + "..."

    # ---------------- Scheme-B: TEST_CASES batched per story ----------------

    def _generate_test_cases_batched(
        self,
        system_prompt: str,
        user_template: str,
        state: Dict[str, Any],
        confirmed: Dict[str, Any],
        redo_hint: Optional[str],
    ) -> Dict[str, Any]:
        """
        Generate test cases per story (one LLM call per story), then merge.

        Returns:
          {"test_cases": [ ... ]}  # stable wrapper for downstream
        """
        base_ctx = self._build_context("TEST_CASES", state, confirmed, redo_hint=redo_hint)

        stories_obj = confirmed.get("STORIES")
        stories_list = self._unwrap_list(stories_obj, ("user_stories", "stories", "items", "data"))
        if not isinstance(stories_list, list) or len(stories_list) == 0:
            user_prompt = self._safe_format(user_template, **base_ctx)
            return self._call_json(system_prompt, user_prompt, step="TEST_CASES")

        features_obj = confirmed.get("FEATURES")
        features_list = self._unwrap_list(features_obj, ("features", "items", "data"))
        feature_map: Dict[str, Dict[str, Any]] = {}
        if isinstance(features_list, list):
            for f in features_list:
                if isinstance(f, dict):
                    fid = f.get("id") or f.get("feature_id")
                    if fid:
                        feature_map[str(fid)] = f

        plan_obj = confirmed.get("TEST_PLAN")
        plan_distilled = self._distill_test_plan(plan_obj)
        plan_text = self._clip_json(plan_distilled, self.MAX_SINGLE_TESTPLAN_CHARS)

        all_cases: List[Dict[str, Any]] = []

        for idx, s in enumerate(stories_list, start=1):
            if not isinstance(s, dict):
                continue

            story_distilled = {
                "id": s.get("id") or s.get("story_id") or f"US-{idx}",
                "feature_id": s.get("feature_id"),
                "title": s.get("title") or s.get("name"),
                "acceptance_criteria": s.get("acceptance_criteria") or s.get("ac"),
            }
            story_id = str(story_distilled["id"])

            fid = story_distilled.get("feature_id")
            feature = feature_map.get(str(fid)) if fid is not None else None
            feature_distilled = None
            if isinstance(feature, dict):
                feature_distilled = {
                    "id": feature.get("id") or feature.get("feature_id") or str(fid),
                    "name": feature.get("name") or feature.get("title"),
                    "description": feature.get("description") or feature.get("summary"),
                }

            per_story_ctx = dict(base_ctx)
            per_story_ctx["story_id"] = story_id  # IMPORTANT for {story_id} placeholder in prompt
            per_story_ctx["story_json"] = self._clip_json(story_distilled, self.MAX_SINGLE_STORY_CHARS)
            per_story_ctx["feature_json"] = (
                self._clip_json(feature_distilled, self.MAX_SINGLE_FEATURE_CHARS) if feature_distilled else ""
            )
            per_story_ctx["test_plan_json"] = plan_text

            user_prompt = self._safe_format(user_template, **per_story_ctx)

            if "{story_id}" in user_prompt:
                user_prompt += f"\n\nNOTE: story_id is {story_id}. Use this exact value for all test cases.\n"

            if "{story_json}" not in user_template:
                user_prompt = (
                    user_prompt.rstrip()
                    + "\n\n---\n"
                    + "Generate test cases ONLY for the following single user story (do not include other stories).\n"
                    + per_story_ctx["story_json"]
                    + "\n\nConstraints:\n"
                    + f"- Return JSON only. Wrapper must be {{\"test_cases\":[...]}}.\n"
                    + f"- Max {self.MAX_TESTCASES_PER_STORY} test cases.\n"
                    + "- Each test case must include: id, story_id, title, priority, preconditions, steps, expected, test_data.\n"
                    + "- test_data must be an object.\n"
                )

            per_story_result = self._call_json(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                step="TEST_CASES_PER_STORY",
            )

            cases = self._normalize_test_cases_result(per_story_result)
            cases = self._postprocess_cases(cases, story_id=story_id)

            if len(cases) > self.MAX_TESTCASES_PER_STORY:
                cases = cases[: self.MAX_TESTCASES_PER_STORY]

            all_cases.extend(cases)

        return {"test_cases": all_cases}

    @staticmethod
    def _normalize_test_cases_result(obj: Any) -> List[Dict[str, Any]]:
        if isinstance(obj, dict):
            for k in ("test_cases", "cases", "items", "data"):
                v = obj.get(k)
                if isinstance(v, list):
                    return [x for x in v if isinstance(x, dict)]
            if "id" in obj and ("steps" in obj or "expected" in obj):
                return [obj]
            return []
        if isinstance(obj, list):
            return [x for x in obj if isinstance(x, dict)]
        return []

    def _postprocess_cases(self, cases: List[Dict[str, Any]], story_id: str) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for i, c in enumerate(cases, start=1):
            tc = dict(c)

            tc["story_id"] = tc.get("story_id") or story_id

            if not tc.get("id"):
                tc["id"] = f"TC-{story_id}-{i}"

            tc["priority"] = tc.get("priority") or self.DEFAULT_TEST_PRIORITY

            for k in ("preconditions", "steps", "expected"):
                v = tc.get(k)
                if v is None:
                    tc[k] = []
                elif isinstance(v, str):
                    tc[k] = [v]
                elif isinstance(v, list):
                    tc[k] = v
                else:
                    tc[k] = [str(v)]

            v = tc.get("test_data")
            if v is None:
                tc["test_data"] = {}
            elif isinstance(v, dict):
                pass
            elif isinstance(v, list):
                tc["test_data"] = {"items": v}
            else:
                tc["test_data"] = {"value": str(v)}

            if not tc.get("title"):
                tc["title"] = f"Test case for {story_id} #{i}"

            out.append(tc)
        return out

    # ---------------- Scheme-C: AUTOMATED_TESTS batched per story ----------------

    def _generate_automated_tests_batched(
        self,
        system_prompt: str,
        user_template: str,
        state: Dict[str, Any],
        confirmed: Dict[str, Any],
        redo_hint: Optional[str],
    ) -> str:
        """
        Generate automated tests per story (one LLM call per story), then merge into one .spec.ts string.

        It expects confirmed["TEST_CASES"] to exist. If not, fallback to single-call generation
        with the clipped test_cases_json (may truncate but keeps behavior predictable).
        """
        base_ctx = self._build_context("AUTOMATED_TESTS", state, confirmed, redo_hint=redo_hint)

        test_cases_obj = confirmed.get("TEST_CASES")
        cases_list = self._unwrap_list(test_cases_obj, ("test_cases", "cases", "items", "data"))
        if not isinstance(cases_list, list) or len(cases_list) == 0:
            # fallback: old behavior (single call)
            user_prompt = self._safe_format(user_template, **base_ctx)
            return self._call_text(system_prompt, user_prompt)

        # Build maps for story & feature context (optional but helps quality)
        stories_obj = confirmed.get("STORIES")
        stories_list = self._unwrap_list(stories_obj, ("user_stories", "stories", "items", "data"))
        story_map: Dict[str, Dict[str, Any]] = {}
        if isinstance(stories_list, list):
            for i, s in enumerate(stories_list, start=1):
                if isinstance(s, dict):
                    sid = s.get("id") or s.get("story_id") or f"US-{i}"
                    story_map[str(sid)] = {
                        "id": sid,
                        "feature_id": s.get("feature_id"),
                        "title": s.get("title") or s.get("name"),
                        "acceptance_criteria": s.get("acceptance_criteria") or s.get("ac"),
                    }

        features_obj = confirmed.get("FEATURES")
        features_list = self._unwrap_list(features_obj, ("features", "items", "data"))
        feature_map: Dict[str, Dict[str, Any]] = {}
        if isinstance(features_list, list):
            for f in features_list:
                if isinstance(f, dict):
                    fid = f.get("id") or f.get("feature_id")
                    if fid:
                        feature_map[str(fid)] = {
                            "id": fid,
                            "name": f.get("name") or f.get("title"),
                            "description": f.get("description") or f.get("summary"),
                        }

        plan_obj = confirmed.get("TEST_PLAN")
        plan_text = self._clip_json(self._distill_test_plan(plan_obj), self.MAX_SINGLE_TESTPLAN_CHARS)

        grouped = self._group_test_cases_by_story(cases_list)

        sections: List[str] = []
        for story_id, story_cases in grouped:
            sid = self._normalize_story_id(story_id)

            story_distilled = story_map.get(sid) or {"id": sid}
            feature_distilled = None
            fid = story_distilled.get("feature_id")
            if fid is not None:
                feature_distilled = feature_map.get(str(fid))

            per_story_ctx = dict(base_ctx)
            per_story_ctx["story_id"] = sid
            per_story_ctx["test_plan_json"] = plan_text
            per_story_ctx["story_json"] = self._clip_json(story_distilled, self.MAX_SINGLE_STORY_CHARS)
            per_story_ctx["feature_json"] = (
                self._clip_json(feature_distilled, self.MAX_SINGLE_FEATURE_CHARS) if feature_distilled else ""
            )
            per_story_ctx["test_cases_json"] = self._clip_json(
                self._distill_test_cases({"test_cases": story_cases}),
                self.MAX_SINGLE_TESTCASES_CHARS
            )

            user_prompt = self._safe_format(user_template, **per_story_ctx)

            # Hard-guard: if template didn't include story_id/test cases clearly, force append constraints
            if "{test_cases_json}" not in user_template:
                user_prompt = (
                    user_prompt.rstrip()
                    + "\n\n---\n"
                    + f"Generate Playwright TypeScript tests ONLY for story_id = {sid}.\n"
                    + "Use ONLY the following test cases JSON (do not invent additional cases):\n"
                    + per_story_ctx["test_cases_json"]
                    + "\n\nConstraints:\n"
                    + "- Output ONLY TypeScript code (no markdown fences).\n"
                    + f"- Wrap tests in describe('{sid} ...', () => {{ ... }}).\n"
                    + "- Ensure all test cases in the JSON are implemented.\n"
                )

            ts = self._generate_tests_for_story(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                story_id=sid,
            )
            ts = self._strip_code_fence(ts)
            sections.append(ts)

        return self._merge_ts_sections(sections)

    def _group_test_cases_by_story(self, cases_list: List[Any]) -> List[Tuple[str, List[Dict[str, Any]]]]:
        """
        Returns stable-ordered groups: [(story_id, [case...]), ...]
        Order follows first appearance in cases_list to keep determinism.
        """
        grouped: DefaultDict[str, List[Dict[str, Any]]] = defaultdict(list)
        order: List[str] = []

        for c in cases_list:
            if not isinstance(c, dict):
                continue
            sid = c.get("story_id") or "UNKNOWN"
            sid = self._normalize_story_id(str(sid))
            if sid not in grouped:
                order.append(sid)
            grouped[sid].append(c)

        return [(sid, grouped[sid]) for sid in order]

    @staticmethod
    def _normalize_story_id(s: str) -> str:
        s = (s or "").strip()
        return s if s else "UNKNOWN"

    def _generate_tests_for_story(self, system_prompt: str, user_prompt: str, story_id: str) -> str:
        """
        Text call for one story. Uses slightly higher per-story max_tokens.
        Retries for transient failures.
        """
        max_attempts = 5
        base_sleep = 2.0
        max_sleep = 25.0

        last_err: Optional[Exception] = None

        for attempt in range(1, max_attempts + 1):
            try:
                return self.copilot.chat_text(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    max_tokens=max(self.max_tokens, self.AUTOMATION_MAX_TOKENS_PER_STORY),
                    temperature=self.AUTOMATION_TEMPERATURE,
                )
            except Exception as e:
                last_err = e

                status_code = None
                resp = None
                try:
                    resp = getattr(e, "response", None)
                    if resp is not None:
                        status_code = getattr(resp, "status_code", None)
                except Exception:
                    resp = None

                if status_code in (429, 500, 502, 503, 504):
                    retry_after = None
                    try:
                        if resp is not None:
                            ra = resp.headers.get("Retry-After")
                            if ra:
                                retry_after = float(ra)
                    except Exception:
                        retry_after = None

                    sleep_s = retry_after if retry_after is not None else min(
                        max_sleep, base_sleep * (1.7 ** (attempt - 1))
                    )
                    print(
                        f"[warn] AUTOMATED_TESTS({story_id}) failed (HTTP {status_code}) "
                        f"attempt {attempt}/{max_attempts}. Sleep {sleep_s:.1f}s..."
                    )
                    time.sleep(sleep_s)
                    continue

                raise

        raise RuntimeError(
            f"AUTOMATED_TESTS({story_id}) failed after {max_attempts} attempts. Last error: {repr(last_err)}"
        ) from last_err

    @staticmethod
    def _strip_code_fence(text: str) -> str:
        """
        Removes ``` fences if model outputs them. Keeps inner code.
        """
        t = (text or "").strip()
        if t.startswith("```"):
            lines = t.splitlines()
            # drop first fence line
            lines = lines[1:]
            # drop last fence line if present
            if lines and lines[-1].strip().startswith("```"):
                lines = lines[:-1]
            return "\n".join(lines).strip()
        return t

    @staticmethod
    def _merge_ts_sections(sections: List[str]) -> str:
        """
        Merge multiple per-story TS blocks into one file.
        If prompts already include imports/helpers per section, this will still work
        (duplicate imports are usually tolerated by TS, but you can refine later).
        Minimal, safe merge: join with clear separators.
        """
        cleaned = []
        for s in sections:
            ss = (s or "").strip()
            if not ss:
                continue
            cleaned.append(ss)

        if not cleaned:
            return ""

        header = (
            "// AUTO-GENERATED Playwright tests (batched by story)\n"
            "// NOTE: This file is merged from per-story generations to avoid truncation.\n\n"
        )
        body = "\n\n// ------------------------------\n\n".join(cleaned)
        return header + body + "\n"

    # ---------------- LLM calls ----------------

    def _call_json(self, system_prompt: str, user_prompt: str, step: Optional[str] = None) -> Any:
        max_tokens = self.max_tokens
        temperature = self.temperature

        if step in ("TEST_CASES", "TEST_CASES_PER_STORY"):
            max_tokens = max(self.max_tokens, 2048)
            temperature = 0.0

        payload = {
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "max_tokens": int(max_tokens),
            "temperature": float(temperature),
            "response_format": {"type": "json_object"},
        }

        max_attempts = 6
        base_sleep = 2.0
        max_sleep = 30.0

        last_err: Optional[Exception] = None

        for attempt in range(1, max_attempts + 1):
            try:
                raw = self.copilot.chat_raw(**payload)
                content = self._safe_get_content(raw)
                return self._safe_json_loads(content)

            except Exception as e:
                last_err = e

                status_code = None
                resp = None
                try:
                    resp = getattr(e, "response", None)
                    if resp is not None:
                        status_code = getattr(resp, "status_code", None)
                except Exception:
                    resp = None

                if status_code in (429, 500, 502, 503, 504):
                    retry_after = None
                    try:
                        if resp is not None:
                            ra = resp.headers.get("Retry-After")
                            if ra:
                                retry_after = float(ra)
                    except Exception:
                        retry_after = None

                    sleep_s = retry_after if retry_after is not None else min(
                        max_sleep, base_sleep * (1.7 ** (attempt - 1))
                    )
                    print(
                        f"[warn] LLM call failed (HTTP {status_code}) on attempt {attempt}/{max_attempts}. "
                        f"Sleeping {sleep_s:.1f}s then retry..."
                    )
                    time.sleep(sleep_s)

                    if step == "TEST_CASES_PER_STORY" and attempt >= 3:
                        payload["max_tokens"] = min(4096, int(payload["max_tokens"]) + 512)

                    continue

                raise

        raise RuntimeError(
            f"LLM call failed after {max_attempts} attempts. Last error: {repr(last_err)}"
        ) from last_err

    def _call_text(self, system_prompt: str, user_prompt: str) -> str:
        return self.copilot.chat_text(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
        )

    @staticmethod
    def _safe_get_content(raw: Dict[str, Any]) -> str:
        try:
            return raw["choices"][0]["message"]["content"]
        except Exception:
            return str(raw)

    # ---------------- JSON parsing helpers ----------------

    @staticmethod
    def _extract_first_json(text: str) -> Optional[str]:
        if not text:
            return None

        start = None
        opener = None
        closer = None

        for i, ch in enumerate(text):
            if ch == "{" or ch == "[":
                start = i
                opener = ch
                closer = "}" if ch == "{" else "]"
                break

        if start is None:
            return None

        depth = 0
        in_str = False
        escape = False

        for j in range(start, len(text)):
            ch = text[j]

            if in_str:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_str = False
                continue

            if ch == '"':
                in_str = True
                continue

            if ch == opener:
                depth += 1
            elif ch == closer:
                depth -= 1
                if depth == 0:
                    return text[start:j + 1]

        return None  # likely truncated

    def _safe_json_loads(self, text: str) -> Any:
        t = (text or "").strip()

        try:
            return json.loads(t)
        except Exception:
            pass

        extracted = self._extract_first_json(t)
        if extracted:
            try:
                return json.loads(extracted)
            except Exception as e:
                raise ValueError(
                    f"Model returned non-JSON content (extracted JSON still invalid). Head:\n{t[:500]}"
                ) from e

        raise ValueError(f"Model returned non-JSON content. Head:\n{t[:500]}")

    # ---------------- Utils ----------------

    @staticmethod
    def _safe_format(template: str, **kwargs) -> str:
        """
        Safer than str.format: if template contains unknown placeholders, we keep them untouched.
        This prevents runtime KeyError when we add optional placeholders like {story_json}.
        """
        class _SafeDict(dict):
            def __missing__(self, key):
                return "{" + key + "}"
        return template.format_map(_SafeDict(**kwargs))
