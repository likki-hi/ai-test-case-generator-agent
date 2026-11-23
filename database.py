"""SQLite storage: one table for requirements, one for their test cases."""
import sqlite3
from contextlib import closing
from datetime import datetime

import pandas as pd

DB_PATH = "test_cases.db"


def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    with closing(_connect()) as conn, conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS requirements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            requirement TEXT NOT NULL,
            feature TEXT,
            assumptions TEXT,
            created_at TEXT NOT NULL)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS test_cases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            requirement_id INTEGER NOT NULL,
            tc_id TEXT, scenario TEXT, title TEXT, preconditions TEXT,
            steps TEXT, test_data TEXT, expected_result TEXT, priority TEXT,
            FOREIGN KEY (requirement_id) REFERENCES requirements(id) ON DELETE CASCADE)""")


def _insert_cases(conn, req_id: int, df: pd.DataFrame):
    rows = [(req_id, r["ID"], r["Scenario"], r["Title"], r["Preconditions"], r["Steps"],
             r["Test Data"], r["Expected Result"], r["Priority"]) for _, r in df.iterrows()]
    conn.executemany("""INSERT INTO test_cases
        (requirement_id, tc_id, scenario, title, preconditions, steps, test_data, expected_result, priority)
        VALUES (?,?,?,?,?,?,?,?,?)""", rows)


def save_new(requirement: str, feature: str, assumptions: list, df: pd.DataFrame) -> int:
    with closing(_connect()) as conn, conn:
        cur = conn.execute(
            "INSERT INTO requirements (requirement, feature, assumptions, created_at) VALUES (?,?,?,?)",
            (requirement, feature, "\n".join(assumptions), datetime.now().strftime("%Y-%m-%d %H:%M")))
        _insert_cases(conn, cur.lastrowid, df)
        return cur.lastrowid


def update_cases(req_id: int, df: pd.DataFrame):
    """Replace the saved test cases of an existing requirement with the edited table."""
    with closing(_connect()) as conn, conn:
        conn.execute("DELETE FROM test_cases WHERE requirement_id = ?", (req_id,))
        _insert_cases(conn, req_id, df)


def list_requirements() -> list[dict]:
    with closing(_connect()) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""SELECT r.id, r.requirement, r.feature, r.created_at,
                               (SELECT COUNT(*) FROM test_cases t WHERE t.requirement_id = r.id) AS n
                               FROM requirements r ORDER BY r.id DESC""").fetchall()
    return [dict(r) for r in rows]


def load_requirement(req_id: int):
    """Return (requirement_row_dict, DataFrame of test cases)."""
    with closing(_connect()) as conn:
        conn.row_factory = sqlite3.Row
        req = conn.execute("SELECT * FROM requirements WHERE id = ?", (req_id,)).fetchone()
        cases = conn.execute("""SELECT tc_id AS ID, scenario AS Scenario, title AS Title,
            preconditions AS Preconditions, steps AS Steps, test_data AS "Test Data",
            expected_result AS "Expected Result", priority AS Priority
            FROM test_cases WHERE requirement_id = ? ORDER BY id""", (req_id,)).fetchall()
    df = pd.DataFrame([dict(c) for c in cases])
    return (dict(req) if req else None), df


def delete_requirement(req_id: int):
    with closing(_connect()) as conn, conn:
        conn.execute("DELETE FROM requirements WHERE id = ?", (req_id,))
