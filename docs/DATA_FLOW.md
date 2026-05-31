# Data Flow

## 1. User selects context (sidebar)

- **Agency** → `st.session_state.current_agency_id` (default `ttc`)  
- **Snapshot day** → must fall within GTFS `calendar.txt` range  
- **Source** → `s3` (DuckDB httpfs) or `local` (downloaded daily parquet)

## 2. Positions scan (GTFS-RT)

```
positions_store.positions_uri()
  → s3://gtfs-rt-etl-data/ttc/positions/year=YYYY/month=MM/day=DD/*.parquet
  OR data/positions_cache/ttc_positions_YYYYMMDD.parquet

positions_store.read_parquet_expr()
  → read_parquet('…', hive_partitioning = true)

positions_store.positions_subquery(route_id, require_trip_id)
  → SELECT trip_id, route_id, … FROM read_parquet WHERE route_id = '29' …
```

Filters pushed in SQL:

- `route_id` on route-specific pages  
- `trip_id IS NOT NULL` for schedule-linked metrics  
- `DATE(timestamp AT TIME ZONE tz)` when using local cache  

## 3. GTFS static join

```
reliability.compute_observed_headways()
  parquet.trip_id → trips.txt (direction_id)
  bbox distance to route reference point → one pass event per trip
  LAG(timestamp) BY direction, local_date, hour → observed headway

reliability.compute_scheduled_headways()
  trips.txt + stop_times.txt → trips per direction per hour
  scheduled_headway_min = 60 / count
```

## 4. Hourly aggregation

```
compute_hourly_reliability()
  → mean/median observed headway per direction/hour
  → merge scheduled headway
  → compute_schedule_comparison() → abs/relative deviation (+ exploratory score)
```

## 5. UI rendering

- **Route Analysis:** primary KPIs + observed vs scheduled chart + detail table  
- **Network page:** heatmap on relative deviation across configured routes  
- **Realtime:** latest ping per vehicle (separate `real_data` queries)

## Mapping diagnostics

`compute_data_quality(route_id)` returns:

- `match_pct` — distinct parquet `trip_id` values found in `trips.txt`  
- `null_trip_pct` — share of GPS rows without `trip_id`  

Low match usually means **misaligned snapshot day vs GTFS feed**.
