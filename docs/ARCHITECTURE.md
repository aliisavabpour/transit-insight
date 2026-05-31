# Architecture Overview

## Goals

1. Query **partitioned GTFS-RT parquet on S3** with DuckDB (no full download by default).  
2. Join **GTFS static** schedules for direction recovery and scheduled headways.  
3. Expose **four primary deviation metrics** via a Streamlit research UI.  
4. Support **multiple agencies** through shared configuration (TTC active; others pending).

## Layout

```
transit-insight/
├── README.md
├── docs/                    # Report-oriented documentation
├── tests/                   # pytest (no Streamlit required)
└── dashboard/
    ├── app.py               # Overview
    ├── pages/
    │   ├── 01_Realtime.py
    │   ├── 03_Reliability.py    # Network heatmaps
    │   └── 05_Route_Analysis.py # Primary demo
    ├── components/
    │   ├── page_guard.py        # require_active_agency, run_data_load
    │   ├── nav.py
    │   └── reliability_ui.py    # Methodology, glossary, diagnostics
    └── utils/
        ├── agency_config.py     # Agency registry + S3 templates
        ├── agency_loader.py     # Session agency + path helpers
        ├── positions_store.py   # DuckDB httpfs, execute_query, timing log
        ├── parquet_date.py      # Snapshot day + S3/local sidebar
        ├── gtfs_loader.py       # GTFS CSV via DuckDB
        ├── reliability.py       # Headway + deviation pipeline
        ├── real_data.py         # Maps, speeds, summaries
        └── route_config.py      # Per-route reference points
```

## Frozen boundaries

- **Do not** add new analytics modes before submission.  
- **Do** optimize queries, document timings, and improve error messages.  
- **Multi-agency:** extend `agency_config.py` + data paths; reuse `positions_store` and `reliability` unchanged.

## Key modules

| Module | Responsibility |
|--------|----------------|
| `agency_config` | Declarative agency entries (S3 glob, GTFS dir, timezone, status) |
| `agency_loader` | Resolve paths for current agency from Streamlit session |
| `positions_store` | `read_parquet(..., hive_partitioning=true)`, column pruning, SQL filters |
| `reliability` | Virtual-stop pass events → LAG headways → schedule comparison |
| `page_guard` | Stop pages cleanly when data/GTFS missing |

## Reference

External notebook `schedule_deviation.ipynb` uses **stop-level spatial deviation**; this app uses **route-level virtual-stop headways** — same data stack, different analytic grain.
