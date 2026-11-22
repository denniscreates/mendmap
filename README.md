# MendMap

**Spot it. Snap it. Mended.** · Made by Denis Ibrahimi

Residents photograph street problems (potholes, broken streetlights, illegal dumping, blocked ramps). Each report becomes a pin on a shared map. City staff move it from Reported → In progress → Fixed, and the resident gets a push notification at each step. Neighbours and skilled volunteers (*mjeshtrit*) can fix small jobs themselves and earn rewards from partner brands.

---

## Quick start (for judges)

You need Python 3.11+ and Node.js 20+. Two terminals:

**1. API and city dashboard**
```powershell
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Set-Content .env "SEED_DEMO=1`nMENDMAP_DEMO_PAYMENTS=on"
uvicorn app.main:app --env-file .env --reload --host 0.0.0.0 --port 8000
```
This uses a local SQLite file (`backend/mendmap.db`), so nothing else has to be installed. `SEED_DEMO=1` fills it with 19 real-looking reports in Prishtina and creates the demo accounts below. `MENDMAP_DEMO_PAYMENTS=on` lets you try paid bookings without a Stripe account.

**2. The app**
```powershell
cd mobile
npm install
npx expo start
```
- **On a phone:** install *Expo Go* and scan the QR code. The phone must be on the same Wi-Fi as the computer.
- **In a browser:** press `w` in the Expo terminal.
- **City dashboard:** http://localhost:8000/admin · **Public page:** http://localhost:8000/city/ · **API docs:** http://localhost:8000/docs

## Demo accounts

While `SEED_DEMO=1` is on, the app's sign-in screen shows a **Demo accounts** box: tap one to sign in, no typing. The city dashboard has a **Demo: sign in as city admin** button. An account drops out of the list as soon as its password is changed, and the list is empty when `SEED_DEMO` is off.

| Role | Email | Password | What to try |
|---|---|---|---|
| **City admin** | `admin@mendmap.local` | `admin123` | The city dashboard at `/admin`: change report status, accept fixes, verify mjeshtrit, rewards, bookings. In the app: the Jobs tab and every report. |
| **Field crew** | `crew@mendmap.local` | `crew123` | Jobs tab: in-progress reports in route order on a map, *Mark fixed* with an after photo, works offline. |
| **Resident** | `citizen@mendmap.local` | `citizen123` | Arta from Prishtina: report a problem, the map, *I see this too*, Fix & earn, badges, partner rewards. |
| **Mjeshtër** | `arben@mendmap.local` | `mjeshter123` | Arben, a verified plumber and builder: takes skilled jobs and answers paid booking requests with a price. |

More demo people: `driton@`, `blerina@` and `ilir@mendmap.local` (`citizen123`), and the mjeshtrit `blerta@` and `dritan@mendmap.local` (`mjeshter123`). You can also create your own account: in demo mode the 6-digit email code is shown on screen with a *Fill in* button.

> These passwords are for the demo only. For real use set `SEED_DEMO=0`, a strong `ADMIN_PASSWORD` and a `JWT_SECRET` (see `backend/.env.example`).

---

## How to use the app

**First launch**
1. A short 3D intro plays (tap *Skip*).
2. The welcome page plays our ad, then a **how-to video**. Close it with the **X**, or tick *Don't show this again*. Watch it again any time: Settings → *How MendMap works*.
3. Sign in, or tap a demo account. New accounts pick their neighbourhood and their **main language**, so an Albanian travelling in Italy still gets the app in Albanian.

**Residents**
- **Map:** every report as a pin (orange = reported, amber = in progress, blue = fixed). Filter by category and status, and tap a pin for details.
- **Report (camera tab):** take one or more photos. The AI suggests the category, severity and a description (you can edit all of it), and GPS places the pin. If someone already reported the same problem nearby, the app offers *I see this too* instead of a duplicate. With no signal the report is kept as a draft and sent later.
- **Report detail:** photos, the AI check, city priority, the status timeline with city comments, and *Share*. You can edit your own reports.
- **Fix & earn:** small, safe jobs (dumping, accessibility, …) a neighbour can fix. Tap *I'll fix it* and send an after photo; when the city accepts it you earn a badge. Badges buy rewards from partner brands (Settings → *Rewards*), given as a voucher code.
- **Chat:** talk with your neighbourhood and the city.
- **City:** fix rate, time to fix, reports near you and the neighbourhood leaderboard.
- **Settings:** my reports, language and main language, light/dark mode, neighbourhood, near-you alerts, become a mjeshtër, sign out.

**Mjeshtrit (skilled volunteers)**
- Settings → *Mjeshtri*: add your skills, the days you're free and a photo or PDF of a diploma or certificate. The AI checks it: clear ones are approved at once, unclear ones go to the city.
- Verified mjeshtrit can take *skilled jobs* (a broken bench, a blocked drain). Residents can also **book** a mjeshtër for a paid job: the mjeshtër sends a price, the resident pays, and the money is held until the resident taps *Job done*. Then the mjeshtër is paid, minus MendMap's 10% commission. If something goes wrong, the city decides.

**Field crew**
- **Jobs tab:** in-progress jobs, nearest first, with a route line and directions. *Mark fixed* needs an after photo. The list is cached, and closed jobs are sent once you're back online.

## How to use the city dashboard (admin)

Open http://localhost:8000/admin and sign in as the city admin (or tap the demo button).

| Tab | What you do there |
|---|---|
| **Reports** | All reports, sorted by city priority (0–100, with reasons: severity, confirmations, waiting time, near a school or hospital). Filter and search. Click a row to see the photos, AI check, voice note and location; change the status with a comment (the resident gets a push); upload an after photo; re-run the AI check; or delete spam. |
| **Map** | Every report on a map of Prishtina. |
| **Statistics** | Totals per status and category, and the average days to fix. |
| **Fixes & rewards** | Accept or reject neighbour fixes (after photos). Add, edit and hide partner rewards, and mark voucher codes as used. |
| **Mjeshtri** | Applications the AI couldn't decide: open the document, then approve or reject. |
| **Chat** | Answer residents and moderate the neighbourhood chats. |
| **Bookings** | Paid jobs between residents and mjeshtrit. Disputes are decided here: pay the mjeshtër or refund the resident. |

The ◐ button switches light and dark mode. *Public page ↗* opens the transparency page residents see.

## Good to know
- **AI** (photo check, descriptions, voice transcription, document check) needs `GEMINI_API_KEY` or `ANTHROPIC_API_KEY` in `backend/.env`. Without a key the app still works and skips the AI parts. Gemini's free plan has a daily limit; reports sent while it's used up are checked automatically later.
- **Payments:** with `MENDMAP_DEMO_PAYMENTS=on` and no Stripe keys, paying just marks the booking paid. Real card payments need Stripe test keys (`STRIPE_SECRET_KEY`, `STRIPE_PUBLISHABLE_KEY`; see `backend/app/bookings.py`).
- **Push notifications** need a development build, not Expo Go (see *Mobile app* below).

---

# Technical reference

### Features
| Feature | Where |
|---|---|
| **AI photo check:** suggests the category and severity, and blocks photos that don't show a street problem | Report screen (needs `ANTHROPIC_API_KEY`) |
| **City priority score** 0–100 with reasons (severity, confirmations, waiting time, near a school/hospital/bus stop, accessibility) | Admin table (default sort), report detail, crew jobs |
| **Badges** and a **neighbourhood leaderboard** | My reports, City tab |
| **Public transparency page** with stats, heatmap and leaderboard, no sign-in | http://localhost:8000/city/ |
| **Accessibility** category (blocked ramps, cars on sidewalks) with its own filter | Everywhere |
| **Near-you alerts** within 500 m of a home area | My reports → Near-you alerts, City tab |
| **Voice note** (up to 60 s) attached to a report | Report screen, detail, admin drawer |
| **Share card** image of a report | Report detail → Share |
| **Neighbour fixes:** at sign-up you pick your neighbourhood (e.g. Kalabria). Residents can tap *I'll fix it* on safe jobs there (illegal dumping, accessibility, other), then send an after photo. The city accepts or rejects it. Every accepted fix is a fixer badge, and **badges buy rewards from partner brands** (e.g. a free dinner for 2 at Zhuzuff Kitchen) | Report detail, Fix & earn tab, Settings → *Rewards*, admin *Fixes & rewards* tab |
| **Crew mode:** jobs in route order on a map, close with an "after" photo, works offline | Jobs tab for `crew@mendmap.local` / `crew123` |

Potholes and streetlights stay with the city crew: they need traffic control, heavy tools or electrical work. A resident can hold 3 jobs at a time, and a rejected fix reopens the report. **Mjeshtri (skilled volunteers):** plumbers, painters, builders and other tradespeople sign up in the app (Settings → Mjeshtri) with their skills, the days they're free (e.g. Sundays) and proof of their skill: a photo or PDF of a diploma, trade certificate, licence or employer letter. Gemini reads the document and checks the name, the skills it shows and signs of forgery: genuine ones are approved at once (`MENDMAP_MJESHTER_AUTO=off` to always ask a person), fakes are rejected with a reason in the user's language, and unclear ones wait in the admin *Mjeshtri* tab. Documents are stored in `backend/private/` and only admins can open them. The AI photo check also marks *skilled jobs* (too much for an ordinary neighbour, but fine for a mjeshtër, e.g. a broken bench or a blocked drain). Verified mjeshtër volunteers with the skill can take them, and anyone can tap *Ask a mjeshtër* to notify them. Live electricity, gas, roads and heights stay with the crew.

**Partner rewards:** admins add, edit and hide partner rewards in the *Fixes & rewards* tab (partner, reward, emoji, badge price, how many vouchers). A fixer spends badges in the app and gets a voucher code such as `MM-7KX2QF` to show at the partner; the admin marks it *Used* so it can't be used twice. Citizens get a push when a new reward is added. MendMap does not move money.

Voice notes are transcribed when a Gemini key is set (see *AI* below); otherwise they stay audio only.

```
mendmap/
├── public/    Public transparency page, served by the API at /city
├── backend/   FastAPI + SQLAlchemy (MySQL in production, SQLite for quick dev)
├── admin/     City dashboard (plain HTML/JS + Leaflet), served by the API at /admin
└── mobile/    Expo (SDK 58) + Expo Router app for Android and iOS
```

> **Windows tip:** keep the project in a short path such as `C:\dev\mendmap`. Deep folders run past Windows' 260-character path limit, which breaks `npm install` and Python DLL loading.

---

## 1. Backend (FastAPI)

```powershell
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env      # then edit DATABASE_URL, JWT_SECRET, ADMIN_PASSWORD
uvicorn app.main:app --env-file .env --reload --host 0.0.0.0 --port 8000
```

- API docs: http://localhost:8000/docs
- City dashboard: http://localhost:8000/admin
- Tables are created on first start. The categories (Pothole, Streetlight, Illegal dumping, Other) and the first admin account (`ADMIN_EMAIL` / `ADMIN_PASSWORD`) are seeded then too.
- `SEED_DEMO=1` adds 19 demo reports in Prishtina, Kosovo (real neighbourhoods, Albanian and English descriptions, a photo on each, city comments), partner rewards and the demo accounts (see *Demo accounts* above), and turns on the one-tap demo sign-in.
- `python -m app.seed --reset-demo` replaces **all** reports with a fresh Prishtina set. Use it on demo databases only.
- If `DATABASE_URL` is not set, the API uses a local `mendmap.db` SQLite file. That's handy for a first try.

### MySQL

```sql
CREATE DATABASE mendmap CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'mendmap'@'%' IDENTIFIED BY 'change-me';
GRANT ALL ON mendmap.* TO 'mendmap'@'%';
```
`DATABASE_URL=mysql+pymysql://mendmap:change-me@localhost:3306/mendmap?charset=utf8mb4`

### Tests
```powershell
python test_api.py
```
This runs the whole lifecycle: register, report with photo, duplicate search, “I see this too”, admin status changes, timeline and stats.

### Data model
| Table | Columns |
|---|---|
| users | id, name, email, password_hash, role (citizen/admin), push_token, created_at |
| categories | id, name, icon |
| reports | id, user_id, category_id, description, photo_url, latitude, longitude, status, confirmations, created_at, updated_at |
| status_updates | id, report_id, admin_id, old_status, new_status, comment, created_at |
| report_confirmations | report_id, user_id, created_at (one “I see this too” per user) |

### API
| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/auth/otp/send` | Sends a 6-digit sign-up code (demo mode returns it as `demo_code`) |
| POST | `/auth/register`, `/auth/login` | Account (register needs the `code`), returns JWT |
| POST | `/auth/social` | **Demo** Google/Apple sign-in: `{provider, name, email, code}` |
| GET | `/auth/demo-accounts` | Demo accounts for the one-tap sign-in (empty unless `SEED_DEMO=1`) |
| GET | `/me` · PUT `/me/push-token` · PUT `/me/language` | Current user · save Expo push token · main language |
| GET | `/categories` | Report categories |
| POST | `/reports` | Multipart: `category_id`, `latitude`, `longitude`, `description?`, `photo` (required, 400 without it) |
| GET | `/reports?category=&status=&near=lat,lng&radius=` | Map pins; with `near`, sorted by distance (`distance_m`) |
| GET | `/reports/{id}` | Report with status timeline |
| POST | `/reports/{id}/confirm` | “I see this too” |
| GET | `/me/reports` | My reports with timelines |
| PATCH | `/admin/reports/{id}/status` | `{status, comment}` and sends a push notification |
| DELETE | `/admin/reports/{id}` | Remove spam |
| GET | `/me/fixer` · `/public/fixers` | Fixer level, open jobs in my area, my jobs · top neighbour fixers |
| GET | `/admin/stats` | Totals per status and category, average days to fix |

Photos are saved to `backend/uploads/` and served at `/uploads/...`.

---

## 2. Mobile app (Expo)

```powershell
cd mobile
npm install
npx expo start
```

The app finds the API automatically: it uses the IP of the computer running `expo start`, on port 8000. Your phone must be on the same Wi-Fi, and the API must run with `--host 0.0.0.0`. For a deployed API, set `EXPO_PUBLIC_API_URL=https://api.example.com`.

**Expo Go vs development build:** maps, camera, GPS and the intro video work in Expo Go. **Push notifications need a development build**:
```powershell
npx eas-cli@latest init          # adds the EAS projectId needed for push tokens
npx eas-cli@latest build --profile development --platform android
```
For Google Maps in store builds, add `androidGoogleMapsApiKey` through the `react-native-maps` config plugin.

### Screens
- **Intro:** the 3D animation (`assets/video/intro.mp4`) plays on every launch. Tap *Skip* to jump ahead. It fades into the app with Reanimated.
- **Welcome page:** after the intro, the ad (`assets/video/ad.mp4`) and the how-to video (`assets/video/tutorial.mp4`) play with sound (muted with a *Sound on* button if the browser blocks sound). The X closes it; *Don't show this again* is remembered on the device.
- **Map:** all reports as pins coloured by status (orange = reported, amber = in progress, blue = fixed), with category and status filters. Tap a pin for a preview card.
- **Report:** take or pick a photo (required), choose a category, and GPS places a draggable pin. Add an optional note. Before sending, it checks for open reports of the same category within 40 m and offers *I see this too* instead of a duplicate. With no signal, the report is saved as an **offline draft** and sent automatically when you're back online.
- **Settings (gear tab):** account card, a **My reports** button (opens the list), *Fix & earn*, appearance and language, your neighbourhood, near-you alerts, badges, and sign out (asks first).
- **My reports** (from Settings): each report with a 3-step progress bar, an All / Open / Fixed filter, and drafts waiting for signal (tap to retry).
- **Report detail:** photo, area, severity and city priority, voice note player, *Share*, mini map, *I see this too* button, and the status timeline with city comments. Tapping a push notification opens this screen.
- **City:** fix rate and time to fix, reports near your home area and the neighbourhood leaderboard.
- **Fix & earn (residents):** every open job the AI calls safe, in any neighbourhood (yours first), with a *Take* button, your jobs with a 48-hour countdown, your fixer level (New fixer → Helper → Fixer → Local hero → Legend at 1/5/10/20 badges), progress to the next partner reward with a *See partner rewards* button, how it works, and the top fixers. Report details show the AI check and say why a job can't be taken (the AI says it isn't safe, or it needs the crew). Residents get a push when a job they can fix appears in their area, and a job not finished within 48 hours goes back to the map.
- **Jobs (crew and admin):** In progress reports in nearest-first order with a route line, directions, and a *Mark fixed* sheet that needs an after photo. The list is cached and finished jobs queue up offline.
- **Report** also runs the AI photo check, has a 1–5 severity picker and records an optional voice note. **My reports** shows badges and the near-you alerts switch.

```
mobile/src/
├── app/            Expo Router routes
│   ├── _layout.tsx          root stack + intro + notification taps + draft sync
│   ├── login.tsx
│   ├── (tabs)/index.tsx     map
│   ├── (tabs)/report.tsx    new report flow
│   ├── (tabs)/mine.tsx      my reports, badges, alerts
│   ├── (tabs)/city.tsx      stats, leaderboard, near you
│   ├── (tabs)/jobs.tsx      crew route + after photo
│   └── report/[id].tsx      detail + timeline
├── components/     Intro, pins, buttons, voice, share card
└── lib/            api client, auth, push, offline drafts, crew queue, theme, i18n
```

### Look and language
- **Font:** Space Grotesk (the font in the intro), regular and medium only. There is no bold text.
- **Light and dark mode:** follows the phone by default, or pick one under *My reports*. It's saved on the phone.
- **Languages:** English plus the language of the country you're in. The country comes from GPS (reverse geocoding), falling back to the phone's region. Kosovo and Albania add Albanian (Shqip), Hungary adds Hungarian (Magyar). Anywhere else the app is English only. Every account also has a **main language** (any language, picked at sign-up or in Settings and saved on the account) that is always offered, so an Albanian in Italy can keep the app in Albanian. Switch on the sign-in screen or in Settings. Push notification text and the city dashboard stay in English.

---

## 3. City dashboard

Open http://localhost:8000/admin and sign in with the admin account.
- **Reports:** a sortable table, sorted by city priority by default, with filters and search. Click a row to see the photo, voice note, priority reasons and location, change the status with a comment (the citizen is notified), upload an after photo, view the timeline, or delete.
- **Public page ↗:** the same data for residents at `/city/`: stats, heatmap and leaderboard.
- **Map:** every report on an OpenStreetMap map, centred on Prishtina.
- **Theme:** the ◐ button switches light and dark. It starts from the system setting and is remembered in the browser.
- **Statistics:** totals per status, reports per category, and average time to fix.

## AI: photo check and voice transcription
Put a key in `backend/.env` (the API loads it on start) and restart the API:
- `GEMINI_API_KEY=...`: Gemini does the **photo check** and **transcribes voice notes** (in the language spoken, e.g. Albanian). The transcript shows under the voice note in the app and in the admin panel. `GEMINI_MODEL` picks the model (default `gemini-3.8-flash`).
- `ANTHROPIC_API_KEY=...`: Claude does the photo check (no transcription).

**Who may fix what:** after a report is saved, the server runs the AI photo check itself and stores the verdict: category, severity (filled in if the citizen left it empty), and whether a neighbour could fix it safely, with a reason. Any resident can take any job in any neighbourhood unless the AI says it isn't safe. Reports the AI hasn't checked fall back to the safe categories (dumping, accessibility, other). The app shows the verdict on the report, and admins can run or re-run the check from the report drawer. Gemini models are asked in parallel (a new one every 2 s until one answers, 25 s at most) and answers are cached for an hour, so the app's check before sending and the server's check after cost one call.

With both keys Gemini is used; set `MENDMAP_AI_PROVIDER=claude` to switch. Photos are downscaled before they're sent. Without a key the photo check returns `{"available": false}` and the app skips it, and voice notes stay audio only. `MENDMAP_AI=off` turns AI off. `GET /ai/status` shows what's switched on.

## Sign-up codes and Google/Apple (demo)
- Every new account confirms its email with a **6-digit code**: valid 10 minutes, 5 tries, a new one every 30 s. Only a hash of the code is stored.
- **Demo mode** (default): no email is sent; the app shows the code on screen with a *Fill in* button.
- In the app the code goes into six boxes (iOS can also suggest it from Mail). A wrong code shakes the boxes, and the screen counts down to when the code expires. Sign-up with an email that already has an account stops before any code is sent.
- **Real email:** set `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` in `backend/.env` (e.g. Brevo's free plan or Gmail with an app password) and restart the API. The code then goes by email only.
- **Continue with Google / Apple** is a demo: no real Google or Apple account is checked. You enter a name and email, and the code confirms it. Signing in again with the same email opens the same account. Real sign-in needs a Google OAuth client ID (`expo-auth-session`) and Sign in with Apple (`expo-apple-authentication`, a paid Apple developer account and a development build), with the API checking the ID token.

## Roadmap
Accessible walking routes · more languages, multi-city setup.
