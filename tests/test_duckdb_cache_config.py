from utils.positions_store import _configure_duckdb, get_duckdb_cache_settings
import duckdb


def test_configure_enables_metadata_and_external_cache():
    con = duckdb.connect()
    _configure_duckdb(con)
    settings = {
        name: value
        for name, value in con.execute(
            """
            SELECT name, value::VARCHAR
            FROM duckdb_settings()
            WHERE name IN ('parquet_metadata_cache', 'enable_external_file_cache')
            """
        ).fetchall()
    }
    con.close()
    assert settings["parquet_metadata_cache"] in ("true", "True", True)
    assert settings["enable_external_file_cache"] in ("true", "True", True)


def test_get_duckdb_cache_settings_keys():
    s = get_duckdb_cache_settings()
    assert "parquet_metadata_cache" in s
    assert "enable_external_file_cache" in s
    assert "threads" in s
