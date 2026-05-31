# STM trip_id match investigation

**Date:** 2026-05-28  
**Probe day:** 2026-05-20 (within shared May 15–31, 2026 window)  
**Script:** `scripts/investigate_stm_trip_match.py`

## Summary

**STM is deactivated** (`status: pending`) for the shared May cohort. S3 positions are available, but **GTFS trip_id match is 0%** on May dates. Scheduled-headway / reliability metrics must not be used for STM until a matching static feed is obtained.

## 1. Does GTFS static cover May 15–31?

**Yes.**

| Source | Range |
|--------|--------|
| `feed_info.txt` | 2026-01-05 → 2026-06-14 |
| `feed_version` | `20260505090000_26M` (generated 2026-05-05) |
| `calendar.txt` services overlapping May 15–31 | **38** service_ids (mostly `26M-*`, spring/summer 2026) |
| `trips.txt` rows on those services | **56,665** trips |

Calendar overlap is **not** the problem.

## 2. Sample trip_id comparison

| Source | Example trip_ids | Numeric range (distinct) |
|--------|------------------|-------------------------|
| **Parquet** (2026-05-20) | `294563043`, `294705986`, `294741899`, `295221218` | ~9.6M – 300.7M (16,601 distinct) |
| **trips.txt** (file start) | `289939539`, `289939540`, … | 289,939,539 – 297,407,248 (176,161 distinct) |
| **May-calendar trips only** | e.g. `296382552` (`26M-GLOBAUX-02-S`) | 293,099,127 – 297,407,248 |

Parquet sample IDs like `294563043` are **not present** anywhere in `trips.txt` (including May `26M` services).

## 3. Root cause

| Hypothesis | Verdict |
|------------|---------|
| Trip IDs changed between static and RT | **Yes** — May RT uses IDs not allocated in this static file |
| Wrong GTFS version downloaded | **Likely** — `feed_version` is 2026-05-05; May 20 RT trip set is disjoint from file |
| Schedule/realtime date mismatch | **Partially** — calendar dates align; **trip_id namespace does not** |
| Missing May calendar | **No** | |

**Control:** Same `trips.txt` vs **2026-03-17** parquet → **99.79%** match (16,444 / 16,478 distinct RT trip_ids).

So the pipeline join logic is correct; the **May static snapshot does not describe the trips STM broadcasts in GTFS-RT on May 20**.

## 4. Match statistics (2026-05-20)

| Metric | Value |
|--------|--------|
| Distinct RT `trip_id` | 16,601 |
| Match vs full `trips.txt` | **0** (0.00%) |
| Match vs May-calendar trips only | **0** (0.00%) |
| Non-null `trip_id` in parquet | 100% |
| March 17 match (same GTFS file) | 99.79% |

## 5. App policy

- `agency_config.py`: `stm` → `status: pending`
- Excluded from sidebar agency selector (active agencies only)
- Do **not** present STM network reliability or schedule deviation until a GTFS static export is validated with ≥50% trip match on a May probe day

## 6. How to re-validate after new GTFS

```bash
python scripts/investigate_stm_trip_match.py
python scripts/validate_active_agencies.py
```

Promote STM to `active` only if May-window trip match ≥ 50% (same bar as other agencies).
