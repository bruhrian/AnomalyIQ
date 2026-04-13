"""
audit_agent.py
Audit DB — Shared audit log backed by PostgreSQL

Real implementations:
  - log_event   : INSERT into audit_logs table
  - query_logs  : SELECT with optional filters
"""
import os
import json
import psycopg2
import psycopg2.extras
from datetime import datetime
from dotenv import load_dotenv
from fastmcp import FastMCP

load_dotenv()

# ── PostgreSQL connection ──────────────────────────────────────────────────────
DB_CONFIG = {
    "host":     os.getenv("POSTGRES_HOST",     "localhost"),
    "port":     int(os.getenv("POSTGRES_PORT", "5432")),
    "dbname":   os.getenv("POSTGRES_DB",       "audit_db"),
    "user":     os.getenv("POSTGRES_USER",     "postgres"),
    "password": os.getenv("POSTGRES_PASSWORD", ""),
}

_conn = None

def get_conn():
    global _conn
    if _conn is None or _conn.closed:
        _conn = psycopg2.connect(**DB_CONFIG)
        _conn.autocommit = True
        _ensure_table()
    return _conn


def _ensure_table():
    """Create the audit_logs table if it doesn't exist."""
    with get_conn().cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS audit_logs (
                id          SERIAL PRIMARY KEY,
                timestamp   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                agent       TEXT        NOT NULL,
                event       TEXT        NOT NULL,
                details     JSONB,
                sensor_id   TEXT        GENERATED ALWAYS AS (details->>'sensor_id') STORED
            );
            CREATE INDEX IF NOT EXISTS idx_audit_agent     ON audit_logs (agent);
            CREATE INDEX IF NOT EXISTS idx_audit_event     ON audit_logs (event);
            CREATE INDEX IF NOT EXISTS idx_audit_sensor_id ON audit_logs (sensor_id);
            CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_logs (timestamp DESC);
        """)


# ── FastMCP server ─────────────────────────────────────────────────────────────
audit = FastMCP("Audit DB")


@audit.tool()
def log_event(agent: str, event: str, details: dict) -> dict:
    """
    Insert an audit event into PostgreSQL.
    All agents call this to maintain a full audit trail.
    """
    with get_conn().cursor() as cur:
        cur.execute(
            """
            INSERT INTO audit_logs (agent, event, details)
            VALUES (%s, %s, %s)
            RETURNING id, timestamp
            """,
            (agent, event, json.dumps(details)),
        )
        row = cur.fetchone()
        entry_id  = row[0]
        timestamp = row[1].isoformat()

    return {
        "status":    "logged",
        "entry_id":  entry_id,
        "timestamp": timestamp,
        "agent":     agent,
        "event":     event,
    }


@audit.tool()
def query_logs(
    agent:     str = "",
    event:     str = "",
    sensor_id: str = "",
    limit:     int = 50,
) -> dict:
    """
    Query audit logs with optional filters.
    Returns up to `limit` most recent entries.
    """
    conditions = []
    params     = []

    if agent:
        conditions.append("agent = %s")
        params.append(agent)
    if event:
        conditions.append("event = %s")
        params.append(event)
    if sensor_id:
        conditions.append("details->>'sensor_id' = %s")
        params.append(sensor_id)

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    params.append(min(limit, 500))  # cap at 500

    with get_conn().cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            f"""
            SELECT id, timestamp, agent, event, details
            FROM audit_logs
            {where}
            ORDER BY timestamp DESC
            LIMIT %s
            """,
            params,
        )
        rows = cur.fetchall()

    logs = [
        {
            "id":        r["id"],
            "timestamp": r["timestamp"].isoformat(),
            "agent":     r["agent"],
            "event":     r["event"],
            "details":   r["details"],
        }
        for r in rows
    ]

    return {
        "count":  len(logs),
        "logs":   logs,
        "filters": {"agent": agent, "event": event, "sensor_id": sensor_id},
    }


if __name__ == "__main__":
    audit.run(transport="stdio")