from __future__ import annotations

import logging
from typing import Any, Optional
import os
from fastapi import FastAPI, HTTPException
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_ollama import ChatOllama
from pydantic import BaseModel

logger = logging.getLogger(__name__)

app = FastAPI(title="Conversation Summary Agent")

class SummaryRequest(BaseModel):
    query: str = "Summarize the context."
    context: Optional[dict[str, Any]] = None

@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "agent": "conversation_summary_agent"}

@app.post("/api/conversation_summary_agent")
def handle_summary(request: SummaryRequest) -> dict[str, Any]:
    context = request.context or {}
    
    # If orchestrator passes dependency outputs or all step results inline
    all_steps = context.get("all_step_results", {})
    history = context.get("history", [])
    
    if not all_steps and not history:
        return {
            "agent": "conversation_summary_agent",
            "status": "completed",
            "output": "There is no previous conversation or active execution step history to summarize."
        }

    try:
        model_name = "llama3.1:8b"
        ollama_base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        
        system_prompt = (
            "You are a conversation summarization agent. "
            "Write a concise, bulleted wrap-up of the user's previous steps and the results that the orchestrator generated. "
            "Focus only on facts, metrics, and actionable intelligence extracted from the other agents."
        )
        
        user_prompt = (
            f"User Goal: {request.query}\n\n"
            f"Context Extracted:\n{all_steps}\n\n"
            f"Please generate a summary."
        )
        
        llm = ChatOllama(
            model=model_name,
            temperature=0.2,
            base_url=ollama_base_url,
            timeout=60,
        )
        response = llm.invoke([SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)])
        summary_text = response.content.strip() if isinstance(response.content, str) else str(response.content)
        
        return {
            "agent": "conversation_summary_agent",
            "status": "completed",
            "output": summary_text
        }
    except Exception as exc:
        logger.error(f"Summarizer LLM failed: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))
