"""
CLI: replay a saved capability with new input params, no LLM involved.

Example:
    python scripts/run_replay.py \\
        --artifact artifacts/capabilities/Open_Savings_Subaccount.json \\
        --param member_id=67890 --param deposit=100
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.schemas import Capability
from replay import run_replay


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact", required=True)
    parser.add_argument("--param", action="append", default=[], help="key=value, repeatable")
    args = parser.parse_args()

    params = dict(p.split("=", 1) for p in args.param)
    capability = Capability.from_json(Path(args.artifact).read_text())

    result = run_replay(capability, params)

    print(result.to_json())
    sys.exit(0 if result.outcome.value in ("success", "business_outcome") else 1)


if __name__ == "__main__":
    main()
