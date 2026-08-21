"""
Minimal, deliberately mocked operator console (see REPORT.md section 5:
a full real-time co-browsing console is explicitly out of scope).

While a discovery or replay run is blocked waiting for a human, run this
in a second terminal to see the pending request and resolve it. The
actual manual work happens directly in the visible, non-headless browser
window the automation opened -- this console is just the signal/notify/
resume channel, not a re-implementation of the browser.

Example:
    python scripts/run_operator.py --run-dir evidence/discovery-1234567
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from escalation import operator_resume


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True)
    args = parser.parse_args()
    run_dir = Path(args.run_dir)

    intervention_path = run_dir / "intervention.json"
    if not intervention_path.exists():
        print("No pending intervention request found in", run_dir)
        return

    request = json.loads(intervention_path.read_text())
    print("=== Pending Intervention Request ===")
    print(json.dumps(request, indent=2))
    print("\nGo perform the needed manual steps in the open browser window.")
    note = input("When done, describe what you did (this is captured as evidence): ")

    operator_resume(run_dir, note)
    print("Control handed back to automation.")


if __name__ == "__main__":
    main()
