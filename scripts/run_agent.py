"""
CLI: run the discovery agent on a goal, save the resulting capability.

Example:
    python scripts/run_agent.py \\
        --goal "Look up member 12345 and open a $100 savings sub-account, reach the confirmation screen" \\
        --target http://127.0.0.1:5055 \\
        --domain 127.0.0.1
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from discovery import run_discovery


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--goal", required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--domain", action="append", required=True, help="Allowed domain (repeatable)")
    args = parser.parse_args()

    capability = run_discovery(goal=args.goal, target_url=args.target, allowed_domains=args.domain)

    out_path = Path("artifacts/capabilities") / f"{capability.name.replace(' ', '_')}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(capability.to_json())

    print(f"\nCapability saved: {out_path}")
    print(f"  name: {capability.name}")
    print(f"  input_params: {[p.name for p in capability.input_params]}")
    print(f"  outputs: {[o.name for o in capability.outputs]}")
    print(f"  steps recorded: {len(capability.steps)}")


if __name__ == "__main__":
    main()
