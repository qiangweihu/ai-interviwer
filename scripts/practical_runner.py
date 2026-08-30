#!/usr/bin/env python3
"""Safe practical-task CLI used by the Codex skills.

It always delegates to the private runner HTTP service.  It deliberately has
no option to execute a candidate file in the current workspace.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from urllib.error import URLError
from urllib.request import Request, urlopen


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a practical interview task in the isolated runner")
    parser.add_argument("--runner-url", default=os.getenv("PRACTICAL_RUNNER_URL", "http://runner:8080"))
    parser.add_argument("--task", required=True, help="JSON file containing task_type, tests and materials")
    parser.add_argument("--language", required=True, choices=("python", "cpp", "sql", "text"))
    parser.add_argument("--source", required=True, help="Candidate source file; it is uploaded, never executed locally")
    parser.add_argument("--hidden", action="store_true", help="Use private tests; do not print test inputs")
    args = parser.parse_args()
    try:
        with open(args.task, encoding="utf-8") as task_file:
            payload = json.load(task_file)
        with open(args.source, encoding="utf-8") as source_file:
            source = source_file.read()
    except (OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "failed", "runtime_error": str(exc)}, ensure_ascii=False))
        return 2
    payload.update({"language": args.language, "source": source, "hidden": args.hidden})
    request = Request(
        f"{args.runner_url.rstrip('/')}/run",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    token = os.getenv("PRACTICAL_RUNNER_TOKEN", "")
    if token:
        request.add_header("X-Runner-Token", token)
    try:
        with urlopen(request, timeout=18) as response:
            sys.stdout.write(response.read().decode("utf-8"))
            sys.stdout.write("\n")
    except (OSError, URLError):
        # Do not echo the internal runner URL or Docker diagnostics to CLI
        # output/logs. Callers only need the stable unavailable status.
        print(json.dumps({"status": "unavailable", "runtime_error": "实操题执行器暂时不可用"}, ensure_ascii=False))
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
