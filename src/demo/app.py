import sys
import os
import requests
import uuid
import streamlit as st

st.set_page_config(page_title="Universal Utility Orchestrator", page_icon="UUO", layout="wide")

AZURE_FUNC_URL = os.getenv("ORCHESTRATOR_API_URL", "http://localhost:7071/api/orchestrator/run" )

def init_session() -> None:
    if "session_id" not in st.session_state:
        st.session_state["session_id"] = str(uuid.uuid4())
    if "messages" not in st.session_state:
        st.session_state["messages"] = [
            {"role": "assistant", "content": "Welcome. How can I help you today?"}
        ]
    if "traces" not in st.session_state:
        st.session_state["traces"] = []

def run_http_orchestrator(query: str, session_id: str) -> dict:
    payload = {
        "query": query,
        "session_id": session_id
    }
    
    response = requests.post(AZURE_FUNC_URL, json=payload, timeout=180)
    response.raise_for_status()
    
    return response.json()

def draw_sidebar():
    with st.sidebar:
        st.header("Orchestrator Telemetry")
        st.caption(f"Session ID: {st.session_state['session_id']}")
        st.caption(f"Connected to: `{AZURE_FUNC_URL}`")
        st.divider()
        
        if not st.session_state["traces"]:
            st.info("No traces yet. Submit a query to see the chain of thought.")
            return

        for idx, wrapper_trace in enumerate(reversed(st.session_state["traces"])):
             # serverless orchestrator wraps the inner trace in a "trace" key
            trace = wrapper_trace.get("trace", {})
            query_used = wrapper_trace.get("query", "Unknown query")
            
            with st.expander(f"Trace for Query: {query_used}", expanded=(idx == 0)):
                st.write("**Status:**", trace.get("status"))
                
                if trace.get("plan"):
                    st.write("**Execution Plan**")
                    st.json(trace["plan"])
                
                if trace.get("steps"):
                    st.write("**Agent Output Chain**")
                    for step_id, result in trace["steps"].items():
                        st.markdown(f"**Step ID**: `{step_id}` | **Agent**: `{result.get('agent', 'Unknown')}`")
                        if result.get("status") == "completed":
                            st.success(f"Output: {result.get('output')}")
                        else:
                            st.error(f"Error: {result.get('error')}")

def main():
    init_session()
    
    st.title("Universal Utility Orchestrator - Demo")
    
    draw_sidebar()
    
    # Render chat messages
    for msg in st.session_state["messages"]:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            
    if prompt := st.chat_input("Type your request (e.g. Can you check my anomaly detection alerts?)"):
        # Display user message securely
        st.session_state["messages"].append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)
            
        with st.chat_message("assistant"):
            with st.spinner("Orchestrator is forming a plan and executing agents via API..."):
                try:
                    result = run_http_orchestrator(prompt, st.session_state["session_id"])
                    
                    # Ensure query is stored so the sidebar accurately names it
                    if "query" not in result:
                        result["query"] = prompt
                        
                    st.session_state["traces"].append(result)
                    
                    final_answer = result.get("final_answer", "No answer found.")
                    
                    # Show status indicator for partial failures
                    orch_status = result.get("status")
                    if orch_status == "failed":
                        st.warning("⚠️ Some agent steps failed. Partial results shown below.")
                    elif orch_status == "blocked":
                        st.error("🚫 Request was blocked by guardrails.")
                    
                    st.markdown(final_answer)
                    st.session_state["messages"].append({"role": "assistant", "content": final_answer})
                except requests.exceptions.HTTPError as e:
                    # Try to extract the JSON body even from error responses
                    try:
                        error_body = e.response.json()
                        if "query" not in error_body:
                            error_body["query"] = prompt
                        st.session_state["traces"].append(error_body)
                        final_answer = error_body.get("final_answer", f"API error: {e.response.status_code}")
                        st.warning(f"⚠️ API returned {e.response.status_code}")
                        st.markdown(final_answer)
                        st.session_state["messages"].append({"role": "assistant", "content": final_answer})
                    except Exception:
                        error_msg = f"API error {e.response.status_code}: {e.response.text[:300]}"
                        st.error(error_msg)
                        st.session_state["messages"].append({"role": "assistant", "content": error_msg})
                except Exception as e:
                    error_msg = f"Failed to reach orchestrator: {str(e)}"
                    st.error(error_msg)
                    st.session_state["messages"].append({"role": "assistant", "content": error_msg})

if __name__ == "__main__":
    main()
