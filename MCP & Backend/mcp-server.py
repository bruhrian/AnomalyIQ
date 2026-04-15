from fastmcp import FastMCP
import asyncio
from langchain_community.tools import DuckDuckGoSearchRun
from dotenv import load_dotenv
from Agents.ESA import ESA_response

load_dotenv()

agent_mcp = FastMCP(
    "OrchestratorMCP",
    instructions="An MCP server that exposes AI agents as a tool and other tools for orchestrator."
)

@agent_mcp.tool()
async def run_explanation_solution_agent(query: str) -> str: 
    response = await ESA_response(query=query)
    return response

@agent_mcp.tool()
async def run_audit_agent(query: str) -> str: 
    response = await audit_response(query=query)
    return response

if __name__ == "__main__":
    agent_mcp.run(transport="http", port=8080)
