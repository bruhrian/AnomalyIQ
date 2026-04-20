import sys
from pathlib import Path #Added#
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))#Added#
from fastmcp import FastMCP
import asyncio
from langchain_community.tools import DuckDuckGoSearchRun
from dotenv import load_dotenv
from Agents.ESA import ESA_response
from Agents.audit_agent import audit_query
from Agents.summarising_agent import summary_response
import json
load_dotenv()

agent_mcp = FastMCP(
    "OrchestratorMCP",
    instructions="An MCP server that exposes AI agents as a tool and other tools for orchestrator."
)

@agent_mcp.tool(description="Explains summarised anomaly's cascade effects and provide solutions to the anomaly")
async def run_explanation_solution_agent(query: str) -> str: 
    response = await ESA_response(coordinator_input=query)
    return json.dumps(response) if isinstance(response, dict) else str(response)

@agent_mcp.tool(description="To track what the orchestrator is doing. Needs to called with every other step taken")
async def run_audit_agent(query: str) -> str: 

    response = audit_query(query=query) #Changed#
    return response

@agent_mcp.tool(description="Summarises raw json anomaly data into text form, must always be called first when anomalies are received")
async def run_summarising_agent(query:str) -> str:
    response = await summary_response(query=query)
    return response

if __name__ == "__main__":
    agent_mcp.run(transport="sse", port=8080)
