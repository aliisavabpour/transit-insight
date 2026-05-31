# GitHub and deployment checklist

## Secrets scan

The app uses a **public-read** S3 bucket (`gtfs-rt-etl-data`) with no AWS credentials in code.  
Do not commit `.env`, `.streamlit/secrets.toml`, or API keys.

## Git LFS (large files)

These paths are listed in `.gitattributes` and should use **Git LFS** if committed:

| Path | Approx. size |
|------|----------------|
| `dashboard/data/gtfs/stop_times.txt` | ~347 MB |
| `dashboard/data/positions_0.parquet` | ~86 MB (optional; ignored by default) |
| `attached_assets/*` | varies (folder ignored — do not commit) |

Agency `stop_times.txt` files (TransLink, Edmonton, etc.) total **~1 GB**; required for scheduled headway in Reliability. Prefer LFS or a documented GTFS download step for clones without LFS.

## Recommended: commit

| Area | Notes |
|------|--------|
| `dashboard/app.py`, `home_page.py`, `pages/`, `components/`, `utils/`, `archived/` | Streamlit app |
| `dashboard/.streamlit/config.toml` | Theme / server |
| `dashboard/data/gtfs/`, `translink/`, `edmonton/` | GTFS static for active agencies (`*.txt`; large `stop_times.txt` via LFS) |
| `docs/` | Architecture, audits, validation reports |
| `scripts/` | Validation and audit scripts |
| `tests/` | Pytest suite |
| `pyproject.toml`, `uv.lock` | Python deps |
| `README.md`, `.gitignore`, `.gitattributes`, `.env.example` | Repo metadata |

## Recommended: do not commit (`.gitignore`)

| Pattern | Reason |
|---------|--------|
| `.cursor/`, `.claude/`, `agent-transcripts/` | Editor / AI local state |
| `.replit`, `replit.nix`, `.upm/`, `.cache/`, `.local/` | Replit environment |
| `attached_assets/` | Replit uploads; duplicate data + pasted prompts |
| `dashboard/data/positions_cache/` | Downloaded parquet cache |
| `dashboard/.duckdb/` | DuckDB temp spills |
| `dashboard/data/positions_0.parquet` | Use S3 direct; optional local seed only |
| `dashboard/db/*.db` | Local dev SQLite |
| `__pycache__/`, `.pytest_cache/`, `.venv/`, `.env` | Python local |

## Optional: remove from Git history (manual)

If slimming the public repo, consider `git rm --cached` (not delete locally) for:

- `attached_assets/` — not referenced by the app
- `artifacts/`, `lib/`, root `package.json` / `pnpm-lock.yaml` — Replit/NX scaffold; Streamlit does not import them
- `dashboard/data/positions_0.parquet` — redundant with S3

## Streamlit Cloud

- **Main file:** `dashboard/app.py` (repo root as working directory)
- **Python:** 3.11+
- **Do not** set a custom run command with `--server.port 5000` (Replit legacy)
- **Port:** `.streamlit/config.toml` sets `server.port = 8501` (required for health check)
- **Secrets:** none required for public S3 GTFS-RT
- Ensure GTFS folders for TTC, TransLink, and Edmonton are present (or add a deploy step to fetch static GTFS)

If deploy logs show `Uvicorn server started on 0.0.0.0:5000` while health checks hit `:8501`, the app is still using an old config or a custom Cloud run command — push latest `.streamlit/config.toml` and clear any custom start command in App settings.

## Verify before push

```bash
pytest tests/ -q
python scripts/validate_pages_load.py --date 2026-05-20
python scripts/validate_active_agencies.py
```
