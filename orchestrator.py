from langgraph.prebuilt import create_react_agent
from langchain_core.messages import HumanMessage, BaseMessage
from langchain_mcp_adapters.tools import load_mcp_tools
from langchain_community.chat_message_histories import SQLChatMessageHistory
from mcp.client.sse import sse_client
from mcp import ClientSession
from dotenv import load_dotenv
from langchain_ollama import ChatOllama
import os, time, psycopg2

load_dotenv()

ORCHESTRATOR_PROMPT_PATH = os.getenv('orc_prompt')
MODEL = "gemma4:e4b"
MCP_SERVER_IP = os.getenv('mcp_server_ip')
DEFAULT_SESSION_ID = "orchestrator-default-session"

DB_CONN = os.getenv('agents_memory')
if not DB_CONN:
    raise ValueError("❌ agents_memory_db not set. Please add a PostgreSQL connection string to your .env")
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

async def orchestrator_response(
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

    with open(ORCHESTRATOR_PROMPT_PATH, 'r', encoding='utf-8') as f:
        system_prompt = f.read()

    llm = ChatOllama(model=MODEL)

    async with sse_client(MCP_SERVER_IP) as (read, write):
        async with ClientSession(read, write) as mcp_session:
            await mcp_session.initialize()
            tools = await load_mcp_tools(mcp_session)

            agent = create_react_agent(
                model=llm,
                tools=tools,
                prompt=system_prompt,
            )

            history = get_session_history(session_id, conn_string)
            messages_in = history.messages + [HumanMessage(content=query)]

            print(f"📨 Sending {len(messages_in)} message(s) to agent "f"({len(history.messages)} from history + 1 new)")

            try:
                start_time = time.time()

                raw_res = await agent.ainvoke({"messages": messages_in})
                output = raw_res["messages"][-1].content
                elapsed = time.time() - start_time

                history.add_user_message(query)
                history.add_ai_message(output)
                print(f"💾 Turn saved to DB (session: {session_id})")

                print(f"\n💬 Response : {output}")
                print(f"⏱️  Elapsed  : {elapsed:.2f}s")
                print(f"🗂️  Session  : {session_id}")

                return {
                    "result": output,
                    "session_id": session_id, 
                    "elapsed_time": elapsed
                }

            except Exception as e:
                print(f"❌ Agent execution error: {e}")
                return {
                    "result": f"Error processing request: {str(e)}",
                    "error": str(e),
                    "session_id": session_id
                }
