import duckdb
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "../db/ttc.db")


def get_connection(read_only: bool = False) -> duckdb.DuckDBPyConnection:
    """Return a DuckDB connection to the TTC database."""
    return duckdb.connect(DB_PATH, read_only=read_only)


def init_db():
    """Initialize the database schema if tables do not exist."""
    con = get_connection()

    con.execute("""
        CREATE TABLE IF NOT EXISTS vehicle_positions (
            vehicle_id      VARCHAR,
            route_id        VARCHAR,
            trip_id         VARCHAR,
            latitude        DOUBLE,
            longitude       DOUBLE,
            bearing         DOUBLE,
            speed           DOUBLE,
            timestamp       TIMESTAMP,
            current_stop    VARCHAR,
            stop_sequence   INTEGER
        )
    """)

    con.execute("""
        CREATE TABLE IF NOT EXISTS stop_times (
            trip_id         VARCHAR,
            route_id        VARCHAR,
            stop_id         VARCHAR,
            stop_name       VARCHAR,
            arrival_time    VARCHAR,
            departure_time  VARCHAR,
            stop_sequence   INTEGER,
            shape_dist_traveled DOUBLE
        )
    """)

    con.execute("""
        CREATE TABLE IF NOT EXISTS routes (
            route_id        VARCHAR PRIMARY KEY,
            route_short_name VARCHAR,
            route_long_name VARCHAR,
            route_type      INTEGER,
            route_color     VARCHAR,
            route_text_color VARCHAR
        )
    """)

    con.execute("""
        CREATE TABLE IF NOT EXISTS trips (
            trip_id         VARCHAR PRIMARY KEY,
            route_id        VARCHAR,
            service_id      VARCHAR,
            trip_headsign   VARCHAR,
            direction_id    INTEGER,
            shape_id        VARCHAR
        )
    """)

    con.execute("""
        CREATE TABLE IF NOT EXISTS stops (
            stop_id         VARCHAR PRIMARY KEY,
            stop_name       VARCHAR,
            stop_lat        DOUBLE,
            stop_lon        DOUBLE
        )
    """)

    con.execute("""
        CREATE TABLE IF NOT EXISTS headway_metrics (
            route_id        VARCHAR,
            direction_id    INTEGER,
            hour            INTEGER,
            date            DATE,
            scheduled_headway_sec  DOUBLE,
            actual_headway_sec     DOUBLE,
            headway_deviation_sec  DOUBLE,
            on_time_pct     DOUBLE
        )
    """)

    con.close()
