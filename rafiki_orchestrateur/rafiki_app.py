"""Application locale Rafiki v1.

Lance une petite interface web pour discuter naturellement avec Rafiki.
Le navigateur fournit l'entree micro et la sortie vocale quand elles sont
disponibles; le serveur garde l'orchestration LLM + MCP.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from rafiki_agent import (
    LMSTUDIO_BASE_URL,
    LMSTUDIO_MODEL,
    RafikiConversationSession,
    clean_agent_response,
    direct_tool_call,
)


logger = logging.getLogger("rafiki.app")
BASE_DIR = Path(__file__).resolve().parent

import sys
REPO_ROOT = BASE_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

STATIC_DIR = BASE_DIR / "static"
VISION_UPLOAD_DIR = BASE_DIR / "runtime" / "vision_uploads"
# Le serveur est le point d'entree du reseau local: la Raspberry doit pouvoir
# l'atteindre sans qu'une option oubliee le limite a localhost.
APP_HOST = os.getenv("RAFIKI_APP_HOST", "0.0.0.0")
APP_PORT = int(os.getenv("RAFIKI_APP_PORT", "7860"))
APP_CORS_ORIGINS = [
    origin.strip()
    for origin in os.getenv("RAFIKI_APP_CORS_ORIGINS", "*").split(",")
    if origin.strip()
]
SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
VISION_CAPTURE_TIMEOUT_SECONDS = max(
    1.0, float(os.getenv("RAFIKI_VISION_CAPTURE_TIMEOUT_SECONDS", "8"))
)
VISION_MAX_BYTES = max(1024, int(os.getenv("RAFIKI_VISION_MAX_BYTES", str(8 * 1024 * 1024))))


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


class BodyCommandRequest(BaseModel):
    action: str
    params: Dict[str, Any] = Field(default_factory=dict)


class VisionRegisterRequest(BaseModel):
    vision_url: str


class VisionFrameUpload(BaseModel):
    image_base64: str
    width: Optional[int] = None
    height: Optional[int] = None
    camera_type: str = "ov5647"


class AppState:
    sessions: Dict[str, RafikiConversationSession]
    lock: asyncio.Lock
    sessions_lock: asyncio.Lock

    def __init__(self) -> None:
        self.sessions = {}
        self.lock = asyncio.Lock()
        self.sessions_lock = asyncio.Lock()
        self.vision_url: Optional[str] = None
        self.latest_vision_frame: Optional[Dict[str, Any]] = None
        self.latest_vision_status: Dict[str, Any] = {
            "registered_url": None,
            "connected": False,
            "last_capture_timestamp": None,
            "last_error": None,
        }
        self.load_vision_state()

    def save_vision_state(self) -> None:
        try:
            state_file = BASE_DIR / "runtime" / "vision_state.json"
            state_file.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "vision_url": self.vision_url,
                "latest_vision_status": self.latest_vision_status,
            }
            state_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception as exc:
            logger.warning("Impossible de sauvegarder l'etat de la vision : %s", exc)

    def load_vision_state(self) -> None:
        try:
            state_file = BASE_DIR / "runtime" / "vision_state.json"
            if state_file.exists():
                data = json.loads(state_file.read_text(encoding="utf-8"))
                self.vision_url = data.get("vision_url")
                if "latest_vision_status" in data:
                    self.latest_vision_status.update(data["latest_vision_status"])
                logger.info("Etat de la vision restaure : %s", self.vision_url)
        except Exception as exc:
            logger.warning("Impossible de restaurer l'etat de la vision : %s", exc)


state = AppState()


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        from shared.discovery import start_udp_discovery_responder
        start_udp_discovery_responder(APP_PORT)
    except Exception as exc:
        logger.warning("Impossible de lancer le repondeur UDP de decouverte : %s", exc)

    state.sessions["default_session"] = await RafikiConversationSession.create(verbose=False)
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


def validate_session_id(session_id: str) -> str:
    normalized = str(session_id or "default_session").strip()
    if not SESSION_ID_PATTERN.fullmatch(normalized):
        raise HTTPException(status_code=422, detail="session_id invalide.")
    return normalized


async def get_session(
    session_id: str = "default_session", child_id: Optional[str] = None
) -> RafikiConversationSession:
    normalized_session_id = validate_session_id(session_id)
    normalized_child_id = str(child_id or "default").strip() or "default"
    async with state.sessions_lock:
        session = state.sessions.get(normalized_session_id)
        if session is None:
            session = await RafikiConversationSession.create(
                verbose=False,
                child_id=normalized_child_id,
            )
            state.sessions[normalized_session_id] = session
        elif child_id is not None:
            session.bind_child(normalized_child_id)
    return session


def sanitize_reply(text: str) -> str:
    """Nettoie la sortie utilisateur: pas d'emoji, pas de balises techniques."""
    text = clean_agent_response(text)
    text = re.sub(r"[\U0001F000-\U0001FAFF\U00002600-\U000027BF]+", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _normalise_image_base64(value: str) -> tuple[str, bytes]:
    """Accepte le Base64 brut ou une data URI retournee par le service camera."""
    encoded = str(value or "").strip()
    if encoded.startswith("data:"):
        _, separator, encoded = encoded.partition(",")
        if not separator:
            raise ValueError("data URI image invalide")
    encoded = "".join(encoded.split())
    if not encoded:
        raise ValueError("image_base64 est vide")
    try:
        image_bytes = base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError) as exc:
        raise ValueError("image_base64 invalide") from exc
    if not image_bytes:
        raise ValueError("image_base64 est vide")
    return base64.b64encode(image_bytes).decode("ascii"), image_bytes


def _remember_vision_frame(
    image_base64: str,
    *,
    width: Optional[int] = None,
    height: Optional[int] = None,
    camera_type: str = "ov5647",
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    timestamp = time.time()
    frame: Dict[str, Any] = {
        "timestamp": timestamp,
        "image_base64": image_base64,
        "width": width,
        "height": height,
        "camera_type": camera_type or "ov5647",
    }
    if metadata:
        frame["metadata"] = metadata
    state.latest_vision_frame = frame
    state.latest_vision_status.update(
        {
            "connected": True,
            "last_capture_timestamp": timestamp,
            "last_error": None,
        }
    )
    state.save_vision_state()
    try:
        VISION_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        _, image_bytes = _normalise_image_base64(image_base64)
        (VISION_UPLOAD_DIR / "latest_frame.jpg").write_bytes(image_bytes)
    except Exception as exc:
        logger.warning("Impossible d'ecrire latest_frame.jpg: %s", exc)
    return frame


def _normalise_vision_url(value: str) -> str:
    vision_url = str(value or "").strip().rstrip("/")
    parsed = urlparse(vision_url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        raise ValueError("vision_url doit etre une URL HTTP(S) valide, sans identifiants.")
    return vision_url


def _capture_from_raspberry(
    vision_url: str, width: int, height: int, quality: int
) -> tuple[Dict[str, Any], str]:
    """Capture une image de la caméra Raspberry Pi avec support JSON et binaire JPEG direct."""
    clean_url = vision_url.rstrip("/")
    query = urlencode({"width": width, "height": height, "quality": quality})

    # Essai 1 : Endpoint JSON (/capture/json)
    for attempt in range(2):
        try:
            capture_json_url = f"{clean_url}/capture/json?{query}"
            request = Request(capture_json_url, headers={"Accept": "application/json", "User-Agent": "RafikiBrain"})
            with urlopen(request, timeout=VISION_CAPTURE_TIMEOUT_SECONDS) as response:
                raw_payload = response.read(VISION_MAX_BYTES + 1)
            if len(raw_payload) <= VISION_MAX_BYTES:
                payload = json.loads(raw_payload.decode("utf-8"))
                if isinstance(payload, dict):
                    image_value = payload.get("data_uri") or payload.get("image_base64")
                    if image_value:
                        encoded, _ = _normalise_image_base64(str(image_value))
                        return payload, encoded
        except Exception:
            pass

        # Essai 2 : Endpoint JPEG binaire direct (/capture ou /snapshot)
        for ep in ["/capture", "/snapshot", "/api/vision/capture"]:
            try:
                capture_bin_url = f"{clean_url}{ep}"
                request = Request(capture_bin_url, headers={"Accept": "image/jpeg, */*", "User-Agent": "RafikiBrain"})
                with urlopen(request, timeout=VISION_CAPTURE_TIMEOUT_SECONDS) as response:
                    raw_bytes = response.read(VISION_MAX_BYTES + 1)
                if raw_bytes and len(raw_bytes) <= VISION_MAX_BYTES and len(raw_bytes) > 500:
                    encoded = base64.b64encode(raw_bytes).decode("ascii")
                    payload = {
                        "status": "ok",
                        "image_base64": encoded,
                        "data_uri": f"data:image/jpeg;base64,{encoded}",
                        "timestamp": time.time(),
                        "width": width,
                        "height": height,
                    }
                    return payload, encoded
            except Exception:
                pass

        time.sleep(0.3)

    raise RuntimeError(f"Caméra Raspberry inaccessible sur {clean_url} (tentatives épuisées).")


async def _bridge_snapshot(session_id: str = "default_session") -> Dict[str, Any]:
    session = await get_session(session_id)
    systems = await direct_tool_call(session.tools_by_name, "rafiki_status")
    body = systems.get("body", {}) if isinstance(systems, dict) else {}
    body = dict(body) if isinstance(body, dict) else {}
    body.setdefault("online", bool(body.get("connected")))
    body.setdefault("queue_length", body.get("queue_size", 0))
    vision = {
        "registered_url": state.vision_url,
        "latest_frame_time": (
            state.latest_vision_frame.get("timestamp") if state.latest_vision_frame else None
        ),
        "status": dict(state.latest_vision_status),
    }
    return {"body": body, "vision": vision}


async def apply_child_profile_context(
    session: RafikiConversationSession, profile_input: Dict[str, Any]
) -> None:
    """Mémorise le profil envoyé par le mobile sans écraser les champs absents."""
    if not profile_input:
        return

    name = str(profile_input.get("name") or "").strip()
    if name:
        session.session_state["child_name"] = name

    if "child_profile_update" not in session.tools_by_name:
        return

    supplied_fields = {"name", "age", "language", "interests", "level"}
    if not any(field in profile_input for field in supplied_fields):
        return

    stored = await direct_tool_call(
        session.tools_by_name,
        "child_profile_get",
        {"child_id": session.child_id},
    )
    stored_profile = stored.get("profile", {}) if isinstance(stored, dict) else {}

    age = profile_input.get("age", stored_profile.get("age", 7))
    try:
        age = int(age)
    except (TypeError, ValueError):
        age = int(stored_profile.get("age", 7))

    interests = profile_input.get("interests", stored_profile.get("interests", []))
    if not isinstance(interests, list):
        interests = stored_profile.get("interests", [])
    interests = [str(item).strip() for item in interests if str(item).strip()][:12]

    profile = {
        "child_id": session.child_id,
        "name": name or str(stored_profile.get("name") or "enfant"),
        "age": age,
        "language": str(profile_input.get("language") or stored_profile.get("language") or "français simple"),
        "interests": interests,
        "level": str(profile_input.get("level") or stored_profile.get("level") or "débutant"),
    }
    result = await direct_tool_call(session.tools_by_name, "child_profile_update", profile)
    if isinstance(result, dict) and result.get("status") in {"success", "ok"}:
        session.session_state["child_name"] = profile["name"]


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
async def health() -> Dict[str, Any]:
    bridge = await _bridge_snapshot()
    return {
        "status": "ok",
        "app": "rafiki-v1",
        "lmstudio": {
            "base_url": LMSTUDIO_BASE_URL,
            "model": LMSTUDIO_MODEL,
        },
        "bridge": bridge,
    }


@app.get("/health")
async def bridge_health() -> Dict[str, Any]:
    """Alias compatible avec le serveur Raspberry Pi de reference."""
    bridge = await _bridge_snapshot()
    return {
        "status": "online",
        "timestamp": time.time(),
        "bridge": {
            "body_pull_client_online": bool(bridge["body"].get("connected")),
            "pending_body_commands": int(bridge["body"].get("queue_size", 0)),
            "vision_url": bridge["vision"]["registered_url"],
            "has_latest_frame": bridge["vision"]["latest_frame_time"] is not None,
        },
    }


@app.post("/api/chat")
async def chat(payload: ChatRequest) -> Dict[str, Any]:
    session = await get_session(payload.session_id, payload.child_id)
    async with state.lock:
        previous_force_llm = session.force_llm
        started_at = time.perf_counter()
        try:
            if payload.force_llm:
                session.force_llm = True
            await apply_child_profile_context(session, payload.child_profile)
            result = await session.ask(payload.message, input_mode=payload.input_mode)
            result["reply"] = sanitize_reply(result["reply"])
            result["body_feedback"] = []
            logger.info(
                "chat source=%s duration=%.2fs input=%r reply=%r",
                result.get("source"),
                time.perf_counter() - started_at,
                payload.message[:120],
                result["reply"][:160],
            )
            return result
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        finally:
            session.force_llm = previous_force_llm


@app.post("/api/reset")
async def reset(session_id: str = "default_session", child_id: str = "default") -> Dict[str, Any]:
    session = await get_session(session_id, child_id)
    async with state.lock:
        result = session.start()
    return {"status": "ok", "message": "Conversation remise a zero.", **result}


@app.post("/api/start")
async def start(session_id: str = "default_session", child_id: str = "default") -> Dict[str, Any]:
    session = await get_session(session_id, child_id)
    async with state.lock:
        return session.start()


@app.get("/api/status")
async def status(session_id: str = "default_session") -> Dict[str, Any]:
    session = await get_session(session_id)
    systems = await direct_tool_call(session.tools_by_name, "rafiki_status")
    return {"status": "ok", "systems": systems}


@app.get("/api/bridge/status")
async def bridge_status(session_id: str = "default_session") -> Dict[str, Any]:
    """Etat du pont corps/camera, compatible avec la documentation Raspberry."""
    bridge = await _bridge_snapshot(session_id)
    return {"timestamp": time.time(), **bridge}


@app.get("/api/body/next")
async def body_next(session_id: str = "default_session") -> Dict[str, Any]:
    session = await get_session(session_id)
    return await direct_tool_call(session.tools_by_name, "body_command_next")


@app.get("/api/body/queue")
async def body_queue(limit: int = 10, session_id: str = "default_session") -> Dict[str, Any]:
    session = await get_session(session_id)
    return await direct_tool_call(session.tools_by_name, "body_command_peek", {"limit": limit})


@app.post("/api/body/status")
async def body_status(
    payload: BodyStatusRequest, session_id: str = "default_session"
) -> Dict[str, Any]:
    session = await get_session(session_id)
    return await direct_tool_call(
        session.tools_by_name,
        "body_status_update",
        {"status": payload.status},
    )


@app.get("/api/body/status")
async def get_body_status(session_id: str = "default_session") -> Dict[str, Any]:
    bridge = await _bridge_snapshot(session_id)
    body = bridge["body"]
    return {
        "online": bool(body.get("connected")),
        "queue_length": int(body.get("queue_size", 0)),
        "status": body,
    }


@app.post("/api/body/enqueue")
@app.post("/api/body/command")
async def enqueue_body_command(
    payload: BodyCommandRequest, session_id: str = "default_session"
) -> Dict[str, Any]:
    """Ajoute une commande compatible avec le client pull de la Raspberry."""
    session = await get_session(session_id)
    result = await direct_tool_call(
        session.tools_by_name,
        "body_command_enqueue",
        {"action": payload.action, "params": payload.params},
    )
    if not isinstance(result, dict) or result.get("status") != "success":
        message = result.get("message", "Commande corps invalide.") if isinstance(result, dict) else "Commande corps invalide."
        raise HTTPException(status_code=422, detail=message)
    return {
        "status": "enqueued",
        "command_id": result["command_id"],
        "queue_length": result["queue_size"],
        "command": {"action": result["action"], "params": result["params"]},
    }


@app.post("/api/vision")
async def vision(payload: VisionRequest) -> Dict[str, Any]:
    session = await get_session()
    VISION_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    suffix = Path(payload.filename).suffix.lower()
    if suffix not in {".jpg", ".jpeg", ".png", ".webp"}:
        suffix = ".jpg"
    image_path = VISION_UPLOAD_DIR / f"{uuid.uuid4().hex}{suffix}"
    try:
        encoded, image_bytes = _normalise_image_base64(payload.image_base64)
        image_path.write_bytes(image_bytes)
        _remember_vision_frame(encoded, camera_type="raspberry")
        result = await direct_tool_call(
            session.tools_by_name,
            "vision_observe",
            {"prompt": payload.prompt, "image_path": str(image_path)},
        )
        return {"status": "ok", "vision": result}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/vision/register")
async def register_vision_service(payload: VisionRegisterRequest) -> Dict[str, Any]:
    """Enregistre le microservice camera expose par la Raspberry Pi."""
    try:
        vision_url = _normalise_vision_url(payload.vision_url)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    state.vision_url = vision_url
    state.latest_vision_status.update(
        {
            "registered_url": vision_url,
            "connected": False,
            "last_error": None,
        }
    )
    state.save_vision_state()
    logger.info("Service vision Raspberry enregistre: %s", vision_url)
    return {"status": "registered", "vision_url": vision_url}


@app.post("/api/vision/upload")
async def upload_vision_frame(payload: VisionFrameUpload) -> Dict[str, Any]:
    """Recoit une image Base64 poussee par la Raspberry ou son service camera."""
    try:
        encoded, _ = _normalise_image_base64(payload.image_base64)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    frame = _remember_vision_frame(
        encoded,
        width=payload.width,
        height=payload.height,
        camera_type=payload.camera_type,
    )
    return {"status": "received", "timestamp": frame["timestamp"]}


@app.get("/api/vision/latest")
async def latest_vision_frame() -> Dict[str, Any]:
    if state.latest_vision_frame is None:
        raise HTTPException(status_code=404, detail="Aucune image camera recue.")
    return state.latest_vision_frame


@app.get("/api/vision/status")
async def vision_status() -> Dict[str, Any]:
    return {
        "vision_url": state.vision_url,
        "has_frame": state.latest_vision_frame is not None,
        "latest_frame_time": (
            state.latest_vision_frame.get("timestamp") if state.latest_vision_frame else None
        ),
        "status": state.latest_vision_status,
    }


@app.api_route("/api/vision/capture", methods=["GET", "POST"])
async def capture_vision_frame(
    width: int = 1280, height: int = 720, quality: int = 85
) -> Dict[str, Any]:
    """Demande une capture au microservice vision inscrit par la Raspberry."""
    if not state.vision_url:
        raise HTTPException(status_code=409, detail="Aucun service vision Raspberry enregistre.")
    width = max(1, min(int(width), 3840))
    height = max(1, min(int(height), 2160))
    quality = max(1, min(int(quality), 100))
    try:
        payload, encoded = await asyncio.to_thread(
            _capture_from_raspberry, state.vision_url, width, height, quality
        )
        metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else None
        frame = _remember_vision_frame(
            encoded,
            width=payload.get("width", width),
            height=payload.get("height", height),
            camera_type=str(payload.get("camera_type", "ov5647")),
            metadata=metadata,
        )
        return {"status": "captured", "frame": frame, "camera_response": payload}
    except (RuntimeError, ValueError) as exc:
        state.latest_vision_status.update({"connected": False, "last_error": str(exc)})
        state.save_vision_state()
        logger.warning("Capture camera Raspberry impossible: %s", exc)
        if state.latest_vision_frame is not None:
            return {
                "status": "warning",
                "message": str(exc),
                "cached_frame": state.latest_vision_frame,
            }
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/profile")
async def profile(
    session_id: str = "default_session", child_id: str = "default"
) -> Dict[str, Any]:
    session = await get_session(session_id, child_id)
    return await direct_tool_call(
        session.tools_by_name,
        "child_profile_get",
        {"child_id": session.child_id},
    )


@app.get("/api/parent-report")
async def parent_report(
    limit: int = 6, session_id: str = "default_session", child_id: str = "default"
) -> Dict[str, Any]:
    session = await get_session(session_id, child_id)
    return await direct_tool_call(
        session.tools_by_name,
        "parent_report_get",
        {"child_id": session.child_id, "limit": limit},
    )


def main() -> None:
    import uvicorn
    import socket
    
    hostname = socket.gethostname()
    logger.info("=== Informations Reseau Rafiki ===")
    logger.info("Nom de machine : %s.local (mDNS)", hostname)
    try:
        ips = socket.gethostbyname_ex(hostname)[2]
        local_ips = [ip for ip in ips if not ip.startswith("127.")]
        logger.info("Adresses IP locales detectees : %s", ", ".join(local_ips))
    except Exception as exc:
        logger.warning("Impossible de lister les IPs locales : %s", exc)
    logger.info("==================================")

    uvicorn.run("rafiki_app:app", host=APP_HOST, port=APP_PORT, reload=False)


if __name__ == "__main__":
    main()
