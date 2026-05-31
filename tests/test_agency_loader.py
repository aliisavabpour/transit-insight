from datetime import date

from utils.agency_config import (
    AGENCIES,
    ACTIVE_AGENCY_IDS,
    DEFAULT_SNAPSHOT_DATE,
    SHARED_ANALYSIS_END,
    SHARED_ANALYSIS_START,
    validate_agency_config,
)
from utils.agency_loader import (
    cache_path_for_date,
    gtfs_file_path,
    list_selectable_agencies,
    s3_glob_for_date,
    s3_https_url_for_date,
)
from utils.parquet_date import get_shared_analysis_bounds, is_date_in_shared_window


def test_agency_config_valid():
    assert validate_agency_config() == []


def test_active_agency_set():
    assert set(ACTIVE_AGENCY_IDS) == {"ttc", "translink", "edmonton"}
    assert AGENCIES["octranspo"]["status"] == "pending"
    assert AGENCIES["calgary"]["status"] == "pending"
    assert AGENCIES["stm"]["status"] == "pending"


def test_selectable_agencies_active_only():
    assert set(list_selectable_agencies()) == set(ACTIVE_AGENCY_IDS)


def test_ttc_s3_glob_format():
    d = date(2026, 5, 20)
    glob = s3_glob_for_date(d, "ttc")
    assert glob.startswith("s3://gtfs-rt-etl-data/ttc/positions/")
    assert "year=2026" in glob
    assert "month=05" in glob
    assert "day=20" in glob


def test_translink_s3_glob():
    glob = s3_glob_for_date(date(2026, 5, 20), "translink")
    assert "/translink/positions/" in glob


def test_ttc_https_url():
    url = s3_https_url_for_date(date(2026, 5, 20), "ttc")
    assert "amazonaws.com/ttc/positions/" in url


def test_cache_path_includes_agency_id():
    path = cache_path_for_date(date(2026, 5, 20), "stm")
    assert "stm_positions_20260520.parquet" in path.replace("\\", "/")


def test_shared_analysis_window():
    assert get_shared_analysis_bounds() == (SHARED_ANALYSIS_START, SHARED_ANALYSIS_END)
    assert is_date_in_shared_window(DEFAULT_SNAPSHOT_DATE)
    assert not is_date_in_shared_window(date(2026, 6, 1))


def test_gtfs_paths_exist_for_ttc():
    import os

    path = gtfs_file_path("trips.txt", "ttc")
    assert os.path.exists(path) or not os.path.isdir(os.path.dirname(path))
