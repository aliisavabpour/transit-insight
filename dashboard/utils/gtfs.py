"""
Utility helpers for loading and parsing GTFS static feed files.
GTFS files (routes.txt, trips.txt, stop_times.txt, stops.txt) should be
placed in dashboard/data/gtfs/ before calling these loaders.
"""
import os
import pandas as pd
import duckdb
from utils.db import get_connection

GTFS_DIR = os.path.join(os.path.dirname(__file__), "../data/gtfs")


def _gtfs_path(filename: str) -> str:
    return os.path.join(GTFS_DIR, filename)


def load_routes_to_db():
    """Load routes.txt into the routes table."""
    path = _gtfs_path("routes.txt")
    if not os.path.exists(path):
        return False
    df = pd.read_csv(path, dtype=str)
    df.columns = [c.strip() for c in df.columns]
    con = get_connection()
    con.execute("DELETE FROM routes")
    con.register("routes_df", df)
    con.execute("""
        INSERT INTO routes
        SELECT
            route_id,
            route_short_name,
            route_long_name,
            CAST(route_type AS INTEGER),
            COALESCE(route_color, 'E53935'),
            COALESCE(route_text_color, 'FFFFFF')
        FROM routes_df
    """)
    con.close()
    return True


def load_stops_to_db():
    """Load stops.txt into the stops table."""
    path = _gtfs_path("stops.txt")
    if not os.path.exists(path):
        return False
    df = pd.read_csv(path, dtype=str)
    df.columns = [c.strip() for c in df.columns]
    con = get_connection()
    con.execute("DELETE FROM stops")
    con.register("stops_df", df)
    con.execute("""
        INSERT INTO stops
        SELECT stop_id, stop_name,
               CAST(stop_lat AS DOUBLE),
               CAST(stop_lon AS DOUBLE)
        FROM stops_df
    """)
    con.close()
    return True


def get_routes_df() -> pd.DataFrame:
    """Return all routes as a DataFrame."""
    con = get_connection()
    df = con.execute("SELECT * FROM routes ORDER BY route_short_name").df()
    con.close()
    return df


def get_stops_df() -> pd.DataFrame:
    """Return all stops as a DataFrame."""
    con = get_connection()
    df = con.execute("SELECT * FROM stops").df()
    con.close()
    return df
