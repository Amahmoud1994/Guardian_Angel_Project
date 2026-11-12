"""Outgoing email: Resend's HTTPS API when RESEND_API_KEY is set (works where SMTP ports are blocked), else SMTP."""
import io
import json
import urllib.error
import urllib.request

import pytest

import main


@pytest.fixture
def resend(monkeypatch):
    """Fake Resend API: records every request instead of sending."""
    calls = []

    class FakeResponse(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def fake_urlopen(req, timeout=None):
        calls.append({"url": req.full_url, "headers": {k.lower(): v for k, v in req.header_items()},
                      "payload": json.loads(req.data), "timeout": timeout})
        return FakeResponse(b'{"id": "abc"}')

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setenv("RESEND_API_KEY", "re_test_key")
    monkeypatch.setenv("EMAIL_FROM", "Guardian Angel <no-reply@guardianangel.at>")
    monkeypatch.setenv("SUPPORT_EMAIL", "support@guardianangel.at")
    return calls


def test_resend_is_used_when_key_is_set(resend):
    assert main.email_provider() == "resend"
    main.deliver_email(["a@example.com", "b@example.com"], "Subject ✓", "<p>Hi</p>")
    assert [c["payload"]["to"] for c in resend] == [["a@example.com"], ["b@example.com"]]  # one email each
    first = resend[0]
    assert first["url"] == "https://api.resend.com/emails"
    assert first["headers"]["authorization"] == "Bearer re_test_key"
    assert first["payload"]["from"] == "Guardian Angel <no-reply@guardianangel.at>"
    assert first["payload"]["reply_to"] == "support@guardianangel.at"
    assert first["payload"]["subject"] == "Subject ✓" and first["payload"]["html"] == "<p>Hi</p>"
    assert first["timeout"] == main.SMTP_TIMEOUT


def test_resend_errors_are_reported(resend, monkeypatch):
    def failing(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 403, "Forbidden", {}, io.BytesIO(b'{"message":"domain not verified"}'))
    monkeypatch.setattr(urllib.request, "urlopen", failing)
    with pytest.raises(RuntimeError, match="HTTP 403.*domain not verified"):
        main.deliver_email(["a@example.com"], "s", "<p>x</p>")


async def test_app_emails_go_through_resend(resend):
    await main.send_html_email("tester@example.com", "🛡 Welcome", "<p>You're in</p>")
    assert resend[-1]["payload"]["to"] == ["tester@example.com"]


def test_smtp_is_the_fallback(monkeypatch):
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    monkeypatch.setenv("SMTP_USER", "me@gmail.com")
    monkeypatch.setenv("SMTP_PASS", "app pass")
    sent = []

    class FakeSMTP:
        def __init__(self, host, port, timeout=None): self.timeout = timeout
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def ehlo(self): pass
        def starttls(self): pass
        def login(self, user, pw): assert pw == "apppass"
        def sendmail(self, frm, to, msg): sent.append((to, self.timeout))

    monkeypatch.setattr(main.smtplib, "SMTP", FakeSMTP)
    assert main.email_provider() == "smtp"
    main.deliver_email(["a@example.com", "b@example.com"], "s", "<p>x</p>")
    assert sent == [("a@example.com", main.SMTP_TIMEOUT), ("b@example.com", main.SMTP_TIMEOUT)]


def test_no_provider_configured(monkeypatch):
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    monkeypatch.setenv("SMTP_USER", "")
    assert not main.email_configured()
    with pytest.raises(RuntimeError, match="isn't configured"):
        main.deliver_email(["a@example.com"], "s", "<p>x</p>")
