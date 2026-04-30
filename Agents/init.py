from langchain_community.tools import WikipediaQueryRun, DuckDuckGoSearchRun
from langchain_community.utilities import WikipediaAPIWrapper
from langchain_classic.tools import Tool
from Agents.tools.RAG_tool import rag_query 

rag_instance = RAG_tool.RAG_solution("", {})

search = DuckDuckGoSearchRun()
search_tool = Tool(
    name="search",
    func=search.run,
    description="Provide solutions for new and/or unknown issues."
)

RAG_soln_tool = Tool(
    name="RAG_solution",
    func=rag_query,  
    description="Search for historical solutions from past incidents. Input should be a description of the current anomaly."
)

api_wrapper = WikipediaAPIWrapper(top_k_results=1, doc_content_chars_max=100)
wiki_tool = WikipediaQueryRun(api_wrapper=api_wrapper)
