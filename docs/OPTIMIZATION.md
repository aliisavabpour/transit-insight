# Optimization & Caching

**DuckDB version (project):** 1.5.2  
**Benchmark query:** Route 29 observed headways, May 12, 2026 (`scripts/benchmark_cache_layers.py`)

---

## Caching layers (stack)

| Layer | What it caches | Scope | We use? |
|-------|----------------|-------|---------|
| **DuckDB `enable_external_file_cache`** | Remote Parquet **byte ranges** in RAM (Buffer Manager) | **Per DuckDB connection** | Yes (default + explicit `SET true`) |
| **DuckDB `parquet_metadata_cache`** | Parquet **footer / schema / row-group metadata** | Per connection | Yes (`SET true` in `_configure_duckdb`) |
| **DuckDB `enable_object_cache`** | — | — | **No** — legacy placeholder in 1.5.x, does nothing |
| **Persistent disk cache (httpfs)** | S3 blocks on SSD | Extensions (`cache_httpfs`, `diskcache`) | **No** — not installed |
| **Streamlit `@st.cache_data`** | Python **DataFrame / dict** results | Per Streamlit server, keyed by args | Yes (`reliability`, `gtfs_loader`, `real_data`) |
| **Streamlit `@st.cache_resource`** | **DuckDB connection** object | Per Streamlit server process | Yes (`_streamlit_duckdb_connection`) |
| **Local parquet fallback** | Full daily file on disk | `dashboard/data/positions_cache/` | Optional sidebar checkbox |

## Verification checklist (current implementation)

- **S3 direct is default:** yes (`get_data_source()` defaults to `"s3"`).
- **DuckDB `httpfs` enabled:** yes (`INSTALL/LOAD httpfs` in `_configure_duckdb`).
- **Partition pruning:** yes (S3 path is built as `.../year=.../month=.../day=.../*.parquet`).
- **Column pruning:** yes (`positions_subquery()` selects only `POSITION_COLUMNS`).
- **Route/date filters pushed in SQL:** yes (`route_id`, `trip_id IS NOT NULL`, and local-day filter in `positions_where_clause()`).
- **Connection reuse for warm cache:** yes (`@st.cache_resource` shared DuckDB connection).
- **Local cache fallback optional:** yes (sidebar checkbox; off by default).

### What each layer does

1. **`parquet_metadata_cache`** — Avoids re-fetching Parquet file footers and re-parsing schema when the same files are read again on the **same connection**. Does **not** cache all column data by itself.

2. **`enable_external_file_cache`** — Caches **remote file blocks** (S3 via httpfs) in memory so repeated scans can skip network I/O. This is the main reason a **warm** S3 repeat drops from ~22 s → ~1.5 s. Cache is **in-memory only**; it is **lost when the connection closes**. There is no built-in persistent S3 disk cache in stock DuckDB 1.5.2.

3. **`@st.cache_data`** — Skips re-running entire loader functions (e.g. `compute_observed_headways`, `load_network_headway_metrics`) when inputs unchanged. Cleared on date/agency/source change via `st.cache_data.clear()`.

4. **`@st.cache_resource` (DuckDB connection)** — Keeps one configured DuckDB session alive so layers (1) and (2) survive **across queries in the same Streamlit process**. **Critical fix:** previously every `execute_query()` opened and closed a connection, which **defeated** the external file cache.

5. **Local parquet fallback** — Downloads ~90 MB/day once; queries read local files (fast, offline). Still benefits from metadata cache on the shared connection, but network is no longer the bottleneck.

---

## Settings enabled in `positions_store._configure_duckdb`

```sql
INSTALL httpfs; LOAD httpfs;
SET parquet_metadata_cache = true;
SET enable_external_file_cache = true;   -- already default true; kept explicit
SET memory_limit = '4GB';                -- env: DUCKDB_MEMORY_LIMIT
SET threads = <min(8, cpu_count)>;       -- env: DUCKDB_THREADS
SET temp_directory = 'dashboard/.duckdb/tmp';
SET timezone = '<agency timezone>';
```

**Not set:** `PRAGMA enable_object_cache` (no-op in 1.5.2).

**Optional future:** `SET enable_http_metadata_cache = true` for HTTP directory listings; not enabled yet.

---

## Benchmark results (May 12, Route 29, 245 headways)

| Mode | Run 1 (cold) | Run 2 (warm, same connection) | New connection |
|------|--------------|----------------------------------|----------------|
| **S3 direct** | ~21.6 s | ~1.6 s (**~14× faster**) | ~23 s (cache lost) |
| **Local file** | ~0.8 s | ~0.9 s | ~0.7 s |

**Interpretation**

- Repeated S3 queries **do** improve dramatically when the **same DuckDB connection** is reused → DuckDB is caching **remote data blocks**, not metadata only.
- A **new connection** returns to cold S3 latency → external file cache is **not** process-global.
- Local cache is **~25× faster** than cold S3 and stable across connections (OS page cache + no httpfs).

---

## What we were missing (before fix)

| Issue | Impact |
|-------|--------|
| `con.close()` after every query | External file cache discarded every time |
| No `@st.cache_resource` for DuckDB | Every page load paid full S3 cold cost per query |
| `enable_object_cache` suggested in older blogs | Misleading — no effect in 1.5.2 |
| Only `parquet_metadata_cache` documented | Understated the value of `enable_external_file_cache` + connection reuse |

---

## Recommendations

### Live demo

- Enable **local cache** once, or stay on S3 but **avoid restarting Streamlit** between pages (shared connection warms).
- Navigate Route Analysis → Network on the **same running app** to benefit from warm S3.

### Report narrative

- **Scalability:** S3-direct + column pruning + hive partitions (no full download).
- **Caching:** DuckDB external file cache + metadata cache + Streamlit result cache + optional local snapshot.
- **Limitation:** Caches are **session-scoped** (RAM, not durable across restarts). For production, consider community extensions (`cache_httpfs`, `diskcache`) or materialized local partitions.

### Why local cache still matters

Even with warm S3 (~1.5 s/query), local cache gives:

- **~0.7 s** cold, no AWS dependency  
- Predictable demos without network variance  
- Offline fallback when S3 is unreachable  

### Why both caching approaches exist

- **DuckDB cache** optimizes repeated S3 access while preserving cloud-native querying (no mandatory download).
- **Local fallback cache** optimizes demo reliability and offline operation.
- Keeping both supports two goals at once: **scalable architecture story** (S3 direct) and **stable demo execution** (local fallback).

---

## Other optimizations (unchanged)

- Column pruning on positions scan (8 columns).  
- SQL filters: `route_id`, `trip_id IS NOT NULL`, local date when in cache mode.  
- `QUALIFY` must run on direct `read_parquet` (not nested bbox subquery).  
- Query timing log: `st.session_state.duckdb_query_log` (sidebar expander).

## Scripts

```bash
python scripts/inspect_duckdb_cache.py      # version + settings + pragma checks
python scripts/benchmark_cache_layers.py    # S3 cold/warm/local timing
```
