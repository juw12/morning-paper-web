# Morrow: web edition

*Formerly The Morning Paper. Same app, shorter name; the address is unchanged.*

**Live: https://juw12.github.io/morning-paper-web/**

A morning newspaper for markets, AI and chips, robotics, space and tech. Hundreds of headlines are boiled down to the stories that matter: coverage from several outlets is merged, there's an AI brief at the top and a "why it matters" line on every story. A stock desk sits alongside with valuation scores for big US tech and Indonesian blue chips.

## What you get

- **Curated news**: refreshed through the day, with stories you already saw in earlier editions skipped.
- **Stock desk**: forward P/E, quality and valuation scores, and live prices with intraday charts.
- **Your portfolio and price alerts, on every device**: sign in with email + password once, and your holdings and alerts follow you to your phone, laptop and work PC. Alerts cover price above/below, support breaks and SMA-200 crosses.
- **Installable**: add it to your home screen and it behaves like an app (PWA).

## How it works

- This repo only hosts the published page. A private generator builds `index.html` every morning (and every 30 minutes during the day) and pushes it here; GitHub Pages serves it.
- Sign-in and storage use a free Supabase project. Each account is one database row protected by row-level security, so an account can only ever read or write its own data. The key embedded in the page is Supabase's public "anon" key, which is designed to be shipped to browsers.
- Live prices come from a small Supabase edge function, so the page never needs your own API keys.
- `.github/workflows/keepalive.yml` pings the backend daily so the free project never pauses.

## Portfolio briefing waitlist

A planned add-on: last night's US move plus the rupiah, coal, oil and nickel, mapped to the stocks **you** hold, before the IDX opens. It's free to join: [join the waitlist](https://github.com/juw12/morning-paper-web/issues/new?template=portfolio-briefing.yml) (a short public form; please don't post your holdings).

- `.github/workflows/waitlist.yml` thanks each sign-up and keeps a live tally issue up to date (`scripts/waitlist_tally.py`, tests in `tests/`).
- Success line: 50 sign-ups between 2026-11-08 and 2026-11-22. 15-49 means rework the pitch; under 15 means stop.

## Notes

- Built by [Juwen Lie](https://github.com/juw12) as an independent personal project. Still being built, so expect changes.
- Not financial advice.
