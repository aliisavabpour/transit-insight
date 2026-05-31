# Corridor Reference Point Validation

**Probe date:** 2026-05-20 · Compares GPS centroid vs GTFS shape corridor refs

Usable route = **≥3 pass events** (minimum for hourly headway samples).

## Agency summary

| Agency | Routes tested | Pass events before | Pass events after | Usable before | Usable after | Newly unblocked |
|--------|--------------:|-------------------:|------------------:|--------------:|-------------:|----------------:|
| TRANSLINK | 12 | 1122 | 2831 | 50.0% | 100.0% | 6 |
| EDMONTON | 12 | 570 | 1843 | 33.3% | 100.0% | 8 |

## TRANSLINK — per route

**Newly unblocked:** 6641, 37810, 6622, 23384, 6705, 6712

| Route | Old min dist (m) | New min dist (m) | Pass before | Pass after | Δ | Headways | Unblocked |
|-------|-----------------:|-----------------:|------------:|-----------:|--:|---------:|-----------|
| 6641 | 2003.5 | 4.5 | 0 | 438 | +438 | 357 | yes |
| 6636 | 248.7 | 4.2 | 305 | 304 | -1 | 242 | was ok |
| 37810 | 1698.3 | 6.8 | 0 | 377 | +377 | 315 | yes |
| 6622 | 2495.6 | 3.4 | 0 | 185 | +185 | 136 | yes |
| 23384 | 764.9 | 4.6 | 0 | 193 | +193 | 150 | yes |
| 6705 | 1287.8 | 2.6 | 0 | 219 | +219 | 169 | yes |
| 6627 | 402.0 | 8.2 | 180 | 180 | +0 | 133 | was ok |
| 37807 | 126.3 | 6.4 | 204 | 211 | +7 | 164 | was ok |
| 6712 | 682.3 | 0.8 | 0 | 190 | +190 | 143 | yes |
| 6624 | 174.3 | 8.3 | 190 | 190 | +0 | 142 | was ok |
| 16718 | 33.5 | 0.5 | 164 | 157 | -7 | 104 | was ok |
| 6728 | 350.0 | 5.4 | 79 | 187 | +108 | 142 | was ok |

## EDMONTON — per route

**Newly unblocked:** 004, 008, 005, 056, 007, 055, 114, 053

| Route | Old min dist (m) | New min dist (m) | Pass before | Pass after | Δ | Headways | Unblocked |
|-------|-----------------:|-----------------:|------------:|-----------:|--:|---------:|-----------|
| 004 | 1178.6 | 0.4 | 0 | 191 | +191 | 146 | yes |
| 008 | 280.3 | 0.1 | 1 | 159 | +158 | 111 | yes |
| 009 | 569.3 | 0.8 | 240 | 238 | -2 | 188 | was ok |
| 005 | 218.6 | 0.5 | 1 | 233 | +232 | 189 | yes |
| 056 | 758.1 | 0.4 | 0 | 141 | +141 | 99 | yes |
| 002 | 459.8 | 0.2 | 153 | 170 | +17 | 123 | was ok |
| 007 | 1143.3 | 0.2 | 0 | 192 | +192 | 147 | yes |
| 055 | 810.0 | 0.2 | 0 | 108 | +108 | 70 | yes |
| 114 | 948.4 | 0.5 | 0 | 133 | +133 | 94 | yes |
| 701 | 115.4 | 0.7 | 88 | 105 | +17 | 68 | was ok |
| 052 | 339.9 | 0.2 | 87 | 86 | -1 | 48 | was ok |
| 053 | 739.1 | 0.5 | 0 | 87 | +87 | 51 | yes |

## Conclusions

- Corridor shape references place virtual stops **on the route polyline**, sharply reducing min GPS distance.
- Routes with **zero centroid pass events** often gain usable pass events with corridor refs.
- Reliability metrics (observed headways) become available on newly unblocked routes without formula changes.
- TTC configured intersection refs are unchanged.

Re-run: `python scripts/validate_corridor_refs.py`
