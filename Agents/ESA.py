from langchain_ollama import ChatOllama
from dotenv import load_dotenv
from pydantic import BaseModel
import os, time
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import PydanticOutputParser
from langchain_classic.agents import AgentExecutor, create_tool_calling_agent
from typing import Optional 

load_dotenv()
ESA_prompt = os.getenv('ESA_prompt_template')
model="gemma4:e4b"

class ESA_Response(BaseModel):
    Impact_analysis: str
    cascade_effects: list[str]
    solutions: str
    tools_used: list[str]
    sources: list[str]
    
def ESA_response(coordinator_input: str, context: Optional[str] = None):
    llm = ChatOllama(
        model=model
    )

    with open(ESA_prompt, 'r') as f:
        ESA_prompt_content = f.read()

    parser= PydanticOutputParser(pydantic_object=ESA_Response)
    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system", ESA_prompt_content
            ),
            # ("placeholder", "{chat_history}"), # For session memory
            ("user", "Context: {context}\n\nQuestion: {coordinator_input}"),
            ("placeholder", "{agent_scratchpad}"),
        ]
    ).partial(format_instructions=parser.get_format_instructions())

    tools = []

    agent = create_tool_calling_agent(
        llm=llm,
        prompt=prompt,
        tools=tools
    )

    agent_exe = AgentExecutor(
        agent=agent,
        tools=tools,
        verbose=False
    )

    try:
        start_time = time.time()
        raw_res=agent_exe.invoke(
            {
                "context": context or "No additional context provided",
                "coordinator_input": coordinator_input
            },
        )
        output = raw_res.get("output", "")
        parsed_res = parser.parse(output)
        final_res={
            "thinking": [
                    "🤔 *Starting Analysis...*",
                    f"🔍 *Processing input:* `{coordinator_input}`",
                    "✨ *Analysis complete!*"
                ],
                "result": parsed_res,
                "raw_output": output
        }
        elapsed = time.time() - start_time
        
        # Print for console/debugging
        print("\n" + "="*50)
        print("FINAL PARSED RESPONSE:")
        print(parsed_res)
        print("="*50 + "\n")
        print(f"Elapsed time - {elapsed:.2f} seconds")

        return final_res

    except Exception as e:
        print(f"Error in agent execution: {e}")
        return {
            "thinking": [
                "🤔 *Starting Analysis...*",
                    f"🔍 *Processing input:* `{coordinator_input}`",
                    "✨ *Analysis complete!*"
            ],
            "result": f"Error processing request: {str(e)}",
            "error": str(e)
        }
