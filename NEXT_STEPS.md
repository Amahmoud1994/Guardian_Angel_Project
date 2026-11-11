# Guardian Angel: next steps for the beta

*Saved November 10, 2026. To pick this up again, open this file and tell Claude which step you're on.*

---

## Where things stand

Checked on the live site on November 10, 2026:

- [x] **Website live** at https://guardianangel.at with HTTPS
- [x] **Security fixes deployed.** Strangers can't send email, read other people's journeys, see codes, or end journeys.
- [x] **Invite-only sign-up** is on (`BETA_INVITE_ONLY=true`)
- [x] **Play Store app linked to the domain,** for both your upload key and Google's signing key, so it opens full-screen
- [x] **Support email** `support@guardianangel.at` (forwarded through ImprovMX)
- [x] **Beta application form** live at https://guardianangel.at/beta
- [x] **2-step verification** on all accounts, and the GitHub repo is private
- [ ] **Play Console:** closed test submitted and approved by Google (see [Still open in Play Console](#still-open-in-play-console))

---

## If something goes wrong

| If… | What actually happens | What you do |
|---|---|---|
| A tester hits a bug | Normal and expected: that's what a beta is for. | Thank them, fix it, deploy. Testers get the fix automatically, with no new Play upload. |
| Something is seriously broken after a deploy | You can undo it in a minute. | Render → your service → **Events** → **Rollback** to the previous deploy. |
| You want to stop new sign-ups | Already handled. | Sign-up is invite-only, so nobody gets in without your approval. |
| You want to pause everything | — | Render → **Suspend service**. The app shows as unavailable, and no data is lost. Resume when ready. |
| Someone behaves badly | — | Delete their account or application (Monitor tab), and remove their email from Play Console → Closed testing → Testers. |
| Someone relies on it in a real emergency | Covered by the "not an emergency service" text in the Terms, sign-up screen and posts. | Keep reminding testers that it's a test version. |
| A Render or Gmail security alert | — | Revoke the Gmail App Password (Google Account → Security → App passwords), create a new one, and update `SMTP_PASS` on Render. |

> Nobody will think less of you for a bug in a beta. People are generous with solo developers who say "this is my first version, please be honest with me."

---

## Stage 0: your own dry run

*Today, about 30 minutes, nobody else involved.*

- [ ] **Persistent database first:** open https://guardianangel.at/health and check it shows **`"persistent_storage": true`**. If it says `false` or the field is missing, the site is on a temporary database that's wiped on every restart:
  - Render → **New → Postgres** (paid plan, same region as the web service)
  - copy its **Internal Database URL** into the web service's `DATABASE_URL`
  - set the service's **Instance Type** to **Starter** so it never goes to sleep
  - re-register your admin account afterwards
- [ ] **Email through Resend** (Render blocks Gmail's email ports on the free plan; "Network is unreachable" in the logs):
  1. Sign up at https://resend.com, then **Domains → Add Domain** → `guardianangel.at` (region close to your users).
  2. Resend shows **3–4 DNS records**, usually on `send.guardianangel.at` and `resend._domainkey.guardianangel.at`. Add them **exactly** in GoDaddy → DNS. They don't touch your existing website or ImprovMX records.
  3. Wait until Resend shows the domain as **Verified** (minutes, sometimes a few hours).
  4. Resend → **API Keys → Create API Key**, with "Sending access" permission and only this domain. Copy it (it starts with `re_`).
  5. Render → web service → **Environment**:
     - `RESEND_API_KEY` = the key
     - `EMAIL_FROM` = `Guardian Angel <no-reply@guardianangel.at>`
     Then save.
  6. Check: as admin, **Guardians → Test** on a guardian with your email. The email should arrive from `no-reply@guardianangel.at`.
  7. Once it works, delete `SMTP_PASS` from Render and **revoke the Gmail App Password** (Google Account → Security → App passwords). The app no longer needs your Gmail.
- [ ] On Render, add a test email of yours to **`BETA_ALLOWED_EMAILS`** (comma-separated) and save.
- [ ] On your Android phone, open https://guardianangel.at, register a test account with that email, and allow notifications.
- [ ] Add a guardian with an email you control and tap **Verify**. Accept the request from that inbox and check the blue badge appears.
- [ ] Start a journey with **"1 min (Demo)"**, lock the phone, and **don't** check in. Check that:
  - [ ] the notification arrives on the locked phone and vibrates
  - [ ] the guardian inbox receives the alert emails
  - [ ] checking in with the safe code stops the escalation
- [ ] Submit the form at https://guardianangel.at/beta with a second email. Check that the confirmation email arrives and the application shows in **Monitor → Beta Applicants**.
- [ ] Send feedback from **Profile → Send feedback** and check it appears in **Monitor → Tester Feedback** and at `feedback@guardianangel.at`.

If anything looks wrong, stop and tell Claude. It gets fixed before anyone else sees it.

---

## Stage 1: 3–5 people you trust

*This week, no public posts.*

- [ ] Send the short **WhatsApp** message from [store/BETA_RECRUITING.md](store/BETA_RECRUITING.md) to 3–5 friends or family members with Android phones.
- [ ] When they've applied: **Monitor → Beta Applicants** → **⭐ Shortlist** them.
- [ ] **📋 Copy shortlisted emails** → Play Console → **Closed testing → Testers** → paste → save.
- [ ] Copy the **"Join on the web"** opt-in link from Play Console → paste it into **✉ Invite shortlisted testers** → **Send Invites**.
- [ ] Let them use it for 3–4 days. Friends tell you about problems privately; this is where you catch the embarrassing things.
- [ ] Fix anything important they report, with Claude's help.

---

## Stage 2: widen gently

*Only if Stage 1 went fine.*

- [ ] Ask friends, colleagues and friends-of-friends first. **Google needs 12 testers**, and you may reach that without any public posts.
- [ ] If you're still short, post in **one or two small groups** you know (e.g. a local hiking group). Ask the group admin first. The posts (English and German) are in [store/BETA_RECRUITING.md](store/BETA_RECRUITING.md).
- [ ] Shortlist, add to Play Console, and invite the same way as in Stage 1.
- [ ] **Stop at 15–20 testers.** A few extra protect you if someone drops out.

---

## Stage 3: the 14-day test

- [ ] **Day 2–3:** check Play Console's tester count. The 14 days count once **at least 12** have opted in. Gently remind anyone who hasn't joined.
- [ ] **Every couple of days:** read **Monitor → Tester Feedback** and fix the important things.
- [ ] **Day 7:** send everyone the one-week survey from [store/PLAY_LISTING.md](store/PLAY_LISTING.md#one-week-survey-5-questions-eg-google-forms). For short answers, follow up by email with the optional follow-up questions in the same file.
- [ ] **Day 14+:** Play Console → **Dashboard → Apply for production access**, and answer Google's questions about the test.
- [ ] Thank your testers, and tell them when the app goes public.

---

## Still open in Play Console

Before anyone can install the app, Google has to approve the closed test:

- [ ] **Main store listing:** name, descriptions, icon, feature graphic and screenshots, all in [store/PLAY_LISTING.md](store/PLAY_LISTING.md) and the `store/` folder.
- [ ] **App content:** every section (privacy policy, app access, ads, content rating, target audience, data safety, health apps, account deletion). The answers are in [store/PLAY_LISTING.md](store/PLAY_LISTING.md#app-content-answers).
  - For **App access**, first add the reviewer account's email to `BETA_ALLOWED_EMAILS`, then create `play_reviewer` on the live site.
- [ ] Add **yourself** as the first tester.
- [ ] **Publishing overview → Send changes for review.** The first review usually takes a few days.

---

## Useful references

| What | Where |
|---|---|
| Full launch checklist (deploy, DNS, Android, Play) | [LAUNCH.md](LAUNCH.md) |
| Store text, form answers, tester emails, survey | [store/PLAY_LISTING.md](store/PLAY_LISTING.md) |
| Recruiting posts and the selection process | [store/BETA_RECRUITING.md](store/BETA_RECRUITING.md) |
| Signing key backup (never lose it) | `Downloads\personal\Google Play Guardian Angel\` (`signing.keystore` + `signing-key-info.txt`) |
| Play app signing key (for the record) | `CA:9D:61:6A:F8:DC:ED:48:A5:35:9A:38:C1:43:37:DA:1D:1E:2C:B8:ED:B2:2E:2B:B5:F7:6B:E8:78:0E:73:C6` |

## Open questions to continue with Claude

- Where does the Play Console review stand (not submitted, in review, or approved)?
- How did the Stage 0 dry run go, and did anything look wrong?
- Before the public launch: move app emails from Gmail to an email service built for apps (Brevo, Resend or Postmark) using `no-reply@guardianangel.at`.
