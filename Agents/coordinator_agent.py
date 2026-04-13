import os
import json
import ollama
from operator import add
from typing import TypedDict, Annotated
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from dotenv import load_dotenv

from langgraph.graph import StateGraph, END

load_dotenv()

CA_MODEL      = "gemma4"
ROUTER_MODEL  = "gemma4"
ESA_URL       = "http://localhost:8002/mcp"
AUDIT_URL     = "http://localhost:8003/mcp"

TOOL_GROUPS: dict[str, list[str]] = {
    "search":      ["web_search"],
    "explanation": ["ask_ai"],
    "audit":       ["log_event", "query_logs"],
}

ALL_GROUPS = list(TOOL_GROUPS.keys())

class AgentState(TypedDict):
    messages:        Annotated[list, add]  
    tools:           list
    active_tools:    list
    clients:         dict
    tools_map:       dict
    selected_groups: list
    visual_urls:     list   


def _to_dict(msg) -> dict:
    if isinstance(msg, dict):
        return msg

    role = getattr(msg, "type", None) or getattr(msg, "role", "user")

    # LangGraph uses "human" — Ollama expects "user"
    if role == "human":
        role = "user"
    elif role == "ai":
        role = "assistant"

    result = {
        "role":    role,
        "content": getattr(msg, "content", "") or "",
    }

    # Preserve tool_calls if present
    tool_calls = getattr(msg, "tool_calls", None)
    if tool_calls:
        result["tool_calls"] = tool_calls

    return result


# ── MCP helpers ───────────────────────────────────────────────────────────────

async def _fetch_tools(url: str) -> tuple[list[dict], Client]:
    client = Client(StreamableHttpTransport(url))
    await client.__aenter__()
    mcp_tools = await client.list_tools()

    ollama_tools = []
    for tool in mcp_tools:
        ollama_tools.append({
            "type": "function",
            "function": {
                "name":        tool.name,
                "description": tool.description or "",
                "parameters":  tool.inputSchema,
            },
            "_server_url": url,
        })
    return ollama_tools, client


async def _execute_tool(
    tool_name:  str,
    tool_input: dict,
    clients:    dict,
    tools_map:  dict,
) -> str:
    server_url = tools_map.get(tool_name)
    if not server_url:
        return json.dumps({"error": f"Unknown tool: {tool_name}"})

    result = await clients[server_url].call_tool(tool_name, tool_input)

    try:
        if hasattr(result, "content"):
            texts = []
            for block in result.content:
                if hasattr(block, "text"):
                    texts.append(block.text)
                elif hasattr(block, "data"):
                    texts.append(json.dumps(block.data))
            return "\n".join(texts) if texts else json.dumps({"result": str(result)})

        if isinstance(result, list) and result:
            if hasattr(result[0], "text"):
                return result[0].text

        return json.dumps({"result": str(result)})

    except Exception as e:
        return json.dumps({"error": f"Failed to parse tool result: {str(e)}"})


# ── Tool filtering ─────────────────────────────────────────────────────────────

def _filter_tools(all_tools: list, group_names: list[str]) -> list:
    allowed_names = set()
    for group in group_names:
        allowed_names.update(TOOL_GROUPS.get(group, []))
    return [t for t in all_tools if t["function"]["name"] in allowed_names]


# ── Node 1: router ────────────────────────────────────────────────────────────

async def router_node(state: AgentState) -> AgentState:
    # ✅ Fix 2: use _to_dict() so role/content work on any message type
    user_msg = next(
        (_to_dict(m)["content"] for m in reversed(state["messages"])
         if _to_dict(m)["role"] in ("user", "human")),
        ""
    )

    router_prompt = f"""You are a tool router for a predictive maintenance system.

    Available tool groups:
    - search      : search the web for maintenance information
    - explanation : use AI to explain anomalies and generate solutions
    - audit       : log events and query audit history

    Request: {user_msg}

    Which tool groups are needed to handle this request?
    Reply with JSON only, no explanation: {{"groups": ["group1", "group2"]}}
    Only include groups that are genuinely needed."""

    try:
        response = ollama.chat(
            model    = ROUTER_MODEL,
            messages = [{"role": "user", "content": router_prompt}],
            options  = {"temperature": 0.0},
            format   = "json",
        )

        raw    = response["message"].get("content", "") or \
                 response["message"].get("thinking", "")
        parsed = json.loads(raw)
        groups = [g for g in parsed.get("groups", []) if g in ALL_GROUPS]

        if not groups:
            raise ValueError("Router returned no valid groups")

    except Exception as e:
        print(f"[ROUTER] Fallback triggered: {e}")
        groups = ["search", "explanation", "audit"]

    filtered = _filter_tools(state["tools"], groups)

    print(f"[ROUTER] Selected groups : {groups}")
    print(f"[ROUTER] Active tools    : {[t['function']['name'] for t in filtered]}")
    print(f"[ROUTER] Tools shown to model: {len(filtered)} / {len(state['tools'])} total\n")

    return {
        "active_tools":    filtered,
        "selected_groups": groups,
    }


# ── Node 2: call_ollama ───────────────────────────────────────────────────────

async def call_ollama(state: AgentState) -> AgentState:
    tools_to_use = state.get("active_tools") or state["tools"]
    print(f"[CA] Calling Ollama ({CA_MODEL}) with {len(tools_to_use)} tools...")

    # ✅ Fix 3: convert all messages to plain dicts before sending to Ollama
    ollama_messages = [_to_dict(m) for m in state["messages"]]

    response = ollama.chat(
        model    = CA_MODEL,
        messages = ollama_messages,
        tools    = tools_to_use,
        options  = {"temperature": 0.0},
    )

    msg = response["message"]   # Ollama returns a plain dict — safe to store directly
    print(f"[CA] Tool calls requested: {bool(msg.get('tool_calls'))}")

    return {"messages": [msg]}


# ── Node 3: call_tools ────────────────────────────────────────────────────────

async def call_tools(state: AgentState) -> AgentState:
    # ✅ Fix 4: use _to_dict() before calling .get()
    last_msg   = _to_dict(state["messages"][-1])
    tool_calls = last_msg.get("tool_calls", [])

    if not tool_calls:
        return {"messages": []}

    tool_result_messages = []

    for tool_call in tool_calls:
        # tool_call may also be an object in some LangGraph versions
        if isinstance(tool_call, dict):
            tool_name  = tool_call["function"]["name"]
            tool_input = tool_call["function"]["arguments"]
        else:
            tool_name  = tool_call.function.name
            tool_input = tool_call.function.arguments

        if isinstance(tool_input, str):
            tool_input = json.loads(tool_input)

        # Guarantee visual_urls reaches ask_ai even if model forgot to pass it
        if tool_name == "ask_ai" and not tool_input.get("visual_urls"):
            tool_input["visual_urls"] = state.get("visual_urls", [])
            if tool_input["visual_urls"]:
                print(f"[CA] Injected visual_urls: {tool_input['visual_urls']}")

        print(f"[CA] Calling : {tool_name}")
        print(f"[CA] Input   : {json.dumps(tool_input, indent=2)}")

        result_text = await _execute_tool(
            tool_name  = tool_name,
            tool_input = tool_input,
            clients    = state["clients"],
            tools_map  = state["tools_map"],
        )

        print(f"[CA] Result  : {result_text[:200]}{'...' if len(result_text) > 200 else ''}\n")

        tool_result_messages.append({
            "role":    "tool",
            "name":    tool_name,
            "content": result_text,
        })

    return {"messages": tool_result_messages}


# ── Edge: should_continue ─────────────────────────────────────────────────────

def should_continue(state: AgentState) -> str:
    # ✅ Fix 4: use _to_dict() before .get()
    last_msg = _to_dict(state["messages"][-1])
    if last_msg.get("tool_calls"):
        return "call_tools"
    return END


# ── Build graph ───────────────────────────────────────────────────────────────

def _build_graph():
    graph = StateGraph(AgentState)

    graph.add_node("router",      router_node)
    graph.add_node("call_ollama", call_ollama)
    graph.add_node("call_tools",  call_tools)

    graph.set_entry_point("router")
    graph.add_edge("router",      "call_ollama")
    graph.add_conditional_edges("call_ollama", should_continue)
    graph.add_edge("call_tools",  "call_ollama")

    return graph.compile()

_graph = _build_graph()


# ── Core runner ───────────────────────────────────────────────────────────────

async def _run_agent(
    system_prompt: str,
    user_message:  str,
    visual_urls:   list[str] = [],
) -> str:
    all_tools = []
    clients   = {}
    tools_map = {}

    for url in [ESA_URL, AUDIT_URL]:
        try:
            tools, client = await _fetch_tools(url)
            clients[url]  = client
            for tool in tools:
                server_url = tool.pop("_server_url")
                tools_map[tool["function"]["name"]] = server_url
                all_tools.append(tool)
            print(f"[CA] Connected to {url} — {len(tools)} tools loaded")
        except Exception as e:
            print(f"[CA] WARNING: Could not connect to {url}: {e}")

    if not all_tools:
        return "Error: No MCP servers reachable."

    print(f"[CA] Total tools available: {len(all_tools)}")
    print(f"[CA] Tools: {[t['function']['name'] for t in all_tools]}\n")

    initial_state: AgentState = {
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_message},
        ],
        "tools":           all_tools,
        "active_tools":    [],
        "clients":         clients,
        "tools_map":       tools_map,
        "selected_groups": [],
        "visual_urls":     visual_urls,
    }

    try:
        final_state = await _graph.ainvoke(initial_state)

        # ✅ Fix: use _to_dict() on final message
        last_msg = _to_dict(final_state["messages"][-1])
        return last_msg.get("content", "") or last_msg.get("thinking", "") or "No response generated."

    finally:
        for client in clients.values():
            try:
                await client.__aexit__(None, None, None)
            except Exception:
                pass

    return "Agent loop ended unexpectedly."

# ── Entry point 1: Anomaly from CNN pipeline ──────────────────────────────────

async def handle_anomaly_alert(
    machine_id:   str,
    machine_type: str,
    label:        str,
    confidence:   float,
    visual_url:   list[str],
    ) -> dict:
    system_prompt = """You are the Coordinator Agent (CA) for a predictive maintenance system.

    The upstream pipeline has already handled data ingestion, CNN inference, and visual generation.
    You have received a confirmed anomaly result.

    Your job is to:
    1. Call web_search to find relevant external maintenance information for this machine and fault type.
    2. Call ask_ai with:
    - machine_id, machine_type, label, confidence
    - web_results from the web_search result
    - visual_urls: pass the list of visual file paths provided in the anomaly data
    3. Call log_event to record the anomaly, the solution, and the visual URLs in the audit log.

    IMPORTANT: Always pass visual_urls to ask_ai. Do not omit this parameter.
    Do not call any ingestion or CNN tools — those are already done upstream."""

    user_message = f"""Anomaly confirmed by CNN pipeline:

    - machine_id   : {machine_id}
    - machine_type : {machine_type}
    - label        : {label}
    - confidence   : {confidence:.1%}
    - visual_urls  : {json.dumps(visual_url)}

    Generate a maintenance explanation referencing the visuals, then log this event."""

    result = await _run_agent(
        system_prompt = system_prompt,
        user_message  = user_message,
        visual_urls   = visual_url,
    )
    print(f"[CA] Final result for {machine_id}: {result[:200]}\n")
    return {"status": "handled", "machine_id": machine_id, "response": result}


# ── Entry point 2: Operator QA from UI ───────────────────────────────────────

async def handle_qa_question(machine_id: str, question: str) -> dict:
    system_prompt = """You are the Coordinator Agent (CA) for a predictive maintenance system.

    An operator has submitted a question about a machine via the UI.

    Your job is to:
    1. Call query_logs to retrieve recent audit history for this machine.
    2. Call web_search to find relevant external maintenance information.
    3. Call ask_ai with the audit history, web results, and the operator question to generate a full answer.
    4. Call log_event to record this QA interaction in the audit log."""

    user_message = f"""Operator question received:

    - machine_id : {machine_id}
    - question   : {question}

    Research and answer this question fully."""

    result = await _run_agent(
        system_prompt = system_prompt,
        user_message  = user_message,
    )
    return {"machine_id": machine_id, "question": question, "answer": result}