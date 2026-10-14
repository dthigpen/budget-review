
# src/budget_review/cli.py

import argparse
from pathlib import Path

from .budget import run


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Review spending against a budget."
    )
    parser.add_argument(
        "--budget",
        type=Path,
        required=True,
        help="Path to the budget JSON file.",
    )
    parser.add_argument(
        "--ledger",
        type=Path,
        required=True,
        help="Path to the Beancount ledger.",
    )

    args = parser.parse_args()

    for name, path in (
        ("Budget", args.budget),
        ("Ledger", args.ledger),
    ):
        if not path.is_file():
            parser.error(f"{name} file does not exist: {path}")

    run(args.budget, args.ledger)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
