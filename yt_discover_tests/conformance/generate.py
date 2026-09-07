"""Generate deterministic conformance datasets from the command line."""

from __future__ import annotations

import argparse
import json

from .dataset import PROFILE_SIZES, SEED, generate_rows


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--profile", choices=tuple(PROFILE_SIZES), default="small")
    group.add_argument("--size", type=int)
    parser.add_argument("--seed", type=int, default=SEED)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    rows = generate_rows(
        None if args.size is not None else args.profile,
        exact_size=args.size,
        seed=args.seed,
    )
    print(json.dumps(rows, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
