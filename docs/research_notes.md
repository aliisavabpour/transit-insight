# Transit Insight — Research Notes

> Living document for architecture, optimization, and report preparation.  
> **Last updated:** 2026-05-24 (submission phase)  
> **Project direction:** Scalable DuckDB over partitioned S3 GTFS-RT + lightweight exploratory schedule comparison (not operational transit reliability science).

---

## 1. Frozen architecture (do not expand without explicit decision)

```
Streamlit UI (dashboard/)
├── app.py                    # Overview, sidebar date/source controls
├── pages/
│   ├── 01_Realtime.py        # GPS map, speeds
│   ├── 03_Reliability.py     # Network deviation heatmaps
│   └── 05_Route_Analysis.py  # ★ Primary demo (Route 29)
├── components/
│   ├── page_guard.py         # require_active_agency, run_data_load
│   └── nav.py
├── utils/
│   ├── agency_config.py      # Multi-agency registry + S3 templates
│   ├── agency_loader.py      # Path resolution per agency
│   ├── positions_store.py    # ★ S3/local parquet (DuckDB httpfs)
│   ├── parquet_date.py       # Agency sidebar (date, S3/local)
│   ├── real_data.py          # GPS loaders
│   ├── reliability.py        # Headway + deviation (PRIMARY_METRICS frozen)
│   ├── gtfs_loader.py        # Agency-aware GTFS CSV
│   └── route_config.py       # Reference points
└── data/
    ├── gtfs/                 # Static GTFS (May 3–Jun 6, 2026)
    └── positions_cache/      # Optional local parquet per day
```

**Reference notebook (external):** `schedule_deviation.ipynb` — stop-level schedule deviation via spatial SQL on S3; different methodology from this app’s virtual-stop headways.

**Out of scope (frozen):** ML forecasting, multi-week aggregation, auth, multi-city production APIs, official TTC KPI claims, stop-level spatial matching (unless future phase).

---

## 2. Architecture decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Query engine | DuckDB in-process | Fast analytics on parquet/CSV without a server |
| Realtime source | Partitioned S3 parquet | Matches ETL layout; no full-file download by default |
| Static schedule | Local GTFS CSV | `trips.txt`, `stop_times.txt` for direction + scheduled headway |
| Headway method | Virtual-stop pass events | Lightweight vs full stop_times spatial join |
| Pass radius | 670 m (`REF_RADIUS_METERS`) | Reduced from ~900 m; 150–250 m yielded zero events at Route 29 ref on May 12 |
| Direction | `trip_id` → `trips.txt` | Parquet `direction_id` often stores route number |
| Date alignment | Sidebar day must fall in GTFS feed | Misaligned feeds → ~23% match; aligned May 12 → ~97% |
| UI | Streamlit multipage | Research/demo, not production ops |

---

## 3. DuckDB / S3 querying

### S3 path pattern

```
s3://gtfs-rt-etl-data/ttc/positions/year=YYYY/month=MM/day=DD/*.parquet
```

Built dynamically from sidebar **Snapshot day** (`utils/positions_store.s3_glob_for_date`).

### DuckDB session settings (`positions_store._configure_duckdb`)

- `INSTALL/LOAD httpfs`
- `SET parquet_metadata_cache = true`
- `SET enable_external_file_cache = true` (in-RAM remote Parquet blocks; **per connection**)
- `SET memory_limit = '4GB'` (override via env `DUCKDB_MEMORY_LIMIT`)
- `SET threads` (default min(8, CPU count); env `DUCKDB_THREADS`)
- `SET temp_directory = dashboard/.duckdb/tmp`
- `SET timezone` = agency timezone
- `@st.cache_resource` **shared DuckDB connection** (do not close after each query)
- **Not used:** `PRAGMA enable_object_cache` (legacy no-op in DuckDB 1.5.2)
- `read_parquet(..., hive_partitioning = true)`

### Column pruning (positions scan)

`trip_id`, `route_id`, `vehicle_id`, `direction_id`, `timestamp`, `speed`, `bearing`, `bbox`

### SQL filters pushed down

- `route_id = '…'` on route pages
- `trip_id IS NOT NULL` for GTFS-joined headway pipeline
- `DATE(timestamp AT TIME ZONE 'America/Toronto') = …` when using **local cache** only

### Implementation files

| Module | Role |
|--------|------|
| `positions_store.py` | `read_parquet_expr()`, `positions_subquery()`, `execute_query()` + timing log |
| `real_data.py` | Map/speed queries; `QUALIFY` must run on direct `read_parquet` (not nested bbox subquery) |
| `reliability.py` | Observed headways, scheduled headways, hourly merge |

### Known DuckDB constraint

`load_route_positions` **cannot** wrap parquet in an extra subquery before `QUALIFY` — causes INTERNAL error on `bbox` struct. Use direct `FROM read_parquet(...) WHERE route_id = … QUALIFY …`.

---

## 4. Caching strategy

See **`docs/OPTIMIZATION.md`** for full benchmark tables. Summary:

| Layer | Mechanism | Scope / TTL |
|-------|-----------|-------------|
| DuckDB **external file cache** | S3 Parquet byte ranges in RAM | **Per connection** — lost on `close()` |
| DuckDB **parquet_metadata_cache** | Footer/schema reuse | Per connection |
| Streamlit **`@st.cache_resource`** | Shared DuckDB connection | Per Streamlit server process |
| Streamlit **`@st.cache_data`** | Loader DataFrames (`reliability`, `gtfs_loader`) | Cleared on date/agency/source change |
| **Local parquet fallback** | Full daily file on disk | Opt-in; ~90 MB/day |
| GTFS `stop_times` | First DuckDB scan ~60 s | Then `@st.cache_data` |

**Benchmark (Route 29, May 12, DuckDB 1.5.2):** S3 cold ~22 s → warm **~1.6 s** (same connection, ~14×); new connection → cold again (~23 s). Local ~0.8 s.

**Demo:** local cache for reliability; or S3 with **one Streamlit session** (warm connection).  
**Report:** document all layers; note no persistent DuckDB disk cache without extensions.

---

## 5. GTFS ↔ GTFS-RT mapping logic

1. Filter parquet by `route_id`.
2. Inner join `trip_id` (varchar) → `trips.txt` for true `direction_id`.
3. Virtual-stop: closest GPS ping per trip within `REF_RADIUS_METERS` of route reference point.
4. Observed headway: `LAG(timestamp)` over `(direction_id, local_date, hour)`.
5. Scheduled headway: count first departures per direction/hour from `stop_times.txt` → `60 / count`.
6. Compare hourly **mean** observed vs scheduled → deviation metrics.

**Diagnostics:** match %, NULL `trip_id` %, matched/unmatched trip counts (`compute_data_quality`).

---

## 6. Metrics tiering

### Primary (report / demo focus)

| Metric | Definition |
|--------|------------|
| **Observed headway** | Minutes between consecutive pass events (same direction, hour, local date) |
| **Scheduled headway** | `60 ÷ trips per direction per hour` from GTFS |
| **Absolute deviation** | `|mean_observed − scheduled|` (minutes or seconds) |
| **Relative deviation** | `absolute ÷ scheduled` |

### Exploratory / demo-only (secondary)

| Metric | Status | Notes |
|--------|--------|-------|
| Exploratory adherence score | Derived | `max(0, 100×(1 − min(relative_dev, 1)))` — visualization proxy only |
| Adherence band (Good/Moderate/Poor) | Derived | Thresholds 0.25 / 0.50 on relative deviation |
| CoV (coefficient of variation) | Exploratory | Hourly std/mean of capped headways |
| Potential bunching flags | Exploratory | Gap < 3 min between pass events |
| Potential service gap flags | Exploratory | Gap > 15 min |
| Rule-based “insights” | Exploratory | Deterministic bullets, not ML |
| Speed / percentile bands | Context only | GPS quality / activity, not schedule adherence |
| Network heatmaps | Summary view | Aggregates primary metrics across routes |

---

## 7. Performance timings (validated 2026-05-26, Route 29 + network, May 12)

### Local cache (~24 s full validation suite)

| Query | ~seconds |
|-------|----------|
| `observed_headways` (per route) | 0.8–1.5 |
| `route_positions` | 0.45 |
| `load_network_headway_metrics` (4 routes) | ~4–6 total |

### S3 direct (~276 s same suite, cold)

| Query | ~seconds |
|-------|----------|
| `observed_headways` (per route) | 30–47 |
| `route_positions` | ~14 |
| `route_summary` | ~5.5 |
| Full network reliability (4 routes) | ~3–5+ min first load |

### Consistency (local vs S3, May 12, Route 29)

- Observed headways: **245** both  
- Hourly rows: **40** both  
- Mean headway: **8.4 min** both  
- GTFS match: **~96.7%** both  

---

## 8. Bottlenecks

1. **S3 cold reads** — especially repeated per-route headway on Reliability page (4× `observed_headways` + `stop_times`).
2. **`stop_times.txt` scan** — first hourly reliability compute per session.
3. **Sequential route loop** in `load_network_headway_metrics`.
4. **No persistent DuckDB catalog** for GTFS tables (re-read CSV each cold start).
5. **Sidebar snapshot info** — extra queries on each page load.

---

## 9. Bugs / fixes log

| Date | Issue | Fix |
|------|-------|-----|
| 2026-05 | DuckDB INTERNAL on bbox + subquery + QUALIFY | `load_route_positions` uses direct `read_parquet` |
| 2026-05 | March parquet + May GTFS → 23% match | Date selector + aligned May 12 data |
| 2026-05 | Heatmap numeric route axis | Categorical route labels |
| 2026-05 | min/max adherence always ~0% | Replaced with deviation-based score |
| 2026-05 | Full parquet download on every load | S3-direct default; local opt-in |
| 2026-05 | 900 m pass radius | 670 m with documented constraint |

---

## 10. Logic that can be simplified or hidden (no code change required yet)

| Component | Recommendation |
|-----------|----------------|
| `build_route_insights()` / `build_network_insights()` | Collapse by default; label “exploratory” |
| CoV + bunching/gap charts | Move under “Exploratory indicators” expander |
| Adherence score heatmap default | Prefer **relative deviation** or abs deviation as default |
| `04_Route_504_King.py` | De-emphasize or hide from nav for bus-focused submission |
| `06_Comparison.py` | Drop CoV/bunching bar section or collapse |
| `02_Schedule.py` + `utils/db.py` sample path | Mark legacy; not part of S3 story |
| `app.py` DuckDB `headway_metrics` SQL | Legacy/sample; remove from overview KPIs if confusing |
| OC Transpo placeholders | Keep one line “future work” only |
| Confidence “success” banner | Soften; avoid implying statistical validation |

---

## 11. Strongest pages for final challenge demo

**Recommended 5-minute flow**

1. **Overview** — S3 direct, snapshot day, query timing in sidebar  
2. **05 Route Analysis → Route 29** — Diagnostics → observed vs scheduled chart → absolute/relative deviation in table  
3. **03 Reliability** — Network heatmap on relative deviation (single day, hour filter)  
4. **Methodology + limitations** expanders — transparency  

**Optional 30 s:** **01 Realtime** map to show GPS input quality.

**Avoid in short demo:** 504 page (duplicate), Comparison page (busy), Schedule page (off-narrative), first-load S3 cold wait without cache.

---

## 12. Remove / hide / de-emphasize before submission

| Item | Action |
|------|--------|
| Auto-download parquet | ✅ Already removed; keep local cache checkbox |
| Duplicate 504 vs 05 reliability | Hide 504 from sidebar or add “legacy benchmark” |
| Comparison page bunching/CoV bars | Collapse or remove |
| “Service reliability” / “accuracy” wording | Already softened; audit remaining strings |
| Sample data fallback (`sample_data.py`) | Ensure not triggered when parquet available |
| `replit.md` | Replace with root `README.md` aligned to frozen arch |
| Notebook stop-deviation maps | Cite as future direction, not current app |

---

## 13. Report-worthy technical contributions

1. **Partition-aware DuckDB pipeline** — `httpfs` + `hive_partitioning` on public GTFS-RT ETL bucket.  
2. **Pushdown filtering** — route, date, column pruning on parquet.  
3. **GTFS trip join** for direction recovery and match-rate diagnostics.  
4. **Virtual-stop headway** with explicit radius and limitation documentation.  
5. **Deviation-based schedule comparison** (abs + relative) instead of misleading ratio adherence.  
6. **Reproducible single-day experiment** with transparent data-quality panel.  
7. **Performance characterization** — local vs S3 latency tradeoff (scalability vs demo speed).  

---

## 14. Future work (post-submission, optional)

- [ ] Register GTFS tables once per DuckDB session (`CREATE TABLE trips AS …`)  
- [ ] Materialized local cache on first S3 query (background download)  
- [ ] Parallel route queries or single SQL for network metrics  
- [ ] Align reference points to median GPS path (enable smaller radius)  
- [ ] Borrow notebook’s `ST_DWithin` stop-level deviation as Phase 2 page  
- [ ] Thread pool / `SET threads` tuning for DuckDB  
- [ ] Root README + data sources + Streamlit Cloud deploy with secrets-free public bucket  

---

## 15. Changelog (append-only)

### 2026-05-26

- Frozen architecture around `positions_store.py` S3-direct querying.  
- Validated local vs S3 metric parity for May 12 / Route 29.  
- Documented primary vs exploratory metric tiers.  
- Identified Reliability page S3 cold load as main performance risk for demos.  

### 2026-05-24 — Caching audit (DuckDB 1.5.2)

- Inspected: `enable_external_file_cache` (real S3 block cache), `parquet_metadata_cache`, legacy `enable_object_cache` (no-op).  
- **Fix:** `@st.cache_resource` shared connection; stop closing after each `execute_query`.  
- Added `memory_limit`, `threads`, `temp_directory` under `dashboard/.duckdb/tmp`.  
- Benchmark scripts: `scripts/inspect_duckdb_cache.py`, `scripts/benchmark_cache_layers.py`.  

### 2026-05-27 — Multi-agency minimum structure check

- Verified reusable agency scaffolding is centralized in `utils/agency_config.py` + `utils/agency_loader.py`.  
- Confirmed required dimensions are present: agency config, S3 pattern, GTFS path, timezone, status.  
- Added explicit README onboarding steps for new agencies (start `pending`, promote to `active` only after GTFS↔GTFS-RT validation).  
- Kept TTC as active baseline and OC Transpo as pending/future.

### 2026-05-24 — Submission phase

- **UI:** Removed Schedule/504/Comparison pages from `dashboard/pages` so they do not appear in Streamlit navigation.  
- **Metrics frozen:** `PRIMARY_METRICS` tuple in `reliability.py`; Route Analysis shows 4 primary KPIs; CoV/bunching in expanders.  
- **Multi-agency:** `agency_config.py` + `agency_loader.py`; S3 glob `s3://…/{agency_id}/positions/…`; `gtfs_loader` agency-aware.  
- **Stability:** `page_guard.require_active_agency()` + `run_data_load()` on main pages.  
- **Docs:** root `README.md`, `docs/ARCHITECTURE.md`, `DATA_FLOW.md`, `OPTIMIZATION.md`.  
- **Tests:** `tests/test_agency_loader.py`, `tests/test_metrics.py`.  

### 2026-05-28 — Multi-agency data audit (read-only)

- Added `scripts/agency_data_audit.py` — inspects local GTFS, probes S3 parquet via DuckDB (`httpfs`, no download), classifies readiness.  
- Outputs: `docs/AGENCY_DATA_AUDIT.md`, `docs/agency_data_audit.json`.  
- **Do not activate** new agencies in UI until audit shows `ready for full lightweight analysis`.  
- Local GTFS paths: `dashboard/data/gtfs/` (ttc), `dashboard/data/{agency}/` or `{agency}/gtfs/` for others.  
- S3 pattern: `s3://gtfs-rt-etl-data/{agency}/positions/year=YYYY/month=MM/day=DD/*.parquet`.  
- Legacy cleanup candidates documented in audit (do not delete): `positions_0.parquet`, `positions_0_march28_backup.parquet`, `positions_cache/`, `sample/`.

### 2026-05-28 — STM deactivated (trip_id mismatch)

- Investigation: `docs/STM_TRIP_MATCH_INVESTIGATION.md`, `scripts/investigate_stm_trip_match.py`.  
- **Calendar overlaps May 15–31** (38 services, 56k May trips in static).  
- **May 20 parquet vs local `trips.txt`:** 0% trip_id match (16,601 RT ids, zero hits).  
- **March 17 parquet vs same file:** 99.79% match — join logic OK; **static feed version does not match May RT trip namespace**.  
- `feed_version`: `20260505090000_26M`; RT sample ids (`294563043`, …) absent from static.  
- **Action:** `stm` → `pending`; do not use STM reliability metrics in shared May cohort.

### 2026-05-28 — Shared May cohort activated in app

- **Active agencies:** TTC (default), TransLink, Edmonton.  
- **Shared analysis window:** 2026-05-15 → 2026-05-31 (`agency_config.SHARED_ANALYSIS_*`).  
- **Pending:** STM (trip_id mismatch), OC Transpo (GTFS from May 22), Calgary (route_id ETL issue).  
- Sidebar date picker clamped to shared window; agency selector shows active agencies only.  
- TTC retains Route 29 deep-dive; TransLink/Edmonton use fleet overview + network indicators.  
- Validation: `scripts/validate_active_agencies.py` → `docs/active_agency_validation.json`.

### 2026-05-28 — Full multi-agency audit (local GTFS synced)

- Re-ran audit with all six GTFS folders under `dashboard/data/`.  
- Probe dates: midpoint of GTFS window capped at **today** (avoids probing future days with no S3 partition).  
- **All six agencies:** `ready for full lightweight analysis` on probe day inside GTFS window.  
- **Safest non-TTC activation:** **octranspo** (98.9% trip match, 190 RT routes, ~1.0M rows, May 2026 probe; similar trip_id fill to TTC).  
- **Do not activate Calgary next:** S3 shows 1 distinct `route_id` vs 264 static routes (ETL/schema issue).  
- **translink / edmonton / stm** also strong on trip match; stm probe used March 2026 (older but valid).  
- See `docs/AGENCY_DATA_AUDIT.md` for static inventory (routes/trips/stops/timezone/route types).

---

## 16. Agency data audit workflow

**Current app policy:** four active agencies share **May 15–31, 2026**. Run `python scripts/validate_active_agencies.py` after config changes.

Before adding another agency:

1. Place extracted GTFS under `dashboard/data/{agency}/`.  
2. Run `python scripts/agency_data_audit.py`.  
3. Confirm trip match and S3 availability on a day inside the shared window.  
4. Set `status: "active"` in `agency_config.py` only if the agency fits the cohort date range.

| Classification | Meaning |
|----------------|---------|
| ready for full lightweight analysis | Static + RT aligned; safe to wire in app |
| static-only ready | GTFS OK; S3 missing or empty on probe date |
| blocked by missing realtime data | GTFS OK; S3 partition missing or empty |
| blocked by low trip_id match | trip_id match &lt; 50% or low non-null trip_id fill |
| blocked by bad GTFS/parquet date alignment | Missing GTFS, probe outside calendar, or feed_info mismatch |

### 2026-05-28 — TransLink Realtime derived speed

- **Issue:** TransLink parquet `speed` and `bearing` are always 0; bbox coordinates are valid. Realtime page showed Avg Speed = 0 km/h.
- **Fix:** `utils/speed_utils.py` → `compute_derived_speed_kmh` (haversine between consecutive GPS pings per vehicle).
- **Filters:** elapsed 5–600 s, distance > 0, speed ≤ 120 km/h; invalid → NaN (not fake 0).
- **Scope:** Realtime page only (`load_realtime_positions`, `load_realtime_route_summary`). TTC/Edmonton use source speed unchanged.
- **Reliability / Route Analysis / Network Indicators:** not modified.
- Validation: `scripts/validate_translink_speed.py` → `docs/TRANSLINK_SPEED_VALIDATION.md`.

---

*Append new entries to §15 and update §1–§14 when making optimization or methodology changes.*
