"""
Compile-check dashboard entrypoint and visible pages; smoke-test agency loaders.

Usage:
  python scripts/validate_pages_load.py --date 2026-05-20
"""
from __future__ import annotations

import argparse
import py_compile
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DASH = ROOT / "dashboard"
sys.path.insert(0, str(DASH))


def _install_fake_streamlit() -> None:
    class _FakeSessionState(dict):
        def __getattr__(self, k):
            try:
                return self[k]
            except KeyError:
                raise AttributeError(k)

        def __setattr__(self, k, v):
            self[k] = v

    class _FakeStreamlit:
        session_state = _FakeSessionState()

        def cache_resource(self, func):
            return func

        def cache_data(self, *a, **kw):
            def decorator(func):
                return func

            if len(a) == 1 and callable(a[0]) and not kw:
                return decorator(a[0])
            return decorator

        class _Page:
            def __init__(self, *a, **kw):
                pass

        def navigation(self, pages):
            class _Nav:
                def run(self):
                    pass

            return _Nav()

        def set_page_config(self, **kw):
            pass

    sys.modules["streamlit"] = _FakeStreamlit()


def compile_pages() -> list[str]:
    paths = [
        DASH / "app.py",
        DASH / "home_page.py",
        DASH / "pages" / "01_Realtime.py",
        DASH / "pages" / "03_Reliability.py",
    ]
    errors: list[str] = []
    for path in paths:
        try:
            py_compile.compile(str(path), doraise=True)
        except py_compile.PyCompileError as exc:
            errors.append(f"{path.name}: {exc.msg}")
    return errors


def smoke_agencies(probe: date) -> list[str]:
    _install_fake_streamlit()
    from utils.agency_config import DEFAULT_SNAPSHOT_DATE  # noqa: E402
    from utils.real_data import get_parquet_snapshot_info, parquet_available  # noqa: E402

    if probe != DEFAULT_SNAPSHOT_DATE:
        pass

    issues: list[str] = []
    for aid in ("ttc", "translink", "edmonton"):
        st = sys.modules["streamlit"]
        st.session_state.clear()
        st.session_state["current_agency_id"] = aid
        st.session_state[f"{aid}_data_source"] = "s3"
        st.session_state["snapshot_date"] = probe
        try:
            if not parquet_available():
                issues.append(f"{aid}: parquet not available")
                continue
            info = get_parquet_snapshot_info()
            if not info.get("available"):
                issues.append(f"{aid}: snapshot info unavailable")
        except Exception as exc:
            issues.append(f"{aid}: {type(exc).__name__}: {exc}")
    return issues


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default="2026-05-20")
    args = parser.parse_args()
    probe = date.fromisoformat(args.date)

    compile_errors = compile_pages()
    agency_issues = smoke_agencies(probe)

    print("Compile:", "OK" if not compile_errors else compile_errors)
    print("Agencies:", "OK" if not agency_issues else agency_issues)
    return 1 if compile_errors or agency_issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
