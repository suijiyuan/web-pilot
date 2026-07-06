from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urljoin

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page, expect, sync_playwright

from .errors import StepError
from .plan import Plan, Step, TestCase


@dataclass(frozen=True)
class RunOptions:
    base_url: Optional[str] = None
    headed: Optional[bool] = None
    channel: Optional[str] = None
    trace: bool = False
    screenshot_on_failure: bool = True
    timeout_ms: int = 30_000


@dataclass(frozen=True)
class TestResult:
    name: str
    passed: bool
    error: Optional[str] = None
    duration_ms: int = 0
    artifacts_dir: Optional[Path] = None


def _ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def _resolve_url(url: str, base_url: Optional[str]) -> str:
    if base_url and url.startswith("/"):
        return urljoin(base_url.rstrip("/") + "/", url.lstrip("/"))
    return url


def _get_param(params: dict[str, Any], key: str, expected_type: Any, *, where: str, required: bool = False) -> Any:
    if key not in params or params[key] is None:
        if required:
            raise StepError(f"{where}.{key} is required")
        return None
    val = params[key]
    if expected_type is not Any and not isinstance(val, expected_type):
        raise StepError(f"{where}.{key} must be {expected_type}")
    return val


def _run_step(page: Page, step: Step, *, base_url: Optional[str], timeout_ms: int, artifacts_dir: Path) -> None:
    a = step.action
    p = step.params
    where = f"step({a})"

    if a == "goto":
        url = _get_param(p, "url", str, where=where, required=True)
        wait_until = _get_param(p, "waitUntil", str, where=where) or "load"
        page.goto(_resolve_url(url, base_url), wait_until=wait_until, timeout=timeout_ms)
        return

    if a == "click":
        selector = _get_param(p, "selector", str, where=where, required=True)
        page.click(selector, timeout=timeout_ms)
        return

    if a == "dblclick":
        selector = _get_param(p, "selector", str, where=where, required=True)
        page.dblclick(selector, timeout=timeout_ms)
        return

    if a == "fill":
        selector = _get_param(p, "selector", str, where=where, required=True)
        text = _get_param(p, "text", str, where=where, required=True)
        page.fill(selector, text, timeout=timeout_ms)
        return

    if a == "type":
        selector = _get_param(p, "selector", str, where=where, required=True)
        text = _get_param(p, "text", str, where=where, required=True)
        delay_ms = _get_param(p, "delayMs", int, where=where) or 0
        page.type(selector, text, delay=delay_ms, timeout=timeout_ms)
        return

    if a == "press":
        selector = _get_param(p, "selector", str, where=where)
        key = _get_param(p, "key", str, where=where, required=True)
        if selector:
            page.press(selector, key, timeout=timeout_ms)
        else:
            page.keyboard.press(key)
        return

    if a == "wait_for_selector":
        selector = _get_param(p, "selector", str, where=where, required=True)
        state = _get_param(p, "state", str, where=where) or "visible"
        page.wait_for_selector(selector, state=state, timeout=timeout_ms)
        return

    if a == "wait":
        ms = _get_param(p, "ms", int, where=where, required=True)
        page.wait_for_timeout(ms)
        return

    if a == "expect_visible":
        selector = _get_param(p, "selector", str, where=where, required=True)
        expect(page.locator(selector)).to_be_visible(timeout=timeout_ms)
        return

    if a == "expect_hidden":
        selector = _get_param(p, "selector", str, where=where, required=True)
        expect(page.locator(selector)).to_be_hidden(timeout=timeout_ms)
        return

    if a == "expect_text":
        selector = _get_param(p, "selector", str, where=where, required=True)
        text = _get_param(p, "text", str, where=where, required=True)
        contains = bool(_get_param(p, "contains", bool, where=where) or False)
        loc = page.locator(selector)
        if contains:
            expect(loc).to_contain_text(text, timeout=timeout_ms)
        else:
            expect(loc).to_have_text(text, timeout=timeout_ms)
        return

    if a == "expect_title":
        text = _get_param(p, "text", str, where=where, required=True)
        contains = bool(_get_param(p, "contains", bool, where=where) or False)
        if contains:
            expect(page).to_have_title(re.compile(re.escape(text)), timeout=timeout_ms)
        else:
            expect(page).to_have_title(text, timeout=timeout_ms)
        return

    if a == "expect_url":
        text = _get_param(p, "text", str, where=where, required=True)
        contains = bool(_get_param(p, "contains", bool, where=where) or False)
        if contains:
            expect(page).to_have_url(re.compile(re.escape(text)), timeout=timeout_ms)
        else:
            expect(page).to_have_url(text, timeout=timeout_ms)
        return

    if a == "screenshot":
        path = _get_param(p, "path", str, where=where, required=True)
        full_page = bool(_get_param(p, "fullPage", bool, where=where) or False)
        final_path = Path(path)
        if not final_path.is_absolute():
            final_path = artifacts_dir / final_path
        _ensure_dir(final_path.parent)
        page.screenshot(path=str(final_path), full_page=full_page)
        return

    if a == "evaluate":
        expression = _get_param(p, "expression", str, where=where, required=True)
        page.evaluate(expression)
        return

    if a == "set_viewport":
        width = _get_param(p, "width", int, where=where, required=True)
        height = _get_param(p, "height", int, where=where, required=True)
        page.set_viewport_size({"width": width, "height": height})
        return

    raise StepError(f"unsupported action: {a}")


def _run_test(
    plan: Plan,
    test: TestCase,
    *,
    options: RunOptions,
    artifacts_root: Path,
) -> TestResult:
    test_dir = artifacts_root / test.name.replace("/", "_")
    _ensure_dir(test_dir)

    started = time.time()
    trace_path = test_dir / "trace.zip"
    failure_screenshot_path = test_dir / "failure.png"
    browser = None
    context = None
    page = None
    try:
        with sync_playwright() as p:
            channel = options.channel if options.channel is not None else plan.browser.channel
            headless = plan.browser.headless
            if options.headed is True:
                headless = False
            if options.headed is False:
                headless = True

            browser = p.chromium.launch(
                channel=channel,
                headless=headless,
                slow_mo=plan.browser.slow_mo_ms,
                args=list(plan.browser.args),
            )

            context_args: dict[str, Any] = {}
            if plan.context.viewport is not None:
                context_args["viewport"] = plan.context.viewport
            if plan.context.storage_state is not None:
                context_args["storage_state"] = plan.context.storage_state
            if plan.context.user_agent is not None:
                context_args["user_agent"] = plan.context.user_agent
            if plan.context.locale is not None:
                context_args["locale"] = plan.context.locale
            if plan.context.timezone_id is not None:
                context_args["timezone_id"] = plan.context.timezone_id

            context = browser.new_context(**context_args)

            if options.trace:
                context.tracing.start(screenshots=True, snapshots=True, sources=False)

            page = context.new_page()
            page.set_default_timeout(options.timeout_ms)

            for step in test.steps:
                _run_step(
                    page,
                    step,
                    base_url=options.base_url,
                    timeout_ms=options.timeout_ms,
                    artifacts_dir=test_dir,
                )

            if options.trace:
                context.tracing.stop(path=str(trace_path))

            ended = time.time()
            return TestResult(
                name=test.name,
                passed=True,
                duration_ms=int((ended - started) * 1000),
                artifacts_dir=test_dir,
            )
    except (StepError, PlaywrightError, AssertionError, TimeoutError) as e:
        try:
            if options.screenshot_on_failure and page is not None:
                page.screenshot(path=str(failure_screenshot_path), full_page=True)
        except Exception:
            pass

        try:
            if options.trace and context is not None:
                context.tracing.stop(path=str(trace_path))
        except Exception:
            pass

        ended = time.time()
        return TestResult(
            name=test.name,
            passed=False,
            error=str(e),
            duration_ms=int((ended - started) * 1000),
            artifacts_dir=test_dir,
        )
    finally:
        if context is not None:
            try:
                context.close()
            except Exception:
                pass

        if browser is not None:
            try:
                browser.close()
            except Exception:
                pass


def run_plan(plan: Plan, *, options: RunOptions, only_tests: Optional[set[str]] = None) -> list[TestResult]:
    artifacts_root = Path(plan.artifacts_dir) / plan.name
    _ensure_dir(artifacts_root)

    results: list[TestResult] = []
    for test in plan.tests:
        if only_tests is not None and test.name not in only_tests:
            continue
        results.append(_run_test(plan, test, options=options, artifacts_root=artifacts_root))
    return results
