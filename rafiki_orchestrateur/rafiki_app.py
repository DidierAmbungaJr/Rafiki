"""Application locale Rafiki v1.

Lance une petite interface web pour discuter naturellement avec Rafiki.
Le navigateur fournit l'entree micro et la sortie vocale quand elles sont
disponibles; le serveur garde l'orchestration LLM + MCP.
"""

from __future__ import annotations

import asyncio
import base64
import os
import re
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from rafiki_agent import LMSTUDIO_BASE_URL, LMSTUDIO_MODEL, RafikiConversationSession, direct_tool_call


BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
VISION_UPLOAD_DIR = BASE_DIR / "runtime" / "vision_uploads"
APP_HOST = os.getenv("RAFIKI_APP_HOST", "127.0.0.1")
APP_PORT = int(os.getenv("RAFIKI_APP_PORT", "7860"))
APP_CORS_ORIGINS = [
    origin.strip()
    for origin in os.getenv("RAFIKI_APP_CORS_ORIGINS", "*").split(",")
    if origin.strip()
]


class ChatRequest(BaseModel):
    message: str
    input_mode: str = "text"
    live_body: bool = True
    force_llm: bool = False
    child_id: str = "default"
    parent_id: str = "default_parent"
    session_id: str = "default_session"
    child_profile: Dict[str, Any] = Field(default_factory=dict)
    parental_controls: Dict[str, Any] = Field(default_factory=dict)


class VisionRequest(BaseModel):
    prompt: str = "Que vois-tu ?"
    image_base64: str
    filename: str = "raspberry-camera.jpg"


class BodyStatusRequest(BaseModel):
    status: Dict[str, Any]


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
app.add_middleware(
    CORSMiddleware,
    allow_origins=APP_CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
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


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
async def health() -> Dict[str, Any]:
    return {
        "status": "ok",
        "app": "rafiki-v1",
        "lmstudio": {
            "base_url": LMSTUDIO_BASE_URL,
            "model": LMSTUDIO_MODEL,
        },
    }


@app.post("/api/chat")
async def chat(payload: ChatRequest) -> Dict[str, Any]:
    session = get_session()
    async with state.lock:
        previous_force_llm = session.force_llm
        try:
            if payload.force_llm:
                session.force_llm = True
            result = await session.ask(payload.message, input_mode=payload.input_mode)
            result["reply"] = sanitize_reply(result["reply"])
            result["body_feedback"] = []
            return result
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        finally:
            session.force_llm = previous_force_llm


@app.post("/api/reset")
async def reset() -> Dict[str, Any]:
    session = get_session()
    async with state.lock:
        result = session.start()
    return {"status": "ok", "message": "Conversation remise a zero.", **result}


@app.post("/api/start")
async def start() -> Dict[str, Any]:
    session = get_session()
    async with state.lock:
        return session.start()


@app.get("/api/status")
async def status() -> Dict[str, Any]:
    session = get_session()
    systems = await direct_tool_call(session.tools_by_name, "rafiki_status")
    return {"status": "ok", "systems": systems}


@app.get("/api/body/next")
async def body_next() -> Dict[str, Any]:
    session = get_session()
    return await direct_tool_call(session.tools_by_name, "body_command_next")


@app.get("/api/body/queue")
async def body_queue(limit: int = 10) -> Dict[str, Any]:
    session = get_session()
    return await direct_tool_call(session.tools_by_name, "body_command_peek", {"limit": limit})


@app.post("/api/body/status")
async def body_status(payload: BodyStatusRequest) -> Dict[str, Any]:
    session = get_session()
    return await direct_tool_call(
        session.tools_by_name,
        "body_status_update",
        {"status": payload.status},
    )


@app.post("/api/vision")
async def vision(payload: VisionRequest) -> Dict[str, Any]:
    session = get_session()
    VISION_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    suffix = Path(payload.filename).suffix.lower()
    if suffix not in {".jpg", ".jpeg", ".png", ".webp"}:
        suffix = ".jpg"
    image_path = VISION_UPLOAD_DIR / f"{uuid.uuid4().hex}{suffix}"
    try:
        image_path.write_bytes(base64.b64decode(payload.image_base64, validate=True))
        result = await direct_tool_call(
            session.tools_by_name,
            "vision_observe",
            {"prompt": payload.prompt, "image_path": str(image_path)},
        )
        return {"status": "ok", "vision": result}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


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

    uvicorn.run("rafiki_app:app", host=APP_HOST, port=APP_PORT, reload=False)


if __name__ == "__main__":
    main()
