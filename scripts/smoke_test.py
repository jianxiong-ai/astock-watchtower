#!/usr/bin/env python3
"""Minimal deployment smoke test for astock-watchtower.

Usage:
  python3 scripts/smoke_test.py

Environment:
  API_BASE_URL=http://localhost:8000
  WEB_BASE_URL=http://localhost:3000
  SMOKE_TIMEOUT=12
"""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000").rstrip("/")
WEB_BASE_URL = os.getenv("WEB_BASE_URL", "http://localhost:3000").rstrip("/")
TIMEOUT = float(os.getenv("SMOKE_TIMEOUT", "12"))


@dataclass
class Check:
    name: str
    ok: bool
    detail: str


def fetch_json(url: str) -> dict[str, Any]:
    request = Request(url, headers={"User-Agent": "astock-watchtower-smoke-test/0.1"})
    with urlopen(request, timeout=TIMEOUT) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_text(url: str) -> str:
    request = Request(url, headers={"User-Agent": "astock-watchtower-smoke-test/0.1"})
    with urlopen(request, timeout=TIMEOUT) as response:
        return response.read().decode("utf-8", errors="replace")


def run_check(name: str, fn) -> Check:
    started = time.time()
    try:
        detail = fn()
        elapsed = time.time() - started
        return Check(name=name, ok=True, detail=f"{detail} ({elapsed:.2f}s)")
    except (HTTPError, URLError, TimeoutError, OSError, ValueError, KeyError) as exc:
        elapsed = time.time() - started
        return Check(name=name, ok=False, detail=f"{exc} ({elapsed:.2f}s)")


def main() -> int:
    checks = [
        run_check("api /health", lambda: "ok" if fetch_json(f"{API_BASE_URL}/health").get("ok") else "not ok"),
        run_check(
            "api /api/system/health",
            lambda: f"status={fetch_json(f'{API_BASE_URL}/api/system/health').get('status')}",
        ),
        run_check(
            "api /api/scheduler/status",
            lambda: f"running={fetch_json(f'{API_BASE_URL}/api/scheduler/status').get('running')}",
        ),
        run_check(
            "web /",
            lambda: "contains title" if "ASTOCK-WATCHTOWER" in fetch_text(f"{WEB_BASE_URL}/") else "title missing",
        ),
        run_check(
            "web /health",
            lambda: "contains health page" if "系统健康检查" in fetch_text(f"{WEB_BASE_URL}/health") else "health page missing",
        ),
    ]

    failed = [item for item in checks if not item.ok]
    for item in checks:
        prefix = "PASS" if item.ok else "FAIL"
        print(f"[{prefix}] {item.name}: {item.detail}")

    if failed:
        print(f"\n{len(failed)} smoke check(s) failed.", file=sys.stderr)
        return 1
    print("\nAll smoke checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
