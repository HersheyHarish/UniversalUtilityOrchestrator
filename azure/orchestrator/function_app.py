from __future__ import annotations

import asyncio
import json
import logging
import os
import traceback

import azure.functions as func

log = logging.getLogger(__name__)

# Catch import errors at startup so /api/health can report them
_IMPORT_ERROR: str | None = None
try:
    import chat_pipeline
    import dashboard_views
    import executor
    import memory
    import planner
    import runtime_contract
    import sse_events
    import synthesizer
    from trace_writer import TraceContext
    from models import ChatRequest, ProactiveTriggerRequest, StandardResponse, StandardResponse, SessionDoc, SessionStatus
except Exception as _e:
    _IMPORT_ERROR = f"{type(_e).__name__}: {_e}\n{traceback.format_exc()}"
    log.critical("Startup import failed: %s", _IMPORT_ERROR)


_AUTH_LEVEL_BY_NAME: dict[str, func.AuthLevel] = {
    "ANONYMOUS": func.AuthLevel.ANONYMOUS,
    "FUNCTION": func.AuthLevel.FUNCTION,
    "ADMIN": func.AuthLevel.ADMIN,
}

_default_level = "ANONYMOUS" if os.environ.get("USE_LOCAL_EMULATORS", "").lower() == "true" else "FUNCTION"
_configured_level = os.environ.get("ORCHESTRATOR_HTTP_AUTH_LEVEL", _default_level).upper()
_DEMO_STEPS_ENABLED = os.environ.get("ORCHESTRATOR_DEMO_STEPS", "").lower() == "true"
_STREAM_PROGRESS_ENABLED = os.environ.get("ORCHESTRATOR_STREAM_PROGRESS", "").lower() == "true"
_CHAT_STREAM_ENABLED = os.environ.get("ORCHESTRATOR_CHAT_STREAM_ENABLED", "").lower() == "true"

app = func.FunctionApp(http_auth_level=_AUTH_LEVEL_BY_NAME.get(_configured_level, func.AuthLevel.FUNCTION))

_CONFIG_ERRORS: list[str] = []
if not _IMPORT_ERROR:
    try:
        _CONFIG_ERRORS = runtime_contract.validate_runtime_contract()
        if _CONFIG_ERRORS:
            log.critical("Runtime contract validation failed: %s", "; ".join(_CONFIG_ERRORS))
    except Exception as _e:
        _CONFIG_ERRORS = [f"Runtime contract check failed: {_e}"]
        log.critical("Runtime contract validation raised: %s", _e)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _ok(body: dict, status: int = 200) -> func.HttpResponse:
    return func.HttpResponse(
        json.dumps(body, default=str),
        status_code=status,
        mimetype="application/json",
    )


def _err(msg: str, status: int = 400, detail: str | None = None) -> func.HttpResponse:
    payload: dict = {"error": msg}
    if detail:
        payload["detail"] = detail
    return func.HttpResponse(
        json.dumps(payload),
        status_code=status,
        mimetype="application/json",
    )


def _runtime_error_response() -> func.HttpResponse | None:
    if _IMPORT_ERROR:
        return _err("Worker failed to start", 503, _IMPORT_ERROR)
    if _CONFIG_ERRORS:
        return _err("Runtime configuration is invalid", 503, "; ".join(_CONFIG_ERRORS))
    return None


# ── GET /api/health  (ANONYMOUS — no key required) ───────────────────────────

@app.route(route="health", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
async def health(req: func.HttpRequest) -> func.HttpResponse:
    if _IMPORT_ERROR:
        return func.HttpResponse(
            json.dumps({"status": "unhealthy", "import_error": _IMPORT_ERROR}),
            status_code=503,
            mimetype="application/json",
        )

    if _CONFIG_ERRORS:
        return func.HttpResponse(
            json.dumps({"status": "misconfigured", "errors": _CONFIG_ERRORS}),
            status_code=503,
            mimetype="application/json",
        )

    return _ok(
        {
            "status": "ok",
            "service": "orchestrator",
            "build": {
                "version": os.environ.get("BUILD_VERSION", "dev"),
                "sha": os.environ.get("BUILD_SHA", "unknown"),
            },
        }
    )

# ── Common helpers ───────────────────────────

async def _safe_trace_finish(trace: TraceContext | None, error: str | None = None, final_response: str | None = None) -> None:
    if not trace:
        return

    try:
        await trace.finish(error=error, final_response=final_response)
    except Exception as e:
        pass

async def _handle_failure(session_id: str, trace: TraceContext | None, stage: str, message: str, error: Exception):
    log.exception("%s for session %s", message, session_id)

    if trace and _DEMO_STEPS_ENABLED:
        await trace.record_event(
            stage=stage,
            status="failed",
            message=message,
            metadata={"error": str(error)},
        )
    await memory.update_session(session_id, status=SessionStatus.FAILED)

    await _safe_trace_finish(
        trace,
        error=f"{message}: {error}",
    )

    return _err(message, 500, str(error))

async def _build_trace(session_id: str, message: str, customer_id: str, trigger_type: str, metadata: dict | None) -> TraceContext | None:
    try:
        return TraceContext(
            session_id=session_id,
            user_message=message,
            customer_id=customer_id,
            trigger_type=trigger_type,
            proactive_meta=metadata,
        )
    except Exception as e:
        log.error(
            "TraceContext creation failed (continuing without tracing): %s", e
        )
        return None

async def _create_or_load_session(session_id: str | None, message: str, customer_id: str) -> SessionDoc:
    if session_id:
        existing = await memory.get_session(session_id)

        if not existing:
            raise ValueError(f"Session '{session_id}' not found")

        return SessionDoc(**{
            k: v
            for k, v in existing.items()
            if k in SessionDoc.model_fields
        })

    return await memory.create_session(
        SessionDoc(
            user_message=message,
            customer_id=customer_id,
        )
    )

async def _process_request(message: str, customer_id: str, trigger_type: str, session_id: str | None = None, metadata: dict | None = None, save_message_fn = None):
    chat_history = []
    if session_id:
        try:
            chat_history = await memory.get_conversation_history(
                session_id=session_id,
                limit=10,
            )
            log.info(
                "chat: loaded %d history turns for session=%s",
                len(chat_history), session_id,
            )
        except Exception as exc:
            log.error("chat: failed to load history (non-fatal): %s", exc)
            chat_history = []
    
    try:
        session = await _create_or_load_session(
            session_id=session_id,
            message=message,
            customer_id=customer_id,
        )
    except ValueError as e:
        return _err(str(e), 404)

    except Exception as e:
        log.exception("Session init failed")
        return _err("Session creation failed", 500, str(e))

    session_id = session.id

    # Save incoming message
    if save_message_fn:
        try:
            await save_message_fn(session_id)
        except Exception as e:
            log.warning("Could not save message (non-fatal): %s", e)

    trace = await _build_trace(
        session_id=session_id,
        message=message,
        customer_id=customer_id,
        trigger_type=trigger_type,
        metadata=metadata,
    )

    # Planning

    if trace and _DEMO_STEPS_ENABLED and trigger_type == "reactive":
        await trace.record_event("request", "running", "Received user request.")

    try:
        plan = await planner.build_plan(
            message=message,
            customer_id=customer_id,
            trigger_type=trigger_type,
            chat_history=chat_history,
            args=metadata
        )

        await memory.save_plan(session_id, plan)

        log.info("Session %s: plan built — %d steps", session_id, len(plan.steps))

    except Exception as e:
        return await _handle_failure(
            session_id=session_id,
            trace=trace,
            stage="planning",
            message="Planning failed",
            error=e,
        )
    
    if trace:
        try:
            await trace.record_plan(plan)
        except Exception as e:
            log.error("trace.record_plan failed (non-fatal): %s", e)

    # Execution
    if trace and _DEMO_STEPS_ENABLED:
        await trace.record_event("execution", "running", "Starting execution of planned steps.")
    try:
        step_results = await executor.execute_plan(
            plan,
            session_id,
            customer_id,
            trace_ctx=trace,
        )

    except Exception as e:
        return await _handle_failure(
            session_id=session_id,
            trace=trace,
            stage="execution",
            message="Execution failed",
            error=e,
        )

    # Synthesis

    try:
        await memory.update_session(
            session_id,
            status=SessionStatus.SYNTHESIZING,
        )

        if trace and _DEMO_STEPS_ENABLED:
            await trace.record_event("synthesis", "running", "Synthesizing final answer.")

        final_response = await synthesizer.synthesize(
            plan,
            step_results,
            message,
            trigger_type=trigger_type,
            chat_history=chat_history,
            args=metadata
        )

        await memory.save_final_response(
            session_id,
            final_response,
        )
        if trace:
            try:
                await trace.finish(final_response=final_response)
            except Exception as e:
                log.warning("Trace finish failed for session %s: %s", session_id, e)

    except Exception as e:
        log.exception("Synthesis failed for session %s", session_id)
        return await _handle_failure(
            session_id=session_id,
            trace=trace,
            stage="synthesis",
            message="Synthesis failed",
            error=e,
        )

    return _ok(StandardResponse(
        session_id=session_id,
        response=final_response,
        plan_id=plan.plan_id,
        agents_used=[s.agent_name for s in plan.steps],
        steps_completed=len(step_results),
    ).model_dump())


# ── POST /api/chat ─────────────────────────────────────────────────────────────


@app.route(route="chat", methods=["POST"])
async def chat(req: func.HttpRequest) -> func.HttpResponse:
    runtime_err = _runtime_error_response()
    if runtime_err:
        return runtime_err

    try:
        body = req.get_json()
    except Exception as e:
        return _err(f"Could not parse JSON body: {e}")

    try:
        chat_req = ChatRequest(**body)
    except Exception as e:
        return _err(f"Invalid request shape: {e}")

<<<<<<< HEAD
    return await _process_request(
        message=chat_req.message,
        customer_id=chat_req.customer_id,
        trigger_type="reactive",
        session_id=chat_req.session_id,
        metadata=None,
        save_message_fn=lambda sid: memory.save_user_message(
            sid,
            chat_req.message,
        ),
    )

@app.route(route="proactive/trigger", methods=["POST"])
async def proactive_trigger(req: func.HttpRequest) -> func.HttpResponse:
    runtime_err = _runtime_error_response()
    if runtime_err:
        return runtime_err

    try:
        body = req.get_json()
        proactive_req = ProactiveTriggerRequest(**body)

    except Exception as e:
        return _err(f"Invalid request: {e}")

    metadata = {
        "source_agent_name": proactive_req.agent_name,
        "event_type": proactive_req.event_type,
        "context": proactive_req.context,
        "severity": proactive_req.severity,
    }

    return await _process_request(
        message=proactive_req.message,
        customer_id=proactive_req.customer_id,
        trigger_type="proactive",
        metadata=metadata,
        save_message_fn=lambda sid: memory.save_proactive_message(
            sid,
            proactive_req.message,
            metadata=metadata
        ),
=======
    try:
        result = await chat_pipeline.run_chat_pipeline(chat_req)
    except ValueError as e:
        return _err(str(e), 400)
    except LookupError as e:
        return _err(str(e), 404)
    except Exception as e:
        log.exception("Chat pipeline failed")
        return _err("Chat request failed", 500, str(e))

    return _ok(
        ChatResponse(
            session_id=result.session_id,
            response=result.response,
            plan_id=result.plan_id,
            agents_used=result.agents_used,
            steps_completed=result.steps_completed,
            content_segments=result.content_segments,
        ).model_dump()
>>>>>>> 5efa666 (feat(orchestrator): v1.2 streaming, parallel execution, and Foundry OpenAI fix)
    )


@app.route(route="chat/stream", methods=["POST"])
async def chat_stream(req: func.HttpRequest) -> func.HttpResponse:
    runtime_err = _runtime_error_response()
    if runtime_err:
        return runtime_err

    if not _CHAT_STREAM_ENABLED:
        return _err(
            "Streaming chat is disabled. Use POST /api/chat instead.",
            404,
        )

    try:
        body = req.get_json()
    except Exception as e:
        return _err(f"Could not parse JSON body: {e}")

    try:
        chat_req = ChatRequest(**body)
    except Exception as e:
        return _err(f"Invalid request shape: {e}")

    # Azure Functions Python HttpResponse does not accept async generators; buffer SSE chunks.
    chunks: list[str] = []

    async def on_event(event: str, data: dict) -> None:
        chunks.append(sse_events.format_sse(event, data))

    try:
        result = await chat_pipeline.run_chat_pipeline(
            chat_req,
            on_event=on_event,
            stream_tokens=True,
        )
        chunks.append(
            sse_events.format_sse(
                "done",
                {
                    "session_id": result.session_id,
                    "response": result.response,
                    "plan_id": result.plan_id,
                    "agents_used": result.agents_used,
                    "steps_completed": result.steps_completed,
                    "content_segments": result.content_segments,
                },
            )
        )
    except ValueError as e:
        chunks.append(sse_events.format_sse("error", {"error": str(e), "status": 400}))
    except LookupError as e:
        chunks.append(sse_events.format_sse("error", {"error": str(e), "status": 404}))
    except Exception as e:
        log.exception("Streaming chat pipeline failed")
        chunks.append(
            sse_events.format_sse(
                "error",
                {"error": "Chat request failed", "detail": str(e)},
            )
        )

    return func.HttpResponse(
        body="".join(chunks),
        status_code=200,
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ── GET /api/sessions/{session_id} ────────────────────────────────────────────


@app.route(route="sessions/{session_id}", methods=["GET"])
async def get_session(req: func.HttpRequest) -> func.HttpResponse:
    runtime_err = _runtime_error_response()
    if runtime_err:
        return runtime_err

    session_id = req.route_params.get("session_id")
    try:
        session = await memory.get_session(session_id)
        if not session:
            return _err("Session not found", 404)
        messages = await memory.get_step_results(session_id)
        transcript = await memory.get_session_transcript(session_id)
        payload = {
            "session": session,
            "step_results": messages,
            "transcript": transcript,
        }
        if _DEMO_STEPS_ENABLED or _STREAM_PROGRESS_ENABLED:
            payload["demo_events"] = await trace_writer.get_demo_events(session_id)
        return _ok(payload)
    except Exception as e:
        log.exception("get_session failed for %s", session_id)
        return _err(str(e), 500)


# ── GET /api/users/{customer_id}/sessions ─────────────────────────────────────

@app.route(route="users/{customer_id}/sessions", methods=["GET"])
async def get_user_sessions(req: func.HttpRequest) -> func.HttpResponse:
    runtime_err = _runtime_error_response()
    if runtime_err:
        return runtime_err

    customer_id = req.route_params.get("customer_id")
    if not customer_id:
        return _err("customer_id is required", 400)

    try:
        sessions = await memory.get_sessions_by_customer(customer_id)
        # Sort manually just in case cosmos _ts indexing is weird, but query does it too
        return _ok({"sessions": sessions})
    except Exception as e:
        log.exception("get_user_sessions failed for customer %s", customer_id)
        return _err(str(e), 500)


@app.route(route="insights", methods=["GET"])
async def get_insights(req: func.HttpRequest) -> func.HttpResponse:
    runtime_err = _runtime_error_response()
    if runtime_err:
        return runtime_err
    customer_id = req.params.get("customer_id")
    if not customer_id:
        return _err("customer_id is required", 400)
    try:
        since_hours = int(req.params.get("since_hours", "24"))
    except Exception:
        return _err("since_hours must be an integer", 400)
    try:
        insights = await dashboard_views.build_insights(customer_id=customer_id, since_hours=since_hours)
        return _ok({"customer_id": customer_id, "insights": insights})
    except Exception as e:
        log.exception("get_insights failed for customer %s", customer_id)
        return _err("Failed to build insights", 500, str(e))


@app.route(route="copilot/context", methods=["GET"])
async def get_copilot_context(req: func.HttpRequest) -> func.HttpResponse:
    runtime_err = _runtime_error_response()
    if runtime_err:
        return runtime_err
    customer_id = req.params.get("customer_id")
    date = req.params.get("date")
    if not customer_id:
        return _err("customer_id is required", 400)
    if not date:
        return _err("date is required", 400)
    try:
        context = await dashboard_views.build_copilot_context(customer_id=customer_id, date=date)
        return _ok({"customer_id": customer_id, "date": date, "context": context})
    except Exception as e:
        log.exception("get_copilot_context failed for customer %s", customer_id)
        return _err("Failed to build copilot context", 500, str(e))


@app.route(route="alerts", methods=["GET"])
async def get_alerts(req: func.HttpRequest) -> func.HttpResponse:
    runtime_err = _runtime_error_response()
    if runtime_err:
        return runtime_err
    customer_id = req.params.get("customer_id")
    status = (req.params.get("status") or "all").strip().lower()
    if not customer_id:
        return _err("customer_id is required", 400)
    if status not in {"all", "unread", "acked"}:
        return _err("status must be one of: all, unread, acked", 400)
    try:
        alerts = await dashboard_views.build_alerts(customer_id=customer_id, status=status)
        return _ok({"customer_id": customer_id, "status": status, "alerts": alerts})
    except Exception as e:
        log.exception("get_alerts failed for customer %s", customer_id)
        return _err("Failed to build alerts", 500, str(e))


@app.route(route="alerts/{alert_id}/ack", methods=["POST"])
async def ack_alert(req: func.HttpRequest) -> func.HttpResponse:
    runtime_err = _runtime_error_response()
    if runtime_err:
        return runtime_err
    alert_id = req.route_params.get("alert_id")
    if not alert_id:
        return _err("alert_id is required", 400)
    try:
        body = req.get_json()
    except Exception:
        body = {}
    action = (body.get("action") or "ack").strip().lower()
    customer_id = body.get("customer_id")
    if not customer_id:
        return _err("customer_id is required", 400)
    try:
        ack = await dashboard_views.acknowledge_alert(alert_id=alert_id, action=action, customer_id=customer_id)
        return _ok(ack)
    except ValueError as e:
        return _err(str(e), 404)
    except Exception as e:
        log.exception("ack_alert failed for alert %s", alert_id)
        return _err("Failed to acknowledge alert", 500, str(e))


@app.route(route="agents", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
async def list_agents(req: func.HttpRequest) -> func.HttpResponse:
    """Return the list of active agents for the demo UI."""
    runtime_err = _runtime_error_response()
    if runtime_err:
        return runtime_err
    try:
        agents = await memory.get_active_agents()
        simplified = [
            {
                "name": a.get("name", "Unknown"),
                "description": a.get("description", ""),
                "status": a.get("status", "active"),
            }
            for a in agents
        ]
        return _ok({"agents": simplified, "count": len(simplified)})
    except Exception as e:
        log.exception("list_agents failed")
        return _err("Failed to load agents", 500, str(e))


@app.route(route="email_agent", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
async def email_agent(req: func.HttpRequest) -> func.HttpResponse:
    """Mock Email Notification Agent API endpoint."""
    try:
        body = req.get_json()
    except Exception as e:
        return _err(f"Could not parse JSON body: {e}")

    customer_id = body.get("customer_id") or "CUST-1001"
    context = body.get("context") or {}
    dep_outputs = context.get("dependency_outputs") or {}

    from datetime import datetime, timezone
    
    # Look for outage and weather summaries in dependent outputs
    outage_details = "An active service disruption is affecting your neighborhood."
    weather_details = "Please monitor local weather advisories."

    for k, v in dep_outputs.items():
        val_str = str(v)
        if "outage" in k.lower() or "disruption" in k.lower():
            outage_details = val_str
        elif "weather" in k.lower() or "temp" in k.lower():
            weather_details = val_str

    subject = "⚠️ NexusGas Service Alert: Outage Detected & Action Plan"
    email_body = (
        f"Dear customer {customer_id},\n\n"
        f"We have detected a service outage affecting your service area. "
        "Here are the active details and your customized action plan:\n\n"
        f"🔌 OUTAGE STATUS DETAILS:\n{outage_details}\n\n"
        f"🌡️ LOCAL WEATHER CONTEXT:\n{weather_details}\n\n"
        "📋 SAFETY & PREPAREDNESS TIPS:\n"
        "• Keep refrigerator and freezer doors closed as much as possible.\n"
        "• Turn off or disconnect major appliances to prevent surge damage when power is restored.\n"
        "• Avoid downed utility lines and report any hazards immediately.\n\n"
        "Our operations crew has been dispatched to coordinate repairs. We appreciate your patience.\n\n"
        "NexusGas Utility Support Operations"
    )

    response_payload = {
        "agent": "email_notification_agent",
        "status": "completed",
        "result": f"Notification email successfully dispatched to customer {customer_id}.",
        "recipient": "james.doe@example.com" if customer_id == "CUST-1001" else "customer@example.com",
        "subject": subject,
        "body": email_body,
        "sent_at": datetime.now(timezone.utc).isoformat()
    }
    return _ok(response_payload)


@app.route(route="simulate-outage", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
async def simulate_outage(req: func.HttpRequest) -> func.HttpResponse:
    """Trigger an outage simulation: update dataset and execute orchestrator chat pipeline."""
    runtime_err = _runtime_error_response()
    if runtime_err:
        return runtime_err

    try:
        body = req.get_json()
    except Exception:
        body = {}

    customer_id = body.get("customer_id") or "CUST-1001"

    # Step 1: Write an active simulated outage to the JSON dataset
    try:
        from datetime import datetime, timedelta, timezone
        base_dir = os.path.dirname(os.path.abspath(__file__))
        outage_path = os.environ.get("OUTAGE_INPUT_FILE")
        
        if not outage_path:
            curr = base_dir
            for _ in range(5):
                candidate = os.path.join(curr, "src", "data", "demo_outages.json")
                if os.path.exists(candidate):
                    outage_path = candidate
                    break
                curr = os.path.dirname(curr)
        
        if not outage_path:
            outage_path = "/Users/harishsundarakumar/Documents/UniversalUtilityOrchestrator/UniversalUtilityAgent/src/data/demo_outages.json"

        if os.path.exists(outage_path):
            with open(outage_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            # Simulated central time zone (Austin -5:00)
            now_tz = datetime.now(timezone(timedelta(hours=-5)))
            start_str = now_tz.isoformat()
            end_str = (now_tz + timedelta(hours=4)).isoformat()
            
            simulated_event = {
                "outage_id": f"OUT-SIMULATED-{int(datetime.now().timestamp())}",
                "event_start": start_str,
                "event_end": end_str,
                "duration_minutes": 240,
                "cause": "severe_weather",
                "scope": "regional",
                "estimated_customers_affected": 15000,
                "source": "simulation"
            }
            
            if "outages" not in data:
                data["outages"] = {}
            if "78712" not in data["outages"]:
                data["outages"]["78712"] = []
                
            # Keep the dataset clean: filter out older simulated outages
            data["outages"]["78712"] = [
                evt for evt in data["outages"]["78712"] 
                if not str(evt.get("outage_id")).startswith("OUT-SIMULATED-")
            ]
            data["outages"]["78712"].append(simulated_event)
            
            with open(outage_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
                
            log.info("Simulated outage written to dataset successfully.")
    except Exception as e:
        log.exception("Simulation dataset update failed: %s", e)

    # Step 2: Invoke the orchestrator
    try:
        from models import ChatRequest
        prompt = (
            f"An active outage alert was triggered for customer {customer_id}. "
            "First, check if there is an active outage via the outage detection agent. "
            "Second, retrieve active weather contexts for the area. "
            "Third, call the email notification agent to send an outage safety alert email."
        )
        chat_req = ChatRequest(
            message=prompt,
            customer_id=customer_id,
            session_id=None
        )
        result = await chat_pipeline.run_chat_pipeline(chat_req)
        
        return _ok({
            "status": "completed",
            "session_id": result.session_id,
            "response": result.response,
            "plan_id": result.plan_id,
            "agents_used": result.agents_used,
            "steps_completed": result.steps_completed,
            "content_segments": result.content_segments,
        })
    except Exception as e:
        log.exception("Orchestrator pipeline failed inside simulation trigger: %s", e)
        return _err("Simulation pipeline failed", 500, str(e))

