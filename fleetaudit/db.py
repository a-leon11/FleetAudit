"""Load the CSV book into an in-memory DuckDB database and install the SQL layers."""
from __future__ import annotations

from pathlib import Path

import duckdb

from .config import POLICY, TIERS, Policy

ROOT = Path(__file__).resolve().parent.parent
SQL = ROOT / "sql"

# load order respects foreign keys
TABLES = ["dealers", "customers", "customer_limits", "approvers", "vehicle_catalog", "residual_table",
          "rate_sheet", "incentive_programs", "program_models", "contracts", "payments"]


def connect(data_dir: Path | str, policy: Policy = POLICY, path: str = ":memory:") -> duckdb.DuckDBPyConnection:
    data_dir = Path(data_dir)
    con = duckdb.connect(path)
    con.execute((SQL / "01_schema.sql").read_text(encoding="utf-8"))
    row = policy.row()
    cols = ", ".join(row)
    con.execute(f"INSERT INTO policy ({cols}) VALUES ({', '.join('?' for _ in row)})", list(row.values()))
    con.executemany("INSERT INTO tier_policy VALUES (?, ?, ?, ?)",
                    [(t, mn, rank, cap) for t, (mn, rank, cap) in TIERS.items()])
    for t in TABLES:
        f = data_dir / f"{t}.csv"
        if not f.exists():
            raise FileNotFoundError(f"{f} is missing. Run `python -m fleetaudit generate` first.")
        con.execute(f"INSERT INTO {t} BY NAME SELECT * FROM read_csv(?, header = true, auto_detect = true)",
                    [str(f)])
    for name in ("02_quality.sql", "03_rules.sql", "04_analysis.sql"):
        con.execute((SQL / name).read_text(encoding="utf-8"))
    return con


def data_quality(con) -> list[tuple[str, int]]:
    return con.execute("SELECT check_name, failures FROM v_dq ORDER BY check_name").fetchall()
