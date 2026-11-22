# MendMap brand guidelines

Taken from the app itself: `mobile/src/lib/theme.tsx`, `mobile/app.json`, `admin/styles.css` and `admin/logo.svg`. When these files change, update this page to match.

## Name and purpose
**MendMap**: one word, capital M twice. Never "Mend Map", "Mendmap" or "MENDMAP".
*Report it, map it, mend it.* Prishtina's residents photograph street problems, and neighbours and volunteer craftsmen (mjeshtër) fix them.

## Voice and tone
- **Neighbourly and practical.** Write like a helpful neighbour, not like a municipal office.
- **Short and plain.** Say what happens and why. Example: "MendMap uses your location to place your report exactly where the problem is."
- **Credit people, don't lecture them.** Thank the person who reported or fixed something. Never shame anyone.
- **Write in both languages.** Albanian (sq) and English (en) carry equal weight. Use real Albanian with ë and ç, and keep *mjeshtër* as it is.
- **Stay calm.** No exclamation-mark spam and no all-caps. The app has no bold text, so emphasis comes from colour and the medium font weight.

## Colour palette
Dark is the main look: navy night with a blue pin and an orange spark. Light mode is the alternative.

| Role | Token | Dark | Light |
|---|---|---|---|
| Background | `bg` | `#070d1f` | `#f4f6fb` |
| Surface / card | `surface` | `#0e1834` | `#ffffff` |
| Raised surface | `surface2` | `#18264a` | `#eaeef7` |
| Lines / borders | `line` | `#24335c` | `#d8dfec` |
| Text | `text` | `#e9edf7` | `#0b1530` |
| Muted text | `muted` | `#8d9ab8` | `#5d6a87` |
| **Brand blue** (primary buttons, notifications) | `blue` | `#2f63f0` | `#2f63f0` |
| Accent (links, active tabs) | `accent` | `#6d95ff` | `#2452d6` |
| **Brand orange** (spark, counts) | `orange` | `#f26a2e` | `#e2571b` |
| Amber | `amber` | `#f5b638` | `#c98a06` |
| Danger | `danger` | `#ff8a7a` | `#c8372a` |

**Status colours** (pins, chips): Reported = orange, In progress = amber, Fixed = accent blue.
**Logo gradient:** `#3B6FF5` → `#1638B8`. **Android icon background:** `#0e1f45`. Text on blue is always `#ffffff`.

## Typography
- **Space Grotesk**, the font from the intro animation. Use only two weights: Regular 400 for body text and Medium 500 for headings, buttons and emphasis. **No bold.**
- Web fallbacks: `"Space Grotesk", "Segoe UI", system-ui, sans-serif`. Use monospace (`ui-monospace, Consolas`) only for codes.

## Logo and icon
- **The mark:** a blue map pin with a blue gradient, an off-white disc (`#EEF1F7`) and an orange wrench (`#F26A2E`) drawn as a line. It reads as "a place, being fixed". Source file: `admin/logo.svg`. App versions: `mobile/assets/icon.png`, `splash-icon.png` and `android-icon-foreground.png`.
- Put it on navy (`#070d1f`) or on white. It may have a soft blue glow (`drop-shadow #2f63f088`), as on the admin login screen.
- Keep the clear space around it at least half the pin's width. Its smallest size is 24 px tall.
- Don't recolour it, stretch it, rotate it, outline it or swap the wrench out.

## Category icons
| Category | Emoji |
|---|---|
| Pothole | 🕳️ |
| Streetlight | 💡 |
| Illegal dumping | 🗑️ |
| Accessibility | ♿ |
| Other / unknown | 📍 |

Partner rewards use their own emoji, and 🎁 is the default. Map pins are round, with a 2 px white border and a soft shadow, filled with the status colour.

## Do's and don'ts
**Do**
- Use the theme tokens, not one-off hex codes. Support both dark and light mode.
- Use blue for actions, orange for "needs attention" and amber for "being worked on".
- Use darkened OpenStreetMap tiles on maps so they match the navy UI.
- Write every user-facing string in both Albanian and English.

**Don't**
- Use bold weights, extra fonts or gradients other than the one in the logo.
- Use red for ordinary reports. Red (danger) is only for errors and destructive actions.
- Show a status with colour alone. Always pair it with a label or emoji.
- Use a stock-photo look, or a bureaucratic or blaming tone.
