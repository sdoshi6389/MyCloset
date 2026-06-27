"""
db_manager.py — CLI for progress and bug tracking databases.

Usage:
  python db_manager.py progress add   --date DATE --tasks TASKS
  python db_manager.py progress update --id ID [--date DATE] [--tasks TASKS]
  python db_manager.py progress delete --id ID
  python db_manager.py progress list

  python db_manager.py bugs add    --found DATE --desc DESCRIPTION
  python db_manager.py bugs fix    --id ID --date DATE
  python db_manager.py bugs update --id ID [--found DATE] [--desc DESCRIPTION] [--fixed DATE]
  python db_manager.py bugs delete --id ID
  python db_manager.py bugs list

Dates should be in YYYY-MM-DD format.
Tasks can be a semicolon-separated list: "Add login page; Fix navbar; Write tests"
"""

import argparse
import sqlite3
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
PROGRESS_DB = SCRIPT_DIR / "progress.db"
BUGS_DB = SCRIPT_DIR / "bugs.db"


def get_conn(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_dbs():
    with get_conn(PROGRESS_DB) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS progress (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                date      TEXT NOT NULL,
                tasks     TEXT NOT NULL
            )
        """)

    with get_conn(BUGS_DB) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS bugs (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                date_found  TEXT NOT NULL,
                description TEXT NOT NULL,
                date_fixed  TEXT
            )
        """)


# ── pretty-print helpers ──────────────────────────────────────────────────────

def _col_widths(headers: list[str], rows: list[sqlite3.Row]) -> list[int]:
    widths = [len(h) for h in headers]
    for row in rows:
        for i, val in enumerate(row):
            widths[i] = max(widths[i], len(str(val) if val is not None else ""))
    return widths


def print_table(headers: list[str], rows: list[sqlite3.Row]):
    if not rows:
        print("  (no records)")
        return
    widths = _col_widths(headers, rows)
    sep = "+-" + "-+-".join("-" * w for w in widths) + "-+"
    hdr = "| " + " | ".join(h.ljust(widths[i]) for i, h in enumerate(headers)) + " |"
    print(sep)
    print(hdr)
    print(sep)
    for row in rows:
        cells = [str(v) if v is not None else "" for v in row]
        print("| " + " | ".join(cells[i].ljust(widths[i]) for i in range(len(headers))) + " |")
    print(sep)
    print(f"  {len(rows)} row(s)")


# ── progress commands ─────────────────────────────────────────────────────────

def progress_add(args):
    with get_conn(PROGRESS_DB) as conn:
        cur = conn.execute(
            "INSERT INTO progress (date, tasks) VALUES (?, ?)",
            (args.date, args.tasks),
        )
        print(f"Added progress entry id={cur.lastrowid}  date={args.date}")


def progress_update(args):
    with get_conn(PROGRESS_DB) as conn:
        row = conn.execute("SELECT * FROM progress WHERE id=?", (args.id,)).fetchone()
        if row is None:
            sys.exit(f"Error: no progress entry with id={args.id}")
        new_date  = args.date  if args.date  else row["date"]
        new_tasks = args.tasks if args.tasks else row["tasks"]
        conn.execute(
            "UPDATE progress SET date=?, tasks=? WHERE id=?",
            (new_date, new_tasks, args.id),
        )
        print(f"Updated progress entry id={args.id}")


def progress_delete(args):
    with get_conn(PROGRESS_DB) as conn:
        conn.execute("DELETE FROM progress WHERE id=?", (args.id,))
        print(f"Deleted progress entry id={args.id}")


def progress_list(_args):
    with get_conn(PROGRESS_DB) as conn:
        rows = conn.execute("SELECT id, date, tasks FROM progress ORDER BY date").fetchall()
    print_table(["id", "date", "tasks"], rows)


# ── bugs commands ─────────────────────────────────────────────────────────────

def bugs_add(args):
    with get_conn(BUGS_DB) as conn:
        cur = conn.execute(
            "INSERT INTO bugs (date_found, description, date_fixed) VALUES (?, ?, NULL)",
            (args.found, args.desc),
        )
        print(f"Added bug entry id={cur.lastrowid}  found={args.found}")


def bugs_fix(args):
    with get_conn(BUGS_DB) as conn:
        row = conn.execute("SELECT * FROM bugs WHERE id=?", (args.id,)).fetchone()
        if row is None:
            sys.exit(f"Error: no bug entry with id={args.id}")
        conn.execute("UPDATE bugs SET date_fixed=? WHERE id=?", (args.date, args.id))
        print(f"Marked bug id={args.id} as fixed on {args.date}")


def bugs_update(args):
    with get_conn(BUGS_DB) as conn:
        row = conn.execute("SELECT * FROM bugs WHERE id=?", (args.id,)).fetchone()
        if row is None:
            sys.exit(f"Error: no bug entry with id={args.id}")
        new_found = args.found if args.found else row["date_found"]
        new_desc  = args.desc  if args.desc  else row["description"]
        new_fixed = args.fixed if args.fixed else row["date_fixed"]
        conn.execute(
            "UPDATE bugs SET date_found=?, description=?, date_fixed=? WHERE id=?",
            (new_found, new_desc, new_fixed, args.id),
        )
        print(f"Updated bug entry id={args.id}")


def bugs_delete(args):
    with get_conn(BUGS_DB) as conn:
        conn.execute("DELETE FROM bugs WHERE id=?", (args.id,))
        print(f"Deleted bug entry id={args.id}")


def bugs_list(_args):
    with get_conn(BUGS_DB) as conn:
        rows = conn.execute(
            "SELECT id, date_found, description, date_fixed FROM bugs ORDER BY date_found"
        ).fetchall()
    print_table(["id", "date_found", "description", "date_fixed"], rows)


# ── argument parser ───────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="db_manager",
        description="Manage progress and bug tracking databases.",
    )
    sub = parser.add_subparsers(dest="db", required=True)

    # ── progress ──
    p = sub.add_parser("progress", help="Progress tracking")
    ps = p.add_subparsers(dest="cmd", required=True)

    pa = ps.add_parser("add", help="Add a progress entry")
    pa.add_argument("--date",  required=True, help="Date (YYYY-MM-DD)")
    pa.add_argument("--tasks", required=True, help="Tasks completed (use ; as separator)")
    pa.set_defaults(func=progress_add)

    pu = ps.add_parser("update", help="Update a progress entry")
    pu.add_argument("--id",    type=int, required=True)
    pu.add_argument("--date",  default=None)
    pu.add_argument("--tasks", default=None)
    pu.set_defaults(func=progress_update)

    pd = ps.add_parser("delete", help="Delete a progress entry")
    pd.add_argument("--id", type=int, required=True)
    pd.set_defaults(func=progress_delete)

    pl = ps.add_parser("list", help="List all progress entries")
    pl.set_defaults(func=progress_list)

    # ── bugs ──
    b = sub.add_parser("bugs", help="Bug tracking")
    bs = b.add_subparsers(dest="cmd", required=True)

    ba = bs.add_parser("add", help="Add a bug entry")
    ba.add_argument("--found", required=True, help="Date bug was found (YYYY-MM-DD)")
    ba.add_argument("--desc",  required=True, help="Bug description")
    ba.set_defaults(func=bugs_add)

    bf = bs.add_parser("fix", help="Mark a bug as fixed")
    bf.add_argument("--id",   type=int, required=True)
    bf.add_argument("--date", required=True, help="Date bug was fixed (YYYY-MM-DD)")
    bf.set_defaults(func=bugs_fix)

    bu = bs.add_parser("update", help="Update a bug entry")
    bu.add_argument("--id",    type=int, required=True)
    bu.add_argument("--found", default=None)
    bu.add_argument("--desc",  default=None)
    bu.add_argument("--fixed", default=None)
    bu.set_defaults(func=bugs_update)

    bd = bs.add_parser("delete", help="Delete a bug entry")
    bd.add_argument("--id", type=int, required=True)
    bd.set_defaults(func=bugs_delete)

    bl = bs.add_parser("list", help="List all bug entries")
    bl.set_defaults(func=bugs_list)

    return parser


def main():
    init_dbs()
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
