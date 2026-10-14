# Google Play listing, form answers and tester kit

Everything below can be copied into Play Console. Domain: **https://guardianangel.at**. Support email: **support@guardianangel.at** (set up forwarding first, see [LAUNCH.md](../LAUNCH.md#your-domain-guardianangelat)).

---

## Store listing

**App name** (max 30 characters):
```
Guardian Angel: Trip Safety
```

**Short description** (max 80 characters):
```
Check in on every trip. Miss a check-in and your trusted guardians are alerted.
```

**Full description** (max 4000 characters):
```
Going somewhere alone? Guardian Angel makes sure someone notices if you don't make it.

Plan your trip, choose the people you trust as your guardians, and check in with your private safe code as you go. If you miss a check-in, Guardian Angel escalates step by step: first it reminds you, then it warns you, and then it alerts your guardians by email with your trip details and last known location, so they can reach you or get help.

HOW IT WORKS
• Plan a journey: destination, route, map link, travel companions and how you'll communicate.
• Pick your guardians from your saved list. Verified guardians have confirmed they'll look out for you.
• Check in with your safe code before the timer runs out.
• Miss a check-in? Reminders and warnings come first, then your guardians are alerted.
• In trouble and being watched? Enter your duress code instead. It looks like a normal check-in, but it silently alerts your guardians straight away.

BUILT FOR
• Solo travelers and backpackers
• Hikers, climbers and trail runners
• Late-night commutes and walks home
• Field workers, researchers and journalists working alone

FEATURES
✓ Check-in timers with escalating alerts
✓ Silent duress code
✓ Verified guardians with a blue check mark
✓ Saved journeys: plan ahead and start with one tap, or schedule a start time
✓ Daily Usage: automatic protection during set time windows (e.g. your commute)
✓ Optional live location sharing while the app is open
✓ Messages with your guardians
✓ Emergency number for your destination country
✓ Safety Readiness score showing what to add to be better prepared
✓ Notifications even when the app is closed

PRIVACY FIRST
Your data is only shared with the guardians you choose. No ads, and we never sell your data. Download or delete your data at any time from your profile.

IMPORTANT
Guardian Angel is not an emergency service and does not contact the police or ambulance services for you. Alerts depend on your phone, network and your guardians seeing them. In an emergency, always call your local emergency number.

We're in early access and would love your feedback: Profile → Send feedback, or support@guardianangel.at.
https://guardianangel.at
```

**App category:** Travel & Local. **Tags:** Travel, Safety, Outdoors (choose the closest ones offered).
**Contact details:** email `support@guardianangel.at`, website `https://guardianangel.at`.
**Privacy policy:** `https://guardianangel.at/privacy`

**Graphics:** `store/icon-512.png`, `store/feature-graphic.png` and the six screenshots in `store/screenshots/` (1080×1920). Upload them in this order:
1. `01-active-journey.png`: the countdown and alert status
2. `02-plan-journey.png`: planning with the readiness score
3. `03-verified-guardians.png`: verified guardians
4. `04-saved-journeys.png`: saved and scheduled journeys
5. `05-alert.png`: what an alert looks like
6. `06-profile.png`: profile and readiness

**Release notes (first closed test):**
```
First beta of Guardian Angel. Please try: verify a guardian, save a journey, and run a short demo journey to see the alerts. Send feedback from Profile → Send feedback. Thank you for helping!
```

---

## App content answers

### App access
"All or some functionality is restricted" → add instructions:
```
Sign in with username: play_reviewer / password: <set one>.
To see the main flow: Home → + New Journey → set "Level 0" interval to "1 min (Demo)" → Begin Journey Now.
Do not check in. After about 1 minute the escalation levels start (reminder → warning → guardian alert).
The safe code is SAFE123 (or the custom one shown on the journey screen).
Guardian alert emails go to the guardian email addresses on the account.
```
(Create this account on your live site first and add a guardian with an email address you control. While `BETA_INVITE_ONLY=true`, put the reviewer account's email in `BETA_ALLOWED_EMAILS` first, or it can't register.)

### Ads
No, the app does not contain ads.

### Content rating (IARC questionnaire)
- Category: **Utility, Productivity, Communication, or Other**
- Violence, sexual content, language, drugs, gambling: **No**
- Users can interact or exchange information (messages with guardians): **Yes**
- Shares the user's current physical location with other users: **Yes** (only with the guardians the user chooses)
- Digital purchases: **No**

### Target audience
**18 and over** (keeps the beta out of Google's Families policy requirements).

### News app
No.

### Health apps declaration
The app is a personal-safety app, not a health or medical app. If asked to choose features, pick none (or "Other" with this note):
```
Users can optionally store emergency medical notes (e.g. allergies, blood type) that are shared only with their own guardians if they miss check-ins. The app provides no health monitoring, diagnosis or treatment.
```

### Data safety
**Does your app collect or share any of the required user data types?** Yes.
**Is all user data encrypted in transit?** Yes.
**Do you provide a way for users to request that their data be deleted?** Yes, via `https://guardianangel.at/delete-account` and in-app deletion.

**Sharing:** "No data shared with third parties". Data sent to the guardians the user picks is a user-initiated transfer, and hosting, email and push providers are service providers. Neither counts as "sharing" under Google's definitions.

**Data collected** (all "processed ephemerally: No", all used for the purposes listed):

| Data type | Collected | Required / optional | Purposes |
|---|---|---|---|
| Personal info → Name (username, name on journeys) | Yes | Required | App functionality, Account management |
| Personal info → Email address | Yes | Optional | App functionality, Account management |
| Personal info → Phone number | Yes | Optional | App functionality |
| Personal info → Address | Yes | Optional | App functionality |
| Personal info → Other info (date of birth) | Yes | Optional | App functionality |
| Health and fitness → Health info (blood type, medical notes) | Yes | Optional | App functionality |
| Location → Precise location | Yes | Optional (live location toggle) | App functionality |
| Photos and videos → Photos (profile photo) | Yes | Optional | App functionality |
| Messages → Other in-app messages | Yes | Optional | App functionality |
| App info and performance → Crash logs, Diagnostics | Yes (if Sentry is enabled) | Required | App functionality, Analytics |
| Device or other IDs (push notification token) | Yes | Optional | App functionality |
| Other user-generated content (journeys, routes, guardians' contact details) | Yes | Required | App functionality |

---

## Tester kit

### Where to find testers (aim for 15–20)
Testers apply at **https://guardianangel.at/beta** and are scored automatically. Choose and invite them in the Monitor tab. Ready-to-post social media messages (English and German) and the step-by-step process are in [BETA_RECRUITING.md](BETA_RECRUITING.md).

1. Friends, family and colleagues who travel, hike, or commute late.
2. Hiking, climbing and running clubs; university outdoor societies.
3. Online communities (read each group's rules on self-promotion first): r/solotravel, r/hiking, r/CampingandHiking, solo-female-travel Facebook groups, Meetup hiking groups.
4. 1–2 organizations with people working alone (NGOs, field researchers, journalists' associations) for a free pilot.

### Welcome email
```
Subject: You're in — help test Guardian Angel (10 minutes)

Hi <name>,

Thanks for helping test Guardian Angel (https://guardianangel.at), a safety app that alerts people you trust if you don't check in during a trip.

1) Join the test: <Google Group link>, then <Play opt-in link>, then install from the Play Store.
2) Please try these three things this week:
   • Add a guardian (someone you know, with their email) and tap "Verify".
   • Save a journey you'll actually take, with or without a start time.
   • Run a short demo journey: New Journey → "1 min (Demo)" → Begin, and DON'T check in. Watch the alerts arrive,
     then check in with your safe code. (Warn your guardian first that it's a test!)
3) Tell us anything: Profile → Send feedback, reply to this email, or write to feedback@guardianangel.at.

Please keep the app installed for at least 2 weeks. Google requires it before the app can go public.

Thank you!
<your name>
```

### One-week survey (5 questions, e.g. Google Forms)
1. How likely are you to recommend Guardian Angel to a friend who travels alone? (0–10)
2. What did you use it for? (trip / hike / commute / work / just testing)
3. What was confusing or didn't work?
4. Did the alerts and notifications arrive when you expected? (yes / late / no / didn't test)
5. What one feature would make you use it on every trip?

### Optional follow-up questions (by email, for testers who want to say more)
- Walk me through the last time you used it. What were you doing?
- When did you feel unsure what would happen next?
- Who did you add as a guardian, and how did they react to the verification email?
- What would stop you from relying on it on a real trip?

---

## Growth plan after the beta

- **Every guardian is a potential user:** verification and alert emails reach people who care about safety. Add a "Get Guardian Angel for your own trips" link and Play badge to those emails once the app is public.
- **Store optimization:** use keywords like solo travel safety, hiking check-in, lone worker safety, safe walk home, travel tracker; translate the listing for your top countries; ask for a rating after a journey ends safely.
- **Landing page** on https://guardianangel.at with the Play badge and an iOS waitlist sign-up.
- **Short videos** (Reels, TikTok, Shorts) showing "what happens if I don't check in?"; written safety guides for SEO.
- **Launches:** Product Hunt, "Show HN", travel and hiking newsletters and bloggers.
- **Partnerships:** hiking clubs, hostels, universities, travel insurers; lone-worker pilots with organizations.
- **Paid ads** only after testers keep using it (good day-7 retention): Google App Campaigns, measured by cost per *activated* user (someone who has added a guardian), not per install.
