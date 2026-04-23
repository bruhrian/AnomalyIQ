"""
audit_agent.py
Audit Agent — PostgreSQL-backed audit log with NLP-to-SQL query support

Format follows ESA.py conventions:
  - Pydantic response models
  - Unified thinking + result + raw_output structure
  - Consistent try/except with error returns

Three public functions:
  1. log_event(agent, event, details)   — INSERT one audit row
  2. query_logs(agent, event, sensor_id, limit) — SELECT with filters
  3. audit_query(question)              — NLP-to-SQL via LlamaIndex
                                          e.g. "Show all anomalies for M001 today"
"""

import os
import json
import time
import psycopg2
import psycopg2.extras
from typing import Optional
from pydantic import BaseModel
from dotenv import load_dotenv

from llama_index.core import SQLDatabase, Settings
from llama_index.core.query_engine import NLSQLTableQueryEngine
from llama_index.llms.ollama import Ollama
from sqlalchemy import create_engine

load_dotenv()

# ── Config ─────────────────────────────────────────────────────────────────────
DB_CONFIG = {
    "host":     os.getenv("POSTGRES_HOST"),
    "port":     int(os.getenv("POSTGRES_PORT", "5432")),
    "dbname":   os.getenv("PG_AUDIT"),
    "user":     os.getenv("POSTGRES_USER"),
    "password": os.getenv("POSTGRES_PASSWORD"),
}

MODEL = os.getenv("AUDIT_MODEL") or os.getenv("MODEL") or "gemma3:2b"
AUDIT_QUERY_TIMEOUT_SECONDS = float(os.getenv("AUDIT_QUERY_TIMEOUT_SECONDS", "60"))

# SQLAlchemy connection string for LlamaIndex
DB_URL = (
    f"postgresql+psycopg2://"
    f"{DB_CONFIG['user']}:{DB_CONFIG['password']}"
    f"@{DB_CONFIG['host']}:{DB_CONFIG['port']}"
    f"/{DB_CONFIG['dbname']}"
)

# ── psycopg2 connection (for log_event / query_logs) ──────────────────────────
_conn = None

def _get_conn():
    global _conn
    if _conn is None or _conn.closed:
        _conn = psycopg2.connect(**DB_CONFIG)
        _conn.autocommit = True
        _ensure_table(_conn)
    return _conn

def _ensure_table(conn):
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS audit_logs (
                id          SERIAL PRIMARY KEY,
                timestamp   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                agent       TEXT        NOT NULL,
                event       TEXT        NOT NULL,
                details     JSONB,
                sensor_id   TEXT GENERATED ALWAYS AS (details->>'sensor_id') STORED
            );
            CREATE INDEX IF NOT EXISTS idx_audit_agent     ON audit_logs (agent);
            CREATE INDEX IF NOT EXISTS idx_audit_event     ON audit_logs (event);
            CREATE INDEX IF NOT EXISTS idx_audit_sensor_id ON audit_logs (sensor_id);
            CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_logs (timestamp DESC);
        """)

# ── LlamaIndex NLP-to-SQL engine (lazy init) ──────────────────────────────────
_nl_engine = None

def _get_nl_engine():
    global _nl_engine
    if _nl_engine is None:
        Settings.llm = Ollama(model=MODEL, request_timeout=AUDIT_QUERY_TIMEOUT_SECONDS)
        engine      = create_engine(DB_URL)
        sql_db      = SQLDatabase(engine, include_tables=["audit_logs"])
        _nl_engine  = NLSQLTableQueryEngine(
            sql_database = sql_db,
            tables       = ["audit_logs"],
            verbose      = False,
        )
    return _nl_engine


# ── Pydantic response models ───────────────────────────────────────────────────

class LogEventResult(BaseModel):
    status:    str
    entry_id:  Optional[int]
    timestamp: Optional[str]
    agent:     str
    event:     str

class LogEntry(BaseModel):
    id:        int
    timestamp: str
    agent:     str
    event:     str
    details:   Optional[dict]

class QueryLogsResult(BaseModel):
    count:   int
    logs:    list[LogEntry]
    filters: dict

class AuditQueryResult(BaseModel):
    answer:       str
    sql_generated: Optional[str]
    tools_used:   list[str]


# ── 1. log_event ───────────────────────────────────────────────────────────────

def log_event(agent: str, event: str, details: dict) -> dict:
    """
    Insert one audit event into PostgreSQL.
    Called by CA, ESA, MASA to maintain a full audit trail.

    Args:
        agent   : calling agent name   e.g. "CA", "ESA", "MASA"
        event   : short event label    e.g. "anomaly_detected", "qa_answered"
        details : arbitrary dict       e.g. {"sensor_id": "M001", "confidence": 0.91}
    """
    start = time.time()
    try:
        conn = _get_conn()
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO audit_logs (agent, event, details)
                VALUES (%s, %s, %s)
                RETURNING id, timestamp
                """,
                (agent, event, json.dumps(details)),
            )
            row       = cur.fetchone()
            entry_id  = row[0]
            timestamp = row[1].isoformat()

        parsed_res = LogEventResult(
            status    = "logged",
            entry_id  = entry_id,
            timestamp = timestamp,
            agent     = agent,
            event     = event,
        )

        elapsed = time.time() - start
        print(f"\n{'='*50}")
        print("AUDIT — log_event:")
        print(parsed_res)
        print(f"{'='*50}\n")
        print(f"Elapsed time - {elapsed:.2f} seconds")

        return {
            "thinking": [
                "📋 *Starting audit log...*",
                f"🔍 *Logging event:* `{event}` from `{agent}`",
                "✨ *Event logged successfully!*",
            ],
            "result":     parsed_res,
            "raw_output": parsed_res.model_dump_json(),
        }

    except Exception as e:
        print(f"Error in log_event: {e}")
        return {
            "thinking": [
                "📋 *Starting audit log...*",
                f"🔍 *Logging event:* `{event}` from `{agent}`",
                "❌ *Logging failed.*",
            ],
            "result": LogEventResult(
                status="error", entry_id=None,
                timestamp=None, agent=agent, event=event,
            ),
            "error": str(e),
        }


# ── 2. query_logs ──────────────────────────────────────────────────────────────

def query_logs(
    agent:     str = "",
    event:     str = "",
    sensor_id: str = "",
    limit:     int = 50,
) -> dict:
    """
    Query audit logs with optional filters.
    Returns up to `limit` most recent entries (capped at 500).

    Args:
        agent     : filter by agent name     (empty = all)
        event     : filter by event label    (empty = all)
        sensor_id : filter by machine/sensor (empty = all)
        limit     : max rows to return
    """
    start = time.time()
    try:
        conn       = _get_conn()
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
        params.append(min(limit, 500))

        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                f"""
                SELECT id, timestamp, agent, event, details
                FROM   audit_logs
                {where}
                ORDER  BY timestamp DESC
                LIMIT  %s
                """,
                params,
            )
            rows = cur.fetchall()

        log_entries = [
            LogEntry(
                id        = r["id"],
                timestamp = r["timestamp"].isoformat(),
                agent     = r["agent"],
                event     = r["event"],
                details   = r["details"],
            )
            for r in rows
        ]

        parsed_res = QueryLogsResult(
            count   = len(log_entries),
            logs    = log_entries,
            filters = {"agent": agent, "event": event, "sensor_id": sensor_id},
        )

        elapsed = time.time() - start
        print(f"\n{'='*50}")
        print("AUDIT — query_logs:")
        print(f"  Returned {parsed_res.count} entries")
        print(f"{'='*50}\n")
        print(f"Elapsed time - {elapsed:.2f} seconds")

        return {
            "thinking": [
                "📋 *Starting audit query...*",
                f"🔍 *Filters:* agent=`{agent or 'any'}` event=`{event or 'any'}` sensor=`{sensor_id or 'any'}`",
                f"✨ *Query complete — {parsed_res.count} entries found!*",
            ],
            "result":     parsed_res,
            "raw_output": parsed_res.model_dump_json(),
        }

    except Exception as e:
        print(f"Error in query_logs: {e}")
        return {
            "thinking": [
                "📋 *Starting audit query...*",
                "❌ *Query failed.*",
            ],
            "result": QueryLogsResult(
                count=0, logs=[],
                filters={"agent": agent, "event": event, "sensor_id": sensor_id},
            ),
            "error": str(e),
        }


# ── 3. audit_query — NLP-to-SQL ───────────────────────────────────────────────

def audit_query(question: str = "", query: str = "") -> dict:
    """
    Natural language query against the audit_logs table.
    Uses LlamaIndex NLSQLTableQueryEngine (text-to-SQL) under the hood.

    Examples:
        "Show all anomalies for M001 today"
        "How many events were logged by ESA this week?"
        "What was the last event for sensor M003?"
        "List all qa_answered events in the last hour"

    Args:
        question : plain English question about the audit log
    """
    question = query or question
    start = time.time()
    try:
        engine   = _get_nl_engine()
        response = engine.query(question)

        # LlamaIndex puts the generated SQL in response.metadata
        sql_used = None
        if hasattr(response, "metadata") and response.metadata:
            sql_used = response.metadata.get("sql_query")

        answer = str(response)

        parsed_res = AuditQueryResult(
            answer        = answer,
            sql_generated = sql_used,
            tools_used    = ["LlamaIndex NLSQLTableQueryEngine", "PostgreSQL"],
        )

        elapsed = time.time() - start
        print(f"\n{'='*50}")
        print("AUDIT — audit_query (NLP-to-SQL):")
        print(f"  Q: {question}")
        print(f"  SQL: {sql_used}")
        print(f"  A: {answer[:200]}")
        print(f"{'='*50}\n")
        print(f"Elapsed time - {elapsed:.2f} seconds")

        return {
            "thinking": [
                "📋 *Starting NLP-to-SQL query...*",
                f"🔍 *Processing:* `{question}`",
                f"🛠 *Generated SQL and queried PostgreSQL*",
                "✨ *Query complete!*",
            ],
            "result":     parsed_res,
            "raw_output": parsed_res.model_dump_json(),
        }

    except Exception as e:
        print(f"Error in audit_query: {e}")
        return {
            "thinking": [
                "📋 *Starting NLP-to-SQL query...*",
                f"🔍 *Processing:* `{question}`",
                "❌ *Query failed.*",
            ],
            "result": AuditQueryResult(
                answer        = f"Error processing query: {str(e)}",
                sql_generated = None,
                tools_used    = ["LlamaIndex NLSQLTableQueryEngine"],
            ),
            "error": str(e),
        }
