# Transit Insight

Research prototype for **scalable GTFS-RT analytics** over partitioned S3 parquet, with lightweight **schedule deviation** indicators and a Streamlit demo UI.

Although the architecture was validated against multiple agencies, the **submitted prototype focuses on TTC** for a stable, deeper demonstration of optimized partitioned-parquet querying and lightweight reliability analysis. **TransLink and Edmonton** are active for **cross-agency comparison** over a shared May 2026 window (STM deactivated — see `docs/STM_TRIP_MATCH_INVESTIGATION.md`).

## Quick start

```bash
cd dashboard
pip install -e ..   # or: pip install duckdb pandas plotly streamlit
streamlit run app.py --server.port 5000
```

1. Open **Home** for architecture and fleet summary.  
2. Use **Reliability** for headway deviation heatmaps (TTC, TransLink, Edmonton).  
3. **Realtime** for the fleet GPS map.  
4. Sidebar: pick agency, snapshot day (**shared May 15–31, 2026**), **S3 direct** or **local cache**.

See [docs/GITHUB_AND_DEPLOY.md](docs/GITHUB_AND_DEPLOY.md) for public repo and Streamlit Cloud setup.

## Active agencies (shared May window)

| Agency | Status | GTFS path |
|--------|--------|-----------|
| TTC | active (default) | `dashboard/data/gtfs/` |
| TransLink | active | `dashboard/data/translink/` |
| Edmonton | active | `dashboard/data/edmonton/` |
| STM | pending | 0% May trip_id match vs static GTFS (version mismatch) |
| OC Transpo | pending | GTFS starts May 22 — outside shared May 15–31 cohort |
| Calgary | pending | S3 `route_id` cardinality issue — do not activate |

**Shared analysis window:** May 15–31, 2026 (same calendar dates for all active agencies).

Validate active agencies:

```bash
python scripts/validate_active_agencies.py
python scripts/agency_data_audit.py
```

## Querying defaults (report-ready)

- **Default source is S3 direct** (`get_data_source() -> "s3"` unless local cache is selected).
- DuckDB uses **`httpfs`** for `s3://` parquet access.
- `read_parquet(..., hive_partitioning = true)` enables partition-aware scans.
- **Partition pruning:** `year=YYYY/month=MM/day=DD/*.parquet`.
- DuckDB connection is **reused** with `@st.cache_resource` for warm S3 cache within a session.

## Primary metrics (frozen)

| Metric | Definition |
|--------|------------|
| Observed headway | Minutes between GPS pass events at a route reference point |
| Scheduled headway | `60 ÷ GTFS trips per direction per hour` |
| Absolute deviation | `\|observed − scheduled\|` |
| Relative deviation | Absolute ÷ scheduled |

CoV, bunching/gap flags, and adherence scores are **exploratory only**.

## Documentation

| Doc | Purpose |
|-----|---------|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Module layout |
| [docs/AGENCY_DATA_AUDIT.md](docs/AGENCY_DATA_AUDIT.md) | GTFS + S3 audit results |
| [docs/DATA_FLOW.md](docs/DATA_FLOW.md) | End-to-end query path |
| [docs/OPTIMIZATION.md](docs/OPTIMIZATION.md) | S3 vs local, tuning |
| [docs/research_notes.md](docs/research_notes.md) | Living report notebook |

## Data

- **GTFS-RT:** `s3://gtfs-rt-etl-data/{agency}/positions/year=…/month=…/day=…/*.parquet`  
- **GTFS static:** per-agency folders under `dashboard/data/`  
- **Local cache (optional):** `{agency}/positions_cache/` or `positions_cache/` for TTC  

## Tests

```bash
pip install pytest
pytest tests/ -q
```

## Pages

Overview, Realtime, and Reliability (Home + network indicators). Route-level deep-dive code is in `dashboard/archived/` (not in the sidebar).
