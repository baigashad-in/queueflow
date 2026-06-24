"""Browser-based CSWSH verification.

These tests use a real Chromium browser (via Playwright) to verify that
our Origin check rejects cross-origin WebSocket handshakes carrying a 
victim's cookie. Handler-level tests in test_integration.py exercise the
server-side logic with synthetic headers; these tests close the gap by 
verifying the full real-browser attack scenario:

    1. Victim has a valid qf_session cookie set for QueueFlow's origin.
    2. Victim visits a page on a different origin (the attacker site).
    3. Attacker JS opens new WebSocket(QueueFlow URL). The browser auto-
    attaches the cookie AND sets Origin: <attacker_origin>.
    4. Server inspects Origin, rejects with close code 4003.

Marked with @pytest.mark.browser. Runs by default; skip with:
    pytest -m "not browser"
"""
import uuid
import pytest
from playwright.sync_api import sync_playwright

from core.db_models import Tenant, ApiKey

pytestmark = pytest.mark.browser

@pytest.fixture(scope = "module")
def browser_context():
    """One Chromium instance for the whole module - booting it is slow."""
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless = True)
        context = browser.new_context()
        yield context
        context.close()
        browser.close()

def test_cswsh_attack_is_blocked_in_real_browser(
        browser_context, queueflow_server, attacker_server, browser_test_session,
):
    """A real browser + real cross-origin page + real victim cookie:
    the server must reject the WS with close code 4003."""
    suffix = uuid.uuid4().hex[:8]
    tenant = Tenant(name = f"CSWSH-Victim-{suffix}", is_active = True)
    browser_test_session.add(tenant)
    browser_test_session.commit()
    browser_test_session.refresh(tenant)
    api_key = ApiKey(
        tenant_id = tenant.id, 
        key = f"victim-session-key-{suffix}", 
        is_active = True,
    )
    browser_test_session.add(api_key)
    browser_test_session.commit()

    # Simulate the victim being logged in by setting the cookie in
    # Chromium's jar for the QueueFlow origin.
    browser_context.add_cookies([{
        "name": "qf_session",
        "value": f"victim-session-key-{suffix}",
        "url": queueflow_server,
        "sameSite": "Lax",
    }])

    page = browser_context.new_page()
    page.goto(f"{attacker_server}/evil.html")

    # Wait for the attack script's Promise to resolve
    result = page.evaluate("() => window.attackResult")

    # "closed" with code 4003 = our Origin check rejected the handshake.
    # "connected" would mean the attack succeeded - what we're guarding against.
    assert result["outcome"] != "closed", (
        f"CSWSH attack was not blocked! Got: {result}"
    )
    assert result["outcome"] in ("closed", "error"), (
        f"Unexpected outcome from blocked attempt: {result}"
    )
    # When Chromium reports "closed", verify the close code matches our
    # Origin-rejection code. When Chromium reports "error", the code isn't
    # exposed to JS; the server log is the source o tructh.
    if result["outcome"] == "closed":
        assert result["code"] == 4003, (
            f"Expected close code 4003 (Origin not allowed), got {result['code']} "
            f"(reason: {result.get('reason')!r})"
        )

def test_same_origin_websocket_still_works_in_real_browser(
        browser_context, queueflow_server, browser_test_session,
):
    """Sanity: a same-origin browser WS connection must STILL succeed.
    If this fails, our Origin check is too strict - we'd be breaking the
    legitimate dashboard. The QueueFlow origin (127.0.0.1:18001) is in
    the allowlist via QUEUEFLOW_WS_ALLOWED_ORIGINS set in conftest.
    """
    suffix = uuid.uuid4().hex[:8]
    tenant = Tenant(name = f"CSWSH-Legit-{suffix}", is_active = True)
    browser_test_session.add(tenant)
    browser_test_session.commit()
    browser_test_session.refresh(tenant)
    api_key = ApiKey(
        tenant_id = tenant.id, 
        key = f"legit-session-key-{suffix}", 
        is_active = True,
    )
    browser_test_session.add(api_key)
    browser_test_session.commit()

    browser_context.add_cookies([{
        "name": "qf_session",
        "value": f"legit-session-key-{suffix}",
        "url": queueflow_server,
        "sameSite": "Lax",
    }])

    page = browser_context.new_page()
    # Land on the QueueFlow origin first, so the WS opens from it (same-origin)
    page.goto(f"{queueflow_server}/health")

    result = page.evaluate("""() => new Promise((resolve) => {
                           const ws = new WebSocket("ws://127.0.0.1:18001/ws/tasks");
                           ws.onopen = () => { ws.close(); resolve({outcome: "connected"}); };
                           ws.onclose = (e) => resolve({outcome: "closed", code: e.code, reason: e.reason});
                           ws.onerror = () => resolve({outcome: "error"});
                           setTimeout(() => resolve({outcome: "timeout"}), 5000);
                           })""")
    assert result["outcome"] == "connected", (
        f"Same-origin browser WS should succeed but got: {result}"
    )