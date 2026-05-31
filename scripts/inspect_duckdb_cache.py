"""Inspect DuckDB version and cache-related settings/pragmas."""
from pathlib import Path

import duckdb

print("duckdb.__version__:", duckdb.__version__)
con = duckdb.connect()

keywords = ("cache", "parquet", "memory", "temp", "thread", "object", "external", "file")
rows = con.execute(
    """
    SELECT name, value, description
    FROM duckdb_settings()
    WHERE lower(name) LIKE '%cache%'
       OR lower(name) LIKE '%parquet%'
       OR lower(name) LIKE '%memory%'
       OR lower(name) LIKE '%temp%'
       OR lower(name) LIKE '%thread%'
       OR lower(name) LIKE '%object%'
       OR lower(name) LIKE '%external%'
    ORDER BY name
    """
).fetchdf()
print("\n=== duckdb_settings (filtered) ===")
print(rows.to_string())

for pragma in ("enable_object_cache", "disable_object_cache"):
    try:
        con.execute(f"PRAGMA {pragma}")
        print(f"\nPRAGMA {pragma}: OK (note: enable_object_cache is legacy/no-op in 1.5.x)")
    except Exception as e:
        print(f"\nPRAGMA {pragma}: FAILED — {e}")

# After app-style configure
sys_path = str(Path(__file__).resolve().parents[1] / "dashboard")
import sys
if sys_path not in sys.path:
    sys.path.insert(0, sys_path)
from utils.positions_store import _configure_duckdb as app_configure
con3 = duckdb.connect()
app_configure(con3)
print("\n=== After app _configure_duckdb ===")
for name in (
    "parquet_metadata_cache",
    "enable_external_file_cache",
    "memory_limit",
    "temp_directory",
    "threads",
):
    print(name, "->", con3.execute(f"SELECT current_setting('{name}')").fetchone())
con3.close()

# Current defaults on fresh connection
con2 = duckdb.connect()
con2.execute("INSTALL httpfs; LOAD httpfs;")
for stmt in (
    "SELECT current_setting('parquet_metadata_cache')",
    "SELECT current_setting('memory_limit')",
    "SELECT current_setting('temp_directory')",
    "SELECT current_setting('threads')",
):
    try:
        print(stmt, "->", con2.execute(stmt).fetchone())
    except Exception as e:
        print(stmt, "-> ERROR", e)

con.close()
con2.close()
