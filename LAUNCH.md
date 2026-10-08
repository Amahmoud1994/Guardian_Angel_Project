# Guardian Angel: Android launch checklist

Work through this list from top to bottom. Steps marked ⏳ involve waiting on Google or a provider, so start them early.

---

## Your domain: guardianangel.at

The app's permanent public address is **https://guardianangel.at**. It's used in email links, the Play Store listing, and the Android app, which is bound to this domain.

### Public URLs

| What | URL | Where it's used |
|---|---|---|
| The app | https://guardianangel.at | Testers, Play listing "website" |
| Health check | https://guardianangel.at/health | Render's health check |
| Privacy Policy | https://guardianangel.at/privacy | Play Console → App content, sign-up screen |
| Terms of Use | https://guardianangel.at/terms | Sign-up screen |
| Account deletion | https://guardianangel.at/delete-account | Play Console → Data safety |
| Android domain link | https://guardianangel.at/.well-known/assetlinks.json | Lets the Play Store app open without a browser bar |
| Guardian verification / password reset | `https://guardianangel.at/verify-guardian/…`, `/reset-password/…` | Links inside emails (built from `APP_BASE_URL`) |

### Server setting

On Render, set **`APP_BASE_URL` = `https://guardianangel.at`** (no trailing slash). Every link in guardian, verification and password-reset emails is built from it. On your laptop, leave it unset, so local links keep using `http://localhost:8000`.

### DNS records (at your registrar, after adding the domain in Render)

Render shows the exact values under the service → Settings → Custom Domains. Typically:

| Type | Name / host | Value |
|---|---|---|
| `A` | `@` (guardianangel.at) | the IP address Render shows (currently `216.24.57.1`) |
| `CNAME` | `www` | `<your-service>.onrender.com` |

- Remove any "parking page" or default `A`/`AAAA` records your registrar created for `@`, or they'll conflict.
- New records usually work within an hour; `.at` domains can take up to 24 hours. Render then issues the HTTPS certificate automatically.
- Use **`https://guardianangel.at`** (without `www`) everywhere, including in PWABuilder. The Android app link is checked against this exact host.

### Email addresses on the domain

You don't need a mailbox; free forwarding is enough:
- Set up email forwarding at your registrar, or with Cloudflare Email Routing if you move DNS to Cloudflare. Forward **`support@guardianangel.at`** and **`feedback@guardianangel.at`** to your Gmail.
- On Render, set `SUPPORT_EMAIL=support@guardianangel.at` and `FEEDBACK_EMAIL=feedback@guardianangel.at`.
- The app keeps **sending** through your Gmail account (`SMTP_USER` / `SMTP_FROM`), so test emails before relying on them. To send *as* `support@guardianangel.at`, add it under Gmail → Settings → Accounts → "Send mail as", then set `SMTP_FROM` to it.

---

## 1. Start the slow steps today ⏳

- [x] **Domain bought: `guardianangel.at`.** The Android app is permanently tied to this domain. See [Your domain](#your-domain-guardianangelat) below for DNS and email setup.
- [ ] **Create a Google Play Console developer account** at https://play.google.com/console ($25 one-off).
  - Personal or organization? Organization accounts show the company name and skip the 12-tester rule (see step 5), but need a D-U-N-S number, which takes 1–2 weeks to get.
  - Identity verification can take several days.

## 2. Deploy to Render with a persistent database

1. Push the project to a **private** GitHub repo. `.gitignore` already keeps `.env`, `vapid.json`, `case_key.json` and the local database out of the repo.
2. In Render, go to **New → Blueprint**, pick the repo, and Render reads [render.yaml](render.yaml). It creates:
   - the web service (Starter plan, always on), and
   - a Postgres database (paid plan, so data survives restarts and is backed up).

   If Render rejects a plan name, choose the closest current plan in the dashboard.
3. Fill in the secret values Render asks for:

   | Key | Value |
   |---|---|
   | `APP_BASE_URL` | `https://guardianangel.at` |
   | `SMTP_USER`, `SMTP_FROM` | your Gmail address |
   | `SMTP_PASS` | a **new** Gmail App Password (Google Account → Security → App passwords) |
   | `SUPPORT_EMAIL`, `FEEDBACK_EMAIL` | `support@guardianangel.at`, `feedback@guardianangel.at` (forwarded to your Gmail, see [Your domain](#your-domain-guardianangelat)) |
   | `OPERATOR_NAME` | your name or company, shown in the Privacy Policy and Terms |
   | `ADMIN_USERNAMES` | your own username(s), comma-separated. Register these yourself **before** sharing the link |
   | `VAPID_PUBLIC_KEY` / `VAPID_PRIVATE_KEY` | the `public` / `private` values from your local `vapid.json`. Paste the private key exactly as it appears, `\n` included |
   | `CASE_FILE_ENCRYPTION_KEY` | the `key` value from your local `case_key.json` |
   | `SENTRY_DSN` | optional: create a free project at sentry.io (platform: FastAPI) and paste its DSN |
   | `ANDROID_PACKAGE_NAME`, `ANDROID_CERT_SHA256` | leave empty for now (filled in at step 4) |

4. **Custom domain:** in Render, go to the service → Settings → Custom Domains → add `guardianangel.at` and `www.guardianangel.at`. Then create the DNS records described in [Your domain](#your-domain-guardianangelat). HTTPS is set up automatically once DNS works.
5. **Check it:** open `https://guardianangel.at/health` (it should say `"status":"ok"`), then `/privacy`, `/terms` and `/delete-account`.
6. Register your admin username, open the Monitor tab, and send yourself a test feedback message.

> **Security:** if the laptop server was ever reachable from the internet through the cloudflared tunnel, assume `.env` was exposed: the icon route used to serve any file on Windows (now fixed). Revoke the old Gmail App Password and use a new one on Render.

## 3. Try it on your phone first

- [ ] Open `https://guardianangel.at` in Chrome on Android → ⋮ → **Install app**. Register, enable notifications, add and verify a guardian, then run a 1-minute demo journey with the phone locked.
- [ ] Check that the alert notification arrives and vibrates.

## 4. Build the Android app (no coding needed)

1. Go to https://www.pwabuilder.com, enter `https://guardianangel.at` and click **Package for stores → Android → Generate package**.
2. Recommended options:
   - **Package ID:** your domain reversed plus `.twa`, so **`at.guardianangel.twa`**. **This can never change.**
   - **App name:** `Guardian Angel: Trip Safety`. **Launcher name:** `Guardian`.
   - **Version:** `1.0.0`, version code `1`.
   - **Display mode:** standalone. **Notification delegation:** ON. **Location delegation:** ON.
   - **Signing key:** "Create new".
3. Download the zip. It contains the `.aab` (what you upload to Play), the signing key (`.keystore`) with its passwords, and `assetlinks.json`.
   **Back up the keystore and passwords in two safe places (e.g. a password manager plus an offline copy). If you lose them, you can't update the app.**
4. Open `assetlinks.json` from the zip and copy two values into Render's environment:
   - `ANDROID_PACKAGE_NAME` = the `package_name`
   - `ANDROID_CERT_SHA256` = the `sha256_cert_fingerprints` value
5. After step 5.3 below, Play Console → **Test and release → App integrity → App signing** shows the **App signing key certificate** SHA-256. Add it to `ANDROID_CERT_SHA256` too, comma-separated after the first. Without it, the Play Store version opens with a browser address bar.
6. Check `https://guardianangel.at/.well-known/assetlinks.json`. It should list your package and fingerprints.

## 5. Google Play Console: closed test

1. **Create app:** name `Guardian Angel: Trip Safety`, App, Free.
2. Fill in **Store listing** using [store/PLAY_LISTING.md](store/PLAY_LISTING.md). Upload:
   - Icon: [store/icon-512.png](store/icon-512.png)
   - Feature graphic: [store/feature-graphic.png](store/feature-graphic.png)
   - Phone screenshots: everything in [store/screenshots/](store/screenshots/)
3. **Test and release → Closed testing:** create a track, upload the `.aab`, and add testers. The easiest way is a Google Group (testers join the group, then accept the opt-in link).
4. Complete **App content**. All the answers are in [store/PLAY_LISTING.md](store/PLAY_LISTING.md):
   - Privacy policy: `https://guardianangel.at/privacy`
   - App access: give reviewers a demo account (create one, e.g. `play_reviewer`, and fill in its profile)
   - Data safety, content rating, target audience (18+), ads (none)
   - Account deletion URL: `https://guardianangel.at/delete-account`
   - Health apps declaration (answer as described in the listing file)
5. Send the closed test for review. The first review usually takes a few days.

**Personal developer accounts (created after Nov 2023):** you need **at least 12 testers opted in for 14 days in a row** before Google lets you apply for production. Aim for 15–20 testers so a few dropping out doesn't restart the clock.

## 6. Run the beta (3–4 weeks)

- **Recruit:** post the messages from [store/BETA_RECRUITING.md](store/BETA_RECRUITING.md) linking to https://guardianangel.at/beta, then shortlist, add emails to Play Console and send invites from **Monitor → Beta Applicants**.

- Send testers the welcome email and survey from [store/PLAY_LISTING.md](store/PLAY_LISTING.md).
- Read feedback in the **Monitor tab → Tester Feedback** (it's also emailed to `FEEDBACK_EMAIL`).
- Ship fixes weekly. App changes are just a Render deploy; testers get them automatically, with no new Play upload.
  Upload a new `.aab` only when the manifest, icon, name or package settings change.
- Watch Sentry for crashes (if you set it up).
- After 14 days with 12 or more testers: **Dashboard → Apply for production** and answer Google's questions about your test.

## 7. Production launch and growth

- Turn on the **Production** track (a staged rollout of 20% → 100% is a good idea).
- Before a big public push, consider SMS alerts (Twilio), since email alone is weak in emergencies.
- Growth plan: every guardian who gets a verification email is a potential new user. See the marketing plan in the listing file.

## 8. iOS (after Android is live)

The iPhone app needs a native shell with native push. Plan: Capacitor + Firebase Cloud Messaging, built on Codemagic's cloud Macs, with a TestFlight beta. Apple Developer Program costs $99/yr. Meanwhile, iPhone testers can use Safari → Share → **Add to Home Screen**.
