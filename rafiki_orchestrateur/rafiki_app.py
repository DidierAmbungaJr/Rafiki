"""Application locale Rafiki v1.

Lance une petite interface web pour discuter naturellement avec Rafiki.
Le navigateur fournit l'entree micro et la sortie vocale quand elles sont
disponibles; le serveur garde l'orchestration LLM + MCP.
"""

from __future__ import annotations

import asyncio
import re
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from rafiki_agent import RafikiConversationSession, direct_tool_call


BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"


class ChatRequest(BaseModel):
    message: str
    input_mode: str = "text"
    live_body: bool = True


class BodyFeedbackRequest(BaseModel):
    action: str
    text: str = ""


class AppState:
    session: Optional[RafikiConversationSession] = None
    lock: asyncio.Lock

    def __init__(self) -> None:
        self.lock = asyncio.Lock()


state = AppState()


@asynccontextmanager
async def lifespan(app: FastAPI):
    state.session = await RafikiConversationSession.create(verbose=False)
    yield


app = FastAPI(title="Rafiki Orchestrateur V1", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def get_session() -> RafikiConversationSession:
    if state.session is None:
        raise HTTPException(status_code=503, detail="Rafiki n'est pas encore pret.")
    return state.session


def sanitize_reply(text: str) -> str:
    """Nettoie la sortie utilisateur: pas d'emoji, pas de balises techniques."""
    text = re.sub(r"[\U0001F300-\U0001FAFF\U00002700-\U000027BF]+", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def short_body_text(text: str, limit: int = 18) -> str:
    cleaned = sanitize_reply(text)
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1].rstrip() + "."


async def trigger_body_feedback(
    session: RafikiConversationSession,
    action: str,
    text: str = "",
) -> Dict[str, Any]:
    """Envoie un feedback court au corps Wokwi sans bloquer la conversation si MQTT est absent."""
    try:
        if action == "listening":
            screen = await direct_tool_call(
                session.tools_by_name,
                "rafiki_screen_text",
                {"text": "Je t'ecoute", "expression": "thinking"},
            )
            gesture = await direct_tool_call(session.tools_by_name, "rafiki_gesture", {"gesture": "thinking", "repeat": 1})
            return {"status": "ok", "action": action, "screen": screen, "gesture": gesture}
        if action == "thinking":
            result = await direct_tool_call(session.tools_by_name, "rafiki_think", {"text": "Je reflechis..."})
            return {"status": "ok", "action": action, "body": result}
        if action == "speaking":
            result = await direct_tool_call(
                session.tools_by_name,
                "rafiki_screen_text",
                {"text": short_body_text(text), "expression": "happy"},
            )
            return {"status": "ok", "action": action, "body": result}
        if action == "neutral":
            result = await direct_tool_call(session.tools_by_name, "rafiki_gesture", {"gesture": "neutral", "repeat": 1})
            return {"status": "ok", "action": action, "body": result}
        return {"status": "ignored", "action": action}
    except Exception as exc:
        return {"status": "error", "action": action, "message": str(exc)}


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
async def health() -> Dict[str, Any]:
    return {"status": "ok", "app": "rafiki-v1"}


@app.post("/api/chat")
async def chat(payload: ChatRequest) -> Dict[str, Any]:
    session = get_session()
    async with state.lock:
        try:
            body_events = []
            if payload.live_body:
                body_events.append(await trigger_body_feedback(session, "thinking"))
            result = await session.ask(payload.message, input_mode=payload.input_mode)
            result["reply"] = sanitize_reply(result["reply"])
            if payload.live_body:
                body_events.append(await trigger_body_feedback(session, "speaking", result["reply"]))
            result["body_feedback"] = body_events
            return result
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/reset")
async def reset() -> Dict[str, Any]:
    session = get_session()
    async with state.lock:
        session.reset()
    return {"status": "ok", "message": "Conversation remise a zero."}


@app.get("/api/status")
async def status() -> Dict[str, Any]:
    session = get_session()
    systems = await direct_tool_call(session.tools_by_name, "rafiki_status")
    body = await direct_tool_call(session.tools_by_name, "rafiki_body_status")
    return {"status": "ok", "systems": systems, "body": body}


@app.post("/api/body-feedback")
async def body_feedback(payload: BodyFeedbackRequest) -> Dict[str, Any]:
    session = get_session()
    return await trigger_body_feedback(session, payload.action, payload.text)


@app.get("/api/profile")
async def profile() -> Dict[str, Any]:
    session = get_session()
    return await direct_tool_call(session.tools_by_name, "child_profile_get")


@app.get("/api/parent-report")
async def parent_report(limit: int = 6) -> Dict[str, Any]:
    session = get_session()
    return await direct_tool_call(session.tools_by_name, "parent_report_get", {"limit": limit})


def main() -> None:
    import uvicorn

    uvicorn.run("rafiki_app:app", host="127.0.0.1", port=7860, reload=False)


if __name__ == "__main__":
    main()
