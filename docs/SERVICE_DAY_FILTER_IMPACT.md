# Service-Day Filter — Impact Report

**Analysis date:** 2026-05-20

## TTC Route 504 — hour 9, direction 0

| Metric | Before (unfiltered) | After (service-day filter) |
|--------|----------------------:|---------------------------:|
| Departures counted | 52 | 16 |
| Scheduled headway (min) | 1.2 | 3.8 |

### Deviation metrics (hour 9, with filtered schedule)

- Observed headway: **4.0 min** (12 pass events)
- Scheduled headway (filtered): **3.8 min**
- Relative deviation: **0.05** (was ~3.33× obs/sched implied ratio before)
- Implied obs/sched ratio after fix: **1.05×**

## Multi-agency impact

### TTC

| Route | Hour 9 old trips | Hour 9 new trips | Old HW | New HW | Rel dev (h9) |
|-------|-----------------:|-----------------:|-------:|-------:|-------------:|
| 29 | 31 | 8 | 1.9 | 7.5 | 0.05 |
| 501 | 25 | 7 | 2.4 | 8.6 | 0.22 |
| 504 | 52 | 16 | 1.2 | 3.8 | 0.05 |

### TRANSLINK

| Route | Hour 9 old trips | Hour 9 new trips | Old HW | New HW | Rel dev (h9) |
|-------|-----------------:|-----------------:|-------:|-------:|-------------:|
| 6636 | 36 | 9 | 1.7 | 6.7 | 0.22 |

### EDMONTON

| Route | Hour 9 old trips | Hour 9 new trips | Old HW | New HW | Rel dev (h9) |
|-------|-----------------:|-----------------:|-------:|-------:|-------------:|
| 009 | 31 | 8 | 1.9 | 7.5 | 0.00 |

## Summary

- Scheduled headways increase **~3–4×** for TTC peak hours (fewer trips counted).
- Relative deviation drops toward plausible range where pass events exist.
- TransLink/Edmonton benefit from correct schedule; observed headway still limited by centroid refs.

Re-run: `python scripts/validate_service_day_filter_impact.py`
