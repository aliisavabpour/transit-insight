# Scheduled Headway & Pass-Event Validation

**Probe date:** 2026-05-20 (wednesday) · **Sample route:** TTC 504

Read-only validation — no formulas, UI, or new metrics implemented.

---

## A. Scheduled headway validation (TTC Route 504)

### What `compute_scheduled_headways` does today

| Check | Used in production? |
|-------|---------------------|
| `calendar.txt` day-of-week filter | **No** |
| `calendar_dates.txt` exceptions | **No** |
| `service_id` active on analysis date | **No** |
| Trip filter | `route_id` only |
| Branch aggregation | **Yes** — all headsign/shape variants per direction/hour |

### Trip counts (Route 504, all GTFS vs active service day)

| Metric | Count |
|--------|-------|
| Total trips in `trips.txt` for route | 2,087 |
| Trips active on 2026-05-20 | 581 |
| Reduction | **72.2%** fewer trips with calendar filter |
| Distinct service_ids (route / active day) | 4 / 1 |

### Hour 9, Direction 0 — current vs corrected

| Method | Departures counted | Scheduled headway |
|--------|-------------------:|------------------:|
| **Current** (production) | 52 | 1.2 min |
| **Corrected** (calendar-filtered) | 16 | 3.75 min |
| **Inflation factor** | **3.25×** | current understates headway by ~3.25× |

Peak-hour (06–18) average inflation factor (dir 0): **3.63×**

### Exact trips counted — hour 9, direction 0

- **Current:** 52 trips (3 headsigns, 5 shapes)
- **Corrected:** 16 trips on active service day

Sample corrected departures:

- West - 504A King towards Dundas West Station (shape `shp-504-57`): 130 trips
- East - 504B King towards Broadview Station (shape `shp-504-04`): 129 trips
- East - 504A King towards Distillery (shape `shp-504-05`): 126 trips
- West - 504B King towards Dufferin Gate (shape `shp-504-59`): 78 trips
- West - 504B King towards Dufferin Gate (shape `shp-504-53`): 48 trips
- East - 504 King Short Turn towards Broadview and Queen (shape `shp-504-44`): 10 trips
- West - 504 King towards Distillery (shape `shp-504-97`): 10 trips
- West - 504 King Short Turn towards Roncesvalles and Queen (shape `shp-504-54`): 7 trips

### Hour-by-hour comparison (direction 0)

| Hour | Current trips | Corrected trips | Current HW (min) | Corrected HW (min) | Inflation |
|------|--------------:|----------------:|-----------------:|-------------------:|----------:|
| 5 | 36 | 15 | 1.67 | 4.0 | 2.4× |
| 6 | 33 | 12 | 1.82 | 5.0 | 2.75× |
| 7 | 42 | 18 | 1.43 | 3.33 | 2.33× |
| 8 | 48 | 15 | 1.25 | 4.0 | 3.2× |
| 9 | 52 | 16 | 1.15 | 3.75 | 3.25× |
| 10 | 50 | 14 | 1.2 | 4.29 | 3.57× |
| 11 | 46 | 12 | 1.3 | 5.0 | 3.83× |
| 12 | 49 | 12 | 1.22 | 5.0 | 4.08× |
| 13 | 48 | 12 | 1.25 | 5.0 | 4.0× |
| 14 | 48 | 12 | 1.25 | 5.0 | 4.0× |
| 15 | 48 | 12 | 1.25 | 5.0 | 4.0× |
| 16 | 48 | 12 | 1.25 | 5.0 | 4.0× |
| 17 | 48 | 12 | 1.25 | 5.0 | 4.0× |
| 18 | 50 | 12 | 1.2 | 5.0 | 4.17× |
| 19 | 53 | 13 | 1.13 | 4.62 | 4.08× |
| 20 | 51 | 15 | 1.18 | 4.0 | 3.4× |
| 21 | 50 | 12 | 1.2 | 5.0 | 4.17× |
| 22 | 52 | 13 | 1.15 | 4.62 | 4.0× |

### Is scheduled headway inflated?

**Yes.** Production scheduled headway for TTC 504 on 2026-05-20 is inflated by roughly **3.25× at hour 9** (and ~3.63× across peak hours) because trips from inactive service patterns are included. This is the primary driver of observed/scheduled ratios >3× seen in the prior headway validation — not a bug in observed headway math.

Branch aggregation on the active day is **intentional** for corridor frequency (multiple short-turn patterns passing the same ref point should count), but must be applied **after** service-day filtering.

**Cross-check with observed headway (prior validation):** Route 504, hour 9, direction 0 had **observed mean 4.0 min** vs production scheduled **1.2 min** (ratio 3.3×). With calendar-corrected scheduled **3.75 min**, the implied ratio drops to **~1.07×** — consistent with the schedule filter being the dominant fix, not observed headway rework.

---

## B. Pass-event validation (TransLink & Edmonton)

Centroid ref = mean GPS position. Pass event requires a ping within **670 m** of centroid.

### TRANSLINK

- Routes analyzed (top by GPS volume): 12
- Routes with **zero pass events**: 6 (6641, 37810, 6622, 23384, 6705, 6712)

| Route | GPS records | Pass events | Min dist (m) | Median dist (m) | Nearest stop (m) | Cause |
|-------|------------:|------------:|-------------:|----------------:|-----------------:|-------|
| 6641 | 47,856 | 0 | 2003.5 | 5790.2 | 2009.7 | centroid_off_corridor |
| 6636 | 43,909 | 305 | 248.7 | 8480.4 | 475.4 | centroid_at_radius_edge |
| 37810 | 42,003 | 0 | 1698.3 | 6275.3 | 1711.0 | centroid_off_corridor |
| 6622 | 36,303 | 0 | 2495.6 | 5811.0 | 2529.6 | centroid_off_corridor |
| 23384 | 34,420 | 0 | 764.9 | 11427.7 | 890.2 | centroid_off_corridor |
| 6705 | 33,599 | 0 | 1287.8 | 6610.7 | 1289.3 | centroid_off_corridor |
| 6627 | 31,606 | 180 | 402.0 | 8369.6 | 414.7 | centroid_at_radius_edge |
| 37807 | 27,982 | 204 | 126.3 | 6294.2 | 450.2 | centroid_at_radius_edge |
| 6712 | 27,438 | 0 | 682.3 | 4046.9 | 715.9 | centroid_off_corridor |
| 6624 | 27,435 | 190 | 174.3 | 10361.0 | 263.2 | centroid_at_radius_edge |
| 16718 | 25,376 | 164 | 33.5 | 5623.0 | 616.8 | centroid_at_radius_edge |
| 6728 | 25,022 | 79 | 350.0 | 9813.5 | 1212.7 | centroid_at_radius_edge |

### EDMONTON

- Routes analyzed (top by GPS volume): 12
- Routes with **zero pass events**: 6 (004, 056, 007, 055, 114, 053)

| Route | GPS records | Pass events | Min dist (m) | Median dist (m) | Nearest stop (m) | Cause |
|-------|------------:|------------:|-------------:|----------------:|-----------------:|-------|
| 004 | 33,892 | 0 | 1178.6 | 7656.1 | 1248.0 | centroid_off_corridor |
| 008 | 27,512 | 1 | 280.3 | 3635.0 | 1590.9 | centroid_at_radius_edge |
| 009 | 26,669 | 240 | 569.3 | 4274.2 | 583.0 | centroid_at_radius_edge |
| 005 | 24,853 | 1 | 218.6 | 3059.0 | 1409.5 | centroid_at_radius_edge |
| 056 | 24,652 | 0 | 758.1 | 9203.3 | 1776.5 | centroid_off_corridor |
| 002 | 21,517 | 153 | 459.8 | 5546.2 | 624.7 | centroid_at_radius_edge |
| 007 | 17,358 | 0 | 1143.3 | 4825.2 | 1168.7 | centroid_off_corridor |
| 055 | 12,870 | 0 | 810.0 | 8895.6 | 829.6 | centroid_off_corridor |
| 114 | 12,203 | 0 | 948.4 | 2862.8 | 1188.4 | centroid_off_corridor |
| 701 | 11,983 | 88 | 115.4 | 2078.7 | 111.4 | centroid_at_radius_edge |
| 052 | 11,978 | 87 | 339.9 | 4497.7 | 376.8 | centroid_at_radius_edge |
| 053 | 11,543 | 0 | 739.1 | 5484.1 | 830.1 | centroid_off_corridor |

### Why zero pass events?

1. **Centroid off corridor:** Mean GPS lat/lon can fall between branches, in yards, or away from the common trunk. If *minimum* distance from any ping to centroid exceeds 670 m, pass events = 0 despite tens of thousands of GPS records.
2. **Nearest stop distance** confirms this: centroids for failed routes are often **>1 km** from the nearest stop on the route, while successful routes (e.g. TransLink 6636, Edmonton 009) have nearest-stop distances within the capture radius.
3. **Not a trip-match or pipeline bug:** GTFS join and virtual-stop logic work when the ref point intersects the corridor.

### Are centroid references appropriate?

**No**, not as a default for network reliability. Acceptable only as a bootstrap placeholder with automatic QA (min/median distance checks). TTC uses hand-picked intersection refs; TransLink/Edmonton need equivalent corridor refs (major stop, shape midpoint, or map-picked point).

---

## C. Recommendations

### Must fix before reliability metrics can be trusted

| # | Fix | Why | Effort |
|---|-----|-----|--------|
| 1 | **Add service-day filter to `compute_scheduled_headways`** — join `calendar.txt` + `calendar_dates.txt`, filter trips by active `service_id` for analysis date | Removes ~3–4× scheduled inflation on TTC 504; aligns schedule with RT day | **Small** (0.5–1 day): SQL change + unit tests; handle `calendar_dates`-only feeds (Edmonton) |
| 2 | **Replace GPS centroid refs for TransLink/Edmonton** with corridor refs (configured stop or shape-based point) + QA gate (require min ping distance < radius) | **50%** of top-12 routes by GPS volume produce zero pass events (6/12 each agency) | **Medium** (2–3 days): ref selection script, store in route config or auto-pick nearest high-traffic stop |
| 3 | **Expose sample-size / ref-quality guards** before showing deviation KPIs (`pass_events ≥ 3`, centroid distance check) | Prevents silent null/misleading metrics | **Small** (0.5 day): data layer flags only (UI later) |

### Can remain as future work

| Item | Notes | Effort |
|------|-------|--------|
| EWT / CoV metrics | User requested not yet | Medium |
| UI warnings for low-confidence cells | After data-layer guards exist | Small |
| Per-branch scheduled headway (504A vs 504B) | Only if ref point is branch-specific | Medium |
| Shape-based virtual stop (snap to nearest shape point) | Better than centroid, harder than fixed ref | Medium–Large |
| TTC Route 29 ref re-tuning | Median dist 634 m at configured ref | Small |

### Priority order

1. Service-day schedule filter (unblocks all agencies, largest ratio correction)
2. Corridor reference points for TransLink/Edmonton (unblocks observed headway)
3. Ref-quality / sample-size guards (prevents false KPIs)

---

## Re-run

```bash
python scripts/validate_scheduled_and_pass_events.py
python scripts/validate_scheduled_and_pass_events.py --date 2026-05-20 --route 504
```
