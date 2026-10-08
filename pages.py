"""Public, server-rendered pages: privacy policy, terms, account deletion info, password reset.

These must be reachable without signing in (Google Play links to the privacy policy and the
account-deletion page from the store listing). Content is a starting draft — have it reviewed
before a public launch, and keep LEGAL_UPDATED in sync when the wording changes.
"""

import html
import os

LEGAL_UPDATED = "October 7, 2026"


def operator_name() -> str:
    return os.getenv("OPERATOR_NAME", "the Guardian Angel team")


def support_email() -> str:
    return os.getenv("SUPPORT_EMAIL") or os.getenv("SMTP_FROM") or os.getenv("SMTP_USER") or "support@example.com"


def page(title: str, body_html: str, accent: str = "#00e5a0") -> str:
    """Shared shell for every public page — mobile-first, matches the app's dark theme."""
    return f"""<!DOCTYPE html><html lang="en"><head>
<meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>{html.escape(title)} · Guardian Angel</title>
<style>
  body{{margin:0;background:#0a0d0f;color:#e8eef2;font-family:Arial,Helvetica,sans-serif;line-height:1.6;}}
  main{{max-width:720px;margin:0 auto;padding:24px 16px 64px;}}
  .brand{{font-size:12px;color:#5a7080;letter-spacing:1px;margin-bottom:8px;}}
  .brand a{{color:inherit;text-decoration:none;}}
  h1{{font-size:24px;color:{accent};margin:0 0 4px;}}
  h2{{font-size:17px;margin:28px 0 8px;color:#e8eef2;}}
  p,li{{font-size:14px;color:#c8d4dc;}}
  .muted{{color:#5a7080;font-size:12px;}}
  a{{color:#00e5a0;}}
  .callout{{border:1px solid #ff4757;background:#1f0e0e;border-radius:10px;padding:12px 16px;margin:16px 0;}}
  .card{{background:#161b1f;border:1px solid #1f2a30;border-radius:12px;padding:20px;margin-top:16px;}}
  label{{display:block;font-size:12px;color:#5a7080;margin:12px 0 6px;}}
  input{{width:100%;box-sizing:border-box;padding:11px 14px;border-radius:8px;border:1px solid #1f2a30;
         background:#111518;color:#e8eef2;font-size:15px;}}
  button{{margin-top:18px;width:100%;padding:12px;border:none;border-radius:8px;background:#00e5a0;color:#0a0d0f;
          font-weight:bold;font-size:15px;cursor:pointer;}}
  .err{{color:#ff4757;font-size:13px;}}
</style></head><body><main>
<div class="brand"><a href="/">🛡 GUARDIAN ANGEL</a></div>
{body_html}
</main></body></html>"""


def _contact() -> str:
    e = html.escape(support_email())
    return f'<a href="mailto:{e}">{e}</a>'


def privacy_page() -> str:
    op = html.escape(operator_name())
    return page("Privacy Policy", f"""
<h1>Privacy Policy</h1>
<p class="muted">Last updated: {LEGAL_UPDATED}</p>

<p>Guardian Angel is a personal safety app operated by {op} ("we"). This policy explains what we
collect, why, and the choices you have. Questions: {_contact()}.</p>

<h2>What we collect</h2>
<ul>
  <li><strong>Account:</strong> username, password (stored only as a secure hash), optional email address.</li>
  <li><strong>Profile (optional):</strong> phone, address, date of birth, photo, blood type and medical notes.
      Blood type and medical notes are health information — you choose whether to provide them.</li>
  <li><strong>Guardians and companions:</strong> names and contact details you enter for the people you list.</li>
  <li><strong>Journeys:</strong> destination, route, map link, coordinates, country, check-in times, escalation
      events and messages between you and your guardians.</li>
  <li><strong>Location:</strong> your device's GPS position, only when you switch on live location for a journey,
      and only while the app is open.</li>
  <li><strong>Technical:</strong> push-notification tokens, app version, device/browser type, and error reports
      used to fix crashes.</li>
</ul>

<h2>Why we use it</h2>
<ul>
  <li>To run your journeys and check-ins, and to alert your guardians if you miss a check-in or enter your duress code.</li>
  <li>To prepare an encrypted case file for your guardians at the highest alert level.</li>
  <li>To send you notifications, password-reset emails and guardian verification emails.</li>
  <li>To keep the service secure and to fix problems.</li>
</ul>
<p>Our legal bases are performing the service you asked for, your explicit consent (for health and location
information, which you can withdraw at any time by deleting it or your account), and our legitimate interest in
keeping the service secure. <strong>We do not sell your data and do not use it for advertising.</strong></p>

<h2>Who sees it</h2>
<ul>
  <li><strong>Your guardians</strong> receive journey details, your last known location and, at the highest alert
      level, your case file (including profile and medical notes) — that is the purpose of the app.</li>
  <li><strong>Service providers</strong> that run the app for us: hosting and database, email delivery,
      push-notification services (Google, Apple, browser vendors) and error monitoring. They process data only
      on our instructions.</li>
  <li><strong>Authorities</strong> only when required by law, or when your guardians share information with them
      in an emergency.</li>
</ul>

<h2>How long we keep it</h2>
<p>We keep your data while your account exists. When you delete your account, your profile, guardians, saved and
past journeys, messages and location history are deleted immediately from the live database; backups are
overwritten within 30 days.</p>

<h2>Your rights</h2>
<p>You can view and edit your data in the app, download a copy (Profile → Download my data), and delete your
account (Profile → Delete account, or see <a href="/delete-account">how to delete your account</a>). Depending on
where you live (for example under the GDPR) you may also object to or restrict processing and complain to your
data-protection authority. Contact us at {_contact()}.</p>

<h2>Security</h2>
<p>Connections are encrypted (HTTPS), passwords are hashed, and case files are encrypted at rest. No system is
perfectly secure, so please use a strong, unique password.</p>

<h2>Children</h2>
<p>Guardian Angel is not intended for children under 16 without a parent's or guardian's involvement.</p>

<h2>Changes</h2>
<p>We'll update the date above when this policy changes and tell you in the app about important changes.</p>
""")


def terms_page() -> str:
    op = html.escape(operator_name())
    return page("Terms of Use", f"""
<h1>Terms of Use</h1>
<p class="muted">Last updated: {LEGAL_UPDATED}</p>

<div class="callout"><strong>Guardian Angel is not an emergency service.</strong> It does not contact police,
ambulance or other emergency services on your behalf. In an emergency, always call your local emergency number
first.</div>

<h2>The service</h2>
<p>Guardian Angel, operated by {op}, helps you share journey plans with people you trust ("guardians") and alerts
them if you don't check in. Alerts depend on things outside our control — your device, battery, mobile signal,
internet access, email and push-notification providers, and whether your guardians see and act on the alert.
<strong>Alerts may be delayed or may not arrive, and the service is provided "as is" without any guarantee.</strong></p>

<h2>Your responsibilities</h2>
<ul>
  <li>Keep your safe and duress codes private, and your guardians' contact details up to date.</li>
  <li>Only add people as guardians who have agreed to it (use guardian verification).</li>
  <li>Don't misuse the service — for example to harass people, send false alerts, or track others without consent.</li>
  <li>Keep your password secure; you're responsible for activity on your account.</li>
</ul>

<h2>Beta</h2>
<p>During testing, features may change, break or be removed, and we may reset test data with notice.</p>

<h2>Liability</h2>
<p>To the extent allowed by law, we are not liable for any loss or harm arising from alerts that are delayed, not
delivered or not acted on, or from use of the service. Nothing in these terms limits liability that cannot be
limited by law.</p>

<h2>Ending</h2>
<p>You can stop using Guardian Angel and delete your account at any time. We may suspend accounts that break
these terms.</p>

<h2>Contact</h2>
<p>{_contact()} · See also our <a href="/privacy">Privacy Policy</a>.</p>
""")


def delete_account_page() -> str:
    return page("Delete Your Account", f"""
<h1>Delete your Guardian Angel account</h1>
<p>You can delete your account and all associated data at any time.</p>

<h2>In the app</h2>
<ol>
  <li>Open Guardian Angel and sign in.</li>
  <li>Go to the <strong>Profile</strong> tab.</li>
  <li>Scroll to <strong>Account</strong> and tap <strong>Delete account</strong>.</li>
  <li>Confirm with your password.</li>
</ol>

<h2>Without the app</h2>
<p>Email {_contact()} from the email address on your account (or include your username) with the subject
"Delete my account". We'll confirm and complete the deletion within 30 days.</p>

<h2>What gets deleted</h2>
<p>Your profile (including photo and medical notes), guardians, saved journeys, past journeys with their check-ins,
messages and location history, and your notification registrations. Feedback you sent is kept without your
name. Backups are overwritten within 30 days. See our <a href="/privacy">Privacy Policy</a>.</p>
""")


def reset_form_page(token: str, error: str = "") -> str:
    err = f'<p class="err">{html.escape(error)}</p>' if error else ""
    tok = html.escape(token)
    return page("Reset Password", f"""
<h1>Choose a new password</h1>
<div class="card">
  {err}
  <form method="post" action="/reset-password/{tok}">
    <label for="pw">New password (at least 8 characters)</label>
    <input id="pw" name="password" type="password" minlength="8" required autocomplete="new-password"/>
    <label for="pw2">Repeat new password</label>
    <input id="pw2" name="password_confirm" type="password" minlength="8" required autocomplete="new-password"/>
    <button type="submit">Set new password</button>
  </form>
</div>
""")


def message_page(title: str, message_html: str, accent: str = "#00e5a0") -> str:
    return page(title, f'<h1>{html.escape(title)}</h1><p>{message_html}</p>'
                       '<p><a href="/">Open Guardian Angel →</a></p>', accent)
