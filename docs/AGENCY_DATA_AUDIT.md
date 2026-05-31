# Agency Data Audit

Generated: 2026-05-28T20:54:39

Read-only audit of local GTFS static folders vs partitioned GTFS-RT on S3. **No agencies were activated in the app.**

S3 pattern:

```
s3://gtfs-rt-etl-data/{agency}/positions/year=YYYY/month=MM/day=DD/*.parquet
```

## Expected local GTFS paths

| Agency | Look under `dashboard/data/` |
|--------|------------------------------|
| ttc | `gtfs`, `ttc`, `ttc/gtfs` |
| octranspo | `octranspo`, `octranspo/gtfs` |
| calgary | `calgary`, `calgary/gtfs` |
| translink | `translink`, `translink/gtfs` |
| stm | `stm`, `stm/gtfs` |
| edmonton | `edmonton`, `edmonton/gtfs` |

## GTFS static inventory

| Agency | GTFS dir | Date range | Routes | Trips | Stops | Timezone | Route types (GTFS) |
|--------|----------|------------|--------|-------|-------|----------|-------------------|
| ttc | `dashboard/data/gtfs` | 2026-05-03 → 2026-06-06 | 231 | 134744 | 9406 | America/Toronto | Bus (209), Tram/Light rail (19), Subway/Metro (3) |
| octranspo | `dashboard/data/octranspo` | 2026-05-22 → 2026-06-22 | 189 | 67433 | 5893 | Canada/Eastern | Bus (186), Tram/Light rail (3) |
| calgary | `dashboard/data/calgary` | 2026-05-22 → 2026-06-21 | 264 | 28222 | 6168 | America/Edmonton | Bus (262), Tram/Light rail (2) |
| translink | `dashboard/data/translink` | 2026-04-20 → 2026-09-06 | 246 | 134661 | 8952 | America/Vancouver | Bus (240), Subway/Metro (3), type 715 (1), Rail (1), Ferry (1) |
| stm | `dashboard/data/stm` | 2026-01-05 → 2026-06-14 | 216 | 176161 | 8897 | America/Montreal | Bus (212), Subway/Metro (4) |
| edmonton | `dashboard/data/edmonton` | 2026-05-15 → 2026-06-20 | 236 | 50522 | 6835 | America/Edmonton | Bus (233), Tram/Light rail (3) |

## S3 realtime (probe day inside GTFS window)

| Agency | Probe | S3 | Rows | RT routes | trip_id % | trip match % | Classification |
|--------|-------|----|------|-----------|-----------|--------------|----------------|
| ttc | 2026-05-15 | yes | 4,367,529 | 221 | 69.43 | 96.7 | **ready for full lightweight analysis** |
| octranspo | 2026-05-25 | yes | 1,028,661 | 190 | 70.06 | 98.9 | **ready for full lightweight analysis** |
| calgary | 2026-05-25 | yes | 965,649 | 1 | 100.0 | 82.3 | **ready for full lightweight analysis** |
| translink | 2026-05-09 | yes | 1,569,192 | 193 | 100.0 | 100.0 | **ready for full lightweight analysis** |
| stm | 2026-03-17 | yes | 1,610,244 | 209 | 100.0 | 99.8 | **ready for full lightweight analysis** |
| edmonton | 2026-05-21 | yes | 931,265 | 230 | 100.0 | 99.9 | **ready for full lightweight analysis** |

## Per-agency detail

### ttc

- **GTFS path:** `dashboard/data/gtfs`
- **feed_info.txt:** 2026-05-03 → 2026-06-06
- **calendar.txt:** 2026-05-03 → 2026-06-06
- **Service window (for probing):** 2026-05-03 → 2026-06-06
- **Static counts:** 231 routes, 134,744 trips, 9,406 stops
- **Timezone:** America/Toronto
- **Route types:** Bus: 209, Tram/Light rail: 19, Subway/Metro: 3
- **Required GTFS files:** agency.txt:✓ routes.txt:✓ trips.txt:✓ stops.txt:✓ stop_times.txt:✓ calendar.txt:✓ calendar_dates.txt:✓ feed_info.txt:✓
- **S3 glob:** `s3://gtfs-rt-etl-data/ttc/positions/year=2026/month=05/day=15/*.parquet`
- **Timestamp range:** 2026-05-14 23:52:28-04 → 2026-05-15 23:59:29-04
- **Parquet columns:** trip_id, route_id, direction_id, vehicle_id, bearing, speed, timestamp, geohash, geometry, bbox, day, month, year
- **Classification:** `ready for full lightweight analysis`

### octranspo

- **GTFS path:** `dashboard/data/octranspo`
- **feed_info.txt:** 2026-05-22 → 2026-06-22
- **calendar.txt:** 2026-05-22 → 2026-06-22
- **Service window (for probing):** 2026-05-22 → 2026-06-22
- **Static counts:** 189 routes, 67,433 trips, 5,893 stops
- **Timezone:** Canada/Eastern
- **Route types:** Bus: 186, Tram/Light rail: 3
- **Required GTFS files:** agency.txt:✓ routes.txt:✓ trips.txt:✓ stops.txt:✓ stop_times.txt:✓ calendar.txt:✓ calendar_dates.txt:✓ feed_info.txt:✓
- **S3 glob:** `s3://gtfs-rt-etl-data/octranspo/positions/year=2026/month=05/day=25/*.parquet`
- **Timestamp range:** 2026-05-24 23:49:13-04 → 2026-05-25 23:58:43-04
- **Parquet columns:** trip_id, route_id, direction_id, vehicle_id, bearing, speed, timestamp, geohash, geometry, bbox, day, month, year
- **Classification:** `ready for full lightweight analysis`

### calgary

- **GTFS path:** `dashboard/data/calgary`
- **calendar.txt:** 2026-05-22 → 2026-06-21
- **Service window (for probing):** 2026-05-22 → 2026-06-21
- **Static counts:** 264 routes, 28,222 trips, 6,168 stops
- **Timezone:** America/Edmonton
- **Route types:** Bus: 262, Tram/Light rail: 2
- **Required GTFS files:** agency.txt:✓ routes.txt:✓ trips.txt:✓ stops.txt:✓ stop_times.txt:✓ calendar.txt:✓ calendar_dates.txt:✓ feed_info.txt:✗
- **S3 glob:** `s3://gtfs-rt-etl-data/calgary/positions/year=2026/month=05/day=25/*.parquet`
- **Timestamp range:** 2026-05-25 01:19:24-04 → 2026-05-26 01:58:48-04
- **Parquet columns:** trip_id, route_id, direction_id, vehicle_id, bearing, speed, timestamp, geohash, geometry, bbox, day, month, year
- **Classification:** `ready for full lightweight analysis`

### translink

- **GTFS path:** `dashboard/data/translink`
- **calendar.txt:** 2026-04-20 → 2026-09-06
- **Service window (for probing):** 2026-04-20 → 2026-09-06
- **Static counts:** 246 routes, 134,661 trips, 8,952 stops
- **Timezone:** America/Vancouver
- **Route types:** Bus: 240, Subway/Metro: 3, type 715: 1, Rail: 1, Ferry: 1
- **Required GTFS files:** agency.txt:✓ routes.txt:✓ trips.txt:✓ stops.txt:✓ stop_times.txt:✓ calendar.txt:✓ calendar_dates.txt:✓ feed_info.txt:✗
- **S3 glob:** `s3://gtfs-rt-etl-data/translink/positions/year=2026/month=05/day=09/*.parquet`
- **Timestamp range:** 2026-05-09 02:50:11-04 → 2026-05-10 02:59:28-04
- **Parquet columns:** trip_id, route_id, direction_id, vehicle_id, bearing, speed, timestamp, geohash, geometry, bbox, day, month, year
- **Classification:** `ready for full lightweight analysis`

### stm

- **GTFS path:** `dashboard/data/stm`
- **feed_info.txt:** 2026-01-05 → 2026-06-14
- **calendar.txt:** 2026-01-05 → 2026-06-14
- **Service window (for probing):** 2026-01-05 → 2026-06-14
- **Static counts:** 216 routes, 176,161 trips, 8,897 stops
- **Timezone:** America/Montreal
- **Route types:** Bus: 212, Subway/Metro: 4
- **Required GTFS files:** agency.txt:✓ routes.txt:✓ trips.txt:✓ stops.txt:✓ stop_times.txt:✓ calendar.txt:✓ calendar_dates.txt:✓ feed_info.txt:✓
- **S3 glob:** `s3://gtfs-rt-etl-data/stm/positions/year=2026/month=03/day=17/*.parquet`
- **Timestamp range:** 2026-03-16 23:50:59-04 → 2026-03-17 23:59:37-04
- **Parquet columns:** trip_id, route_id, direction_id, vehicle_id, bearing, speed, timestamp, geohash, geometry, bbox, day, month, year
- **Classification:** `ready for full lightweight analysis`

### edmonton

- **GTFS path:** `dashboard/data/edmonton`
- **feed_info.txt:** 2026-05-15 → 2026-06-20
- **Service window (for probing):** 2026-05-15 → 2026-06-20
- **Static counts:** 236 routes, 50,522 trips, 6,835 stops
- **Timezone:** America/Edmonton
- **Route types:** Bus: 233, Tram/Light rail: 3
- **Required GTFS files:** agency.txt:✓ routes.txt:✓ trips.txt:✓ stops.txt:✓ stop_times.txt:✓ calendar.txt:✗ calendar_dates.txt:✓ feed_info.txt:✓
- **S3 glob:** `s3://gtfs-rt-etl-data/edmonton/positions/year=2026/month=05/day=21/*.parquet`
- **Timestamp range:** 2026-05-21 01:59:23-04 → 2026-05-22 01:59:36-04
- **Parquet columns:** trip_id, route_id, direction_id, vehicle_id, bearing, speed, timestamp, geohash, geometry, bbox, day, month, year
- **Classification:** `ready for full lightweight analysis`

## App activation policy (2026-05-28)

**Active in UI:** TTC (default), TransLink, Edmonton — **shared May analysis window: May 15–31, 2026**.

**Inactive:** STM (0% May trip_id match — see `docs/STM_TRIP_MATCH_INVESTIGATION.md`), OC Transpo (GTFS from May 22), Calgary (S3 `route_id` issue).

**Validation on 2026-05-20** (`docs/active_agency_validation.json`):

| Agency | S3 | Rows | trip match % | Notes |
|--------|----|------|--------------|-------|
| TTC | yes | 4.3M | 96.8 | Primary deep demo (Route 29) |
| TransLink | yes | 2.0M | 100.0 | Network comparison |
| Edmonton | yes | 0.9M | 99.9 | Network comparison |
| STM | — | — | **deactivated** | 0% May trip match; March RT matched 99.8% with same GTFS — version mismatch |

**Avoid activating Calgary** until S3 `route_id` cardinality is fixed. **OC Transpo** only if switching to a May 22+ analysis window.

## Legacy / cleanup candidates (do not delete yet)

| Path | Present | Recommendation |
|------|---------|----------------|
| `positions_0.parquet` | yes (85.5 MB) | Legacy single-file TTC snapshot (~90 MB); superseded by S3 + positions_cache |
| `positions_0_march28_backup.parquet` | yes (71.0 MB) | Backup of March 28 snapshot; historical only |
| `positions_cache/` | yes (85.5 MB) | Optional local daily downloads; keep for demo fallback |
| `sample/` | yes | Sample/seed data for legacy DuckDB path; not used by S3-direct pipeline |
| `gtfs/` | yes (402.2 MB) | Active TTC static GTFS — not legacy (do not delete) |

## How to re-run

```bash
python scripts/agency_data_audit.py
python scripts/agency_data_audit.py --probe-date 2026-05-12
```
