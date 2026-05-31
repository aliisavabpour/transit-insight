"""
Generate synthetic TTC-like sample data for MVP development.
Run this once to populate the DuckDB database with demo data.
"""
import random
import numpy as np
import pandas as pd
from datetime import datetime, timedelta, date
from utils.db import get_connection, init_db

SAMPLE_ROUTES = [
    ("501", "Queen", 0, "E53935"),
    ("504", "King", 0, "E53935"),
    ("506", "Carlton", 0, "E53935"),
    ("510", "Spadina", 0, "E53935"),
    ("512", "St. Clair", 0, "E53935"),
    ("29", "Dufferin", 3, "1976D2"),
    ("36", "Finch West", 3, "1976D2"),
    ("60", "Steeles West", 3, "1976D2"),
    ("1", "Yonge-University", 1, "4CAF50"),
    ("2", "Bloor-Danforth", 1, "4CAF50"),
]

TORONTO_BBOX = {
    "lat_min": 43.62, "lat_max": 43.78,
    "lon_min": -79.55, "lon_max": -79.25,
}


def seed_routes():
    con = get_connection()
    con.execute("DELETE FROM routes")
    rows = [(rid, short, long, rtype, color, "FFFFFF")
            for rid, short, long, rtype, color in SAMPLE_ROUTES]
    con.executemany(
        "INSERT INTO routes VALUES (?, ?, ?, ?, ?, ?)", rows
    )
    con.close()


def seed_vehicle_positions(n_vehicles: int = 120):
    """Generate synthetic GPS pings for the last 24 hours."""
    con = get_connection()
    con.execute("DELETE FROM vehicle_positions")

    records = []
    now = datetime.utcnow()
    for i in range(n_vehicles):
        route = random.choice(SAMPLE_ROUTES)
        route_id = route[0]
        for h in range(24):
            ts = now - timedelta(hours=24 - h) + timedelta(minutes=random.randint(0, 59))
            records.append({
                "vehicle_id": f"V{i:04d}",
                "route_id": route_id,
                "trip_id": f"T{route_id}-{i}-{h}",
                "latitude": random.uniform(TORONTO_BBOX["lat_min"], TORONTO_BBOX["lat_max"]),
                "longitude": random.uniform(TORONTO_BBOX["lon_min"], TORONTO_BBOX["lon_max"]),
                "bearing": random.uniform(0, 360),
                "speed": random.uniform(0, 55),
                "timestamp": ts,
                "current_stop": f"STOP{random.randint(1, 200):04d}",
                "stop_sequence": random.randint(1, 30),
            })

    df = pd.DataFrame(records)
    con.register("vp_df", df)
    con.execute("INSERT INTO vehicle_positions SELECT * FROM vp_df")
    con.close()


def seed_headway_metrics(n_days: int = 7):
    """Synthetic on-time performance metrics per route/hour for the past week."""
    con = get_connection()
    con.execute("DELETE FROM headway_metrics")

    records = []
    today = date.today()
    for route_id, _, _, _, _ in SAMPLE_ROUTES:
        for day_offset in range(n_days):
            d = today - timedelta(days=day_offset)
            for hour in range(5, 24):
                scheduled = random.uniform(300, 900)  # 5-15 min headway
                noise = np.random.normal(0, 120)       # ±2 min noise
                actual = max(60, scheduled + noise)
                deviation = actual - scheduled
                on_time = max(0.0, min(1.0, 1.0 - abs(deviation) / scheduled))
                records.append({
                    "route_id": route_id,
                    "direction_id": random.choice([0, 1]),
                    "hour": hour,
                    "date": d,
                    "scheduled_headway_sec": round(scheduled, 1),
                    "actual_headway_sec": round(actual, 1),
                    "headway_deviation_sec": round(deviation, 1),
                    "on_time_pct": round(on_time * 100, 1),
                })

    df = pd.DataFrame(records)
    con.register("hw_df", df)
    con.execute("INSERT INTO headway_metrics SELECT * FROM hw_df")
    con.close()


def seed_stops(n: int = 300):
    con = get_connection()
    con.execute("DELETE FROM stops")
    rows = []
    for i in range(n):
        rows.append((
            f"STOP{i:04d}",
            f"Stop {i}",
            random.uniform(TORONTO_BBOX["lat_min"], TORONTO_BBOX["lat_max"]),
            random.uniform(TORONTO_BBOX["lon_min"], TORONTO_BBOX["lon_max"]),
        ))
    con.executemany("INSERT INTO stops VALUES (?, ?, ?, ?)", rows)
    con.close()


def run_all():
    init_db()
    seed_routes()
    seed_vehicle_positions()
    seed_headway_metrics()
    seed_stops()
    print("Sample data seeded successfully.")


if __name__ == "__main__":
    run_all()
