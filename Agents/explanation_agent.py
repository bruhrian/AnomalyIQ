"""
explanation_agent.py
ESA — Explanation & Solution Agent MCP server
Runs on port 8002.

Tools:
  - web_search : DuckDuckGo search
  - ask_ai     : Ollama LLM explanation + solution
"""
import base64
import os
import httpx
import ollama
from pathlib import Path
from dotenv import load_dotenv
from fastmcp import FastMCP

load_dotenv()

ESA_MODEL = "gemma4"

esa = FastMCP("ESA Agent")

@esa.tool()
def web_search(query: str, max_results: int = 3) -> dict:
    """Search the web for maintenance-related information using DuckDuckGo."""
    try:
        resp = httpx.get(
            "https://api.duckduckgo.com/",
            params={"q": query, "format": "json", "no_html": "1"},
            timeout=8.0,
        )
        data = resp.json()
        results = []

        if data.get("AbstractText"):
            results.append({
                "source": data.get("AbstractSource", "Web"),
                "text":   data["AbstractText"],
                "url":    data.get("AbstractURL", ""),
            })

        for topic in data.get("RelatedTopics", [])[:max_results]:
            if isinstance(topic, dict) and topic.get("Text"):
                results.append({
                    "source": "DuckDuckGo",
                    "text":   topic["Text"],
                    "url":    topic.get("FirstURL", ""),
                })

        return {
            "query":   query,
            "results": results[:max_results],
            "count":   len(results[:max_results]),
        }

    except Exception as e:
        return {"query": query, "results": [], "count": 0, "error": str(e)}


@esa.tool()
def ask_ai(
    machine_id:   str,
    machine_type: str,
    label:        str,
    confidence:   float,
    web_results:  list[dict] = [],
    question:     str = "",       
    visual_urls:  list[str] = [],
    ) -> dict:
    
    images_b64 = []
    for path_str in visual_urls:
        print(f"[ESA] Loading visual from {path_str}...")
        path = Path(path_str)
        if path.exists():
            with open(path, "rb") as f:
                encoded = base64.b64encode(f.read()).decode("utf-8")
                images_b64.append(encoded)
                print(f"[ESA] Loaded image: {path.name} ({len(encoded)} chars b64)")
        else:
            print(f"[ESA] WARNING: Visual not found at {path_str}")

    visual_note = (
        f"{len(images_b64)} anomaly chart(s) attached — line plot and bar chart "
        f"showing raw signal, normalised values, and anomaly threshold."
        if images_b64 else "No visuals available."
    )

    web_context = "\n\n".join(
        f"[Web {i+1}] {r.get('text', r.get('snippet', ''))}"
        for i, r in enumerate(web_results)
    ) if web_results else "No web results provided."

    user_message = f"""You are a predictive maintenance expert.

    ## Machine Alert
    - Machine ID   : {machine_id}
    - Machine Type : {machine_type}
    - Prediction   : {label}
    - Confidence   : {confidence:.1%}

    ## Web Context
    {web_context}
    
    ## Visuals
    {visual_note}
    Analyse the charts and reference specific patterns you observe.

    ## Your Task
    1. Describe what the charts show — identify where the signal exceeds the threshold.
    2. Explain what is likely happening with this machine in 2-3 sentences.
    3. Provide a clear, prioritised list of recommended actions.
    4. Estimate urgency: Critical / High / Medium / Low.
    {"5. Also answer this operator question: " + question if question else ""}

    Be concise and practical."""
    
    if images_b64:
        response = ollama.chat(
            model    = ESA_MODEL,
            messages = [{
                "role":    "user",
                "content": user_message,
                "images":  images_b64,   # ← ollama accepts raw base64 list here
            }],
            options  = {"temperature": 0.0, "num_predict": 512},
        )
    else:
        # No images — fall back to text-only
        response = ollama.chat(
            model    = ESA_MODEL,
            messages = [{"role": "user", "content": user_message}],
            options  = {"temperature": 0.0, "num_predict": 512},
        )

    full_response = response["message"]

    return {
        "machine_id":  machine_id,
        "label":       label,
        "confidence":  confidence,
        "explanation": full_response,
        "qa_answer":   full_response if question else "",
    }


if __name__ == "__main__":
    # FastMCP v3 — use "streamable-http" for HTTP transport
    esa.run(transport="streamable-http", host="0.0.0.0", port=8002)