"""
Mock "legacy" core-banking admin console.

Why this exists (see REPORT.md section 1 for the full reasoning):
Real bank back-office screens are server-rendered, table-heavy, and have
no test IDs or stable CSS hooks -- the only reliable surface is what a
human operator reads and clicks. This app deliberately reproduces that:
plain <table> layouts, no id/data-testid attributes on interactive
elements, and a handful of REPRODUCIBLE runtime conditions (not-found,
validation error, permission denial, session-timeout interstitial) so
the agent and replay engine have real error states to detect and handle
-- not just a happy path.

This is a stand-in for a real bank system, per the assignment's
"pick a proxy target" instruction. No real data, no real credentials.
"""

from flask import Flask, request, redirect, url_for, session
import uuid
import random

app = Flask(__name__)
app.secret_key = "dev-only-not-a-real-secret"  # local mock app only

# ---------------------------------------------------------------------------
# In-memory "core banking" data. Nothing here is real. IDs are fake.
# ---------------------------------------------------------------------------
MEMBERS = {
    "12345": {"name": "Dana Whitfield", "savings": 4820.11, "checking": 1023.55, "flagged": False},
    "67890": {"name": "Marcus Ilo", "savings": 150.00, "checking": 42.10, "flagged": False},
    "99999": {"name": "Restricted Test Member", "savings": 0.0, "checking": 0.0, "flagged": True},
}

SUBACCOUNTS = {}  # member_id -> list of {type, deposit, confirmation_no}


def base_page(title, body, interstitial=False):
    """Wraps body HTML in a deliberately old-school, nested-table shell.
    No semantic tags, no ids/classes on interactive elements -- forces
    locator strategies that don't depend on a clean DOM."""
    interstitial_html = ""
    if interstitial:
        interstitial_html = """
        <table border="1" cellpadding="10" style="position:fixed;top:40%;left:35%;background:#fff8dc;">
          <tr><td>
            <table><tr><td>Your session will expire soon.</td></tr>
            <tr><td><form method="post" action="/extend-session">
              <button type="submit">Extend Session</button></form></td></tr></table>
          </td></tr>
        </table>
        """
    return f"""
    <html><head><title>{title}</title></head>
    <body>
    <table width="100%"><tr><td>
      <table><tr><td><b>CoreServ Admin Console</b></td></tr></tr></table>
      <table><tr><td>
        {body}
      </td></tr></table>
    </td></tr></table>
    {interstitial_html}
    </body></html>
    """


@app.route("/", methods=["GET"])
def home():
    body = """
    <table><tr><td>Member Lookup</td></tr>
    <tr><td>
      <form method="get" action="/members/search">
        <table><tr>
          <td>Member ID:</td>
          <td><input type="text" name="member_id"></td>
          <td><button type="submit">Search</button></td>
        </tr></table>
      </form>
    </td></tr></table>
    """
    return base_page("CoreServ - Home", body)


@app.route("/members/search", methods=["GET"])
def search():
    member_id = request.args.get("member_id", "").strip()
    # Occasionally (and deterministically when forced) show a session
    # interstitial -- a RECOVERABLE condition, not a failure.
    force_interstitial = request.args.get("simulate_interstitial") == "1"
    show_interstitial = force_interstitial or (random.random() < 0.05)

    if not member_id:
        return base_page("Search", "<table><tr><td>Enter a member ID.</td></tr></table>")

    if member_id not in MEMBERS:
        # Expected BUSINESS OUTCOME, not a crash.
        body = f"""
        <table><tr><td>No such member: {member_id}</td></tr>
        <tr><td><i>Result code: MEMBER_NOT_FOUND</i></td></tr></table>
        """
        return base_page("Search Result", body, interstitial=show_interstitial)

    m = MEMBERS[member_id]
    if m["flagged"]:
        # Expected BUSINESS OUTCOME (permission denial), not a crash.
        body = f"""
        <table><tr><td>Access denied for member {member_id}.</td></tr>
        <tr><td><i>Result code: PERMISSION_DENIED</i></td></tr>
        <tr><td>This record requires supervisor approval to view.</td></tr></table>
        """
        return base_page("Search Result", body, interstitial=show_interstitial)

    body = f"""
    <table><tr><td>
      <table border="1">
        <tr><td>Name</td><td>{m['name']}</td></tr>
        <tr><td>Member ID</td><td>{member_id}</td></tr>
        <tr><td>Savings Balance</td><td>${m['savings']:.2f}</td></tr>
        <tr><td>Checking Balance</td><td>${m['checking']:.2f}</td></tr>
      </table>
    </td></tr>
    <tr><td>
      <form method="get" action="/members/{member_id}/new-subaccount">
        <button type="submit">Open Sub-Account</button>
      </form>
    </td></tr></table>
    """
    return base_page("Member Detail", body, interstitial=show_interstitial)


@app.route("/members/<member_id>/new-subaccount", methods=["GET"])
def new_subaccount_form(member_id):
    if member_id not in MEMBERS:
        return base_page("Error", "<table><tr><td>No such member.</td></tr></table>")
    body = f"""
    <table><tr><td>Open Sub-Account for {member_id}</td></tr>
    <tr><td>
      <form method="post" action="/members/{member_id}/new-subaccount">
        <table>
          <tr><td>Account Type:</td><td>
            <select name="account_type">
              <option value="savings">Savings</option>
              <option value="checking">Checking</option>
            </select></td></tr>
          <tr><td>Initial Deposit:</td><td><input type="text" name="deposit"></td></tr>
          <tr><td colspan="2"><button type="submit">Continue</button></td></tr>
        </table>
      </form>
    </td></tr></table>
    """
    return base_page("New Sub-Account", body)


@app.route("/members/<member_id>/new-subaccount", methods=["POST"])
def new_subaccount_submit(member_id):
    account_type = request.form.get("account_type", "")
    deposit_raw = request.form.get("deposit", "")
    try:
        deposit = float(deposit_raw)
        if deposit < 25:
            raise ValueError()
    except ValueError:
        # Expected BUSINESS OUTCOME: validation error, not a crash.
        body = f"""
        <table><tr><td>Validation error: initial deposit must be a number >= $25.</td></tr>
        <tr><td><i>Result code: VALIDATION_ERROR</i></td></tr>
        <tr><td><a href="/members/{member_id}/new-subaccount">Back</a></td></tr></table>
        """
        return base_page("Validation Error", body)

    body = f"""
    <table><tr><td>Confirm: open a {account_type} sub-account for {member_id}
      with an initial deposit of ${deposit:.2f}?</td></tr>
    <tr><td>
      <form method="post" action="/members/{member_id}/new-subaccount/confirm">
        <input type="hidden" name="account_type" value="{account_type}">
        <input type="hidden" name="deposit" value="{deposit}">
        <button type="submit">Confirm</button>
      </form>
    </td></tr></table>
    """
    return base_page("Confirm", body)


@app.route("/members/<member_id>/new-subaccount/confirm", methods=["POST"])
def new_subaccount_confirm(member_id):
    account_type = request.form.get("account_type")
    deposit = float(request.form.get("deposit"))
    confirmation_no = f"SA-{uuid.uuid4().hex[:8].upper()}"
    SUBACCOUNTS.setdefault(member_id, []).append(
        {"type": account_type, "deposit": deposit, "confirmation_no": confirmation_no}
    )
    body = f"""
    <table><tr><td>Sub-account created.</td></tr>
    <tr><td>Confirmation #: {confirmation_no}</td></tr></table>
    """
    return base_page("Confirmation", body)


@app.route("/extend-session", methods=["POST"])
def extend_session():
    return redirect(request.referrer or url_for("home"))


if __name__ == "__main__":
    app.run(port=5055, debug=True)
