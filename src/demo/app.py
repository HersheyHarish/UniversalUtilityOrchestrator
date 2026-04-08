import sys
import os
import requests
import uuid
import streamlit as st
import json

st.set_page_config(page_title="Universal Utility Orchestrator", page_icon="⚡", layout="wide")

AZURE_FUNC_URL = os.getenv("ORCHESTRATOR_API_URL", "http://localhost:7071/api/orchestrator/run" )

# Setup custom CSS for a premium look
st.markdown("""
<style>
    /* Sleek container for the chain of thought */
    .cot-container {
        background: #1E1E1E;
        border: 1px solid #333;
        border-radius: 8px;
        padding: 1rem;
        margin: 1rem 0;
        font-family: 'Inter', sans-serif;
    }
    .cot-header {
        font-size: 1.1rem;
        font-weight: 600;
        color: #E2E8F0;
        margin-bottom: 0.5rem;
        display: flex;
        align-items: center;
        gap: 0.5rem;
    }
    .cot-step {
        background: #2D3748;
        border-left: 4px solid #4299E1;
        padding: 0.75rem;
        margin: 0.5rem 0;
        border-radius: 0 4px 4px 0;
    }
    .cot-step-failed {
        border-left-color: #E53E3E;
    }
    .cot-eval {
        background: #276749;
        color: white;
        padding: 0.75rem;
        border-radius: 4px;
        margin-top: 1rem;
    }
    .agent-tag {
        background: #4A5568;
        padding: 0.2rem 0.5rem;
        border-radius: 4px;
        font-size: 0.8rem;
        font-family: monospace;
    }
</style>
""", unsafe_allow_html=True)

def init_session() -> None:
    if "session_id" not in st.session_state:
        st.session_state["session_id"] = str(uuid.uuid4())
    if "messages" not in st.session_state:
        st.session_state["messages"] = [
            {"role": "assistant", "content": "Welcome. How can I help you today?", "trace": None}
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

def render_inline_trace(trace_wrapper: dict):
    """Renders the detailed orchestrator thought process inline recursively"""
    trace = trace_wrapper.get("trace", {})
    if not trace:
        return
        
    plan = trace.get("plan", {})
    steps = trace.get("steps", {})
    eval_blob = trace.get("evaluation")
    tokens = trace.get("tokens", 0)
    
    with st.expander("🧠 View Orchestrator Chain of Thought", expanded=False):
        st.markdown(f"**Goal**: {plan.get('goal', 'Unknown')}")
        if tokens > 0:
            st.caption(f"Estimated Tokens: {tokens}")
            
        # Draw steps
        for step in plan.get("steps", []):
            step_id = step.get("id")
            result = steps.get(step_id, {})
            status = result.get("status", "pending")
            agent = result.get("agent", step.get("preferred_agent", "Auto-selected"))
            
            icon = "✅" if status == "completed" else "❌" if status == "failed" else "⏳"
            
            st.markdown(f"#### {icon} Step: `{step_id}`")
            st.markdown(f"**Objective**: {step.get('objective')}")
            st.markdown(f"**Agent Routed**: <span class='agent-tag'>{agent}</span>", unsafe_allow_html=True)
            
            if status == "completed":
                # Pretty print JSON if possible
                out_raw = result.get("output", "")
                try:
                    if isinstance(out_raw, str):
                        out_json = json.loads(out_raw)
                        st.json(out_json)
                    else:
                        st.json(out_raw)
                except:
                    st.success(str(out_raw))
            elif status == "failed":
                st.error(result.get("error", "Unknown error"))
            
            st.divider()
            
        # Draw Evaluation
        if eval_blob:
            st.markdown("#### 🎯 Execution Evaluation")
            col1, col2, col3 = st.columns(3)
            col1.metric("Goal Met", "Yes" if eval_blob.get("goal_met") else "No")
            col2.metric("Score", f"{eval_blob.get('score', 0):.2f}")
            col3.metric("Retry Advised", "Yes" if eval_blob.get("retry_recommended") else "No")
            st.info(f"**Summary**: {eval_blob.get('summary', '')}")
            if eval_blob.get('issues'):
                num_issues = len(eval_blob.get('issues'))
                st.warning(f"Issues Detected ({num_issues}): {', '.join(eval_blob.get('issues'))}")

def draw_sidebar():
    with st.sidebar:
        st.header("⚡ System Telemetry")
        st.caption(f"Session ID: `{st.session_state['session_id'][:8]}...`")
        st.caption(f"Connected to: `{AZURE_FUNC_URL}`")
        if st.button("🔄 Reset Session"):
            st.session_state["session_id"] = str(uuid.uuid4())
            st.session_state["messages"] = [
                 {"role": "assistant", "content": "Session reset. How can I help you?", "trace": None}
            ]
            st.session_state["traces"] = []
            st.rerun()
            
        st.divider()
        
        # We can read agents.json to show active agents, but for a real stateless UI, 
        # we'd normally call a /registry endpoint. Since we share a filesystem here, we can cheat for the POC:
        try:
            repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            registry_path = os.path.join(repo_root, "src", "core", "agents.json")
            with open(registry_path, "r") as f:
                registry_data = json.load(f)
                agents = registry_data.get("agents", [])
                
            with st.expander(f"🔌 Registered Agents ({len(agents)})", expanded=True):
                for a in agents:
                    st.markdown(f"- **{a.get('name')}**: {a.get('description')[:60]}...")
        except Exception:
            st.caption("Agent registry file not found locally.")

        st.divider()
        st.subheader("Trace History")
        if not st.session_state["traces"]:
            st.info("No traces yet.")
            return

        for idx, wrapper_trace in enumerate(reversed(st.session_state["traces"])):
            trace = wrapper_trace.get("trace", {})
            query_used = wrapper_trace.get("query", "Unknown query")
            
            with st.expander(f"Q: {query_used[:30]}...", expanded=False):
                st.write("**Status:**", trace.get("status"))
                if trace.get("tokens"):
                    st.write(f"**Tokens**: {trace.get('tokens')}")
                if trace.get("evaluation"):
                    score = trace["evaluation"].get("score", 0)
                    st.write(f"**Eval Score**: {score:.2f}")

def main():
    init_session()
    
    st.title("Universal Utility Orchestrator")
    st.markdown("Multi-agent system powering billing, anomalies, and operations.")
    
    draw_sidebar()
    
    # Render chat messages
    for msg in st.session_state["messages"]:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            if msg.get("trace"):
                 render_inline_trace(msg["trace"])
            
    if prompt := st.chat_input("Type your request..."):
        # Display user message securely
        st.session_state["messages"].append({"role": "user", "content": prompt, "trace": None})
        with st.chat_message("user"):
            st.markdown(prompt)
            
        with st.chat_message("assistant"):
            with st.spinner("Orchestrator working..."):
                try:
                    result = run_http_orchestrator(prompt, st.session_state["session_id"])
                    
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
                    render_inline_trace(result)
                    
                    st.session_state["messages"].append({
                        "role": "assistant", 
                        "content": final_answer,
                        "trace": result
                    })
                except requests.exceptions.HTTPError as e:
                    try:
                        error_body = e.response.json()
                        if "query" not in error_body:
                            error_body["query"] = prompt
                        st.session_state["traces"].append(error_body)
                        final_answer = error_body.get("final_answer", f"API error: {e.response.status_code}")
                        st.warning(f"⚠️ API returned {e.response.status_code}")
                        st.markdown(final_answer)
                        render_inline_trace(error_body)
                        st.session_state["messages"].append({
                            "role": "assistant", 
                            "content": final_answer,
                            "trace": error_body
                        })
                    except Exception:
                        error_msg = f"API error {e.response.status_code}: {e.response.text[:300]}"
                        st.error(error_msg)
                        st.session_state["messages"].append({"role": "assistant", "content": error_msg, "trace": None})
                except Exception as e:
                    error_msg = f"Failed to reach orchestrator: {str(e)}"
                    st.error(error_msg)
                    st.session_state["messages"].append({"role": "assistant", "content": error_msg, "trace": None})

if __name__ == "__main__":
    main()
