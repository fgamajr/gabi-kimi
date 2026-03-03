#!/usr/bin/env python3
"""Local check for User-Agent rotation; no external requests are performed."""

from __future__ import annotations

from crawler.user_agent_rotator import create_default_rotator


def main() -> int:
    rotator = create_default_rotator()
    picks = [rotator.next() for _ in range(12)]

    unique = len(set(picks))
    print("User-Agent picks:")
    for i, ua in enumerate(picks, start=1):
        print(f"{i:02d}: {ua}")

    if unique < 2:
        print("\nFAIL: rotation did not occur (only one unique User-Agent).")
        return 1

    # Round-robin check: sequence repeats exactly after pool size.
    pool_size = len(rotator.user_agents)
    if picks[0] != picks[pool_size]:
        print("\nFAIL: expected deterministic round-robin rotation.")
        return 1

    print(f"\nOK: rotation active ({unique} unique user agents over {len(picks)} picks).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
