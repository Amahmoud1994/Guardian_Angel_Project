"""Beta tester applications: the public /beta survey, its validation, and applicant scoring.

Scoring ranks applicants by how likely they are to really use the app during the 14-day closed
test and give useful feedback. Eligibility gates are Google Play requirements for the closed test
(Android phone + Google account) and our target audience (18+).
"""

import html
import re

import pages

USE_CASES = {
    "solo_travel": "Solo travel / backpacking",
    "hiking":      "Hiking, climbing, trail running or other outdoor trips",
    "commute":     "Late commutes or walking home alone",
    "lone_work":   "Working alone (field work, research, journalism, deliveries…)",
    "family":      "Keeping family members safe on their trips",
    "other":       "Something else",
}
TRIP_FREQUENCY = {
    "weekly":  "Several times a week",
    "few":     "2–3 times in the next month",
    "once":    "About once in the next month",
    "none":    "Probably not in the next month",
}
GUARDIAN = {
    "yes":   "Yes — I have someone in mind",
    "maybe": "Maybe — I'd need to ask someone",
    "no":    "No",
}
FEEDBACK = {
    "call":   "Short survey + a 15-minute video call",
    "survey": "Short written survey only",
    "none":   "I'd rather just use the app",
}
PLATFORMS = {
    "android": "Android",
    "iphone":  "iPhone (join the iOS waitlist)",
}
HEARD_FROM = {
    "facebook": "Facebook group",
    "reddit":   "Reddit",
    "linkedin": "LinkedIn",
    "whatsapp": "WhatsApp / Telegram",
    "friend":   "A friend",
    "other":    "Other",
}

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def score(a: dict) -> int:
    """0–100. Higher = more likely to actively test for 14 days and give useful feedback."""
    pts = 0
    uses = set(a.get("use_cases") or [])
    pts += min(25, 10 * len(uses & {"solo_travel", "hiking", "lone_work"}) + 7 * len(uses & {"commute", "family"})
               + (3 if "other" in uses else 0))
    pts += {"weekly": 25, "few": 20, "once": 10, "none": 0}.get(a.get("trip_frequency"), 0)
    pts += {"yes": 20, "maybe": 10}.get(a.get("guardian"), 0)
    pts += {"call": 20, "survey": 12}.get(a.get("feedback"), 0)
    motivation = (a.get("motivation") or "").strip()
    pts += 10 if len(motivation) >= 60 else 5 if len(motivation) >= 20 else 0
    return min(100, pts)


def is_eligible(a: dict) -> bool:
    return a.get("platform") == "android" and bool(a.get("adult")) and bool(a.get("commit_14_days"))


def validate(form: dict) -> tuple[dict, list[str]]:
    """Normalize raw form values → (application dict, list of error messages)."""
    def one(name, allowed):
        v = (form.get(name) or "").strip()
        return v if v in allowed else ""

    a = {
        "name":           (form.get("name") or "").strip()[:80],
        "email":          (form.get("email") or "").strip().lower()[:120],
        "country":        (form.get("country") or "").strip()[:60],
        "platform":       one("platform", PLATFORMS),
        "phone_model":    (form.get("phone_model") or "").strip()[:60],
        "use_cases":      [u for u in (form.get("use_cases") or []) if u in USE_CASES],
        "trip_frequency": one("trip_frequency", TRIP_FREQUENCY),
        "guardian":       one("guardian", GUARDIAN),
        "feedback":       one("feedback", FEEDBACK),
        "motivation":     (form.get("motivation") or "").strip()[:1000],
        "heard_from":     one("heard_from", HEARD_FROM),
        "adult":          form.get("adult") == "yes",
        "commit_14_days": form.get("commit_14_days") == "yes",
        "consent":        form.get("consent") == "yes",
    }
    errors = []
    if not a["name"]:
        errors.append("Please enter your name.")
    if not EMAIL_RE.match(a["email"]):
        errors.append("Please enter a valid email address.")
    if not a["country"]:
        errors.append("Please enter your country.")
    if not a["platform"]:
        errors.append("Please tell us which phone you use.")
    if a["platform"] == "android":
        if not a["use_cases"]:
            errors.append("Please choose at least one way you'd use Guardian Angel.")
        for key, label in (("trip_frequency", "how often you travel"), ("guardian", "whether you have a guardian in mind"),
                           ("feedback", "how you'd like to give feedback")):
            if not a[key]:
                errors.append(f"Please tell us {label}.")
        if not a["adult"]:
            errors.append("The beta is open to people aged 18 or over.")
        if not a["commit_14_days"]:
            errors.append("Testers need to keep the app installed for 14 days (a Google Play requirement).")
    if not a["consent"]:
        errors.append("Please agree to being contacted about the beta.")
    return a, errors


# ── Rendering ─────────────────────────────────
FORM_CSS = """
<style>
  fieldset{border:1px solid #1f2a30;border-radius:12px;padding:14px 16px 16px;margin:18px 0 0;background:#161b1f;}
  legend{font-size:14px;font-weight:bold;color:#e8eef2;padding:0 6px;}
  .hint{font-size:12px;color:#5a7080;margin:4px 0 8px;}
  .opt{display:flex;gap:10px;align-items:flex-start;font-size:14px;color:#c8d4dc;margin:9px 0;cursor:pointer;line-height:1.4;}
  .opt input{width:18px;height:18px;margin:1px 0 0;flex-shrink:0;accent-color:#00e5a0;}
  textarea,select{width:100%;box-sizing:border-box;padding:11px 14px;border-radius:8px;border:1px solid #1f2a30;
                  background:#111518;color:#e8eef2;font-size:15px;font-family:inherit;}
  .errors{border:1px solid #ff4757;background:#1f0e0e;border-radius:10px;padding:10px 16px;margin:16px 0;}
  .errors li{color:#ffb3b3;font-size:13px;}
  .perks li{margin:4px 0;}
  .hp{position:absolute;left:-5000px;}
  .android-only[hidden]{display:none;}
</style>"""


def _radio(name, options, current):
    return "".join(
        f'<label class="opt"><input type="radio" name="{name}" value="{k}"{" checked" if current == k else ""}/> {html.escape(v)}</label>'
        for k, v in options.items())


def _checks(name, options, current):
    return "".join(
        f'<label class="opt"><input type="checkbox" name="{name}" value="{k}"{" checked" if k in current else ""}/> {html.escape(v)}</label>'
        for k, v in options.items())


def _yes(name, label, checked):
    return f'<label class="opt"><input type="checkbox" name="{name}" value="yes"{" checked" if checked else ""}/> <span>{label}</span></label>'


def form_page(values: dict | None = None, errors: list[str] | None = None) -> str:
    v = values or {}
    e = lambda k: html.escape(str(v.get(k) or ""))  # noqa: E731
    err_html = ("<div class='errors'><ul>" + "".join(f"<li>{html.escape(x)}</li>" for x in errors) + "</ul></div>") if errors else ""
    android_hidden = "" if v.get("platform", "android") != "iphone" else " hidden"
    return pages.page("Become a Beta Tester", FORM_CSS + f"""
<h1>Become a Guardian Angel beta tester</h1>
<p>Guardian Angel is a personal safety app: plan a trip, check in with your private code, and if you miss a
check-in your trusted guardians are alerted. We're looking for <strong>12–20 Android users</strong> to try the
first version for two weeks and tell us honestly what works and what doesn't.</p>
<ul class="perks">
  <li>🆓 Free early access before anyone else</li>
  <li>🗣️ Your feedback directly shapes the app</li>
  <li>⏱️ About 10 minutes to set up, then use it on your real trips</li>
</ul>
<p class="muted">Takes about 2 minutes · We'll only email you about the beta · <a href="/privacy">Privacy Policy</a></p>
{err_html}
<form method="post" action="/beta" novalidate>
  <input class="hp" type="text" name="website" tabindex="-1" autocomplete="off" aria-hidden="true"/>

  <fieldset><legend>About you</legend>
    <label for="name">Your first name</label><input id="name" name="name" value="{e('name')}" autocomplete="given-name" required/>
    <label for="email">Email of your Google account (the one on your Android phone)</label>
    <input id="email" name="email" type="email" value="{e('email')}" autocomplete="email" required/>
    <div class="hint">Google Play only lets testers in by their Google account email — usually your @gmail.com address.</div>
    <label for="country">Country you live in</label><input id="country" name="country" value="{e('country')}" autocomplete="country-name" required/>
  </fieldset>

  <fieldset><legend>Your phone</legend>
    {_radio("platform", PLATFORMS, v.get("platform", ""))}
    <div class="hint">The first version is Android-only. iPhone users: we'll email you when the iOS version is ready.</div>
    <label for="phone_model">Phone model <span class="muted">(optional)</span></label>
    <input id="phone_model" name="phone_model" value="{e('phone_model')}" placeholder="e.g. Samsung Galaxy S23, Pixel 8"/>
  </fieldset>

  <div class="android-only"{android_hidden}>
  <fieldset><legend>How would you use Guardian Angel?</legend>
    <div class="hint">Choose all that apply.</div>
    {_checks("use_cases", USE_CASES, set(v.get("use_cases") or []))}
  </fieldset>

  <fieldset><legend>How often will you travel or go out alone in the next month?</legend>
    {_radio("trip_frequency", TRIP_FREQUENCY, v.get("trip_frequency", ""))}
  </fieldset>

  <fieldset><legend>Do you have someone who could be your guardian during the test?</legend>
    <div class="hint">A friend or family member who would receive an alert email if you miss a check-in.</div>
    {_radio("guardian", GUARDIAN, v.get("guardian", ""))}
  </fieldset>

  <fieldset><legend>How would you like to give feedback?</legend>
    {_radio("feedback", FEEDBACK, v.get("feedback", ""))}
  </fieldset>

  <fieldset><legend>Why are you interested? <span class="muted">(optional, but it helps us choose)</span></legend>
    <textarea name="motivation" rows="4" maxlength="1000" placeholder="e.g. I hike alone most weekends and my partner worries…">{e('motivation')}</textarea>
  </fieldset>
  </div>

  <fieldset><legend>Where did you hear about us?</legend>
    <select name="heard_from"><option value="">Choose…</option>{"".join(
        f'<option value="{k}"{" selected" if v.get("heard_from") == k else ""}>{html.escape(t)}</option>' for k, t in HEARD_FROM.items())}</select>
  </fieldset>

  <fieldset><legend>Almost done</legend>
    {_yes("adult", "I'm 18 or older.", v.get("adult"))}
    {_yes("commit_14_days", "If selected, I'll keep the app installed for at least <strong>14 days</strong> (Google requires this before the app can go public).", v.get("commit_14_days"))}
    {_yes("consent", "You may email me about the beta. I've read the <a href='/privacy' target='_blank' rel='noopener'>Privacy Policy</a>.", v.get("consent"))}
  </fieldset>

  <button type="submit">Apply to the beta</button>
  <p class="muted">Guardian Angel is not an emergency service. In an emergency, always call your local emergency number.</p>
</form>
<script>
  // Hide the Android-only questions for iPhone users (they join the iOS waitlist instead).
  document.querySelectorAll('input[name=platform]').forEach(r => r.addEventListener('change', () => {{
    document.querySelector('.android-only').hidden = document.querySelector('input[name=platform]:checked')?.value === 'iphone';
  }}));
</script>
""")


def thanks_page(name: str, platform: str) -> str:
    n = html.escape(name or "there")
    if platform == "iphone":
        msg = (f"Thanks, {n}! You're on the <strong>iOS waitlist</strong> — we'll email you as soon as the iPhone "
               "version is ready for testing.")
    else:
        msg = (f"Thanks, {n}! Your application is in. We're choosing testers over the next few days and will email "
               "you with the next steps if you're selected. Check your inbox (and spam folder) for a confirmation.")
    return pages.message_page("Application received 🛡", msg)


def confirmation_email(name: str, platform: str) -> str:
    n = html.escape(name or "there")
    body = ("You're on the iOS waitlist — we'll email you as soon as the iPhone version is ready."
            if platform == "iphone" else
            "We're picking our first testers over the next few days. If you're selected, you'll get an email with "
            "a link to join the test on Google Play.")
    return f"""<!DOCTYPE html><html><body style="margin:0;padding:20px;font-family:Arial,sans-serif;background:#0a0d0f;color:#e8eef2;">
<div style="max-width:520px;margin:0 auto;background:#161b1f;border-radius:12px;border:2px solid #00e5a0;padding:24px;">
  <p style="margin:0 0 16px;font-size:20px;font-weight:bold;color:#00e5a0;">🛡 GUARDIAN ANGEL</p>
  <p style="font-size:14px;line-height:1.6;">Hi {n},</p>
  <p style="font-size:14px;line-height:1.6;">Thanks for applying to the Guardian Angel beta! {body}</p>
  <p style="font-size:12px;color:#5a7080;">You're receiving this because you applied at guardianangel.at/beta. Reply to this email if you'd like us to delete your application.</p>
</div></body></html>"""


def invite_email(name: str, optin_url: str, store_url: str, group_url: str = "") -> str:
    n = html.escape(name or "there")
    o, s_, g = html.escape(optin_url), html.escape(store_url), html.escape(group_url)
    group_step = (f'<li style="margin-bottom:10px;">Join our tester group with the same Google account: '
                  f'<a href="{g}" style="color:#00e5a0;">{g}</a></li>') if group_url else ""
    btn = "display:inline-block;padding:10px 18px;border-radius:8px;background:#00e5a0;color:#0a0d0f;font-weight:bold;text-decoration:none;"
    return f"""<!DOCTYPE html><html><body style="margin:0;padding:20px;font-family:Arial,sans-serif;background:#0a0d0f;color:#e8eef2;">
<div style="max-width:560px;margin:0 auto;background:#161b1f;border-radius:12px;border:2px solid #00e5a0;padding:24px;font-size:14px;line-height:1.6;">
  <p style="margin:0 0 16px;font-size:20px;font-weight:bold;color:#00e5a0;">🛡 GUARDIAN ANGEL — YOU'RE IN!</p>
  <p>Hi {n},</p>
  <p>You've been selected as one of our first Guardian Angel beta testers — thank you! Here's how to get started
     (on your Android phone, signed in with the Google account you applied with):</p>
  <ol style="padding-left:20px;">
    {group_step}
    <li style="margin-bottom:10px;">Accept the test invitation: <br/><a href="{o}" style="{btn}">Become a tester →</a></li>
    <li style="margin-bottom:10px;">Install the app from Google Play: <br/><a href="{s_}" style="{btn}">Open in Google Play →</a><br/>
        <span style="font-size:12px;color:#a0b4c0;">If it says the app isn't available, wait a few minutes after step 1 and try again.</span></li>
  </ol>
  <p><strong>This week, please try these three things:</strong></p>
  <ul style="padding-left:20px;">
    <li>Add a guardian (with their email) and tap <strong>Verify</strong>.</li>
    <li>Save a journey you'll actually take — with or without a start time.</li>
    <li>Run a short demo journey: New Journey → "1 min (Demo)" → Begin, and <strong>don't</strong> check in. Watch the
        alerts arrive, then check in with your safe code. (Tell your guardian it's a test first!)</li>
  </ul>
  <p>Please keep the app installed for at least <strong>14 days</strong> — Google requires it before the app can go public.
     Tell us anything, anytime: <strong>Profile → Send feedback</strong> in the app, or just reply to this email.</p>
  <p>Thank you for helping make solo trips safer! 💚</p>
  <p style="font-size:12px;color:#5a7080;margin-top:20px;">Guardian Angel is not an emergency service. In an emergency, always call your local emergency number.</p>
</div></body></html>"""
