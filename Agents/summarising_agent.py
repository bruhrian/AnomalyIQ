from langgraph.prebuilt import create_react_agent
from langchain_core.messages import HumanMessage, BaseMessage
from langchain_community.chat_message_histories import SQLChatMessageHistory
from dotenv import load_dotenv
import asyncio
import os, time, psycopg2
from langchain_openai import ChatOpenAI

load_dotenv()

SUMMARISING_PROMPT_PATH = os.getenv('sum_prompt')
MODEL = os.getenv("MODEL")
OPENAI_API_KEY = os.getenv("API_KEY")
BASE_URL = os.getenv("BASE_URL")
MCP_SERVER_IP = os.getenv('mcp_server_ip')
DEFAULT_SESSION_ID = "summary-default-session"
REQUEST_TIMEOUT_SECONDS = float(os.getenv("SUMMARISER_TIMEOUT_SECONDS", "60"))
MAX_HISTORY_MESSAGES = int(os.getenv("SUMMARISER_MAX_HISTORY_MESSAGES", "8"))

DB_CONN = os.getenv('agents_memory')
if not DB_CONN:
    raise ValueError("❌ agents_memory not set. Please add a PostgreSQL connection string to your .env")
else:
    print(f"✅ Postgres connection string loaded.")

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

def get_trimmed_messages(history: SQLChatMessageHistory) -> list[BaseMessage]:
    if MAX_HISTORY_MESSAGES <= 0:
        return []
    if len(history.messages) <= MAX_HISTORY_MESSAGES:
        return history.messages
    trimmed = history.messages[-MAX_HISTORY_MESSAGES:]
    print(f"History trimmed from {len(history.messages)} to {len(trimmed)} messages.")
    return trimmed

async def summary_response(
    query: str,
    session_id: str | None = None,
    conn_string: str = DB_CONN
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

    log_session_history(session_id, conn_string)

    with open(SUMMARISING_PROMPT_PATH, 'r', encoding='utf-8') as f:
        system_prompt = f.read()

    llm = ChatOpenAI(
        model=MODEL,
        api_key= OPENAI_API_KEY,
        base_url= BASE_URL)

    agent = create_react_agent(
        model=llm,
        tools=[],
        prompt=system_prompt,
    )

    history = get_session_history(session_id, conn_string)
    trimmed_history = get_trimmed_messages(history)
    messages_in = trimmed_history + [HumanMessage(content=query)]

    print(
        f"Sending {len(messages_in)} message(s) to agent "
        f"({len(trimmed_history)} from history + 1 new)"
    )

    try:
        start_time = time.time()

        raw_res = await asyncio.wait_for(
            agent.ainvoke({"messages": messages_in}),
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        output = raw_res["messages"][-1].content
        elapsed = time.time() - start_time

        history.add_user_message(query)
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
        print(f"Summarising agent timed out after {REQUEST_TIMEOUT_SECONDS:.0f}s")
        return {
            "result": f"Summariser timed out after {REQUEST_TIMEOUT_SECONDS:.0f}s.",
            "error": "summariser timeout",
            "session_id": session_id
        }
    except Exception as e:
        print(f"Agent execution error: {e}")
        return {
            "result": f"Error processing request: {str(e)}",
            "error": str(e),
            "session_id": session_id
        }
