"""
coordinator_agent.py  (updated)
================================
Same as original ca_response() logic.

Added two wrapper functions that backend.py imports:
  - handle_qa_question(machine_id, question) 
  - handle_anomaly_alert(machine_id, machine_type, label, confidence, visual_url)
"""

from langchain_ollama import ChatOllama
from langgraph.prebuilt import create_react_agent
from langchain_core.messages import HumanMessage, BaseMessage
from langchain_mcp_adapters.tools import load_mcp_tools
from langchain_community.chat_message_histories import SQLChatMessageHistory
from mcp.client.streamable_http import streamable_http_client
from mcp import ClientSession
from dotenv import load_dotenv
from pathlib import Path
import os, time, sqlite3

load_dotenv()

CA_PROMPT_PATH = os.getenv('ca_prompt')
MODEL          = "gemma4:e4b"
MCP_SERVER_IP  = os.getenv('mcp_server_ip')

_raw_db_path = os.getenv('ca_memory_db') or './data/conversations.db'
DB_PATH      = str(Path(_raw_db_path))

DEFAULT_SESSION_ID = "ca-default-session"

if not os.getenv('ca_memory_db'):
    print(f"⚠️  Warning: ca_memory_db not set, using default: {DB_PATH}")
else:
    print(f"✅ ca_memory_db resolved to: {DB_PATH}")


# ── Helpers (unchanged from original) ────────────────────────────────────────

def init_sqlite_db(db_path: str = DB_PATH) -> bool:
    try:
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(db_path))
        conn.execute("SELECT 1")
        conn.close()
        print(f"✅ SQLite DB ready at: {db_path}")
        return True
    except Exception as e:
        print(f"❌ Failed to initialise SQLite DB at '{db_path}': {e}")
        return False

def get_session_history(session_id: str, db_path: str = DB_PATH) -> SQLChatMessageHistory:
    return SQLChatMessageHistory(
        session_id        = session_id,
        connection_string = f"sqlite:///{db_path}",
    )

def log_session_history(session_id: str, db_path: str = DB_PATH) -> None:
    history  = get_session_history(session_id, db_path)
    messages = history.messages
    print(f"\n🔍 Chat history for session [{session_id}]:")
    if not messages:
        print("   ⚠️  No prior messages (normal for a new session)")
        return
    for i, msg in enumerate(messages):
        preview = str(msg.content)[:120]
        if len(str(msg.content)) > 120:
            preview += "..."
        print(f"   [{i}] {type(msg).__name__}: {preview}")


# ── Core agent function (unchanged from original) ─────────────────────────────

async def ca_response(
    query:      str,
    session_id: str | None = None,
    db_path:    str        = DB_PATH,
) -> dict:
    if not init_sqlite_db(db_path):
        return {
            "result":     "Agent could not start: memory database failed to initialise.",
            "error":      "DB init failure",
            "session_id": session_id,
        }

    if not session_id:
        session_id = DEFAULT_SESSION_ID
        print(f"ℹ️  No session_id provided — using default: [{session_id}]")
    else:
        print(f"🔄 Resuming session: [{session_id}]")

    log_session_history(session_id, db_path)

    with open(CA_PROMPT_PATH, 'r', encoding='utf-8') as f:
        system_prompt = f.read()

    llm = ChatOllama(model=MODEL)

    async with streamable_http_client(MCP_SERVER_IP) as (read, write, _):
        async with ClientSession(read, write) as mcp_session:
            await mcp_session.initialize()
            tools = await load_mcp_tools(mcp_session)

            agent = create_react_agent(
                model  = llm,
                tools  = tools,
                prompt = system_prompt,
            )

            history      = get_session_history(session_id, db_path)
            messages_in  = history.messages + [HumanMessage(content=query)]

            print(f"📨 Sending {len(messages_in)} message(s) to agent "
                  f"({len(history.messages)} from history + 1 new)")

            try:
                start_time = time.time()
                raw_res    = await agent.ainvoke({"messages": messages_in})
                output     = raw_res["messages"][-1].content
                elapsed    = time.time() - start_time

                history.add_user_message(query)
                history.add_ai_message(output)
                print(f"💾 Turn saved to DB (session: {session_id})")
                print(f"\n💬 Response : {output}")
                print(f"⏱️  Elapsed  : {elapsed:.2f}s")

                return {
                    "result":       output,
                    "session_id":   session_id,
                    "elapsed_time": elapsed,
                }

            except Exception as e:
                print(f"❌ Agent execution error: {e}")
                return {
                    "result":     f"Error processing request: {str(e)}",
                    "error":      str(e),
                    "session_id": session_id,
                }


# ── Wrappers for backend.py ───────────────────────────────────────────────────

async def handle_qa_question(machine_id: str, question: str) -> dict:
    """
    Called by POST /chat in routers/backend.py.
    Wraps ca_response() with a machine-specific session and context.
    """
    # Use machine_id as part of session so each machine has its own memory
    session_id = f"machine-{machine_id}"

    # Prepend machine context to the question
    full_query = f"[Machine: {machine_id}] {question}"

    return await ca_response(
        query      = full_query,
        session_id = session_id,
    )


async def handle_anomaly_alert(
    machine_id:   str,
    machine_type: str,
    label:        str,
    confidence:   float,
    visual_url:   list[str],
) -> dict:
    """
    Called by POST /anomaly in the original backend.py (port 8005).
    Sends the anomaly context to the CA for analysis and response.
    """
    # Log to audit DB
    try:
        from Agents.audit_agent import log_event
        log_event(
            agent   = "MASA",
            event   = "anomaly_detected",
            details = {
                "sensor_id":   machine_id,
                "machine_type": machine_type,
                "label":        label,
                "confidence":   confidence,
                "visual_url":   visual_url,
            },
        )
    except Exception as e:
        print(f"[CA] Audit log failed: {e}")

    # Build the query for the agent
    query = (
        f"ANOMALY ALERT — Machine {machine_id} ({machine_type})\n"
        f"Label: {label} | Confidence: {confidence:.1%}\n"
        f"Visuals: {', '.join(visual_url) if visual_url else 'none'}\n\n"
        f"Please analyse this anomaly, explain the root cause, "
        f"cascade effects, and recommended actions."
    )

    result = await ca_response(
        query      = query,
        session_id = f"anomaly-{machine_id}",
    )

    # Log the answer to audit DB
    try:
        from Agents.audit_agent import log_event
        log_event(
            agent   = "CA",
            event   = "anomaly_answered",
            details = {
                "sensor_id": machine_id,
                "response":  str(result.get("result", ""))[:500],
            },
        )
    except Exception as e:
        print(f"[CA] Audit log (answer) failed: {e}")

    return result
