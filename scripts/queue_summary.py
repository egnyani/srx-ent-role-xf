#!/usr/bin/env python3
"""Print a quick summary of the local application queue."""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.apply_queue import load_queue


def main() -> int:
    items = load_queue()
    print(f"Total queue items: {len(items)}")
    if not items:
        return 0

    by_status = Counter(item.get("status", "unknown") for item in items)
    by_target = Counter(item.get("apply_target", "unknown") for item in items)
    auto_supported = sum(1 for item in items if item.get("auto_apply_supported"))

    print("By status:")
    for key in sorted(by_status):
        print(f"  {key}: {by_status[key]}")

    print("By target:")
    for key in sorted(by_target):
        print(f"  {key}: {by_target[key]}")

    print(f"Auto-apply ready (initial ATS scope): {auto_supported}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
