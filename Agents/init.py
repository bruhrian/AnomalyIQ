from langchain_community.tools import WikipediaQueryRun, DuckDuckGoSearchRun
from langchain_community.utilities import WikipediaAPIWrapper
from langchain_classic.tools import Tool
from datetime import datetime
from Agents.tools import RAG_tool
from Agents.ESA import ESA_response

rag_instance = RAG_tool.RAG_solution("", {})

search = DuckDuckGoSearchRun()
search_tool = Tool(
    name="search",
    func=search.run,
    description="Provide solutions for new and/or unknown issues."
)

RAG_soln_tool = Tool(
    name="RAG_solution",
    func=rag_instance.retrieve,  
    description="Search for historical solutions from past incidents. Input should be a description of the current anomaly."
)

ES_agent_tool = Tool(
    name="ES_agent",
    func=ESA_response,
    description="Provide explainations of found anormaly using anormaly summary, provide solutions and cascade effects "
)

api_wrapper = WikipediaAPIWrapper(top_k_results=1, doc_content_chars_max=100)
wiki_tool = WikipediaQueryRun(api_wrapper=api_wrapper)
