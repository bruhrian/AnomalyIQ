from langgraph.prebuilt import create_react_agent
from langchain_core.messages import HumanMessage, SystemMessage, BaseMessage
from langchain_mcp_adapters.tools import load_mcp_tools
from pathlib import Path
from langchain_community.chat_message_histories import SQLChatMessageHistory
from mcp.client.sse import sse_client
from mcp import ClientSession
from dotenv import load_dotenv
from langchain_ollama import ChatOllama
import asyncio
import os, sys, time, psycopg2

load_dotenv(dotenv_path=Path(__file__).resolve().parent.parent / ".env", override=True)
ORCHESTRATOR_PROMPT_PATH = os.getenv('orc_prompt')
MODEL = os.getenv("MODEL")     
DIRECT_CHAT_MODEL = os.getenv("DIRECT_CHAT_MODEL") or MODEL
MCP_SERVER_IP = os.getenv('mcp_server_ip')
DEFAULT_SESSION_ID = "orchestrator-default-session"
REQUEST_TIMEOUT_SECONDS = float(os.getenv("ORCHESTRATOR_TIMEOUT_SECONDS", "180"))
MAX_HISTORY_MESSAGES = int(os.getenv("ORCHESTRATOR_MAX_HISTORY_MESSAGES", "12"))
DIRECT_CHAT_TIMEOUT_SECONDS = float(os.getenv("ORCHESTRATOR_DIRECT_TIMEOUT_SECONDS", "90"))
DIRECT_CHAT_MAX_HISTORY_MESSAGES = int(os.getenv("DIRECT_CHAT_MAX_HISTORY_MESSAGES", "4"))

DB_CONN = os.getenv('agents_memory')
if not DB_CONN:
    raise ValueError("❌ agents_memory_db not set. Please add a PostgreSQL connection string to your .env")
else:
    print(f"✅ Postgres connection string loaded.")


DEFAULT_TOOL_PROMPT = """You are AnomalyIQ AI, the orchestrator for an industrial anomaly detection and predictive maintenance system.

You may use available MCP tools when they are available and useful.

Answer in a clear operator-facing format:

Summary:
- 1-2 short bullets

Likely Cause:
- short bullets grounded in the available context

Risks:
- short bullets about impact or cascade effects

Recommended Actions:
1. concrete next steps

Visual Evidence:
- explicitly mention whether a line plot and heatmap are available
- if visuals are available, explain how they support the diagnosis

Rules:
- Focus on the machine named in the request or anomaly context.
- Do not ask for raw data that is already provided.
- If context is limited, say what is known and what remains uncertain.
- Be concise, practical, and specific.
"""

def init_postgres_db(conn_string: str = DB_CONN) -> bool:
    try:
        conn = psycopg2.connect(conn_string)
        conn.close()
        print(f"✅ Postgres DB connection verified.")
        return True
    except Exception as e:
        print(f"❌ Failed to connect to Postgres: {e}")
        return False

def get_session_history(session_id: str, conn_string: str = DB_CONN) -> SQLChatMessageHistory:
    return SQLChatMessageHistory(
        session_id=session_id,
        connection_string=conn_string
    )

def log_session_history(session_id: str, conn_string: str = DB_CONN) -> None:
    history = get_session_history(session_id, conn_string)
    messages: list[BaseMessage] = history.messages
    print(f"\n🔍 Chat history for session [{session_id}]:")
    if not messages:
        print("   ⚠️  No prior messages (normal for a new session)")
        return
    print(f"   {len(messages)} message(s) loaded:")
    for i, msg in enumerate(messages):
        preview = str(msg.content)[:120]
        if len(str(msg.content)) > 120:
            preview += "..."
        print(f"   [{i}] {type(msg).__name__}: {preview}")

def get_trimmed_messages(history: SQLChatMessageHistory, max_messages: int = MAX_HISTORY_MESSAGES) -> list[BaseMessage]:
    if max_messages <= 0:
        return []
    if len(history.messages) <= max_messages:
        return history.messages
    trimmed = history.messages[-max_messages:]
    print(
        f"History trimmed from {len(history.messages)} to {len(trimmed)} messages "
        f"for faster orchestration."
    )
    return trimmed


def load_orchestrator_prompt() -> str:
    if ORCHESTRATOR_PROMPT_PATH and Path(ORCHESTRATOR_PROMPT_PATH).exists():
        with open(ORCHESTRATOR_PROMPT_PATH, "r", encoding="utf-8") as f:
            return f.read()
    print("Warning: orc_prompt file not found. Falling back to built-in orchestrator prompt.")
    return DEFAULT_TOOL_PROMPT

async def orchestrator_response(
    query: str,
    session_id: str | None = None,
    conn_string: str = DB_CONN,
    use_tools: bool = True,
    request_timeout_seconds: float | None = None,
    persist_history: bool = True,
    history_user_message: str | None = None,
) -> dict:

    if not init_postgres_db(conn_string):
        return {
            "result": "Agent could not start: memory database failed to initialise.",
            "error": "DB init failure",
            "session_id": session_id
        }

    if not session_id:
        session_id = DEFAULT_SESSION_ID
        print(f"ℹ️  No session_id provided — using default: [{session_id}]")
    else:
        print(f"🔄 Resuming session: [{session_id}]")

    if persist_history:
        log_session_history(session_id, conn_string)

    system_prompt = load_orchestrator_prompt()

    effective_timeout = request_timeout_seconds or REQUEST_TIMEOUT_SECONDS
    llm = ChatOllama(model=MODEL, request_timeout=effective_timeout)

    history = get_session_history(session_id, conn_string) if persist_history else None
    trimmed_history = get_trimmed_messages(history) if history else []
    messages_in = trimmed_history + [HumanMessage(content=query)]

    if not use_tools:
        print("MCP tools disabled for this response; using direct model call with supplied backend context.")
        direct_trimmed_history = get_trimmed_messages(history, DIRECT_CHAT_MAX_HISTORY_MESSAGES) if history else []
        direct_messages_in = direct_trimmed_history + [HumanMessage(content=query)]
        direct_timeout = min(effective_timeout, DIRECT_CHAT_TIMEOUT_SECONDS)
        direct_llm = ChatOllama(model=DIRECT_CHAT_MODEL, request_timeout=direct_timeout)
        direct_chat_prompt = (
            "You are AnomalyIQ AI, a diagnostic assistant inside the operator UI.\n"
            "Answer the operator directly, clearly, and in a practical operator-facing style.\n"
            "Do not create plans, do not delegate tasks, and do not claim you will call tools.\n"
            "You do not have tool access in this mode. Use only the user question, chat history, "
            "and any backend context included in the message.\n"
            "If the operator asks whether the backend is connected, explain that this chat request "
            "reached the backend if you are responding.\n"
            "If there is no anomaly record for the target machine, do not stop there. "
            "Still explain the current known machine state from backend context, and then state that no anomaly records are available.\n"
            "If the target machine appears normal, say that clearly.\n"
            "Use this exact response structure:\n"
            "Summary:\n"
            "- one or two short bullets\n\n"
            "Likely Cause:\n"
            "- short bullets\n\n"
            "Risks:\n"
            "- short bullets\n\n"
            "Recommended Actions:\n"
            "1. numbered actions\n\n"
            "Visual Evidence:\n"
            "- mention whether line_plot and heatmap are available for the resolved machine."
        )
        try:
            start_time = time.time()
            raw_msg = await asyncio.wait_for(
                direct_llm.ainvoke([SystemMessage(content=direct_chat_prompt), *direct_messages_in]),
                timeout=direct_timeout,
            )
            output = raw_msg.content
            elapsed = time.time() - start_time

            if history:
                history.add_user_message(history_user_message or query)
                history.add_ai_message(output)
                print(f"Turn saved to DB (session: {session_id})")

            return {
                "result": output,
                "session_id": session_id,
                "elapsed_time": elapsed
            }
        except asyncio.TimeoutError:
            timeout_seconds = direct_timeout
            print(f"Direct chat timed out after {timeout_seconds:.0f}s")
            timeout_msg = (
                f"Request timed out after {timeout_seconds:.0f}s while waiting for the model. "
                "Try a shorter question, reduce local model load, or configure a faster DIRECT_CHAT_MODEL."
            )
            if history:
                history.add_user_message(history_user_message or query)
                history.add_ai_message(timeout_msg)
            return {
                "result": timeout_msg,
                "error": "model timeout",
                "session_id": session_id
            }
        except Exception as e:
            print(f"Direct chat error: {e}")
            error_msg = f"Error processing request: {str(e)}"
            if history:
                history.add_user_message(history_user_message or query)
                history.add_ai_message(error_msg)
            return {
                "result": error_msg,
                "error": str(e),
                "session_id": session_id
            }

    tools = []
    mcp_context = None
    if use_tools:
        mcp_started = time.time()
        print(f"Connecting to MCP server: {MCP_SERVER_IP}")
        mcp_context = sse_client(MCP_SERVER_IP)
        read, write = await mcp_context.__aenter__()
        mcp_session_context = ClientSession(read, write)
        mcp_session = await mcp_session_context.__aenter__()
        try:
            await mcp_session.initialize()
            print(f"MCP session initialized in {time.time() - mcp_started:.2f}s")
            tools = await load_mcp_tools(mcp_session)
            print(f"Loaded {len(tools)} MCP tools")
        except Exception:
            await mcp_session_context.__aexit__(*sys.exc_info())
            await mcp_context.__aexit__(*sys.exc_info())
            raise
    try:
        agent = create_react_agent(
            model=llm,
            tools=tools,
            prompt=system_prompt,
        )

        print(
            f"Sending {len(messages_in)} message(s) to agent "
            f"({len(trimmed_history)} from history + 1 new)"
        )

        try:
            start_time = time.time()

            print(f"Starting agent invocation with {effective_timeout:.0f}s timeout")
            raw_res = await asyncio.wait_for(
                agent.ainvoke({"messages": messages_in}),
                timeout=effective_timeout,
            )
            output = raw_res["messages"][-1].content
            elapsed = time.time() - start_time

            if history:
                history.add_user_message(history_user_message or query)
                history.add_ai_message(output)
                print(f"Turn saved to DB (session: {session_id})")

            print(f"\nResponse : {output}")
            print(f"Elapsed  : {elapsed:.2f}s")
            print(f"Session  : {session_id}")

            return {
                "result": output,
                "session_id": session_id,
                "elapsed_time": elapsed
            }

        except asyncio.TimeoutError:
            print(f"Agent execution timed out after {effective_timeout:.0f}s")
            timeout_msg = (
                f"Request timed out after {effective_timeout:.0f}s while waiting for the "
                "orchestrator or one of its tools."
            )
            if history:
                history.add_user_message(history_user_message or query)
                history.add_ai_message(timeout_msg)
            return {
                "result": timeout_msg,
                "error": "orchestrator timeout",
                "session_id": session_id
            }
        except Exception as e:
            print(f"Agent execution error: {e}")
            error_msg = f"Error processing request: {str(e)}"
            if history:
                history.add_user_message(history_user_message or query)
                history.add_ai_message(error_msg)
            return {
                "result": error_msg,
                "error": str(e),
                "session_id": session_id
            }
    finally:
        if use_tools and mcp_session_context is not None and mcp_context is not None:
            await mcp_session_context.__aexit__(None, None, None)
            await mcp_context.__aexit__(None, None, None)
