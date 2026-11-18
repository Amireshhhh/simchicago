# Social layer: concept and privacy design (not built)

Status: design only. Nothing in SimChicago collects, stores or shares anyone's location today, and
the site has no accounts. This document is what would have to be true before any of it is built.

## Why it needs more than GitHub Pages

GitHub Pages serves static files: it cannot hold accounts, store a profile or relay a friend's
position. Everything below needs a small backend with authentication and a database, for example
a managed Postgres with row-level security, or serverless functions with a key-value store. The
static site stays as it is and calls that backend only for the social features. The CTA keys
stay in GitHub Actions; the social backend never sees them and never calls CTA.

## Principles (non-negotiable)

1. **Off by default, opt-in per feature.** No location leaves a phone until the user turns on a
   specific feature, and turning it off deletes what the server holds.
2. **Friends only, mutual.** A live position is visible only to people the user has accepted, and
   who accepted back. No public map of real people, ever; the public map shows only simulated
   residents and CTA vehicles.
3. **Coarse by default.** Shared positions are snapped to the nearest CTA stop or a ~250 m cell
   unless the user chooses "exact" for a session.
4. **Ephemeral.** A shared session ends by itself (default 1 hour, max 8); positions are kept only
   in memory for the session and are not stored as a history. Journeys a user saves are kept
   as stops and lines, not GPS traces.
5. **No minors in location features.** Location sharing for adults only (in the US, collecting
   personal information from children under 13 triggers COPPA; the simplest safe rule is 18+ for
   any live-location feature).
6. **Panic button.** One tap stops all sharing and hides the user from every friend at once.
7. **No selling, no ads, no third-party trackers;** aggregate statistics only with k-anonymity
   (no cell with fewer than 20 people is ever shown).

## Feature ideas, ranked by fun per privacy risk

| # | Idea | What it is | Location needed? |
|---|---|---|---|
| 1 | **Mystery journey** | Pick a budget (time, fare) and a vibe (food, views, murals, quiet); get a sealed itinerary on real CTA lines: "take the next Pink Line inbound, get off when you see a mural…". Clues unlock at each stop. Uses the GTFS network model and portal datasets (murals, landmarks, sidewalk cafes, benches). | No (clues unlock by checking in at a stop, which can be done by tapping) |
| 2 | **Line collector** | Collect all 8 'L' lines, all 143 stations, all 77 community areas; badges for night owls (owl routes), loop completions, longest single-seat ride. | No (self-reported check-ins; optional on-device verification) |
| 3 | **Meet in the middle** | A group enters their stations; SimChicago finds the fairest meeting point by the network model (minimise the worst person's travel time, not the average), with a place to sit there (benches layer). | No (stations only) |
| 4 | **Beat the bus** | Predict whether your bus arrives before the next train using the live feed; streaks and a weekly leaderboard among friends. | No |
| 5 | **Arcs** | A shareable "arc" is a story of a trip: lines taken, transfers, photos, a song; drawn on the 2D map as a glowing arc. Shared as a link, never live. | No (drawn from stops) |
| 6 | **Ride together** | Two or more friends on the same train see each other's car number while the session lasts. | Yes, coarse, mutual, ephemeral |
| 7 | **Live with friends** | Friends see each other on the map during a session (concerts, nights out). | Yes, the highest-risk feature: last, with every principle above |

Ideas 1-5 need no live location at all and are where the fun is; 6-7 come last, if ever.

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| Stalking or coercive control through location sharing | mutual consent, ephemeral sessions, panic button, no history, re-confirmation every session, visible indicator while sharing |
| A leaked database reveals where people live | no home locations stored; saved journeys keep stops only; positions in memory only |
| Re-identification from aggregates | k >= 20 per cell, no time series finer than an hour |
| Children | 18+ for location features; age gate on sign-up |
| Abuse of mystery clues (sending people to unsafe places) | clues only at CTA stations and public places from City datasets; no user-generated destinations without review |

## Minimal build order (when you decide to build)

1. Accounts (email magic link), profiles without location, line collector and mystery journeys
   (no location at all).
2. Meet in the middle and arcs (stations and saved stops).
3. Only after an outside privacy review: ride together, then live with friends.
