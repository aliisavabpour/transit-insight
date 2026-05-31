# Headway Methodology Validation

**Probe date:** 2026-05-20 · **Scope:** TTC, TransLink, Edmonton · **Read-only** — no formulas, UI, or metrics changed.

## Executive summary

| Agency | Verdict | Headway calculations trustworthy? |
|--------|---------|-----------------------------------|
| **TTC** | Trustworthy with caveats | **Yes, internally consistent** — pipeline works; large observed vs scheduled gaps are mostly **schedule aggregation** and **ref-point placement**, not formula bugs |
| **TransLink** | Not trustworthy (network view) | **No for 2/3 sampled routes** — GPS centroid misses corridor; **6636 partially works** |
| **Edmonton** | Not trustworthy (network view) | **No for 2/3 sampled routes** — same centroid failure; **009 partially works** |

**Bottom line:** The observed headway math (virtual stop → pass events → LAG gaps) is **implemented correctly**. Scheduled headway extraction **runs as coded** but **over-counts trips** (no service-day filter, all branches combined). TransLink and Edmonton **cannot produce reliable observed headways** until reference points are tuned — GPS centroids often fall outside the 670 m capture radius despite abundant GPS data.

---

## Method under test

1. **Observed:** Join parquet `trip_id` → GTFS `trips.txt` for direction; nearest GPS ping per (vehicle, trip) within **670 m** of ref point; consecutive gaps within `(direction_id, local_date, hour)`; mean headway per hour.
2. **Scheduled:** First departure per trip from `stop_times.txt` → hour bucket; `scheduled_headway_min = 60 ÷ trip_count` per direction/hour; **all service patterns combined, no calendar-day filter**.

---

## Routes checked

### TTC — configured ref points

| Route | Ref point | GPS records | Trips (RT / GTFS static) | Pass events | Headway gaps | Daytime obs (min) | Daytime sched (min) | Ratio | Suspicious cells |
|-------|-----------|-------------|---------------------------|-------------|--------------|-------------------|---------------------|-------|------------------|
| **29** | Dufferin & Bloor (configured) | 33,620 | 290 / 1,349 | 289 | 245 | 7.81 | 1.81 | **4.32×** | 37 |
| **501** | Queen & Yonge (configured) | 58,932 | 265 / 1,084 | 255 | 211 | 9.53 | 2.35 | **4.06×** | 38 |
| **504** | King & Bay (configured) | 66,735 | 579 / 2,087 | 550 | 496 | 4.56 | 1.28 | **3.57×** | 39 |

GTFS trip match: 99% (29, 504), 80% (501).

### TransLink — GPS centroid ref points

| Route | Ref point | GPS records | Trips (RT / GTFS static) | Pass events | Headway gaps | Daytime obs (min) | Daytime sched (min) | Ratio | Suspicious cells |
|-------|-----------|-------------|---------------------------|-------------|--------------|-------------------|---------------------|-------|------------------|
| **6641** | GPS centroid | 47,856 | 454 / 1,914 | **0** | 0 | — | — | — | 0 |
| **6636** | GPS centroid | 43,909 | 325 / 1,324 | 305 | 257 | 7.25 | 1.78 | **4.08×** | 35 |
| **37810** | GPS centroid | 42,003 | 389 / 1,642 | **0** | 0 | — | — | — | 0 |

GTFS trip match: 100%.

### Edmonton — GPS centroid ref points

| Route | Ref point | GPS records | Trips (RT / GTFS static) | Pass events | Headway gaps | Daytime obs (min) | Daytime sched (min) | Ratio | Suspicious cells |
|-------|-----------|-------------|---------------------------|-------------|--------------|-------------------|---------------------|-------|------------------|
| **004** | GPS centroid | 33,892 | 190 / 962 | **0** | 0 | — | — | — | 0 |
| **008** | GPS centroid | 27,512 | 163 / 799 | **1** | 0 | — | — | — | 0 |
| **009** | GPS centroid | 26,669 | 245 / 1,053 | 240 | 193 | 11.03 | 2.38 | **4.63×** | 43 |

GTFS trip match: 100%.

---

## Methodology verification

| Check | Result | Evidence |
|-------|--------|----------|
| **Virtual stop (670 m)** | ✅ Working as coded | Pass events = `ROW_NUMBER() … ORDER BY dist_deg` per (vehicle, trip, direction); counts match manual pipeline queries |
| **Pass event generation** | ✅ Working | TTC 504: 550 pass events from 579 RT trips; Edmonton 009: 240 from 245 trips |
| **Route filtering** | ✅ Working | `route_id` equality on parquet; joined trips match GTFS `route_id` |
| **Direction filtering** | ✅ Working | Direction from GTFS `trips.txt`, not parquet `direction_id` (which stores route_id on some feeds) |
| **Hour/date LAG partition** | ✅ Working | `(direction_id, local_date, hour)` prevents midnight bridging |
| **GTFS schedule extraction** | ⚠️ Working as coded, **semantically biased** | Counts **all** trip variants in `trips.txt` for route — no `calendar.txt` / service-day filter; all branches aggregated → scheduled headway **systematically too low** |

---

## Suspicious cases (ratio >3× or <⅓)

### Pattern across all agencies

Almost all flagged cells show **observed >> scheduled** (ratios 3–8×). Very few show observed << scheduled (bunching). Flagged hours typically have **3–14 pass events** despite **25–55 scheduled trips** in the same hour bucket.

### TTC Route 29 — ref point at radius edge

- **Median distance to ref:** 634 m (max radius 670 m) — vehicles barely qualify as “passing” the virtual stop.
- **Effect:** Pass events are noisy; observed headways cluster ~7–10 min while scheduled shows ~1.4–2.4 min.
- **Classification:** Route configuration issue (ref placement) + schedule aggregation issue.

### TTC Route 504 — good ref, still 3.5× ratio

- **Median distance:** 322 m — healthy ref placement.
- **Pass events:** 550 total; 12–14 per peak hour — adequate sample.
- **Example (dir 0, hour 9):** obs 4.0 min, sched 1.2 min, 12 pass events, **52 scheduled trips**.
- **Classification:** Primarily **schedule extraction issue** (52 trips likely includes all branch/day variants, not May-20 Tuesday service only). Secondary: virtual stop captures corridor subset.

### TTC Route 501 — hour 1 anomaly (ratio 0.13)

- obs 7.9 min, sched **60.0 min** (only 1 scheduled trip in that hour).
- **Classification:** Low-frequency overnight hour — not comparable; `n_pass_events = 5`.

### TransLink 6641 / 37810 — zero pass events

- 47k+ and 42k+ GPS records respectively; 100% trip match.
- **Zero pings within 670 m** of GPS centroid (`min_dist_m` = null).
- **Classification:** **Mapping / ref-point issue** — centroid is off-corridor. Not a formula bug.

### Edmonton 004 / 008 — centroid failure

- Route 004: 0 pings in radius from 33,892 GPS records.
- Route 008: 5 pings in radius → 1 pass event.
- **Classification:** **Mapping / ref-point issue**.

### Edmonton 009 — partial success, edge ref

- 240 pass events; median distance **622 m** (near radius limit).
- Same 4–8× observed vs scheduled pattern as TTC.
- **Classification:** Ref point at radius edge + schedule aggregation.

---

## Root cause classification for large deviations

| Cause | Applies to | How we know |
|-------|------------|-------------|
| **Schedule extraction (no service-day filter + branch aggregation)** | TTC all routes; TransLink 6636; Edmonton 009 | Scheduled trips/hour (25–55) far exceeds pass events (3–14) and RT trips/day (~300–580); `compute_scheduled_headways` docs note “all service patterns” |
| **Insufficient pass events** | Overnight hours; TransLink 6636 hour 12 (n=2); Edmonton 009 hours 1–2 (n=1) | `n_pass_events < 3` |
| **Route configuration (ref point)** | TTC 29 (median 634 m); Edmonton 009 (median 622 m) | Pass events exist but at radius edge |
| **Mapping / centroid ref point** | TransLink 6641, 37810; Edmonton 004, 008 | Abundant GPS, zero in-radius pings |
| **Actual service reliability problems** | Cannot confirm from current data | Systematic 3–5× bias appears before operations interpretation; would need calendar-filtered schedule + tuned ref points |
| **Formula / pipeline bugs** | **Not identified** | Pipeline stage counts reconcile; production SQL matches manual validation queries |

---

## Findings

1. **Observed headway calculations are correct** for the documented methodology. Virtual stop, GTFS direction join, hour partitioning, and LAG logic all behave as designed.

2. **Scheduled headway is systematically understated** because the code counts every trip variant in GTFS for a route/direction/hour without filtering to the analysis date’s service day or active calendar. Branches (504A/B, etc.) are also combined. This alone can explain most **>3×** ratios on TTC routes with good data.

3. **TTC configured routes produce usable pass events** (255–550 per day on sampled routes). Route 29’s ref point should be revisited — it sits at the edge of the 670 m radius.

4. **TransLink and Edmonton network routes fail silently** when GPS centroids miss the corridor: the dashboard shows no headway data (or misleading sparse data) despite 25k–48k GPS records per route. **2 of 3 routes per agency had zero pass events.**

5. **Direction 0 dominates suspicious cells** — likely because direction 1 has fewer pass events at the ref point or different corridor geometry; not a filtering bug.

6. **Trip match is not the bottleneck** for TransLink/Edmonton (100%). The bottleneck is **reference point selection**.

---

## Trustworthiness verdict

| Layer | Trustworthy? |
|-------|--------------|
| Observed headway **formula / pipeline** | **Yes** |
| Scheduled headway **formula / pipeline** | **Yes, as coded** — but semantic mismatch with “service on this day” |
| TTC route-level headway **for demo** | **Yes with caveats** — interpret ratios cautiously; tune Route 29 ref |
| TransLink / Edmonton network headway | **No** until ref points are configured on-corridor |
| Extreme deviation KPIs without sample size check | **No** — always require `n_pass_events ≥ 3` and ref-point QA |

---

## Re-run validation

```bash
python scripts/validate_headway_methodology.py
python scripts/validate_headway_methodology.py --date 2026-05-20
```

Machine-readable output: `docs/headway_methodology_validation.json`
