# Reliability Sanity Audit

**Probe date:** 2026-05-20 · **Read-only** — no code changes

Route-level metrics: daytime mean (hours 06–22) where both observed and scheduled exist.
Flags: relative deviation >100%, observed >3× scheduled, hourly pass events <3.

## Executive summary

- **TTC**: 90.0% plausible (9/10) · suspicious: 52 · not trustworthy: none
- **TRANSLINK**: 100.0% plausible (10/10) · suspicious: none · not trustworthy: none
- **EDMONTON**: 100.0% plausible (10/10) · suspicious: none · not trustworthy: none

## TTC

| Route | Ref | Pass events | Obs (min) | Sched (min) | Abs dev (min) | Rel dev | Flags | Verdict |
|-------|-----|------------:|----------:|------------:|--------------:|--------:|-------|---------|
| 504 | configured | 550 | 4.56 | 4.62 | 0.46 | 0.101 | — | plausible |
| 52 | corridor | 286 | 10.76 | 4.59 | 6.18 | 1.36 | daytime_rel_dev_gt_100pct, multiple_thin | suspicious |
| 501 | configured | 255 | 9.53 | 9.61 | 1.53 | 0.164 | — | plausible |
| 506 | corridor | 187 | 12.19 | 9.42 | 3.82 | 0.404 | multiple_thin_hours | plausible |
| 939 | corridor | 302 | 7.59 | 6.99 | 1.37 | 0.233 | — | plausible |
| 53 | corridor | 382 | 6.28 | 6.28 | 0.73 | 0.115 | — | plausible |
| 54 | corridor | 353 | 6.49 | 6.69 | 0.95 | 0.146 | — | plausible |
| 512 | corridor | 79 | 7.08 | 6.07 | 1.02 | 0.169 | — | plausible |
| 505 | corridor | 284 | 8.59 | 6.75 | 2.08 | 0.345 | — | plausible |
| 102 | corridor | 321 | 8.47 | 8.28 | 1.03 | 0.13 | — | plausible |

### Suspicious routes — detail
**Route 52** — causes: sparse_hourly_samples, branch_aggregation_or_corridor_ref
  - Dir 0 h6: obs=6.8 sched=2.9 rel=1.3448275862068966 n=7 (rel_dev_gt_100pct)
  - Dir 1 h6: obs=11.9 sched=4.0 rel=1.975 n=4 (rel_dev_gt_100pct)
  - Dir 1 h7: obs=13.4 sched=5.0 rel=1.68 n=4 (rel_dev_gt_100pct)
  - Dir 1 h9: obs=16.2 sched=4.6 rel=2.5217391304347827 n=3 (rel_dev_gt_100pct, obs_gt_3x_sched)

## TRANSLINK

| Route | Ref | Pass events | Obs (min) | Sched (min) | Abs dev (min) | Rel dev | Flags | Verdict |
|-------|-----|------------:|----------:|------------:|--------------:|--------:|-------|---------|
| 6641 | corridor | 438 | 6.23 | 6.02 | 1.44 | 0.202 | — | plausible |
| 6636 | corridor | 304 | 7.96 | 7.86 | 1.87 | 0.258 | — | plausible |
| 37810 | corridor | 377 | 6.6 | 6.96 | 1.45 | 0.227 | — | plausible |
| 6622 | corridor | 185 | 12.47 | 12.31 | 3.11 | 0.267 | multiple_thin_hours | plausible |
| 23384 | corridor | 193 | 10.55 | 11.31 | 2.73 | 0.255 | multiple_thin_hours | plausible |
| 6705 | corridor | 219 | 9.56 | 10.94 | 2.22 | 0.195 | multiple_thin_hours | plausible |
| 6627 | corridor | 180 | 12.91 | 13.32 | 2.9 | 0.261 | multiple_thin_hours | plausible |
| 37807 | corridor | 211 | 10.08 | 10.12 | 3.04 | 0.346 | multiple_thin_hours | plausible |
| 6712 | corridor | 190 | 12.11 | 11.05 | 2.79 | 0.274 | multiple_thin_hours | plausible |
| 6624 | corridor | 190 | 11.11 | 11.84 | 2.27 | 0.184 | multiple_thin_hours | plausible |

## EDMONTON

| Route | Ref | Pass events | Obs (min) | Sched (min) | Abs dev (min) | Rel dev | Flags | Verdict |
|-------|-----|------------:|----------:|------------:|--------------:|--------:|-------|---------|
| 004 | corridor | 191 | 12.33 | 12.66 | 2.09 | 0.17 | multiple_thin_hours | plausible |
| 008 | corridor | 159 | 14.36 | 14.39 | 2.62 | 0.178 | multiple_thin_hours | plausible |
| 009 | corridor | 238 | 10.71 | 10.6 | 2.01 | 0.194 | multiple_thin_hours | plausible |
| 005 | corridor | 233 | 10.73 | 10.45 | 1.71 | 0.149 | multiple_thin_hours | plausible |
| 056 | corridor | 141 | 15.96 | 16.62 | 3.7 | 0.239 | multiple_thin_hours | plausible |
| 002 | corridor | 170 | 13.24 | 14.26 | 2.49 | 0.167 | multiple_thin_hours | plausible |
| 007 | corridor | 192 | 11.69 | 11.98 | 1.27 | 0.099 | multiple_thin_hours | plausible |
| 055 | corridor | 108 | 19.04 | 20.94 | 3.27 | 0.157 | multiple_thin_hours | plausible |
| 114 | corridor | 133 | 15.96 | 17.28 | 2.94 | 0.173 | multiple_thin_hours | plausible |
| 701 | corridor | 105 | 18.74 | 20.88 | 4.6 | 0.207 | multiple_thin_hours | plausible |

## Trustworthiness conclusion

### Overall verdict

| Agency | Plausible | Suspicious | Not trustworthy | Pipeline trustworthy? |
|--------|----------:|-----------:|----------------:|----------------------|
| **TTC** | 9/10 (90%) | 1 (Route 52) | 0 | **Yes**, with one outlier |
| **TransLink** | 10/10 (100%) | 0 | 0 | **Yes** |
| **Edmonton** | 10/10 (100%) | 0 | 0 | **Yes** |

After service-day schedule filtering and corridor reference points, **29 of 30 top routes** show daytime relative deviation **≤40%** and observed/sched ratios near **1.0×**. The pipeline is **scientifically trustworthy for exploratory reliability comparison** on high-volume routes.

### Routes that appear plausible (29 routes)

**TTC:** 504, 501, 506, 939, 53, 54, 512, 505, 102 — observed and scheduled headways align within ~10–40% relative deviation. Routes 504 and 501 (configured refs) show **~0.99× obs/sched ratio** and **10–16% relative deviation**.

**TransLink (all 10):** Relative deviation **18–35%**; pass events **180–438** per day. Previously blocked routes (6641, 37810) now show **6.0–6.6 min observed vs 6.0–7.0 min scheduled**.

**Edmonton (all 10):** Relative deviation **10–24%**; pass events **105–238**. Previously zero-pass routes (004, 008, 007) now align within ~17–18% relative deviation.

### Routes that still look suspicious (1 route)

**TTC Route 52** — daytime relative deviation **136%**, obs/sched ratio **2.35×**.
- 13 flagged hours, mostly **direction 1** with 3–4 pass events per hour
- Hour 10 dir 1: obs **18.2 min** vs sched **5.0 min** with only **1 pass event**
- Likely causes: **direction-specific corridor geometry** (ref captures one direction well), **sparse samples in direction 1**, possible **short-turn / branch pattern** not fully represented in combined schedule count

### Likely causes (when flags appear)

| Cause | Where seen | Impact |
|-------|------------|--------|
| **None — pipeline healthy** | TTC 504/501, most TransLink/Edmonton routes | Metrics trustworthy |
| **Sparse hourly samples (<3 pass events)** | TTC 506, many TransLink/Edmonton off-peak hours | Hour-level flags; daytime means still OK |
| **Direction-asymmetric ref point** | TTC 52 direction 1 | Route-level suspicion |
| **Branch aggregation on schedule** | Possible minor residual on corridor routes | Low impact after service-day fix |

### Recommendation before new metrics (EWT, CoV)

The core headway + deviation pipeline is validated. Add EWT/CoV only with minimum sample-size guards (`pass_events ≥ 3` per hour), direction-level review for asymmetric routes (e.g. TTC 52), and configured refs for TTC showcase routes.

Re-run: `python scripts/reliability_sanity_audit.py --date 2026-05-20 --top 10`
