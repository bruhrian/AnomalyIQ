from langchain_community.tools import WikipediaQueryRun, DuckDuckGoSearchRun
from langchain_community.utilities import WikipediaAPIWrapper
from langchain_classic.tools import Tool
from datetime import datetime
from RAG_tool import RAG_solution
from agents.ES_agent import ESA_response

rag_instance = RAG_solution("", {})

def save_to_txt(data: str, filename: str = "research_output.txt"): # Must give data type
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    formatted_text = f"--- Research Output ---\nTimestamp: {timestamp}\n\n{data}\n\n"

    with open(filename, "a", encoding="utf-8") as f:
        f.write(formatted_text)
    
    return f"Data successfully saved to {filename}"

save_tool = Tool(
    name="save_text_to_file",
    func=save_to_txt,
    description="Saves structured research data to a text file.",
)

# ====================== Need use ======================
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
# =========================================================

api_wrapper = WikipediaAPIWrapper(top_k_results=1, doc_content_chars_max=100)
wiki_tool = WikipediaQueryRun(api_wrapper=api_wrapper)
