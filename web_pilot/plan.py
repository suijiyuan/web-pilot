from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, MutableMapping, Optional, Sequence

from .errors import PlanError


@dataclass(frozen=True)
class BrowserConfig:
    channel: Optional[str] = "chromium"
    headless: bool = True
    slow_mo_ms: int = 0
    args: tuple[str, ...] = ()


@dataclass(frozen=True)
class ContextConfig:
    viewport: Optional[dict[str, int]] = None
    storage_state: Optional[str] = None
    user_agent: Optional[str] = None
    locale: Optional[str] = None
    timezone_id: Optional[str] = None


@dataclass(frozen=True)
class Step:
    action: str
    params: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TestCase:
    name: str
    steps: tuple[Step, ...]


@dataclass(frozen=True)
class Plan:
    name: str
    browser: BrowserConfig
    context: ContextConfig
    tests: tuple[TestCase, ...]
    artifacts_dir: str = "artifacts"
    vars: dict[str, str] = field(default_factory=dict)


_VAR_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _as_dict(v: Any, *, where: str) -> dict[str, Any]:
    if v is None:
        return {}
    if not isinstance(v, dict):
        raise PlanError(f"{where} must be an object")
    return v


def _as_list(v: Any, *, where: str) -> list[Any]:
    if v is None:
        return []
    if not isinstance(v, list):
        raise PlanError(f"{where} must be an array")
    return v


def _as_str(v: Any, *, where: str, required: bool = False) -> Optional[str]:
    if v is None:
        if required:
            raise PlanError(f"{where} is required")
        return None
    if not isinstance(v, str):
        raise PlanError(f"{where} must be a string")
    return v


def _as_bool(v: Any, *, where: str, default: bool) -> bool:
    if v is None:
        return default
    if not isinstance(v, bool):
        raise PlanError(f"{where} must be a boolean")
    return v


def _as_int(v: Any, *, where: str, default: int) -> int:
    if v is None:
        return default
    if not isinstance(v, int):
        raise PlanError(f"{where} must be an integer")
    return v


def _interpolate(obj: Any, variables: Mapping[str, str]) -> Any:
    if isinstance(obj, str):
        def repl(m: re.Match[str]) -> str:
            key = m.group(1)
            return variables.get(key, m.group(0))

        return _VAR_RE.sub(repl, obj)
    if isinstance(obj, list):
        return [_interpolate(i, variables) for i in obj]
    if isinstance(obj, dict):
        return {k: _interpolate(v, variables) for k, v in obj.items()}
    return obj


def load_plan(plan_path: Path, *, extra_vars: Optional[Mapping[str, str]] = None) -> Plan:
    try:
        raw = json.loads(plan_path.read_text(encoding="utf-8"))
    except FileNotFoundError as e:
        raise PlanError(f"plan not found: {plan_path}") from e
    except json.JSONDecodeError as e:
        raise PlanError(f"invalid json: {e}") from e

    if not isinstance(raw, dict):
        raise PlanError("plan root must be an object")

    base_vars: dict[str, str] = {}
    raw_vars = _as_dict(raw.get("vars"), where="vars")
    for k, v in raw_vars.items():
        if not isinstance(k, str) or not isinstance(v, str):
            raise PlanError("vars must be a string-to-string object")
        base_vars[k] = v
    if extra_vars:
        for k, v in extra_vars.items():
            base_vars[str(k)] = str(v)

    raw = _interpolate(raw, base_vars)

    name = _as_str(raw.get("name"), where="name") or plan_path.stem

    browser_raw = _as_dict(raw.get("browser"), where="browser")
    args_list = _as_list(browser_raw.get("args"), where="browser.args")
    for i, a in enumerate(args_list):
        if not isinstance(a, str):
            raise PlanError(f"browser.args[{i}] must be a string")
    browser = BrowserConfig(
        channel=_as_str(browser_raw.get("channel"), where="browser.channel"),
        headless=_as_bool(browser_raw.get("headless"), where="browser.headless", default=True),
        slow_mo_ms=_as_int(browser_raw.get("slowMoMs"), where="browser.slowMoMs", default=0),
        args=tuple(args_list),
    )

    context_raw = _as_dict(raw.get("context"), where="context")
    viewport = context_raw.get("viewport")
    if viewport is not None:
        if not isinstance(viewport, dict):
            raise PlanError("context.viewport must be an object")
        for k in ("width", "height"):
            if k not in viewport or not isinstance(viewport[k], int):
                raise PlanError("context.viewport requires integer width/height")

    context = ContextConfig(
        viewport=viewport,
        storage_state=_as_str(context_raw.get("storageState"), where="context.storageState"),
        user_agent=_as_str(context_raw.get("userAgent"), where="context.userAgent"),
        locale=_as_str(context_raw.get("locale"), where="context.locale"),
        timezone_id=_as_str(context_raw.get("timezoneId"), where="context.timezoneId"),
    )

    artifacts_dir = _as_str(raw.get("artifactsDir"), where="artifactsDir") or "artifacts"

    tests_raw = _as_list(raw.get("tests"), where="tests")
    if not tests_raw:
        raise PlanError("tests is required and cannot be empty")

    tests: list[TestCase] = []
    for i, t in enumerate(tests_raw):
        if not isinstance(t, dict):
            raise PlanError(f"tests[{i}] must be an object")
        test_name = _as_str(t.get("name"), where=f"tests[{i}].name", required=True)
        steps_raw = _as_list(t.get("steps"), where=f"tests[{i}].steps")
        if not steps_raw:
            raise PlanError(f"tests[{i}].steps cannot be empty")

        steps: list[Step] = []
        for j, s in enumerate(steps_raw):
            if not isinstance(s, dict):
                raise PlanError(f"tests[{i}].steps[{j}] must be an object")
            action = _as_str(s.get("action"), where=f"tests[{i}].steps[{j}].action", required=True)
            params: MutableMapping[str, Any] = dict(s)
            params.pop("action", None)
            steps.append(Step(action=action, params=dict(params)))

        tests.append(TestCase(name=test_name, steps=tuple(steps)))

    return Plan(
        name=name,
        browser=browser,
        context=context,
        tests=tuple(tests),
        artifacts_dir=artifacts_dir,
        vars=base_vars,
    )
