"""
Serveur MCP Rafiki Systems
--------------------------
Ce serveur expose les capacités de Rafiki sous forme d'outils MCP.
Il est volontairement compatible avec un mode SIMULATION sur PC, avant passage
sur Raspberry Pi 5 + ESP32-S3.

Sous-systèmes couverts :
- mémoire locale SQLite
- parole/TTS simulé, prêt pour Piper
- vision simulée, prête pour caméra + Gemma vision
- expressions/servomoteurs via MQTT ou mock
- journal parent
- activités éducatives simples
- fallback cloud désactivé par défaut
"""

from __future__ import annotations

import json
import logging
import os
import base64
import sqlite3
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastmcp import FastMCP

try:
    import paho.mqtt.client as mqtt
except Exception:  # pragma: no cover - paho peut manquer en première installation
    mqtt = None


# Important avec MCP stdio : ne jamais polluer stdout avec des print().
# Les logs vont vers stderr pour ne pas casser le protocole MCP.
logging.basicConfig(
    stream=sys.stderr,
    level=logging.INFO,
    format="[%(levelname)s] %(asctime)s - %(message)s",
)
logger = logging.getLogger("rafiki-mcp")

mcp = FastMCP("Rafiki Systems MCP Server")

BASE_DIR = Path(__file__).resolve().parent
MODE = os.getenv("RAFIKI_MODE", "simulation").lower()
DEFAULT_CHILD_ID = os.getenv("RAFIKI_CHILD_ID", "default")
DB_PATH = Path(os.getenv("RAFIKI_DB_PATH", "./rafiki_memory.sqlite3")).expanduser()

MQTT_ENABLED = os.getenv("RAFIKI_MQTT_ENABLED", "false").lower() == "true"
MQTT_BROKER = os.getenv("RAFIKI_MQTT_BROKER", "localhost")
MQTT_PORT = int(os.getenv("RAFIKI_MQTT_PORT", "1883"))
MQTT_TOPIC_COMMANDS = os.getenv("RAFIKI_MQTT_TOPIC_COMMANDS", "rafiki/esp32/commands")
MQTT_TOPIC_STATUS = os.getenv("RAFIKI_MQTT_TOPIC_STATUS", "rafiki/esp32/status")

CLOUD_ENABLED = os.getenv("RAFIKI_CLOUD_ENABLED", "false").lower() == "true"
CLOUD_API_URL = os.getenv("RAFIKI_CLOUD_API_URL", "http://127.0.0.1:8000")

LMSTUDIO_BASE_URL = os.getenv("LMSTUDIO_BASE_URL", "http://127.0.0.1:1234/v1").rstrip("/")
LMSTUDIO_API_KEY = os.getenv("LMSTUDIO_API_KEY", "lm_studio")
LMSTUDIO_MODEL = os.getenv("LMSTUDIO_MODEL", "bonsai-27b")
RAFIKI_VISION_ENABLED = os.getenv("RAFIKI_VISION_ENABLED", "false").lower() == "true"
RAFIKI_VISION_MODEL = os.getenv("RAFIKI_VISION_MODEL", LMSTUDIO_MODEL)
RAFIKI_VISION_TIMEOUT_SECONDS = int(os.getenv("RAFIKI_VISION_TIMEOUT_SECONDS", "90"))
RAFIKI_VISION_URL = os.getenv("RAFIKI_VISION_URL", "http://localhost:8000").rstrip("/")
BODY_STATUS_TTL_SECONDS = max(2, int(os.getenv("RAFIKI_BODY_STATUS_TTL_SECONDS", "15")))

_RUNTIME_STATE: Dict[str, Any] = {
    "mode": MODE,
    "mqtt_connected": False,
    "last_expression": {"emotion": "neutre", "intensity": 0.5},
    "last_gesture": None,
    "last_spoken_text": None,
    "last_vision": None,
    "esp32_status": {},
    "started_at": datetime.now(timezone.utc).isoformat(),
}

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _body_connection_state() -> Dict[str, Any]:
    """Retourne la disponibilité réelle du corps signalée par la Raspberry."""
    # Les outils MCP peuvent être appelés dans des processus stdio distincts.
    # Le statut du corps ne doit donc pas vivre uniquement dans _RUNTIME_STATE.
    status = _read_body_runtime_status()
    last_seen_at = str(status.get("updated_at") or "")
    age_seconds: Optional[float] = None
    if last_seen_at:
        try:
            seen_at = datetime.fromisoformat(last_seen_at.replace("Z", "+00:00"))
            age_seconds = max(0.0, (datetime.now(timezone.utc) - seen_at).total_seconds())
        except ValueError:
            last_seen_at = ""

    reported_connected = status.get("connected") is True
    connected = bool(
        reported_connected
        and age_seconds is not None
        and age_seconds <= BODY_STATUS_TTL_SECONDS
    )
    if connected:
        state = "connected"
    elif status:
        state = "stale" if reported_connected else "offline"
    else:
        state = "not_reported"

    return {
        "state": state,
        "connected": connected,
        "reported_connected": reported_connected,
        "transport": status.get("transport", "http_pull"),
        "controller": status.get("controller"),
        "body_port": status.get("body_port"),
        "last_seen_at": last_seen_at or None,
        "seconds_since_last_seen": round(age_seconds, 1) if age_seconds is not None else None,
        "ttl_seconds": BODY_STATUS_TTL_SECONDS,
        "last_command_id": status.get("last_command_id"),
        "last_action": status.get("last_action"),
        "last_error": status.get("error"),
        "queue_size": _body_queue_size(),
    }


def _connect_db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def _read_body_runtime_status() -> Dict[str, Any]:
    """Lit le dernier heartbeat persistant de la Raspberry.

    Une valeur en mémoire reste en secours pour la compatibilité avec les appels
    directs, mais SQLite est la source de vérité entre deux processus MCP.
    """
    with _connect_db() as con:
        row = con.execute(
            "SELECT status_json, updated_at FROM body_runtime_status WHERE id = 1"
        ).fetchone()
    if row is None:
        return dict(_RUNTIME_STATE.get("esp32_status") or {})
    try:
        status = json.loads(row["status_json"])
    except (TypeError, json.JSONDecodeError):
        logger.warning("Statut corps persistant illisible; statut ignore.")
        return {}
    if not isinstance(status, dict):
        return {}
    status["updated_at"] = row["updated_at"]
    return status


def _save_body_runtime_status(status: Dict[str, Any]) -> Dict[str, Any]:
    """Enregistre atomiquement le heartbeat, partage entre les processus MCP."""
    saved_at = _now()
    saved_status = {**status, "updated_at": saved_at}
    with _connect_db() as con:
        con.execute(
            """
            INSERT INTO body_runtime_status (id, status_json, updated_at)
            VALUES (1, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                status_json = excluded.status_json,
                updated_at = excluded.updated_at
            """,
            (json.dumps(saved_status, ensure_ascii=False), saved_at),
        )
        con.commit()
    _RUNTIME_STATE["esp32_status"] = saved_status
    return saved_status


def _init_db() -> None:
    with _connect_db() as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS memory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                child_id TEXT NOT NULL,
                category TEXT NOT NULL,
                content TEXT NOT NULL,
                importance INTEGER NOT NULL DEFAULT 3,
                created_at TEXT NOT NULL
            )
            """
        )
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS parent_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                child_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                summary TEXT NOT NULL,
                severity TEXT NOT NULL DEFAULT 'info',
                payload_json TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS child_profiles (
                child_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                age INTEGER NOT NULL,
                language TEXT NOT NULL DEFAULT 'français simple',
                interests_json TEXT NOT NULL DEFAULT '[]',
                level TEXT NOT NULL DEFAULT 'débutant',
                updated_at TEXT NOT NULL
            )
            """
        )
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS body_commands (
                id TEXT PRIMARY KEY,
                command_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS body_runtime_status (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                status_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
_init_db()


_mqtt_client = None


def _mqtt_connect_if_needed() -> None:
    global _mqtt_client
    if not MQTT_ENABLED:
        return
    if mqtt is None:
        logger.warning("paho-mqtt n'est pas installé; MQTT désactivé.")
        return
    if _mqtt_client is not None:
        return

    def on_connect(client, userdata, flags, rc, properties=None):  # paho v1/v2 compatible
        _RUNTIME_STATE["mqtt_connected"] = rc == 0
        logger.info("Connexion MQTT rc=%s", rc)
        try:
            client.subscribe(MQTT_TOPIC_STATUS)
        except Exception as exc:
            logger.warning("Impossible de s'abonner au topic statut: %s", exc)

    def on_message(client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
        except Exception:
            payload = {"raw": msg.payload.decode("utf-8", errors="replace")}
        if not isinstance(payload, dict):
            payload = {"raw": payload}
        _save_body_runtime_status(payload)
        logger.info("Statut ESP32 reçu: %s", payload)

    try:
        _mqtt_client = mqtt.Client(client_id=f"rafiki_mcp_{int(time.time())}")
        _mqtt_client.on_connect = on_connect
        _mqtt_client.on_message = on_message
        _mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
        _mqtt_client.loop_start()
    except Exception as exc:
        logger.warning("MQTT indisponible, passage en simulation: %s", exc)
        _RUNTIME_STATE["mqtt_connected"] = False
        _mqtt_client = None


def _publish_command(action: str, params: Dict[str, Any]) -> Dict[str, Any]:
    command = {
        "id": uuid.uuid4().hex,
        "source": "rafiki_mcp",
        "target": "body",
        "action": action,
        "params": params,
        "created_at": _now(),
    }
    _enqueue_body_command(command)
    _mqtt_connect_if_needed()
    if MQTT_ENABLED and _mqtt_client is not None:
        try:
            _mqtt_client.publish(MQTT_TOPIC_COMMANDS, json.dumps(command, ensure_ascii=False))
            return {"transport": "mqtt", "topic": MQTT_TOPIC_COMMANDS, "command": command}
        except Exception as exc:
            logger.warning("Publication MQTT impossible: %s", exc)
    body = _body_connection_state()
    return {
        "transport": "http_pull" if body["connected"] else "http_pull_queued",
        "topic": None,
        "command": command,
        "body_state": body["state"],
    }


def _enqueue_body_command(command: Dict[str, Any]) -> None:
    with _connect_db() as con:
        con.execute(
            """
            INSERT INTO body_commands (id, command_json, created_at)
            VALUES (?, ?, ?)
            """,
            (
                str(command["id"]),
                json.dumps(command, ensure_ascii=False),
                str(command["created_at"]),
            ),
        )
        con.execute(
            """
            DELETE FROM body_commands
            WHERE id NOT IN (
                SELECT id FROM body_commands
                ORDER BY created_at DESC
                LIMIT 100
            )
            """
        )
        con.commit()


def _body_queue_size() -> int:
    with _connect_db() as con:
        return int(con.execute("SELECT COUNT(*) AS n FROM body_commands").fetchone()["n"])


def _mime_type_for_image(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".webp":
        return "image/webp"
    return "image/png"


def _lmstudio_chat(payload: Dict[str, Any], timeout_seconds: int = 120) -> Dict[str, Any]:
    request = urllib.request.Request(
        f"{LMSTUDIO_BASE_URL}/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {LMSTUDIO_API_KEY}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"LM Studio HTTP {exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"LM Studio indisponible: {exc.reason}") from exc


def _observe_image_with_lmstudio(prompt: str, image_path: Path) -> Dict[str, Any]:
    encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
    image_url = f"data:{_mime_type_for_image(image_path)};base64,{encoded}"
    payload = {
        "model": RAFIKI_VISION_MODEL,
        "temperature": 0.2,
        "max_tokens": 600,
        "reasoning_effort": "none",
        "messages": [
            {
                "role": "system",
                "content": (
                    "Tu es le module vision de Rafiki. Decris uniquement ce qui est visible, "
                    "sans inventer. Reponds en francais simple, utile pour un robot educatif."
                ),
            },
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt or "Que vois-tu ?"},
                    {"type": "image_url", "image_url": {"url": image_url}},
                ],
            },
        ],
    }
    response = _lmstudio_chat(payload, timeout_seconds=RAFIKI_VISION_TIMEOUT_SECONDS)
    msg = response.get("choices", [{}])[0].get("message", {})
    description = (msg.get("content") or "").strip()
    if not description and msg.get("reasoning_content"):
        description = msg.get("reasoning_content", "").strip()
    if not description:
        description = "Image recue, mais le modele vision n'a pas produit de description."
    return {
        "provider": "lmstudio",
        "model": RAFIKI_VISION_MODEL,
        "description": description,
    }


def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    return {key: row[key] for key in row.keys()}


@mcp.tool(
    name="rafiki_status",
    description="Retourne l'état global des sous-systèmes Rafiki: mode, mémoire, MQTT, expression, geste et disponibilité cloud.",
)
def rafiki_status() -> Dict[str, Any]:
    """Diagnostic rapide de l'orchestrateur Rafiki."""
    _mqtt_connect_if_needed()
    with _connect_db() as con:
        memory_count = con.execute("SELECT COUNT(*) AS n FROM memory").fetchone()["n"]
        event_count = con.execute("SELECT COUNT(*) AS n FROM parent_events").fetchone()["n"]
    body = _body_connection_state()
    return {
        "status": "ok",
        "mode": MODE,
        "db_path": str(DB_PATH),
        "memory_count": memory_count,
        "parent_event_count": event_count,
        "mqtt_enabled": MQTT_ENABLED,
        "mqtt_connected": _RUNTIME_STATE["mqtt_connected"],
        "cloud_enabled": CLOUD_ENABLED,
        "last_expression": _RUNTIME_STATE["last_expression"],
        "last_gesture": _RUNTIME_STATE["last_gesture"],
        "last_spoken_text": _RUNTIME_STATE["last_spoken_text"],
        "esp32_status": _read_body_runtime_status(),
        "body": body,
        "started_at": _RUNTIME_STATE["started_at"],
        "checked_at": _now(),
    }


@mcp.tool(
    name="body_command_next",
    description="Retourne et retire la prochaine commande corps en attente pour la Raspberry.",
)
def body_command_next() -> Dict[str, Any]:
    with _connect_db() as con:
        row = con.execute(
            """
            SELECT id, command_json
            FROM body_commands
            ORDER BY created_at ASC
            LIMIT 1
            """
        ).fetchone()
        if not row:
            return {"status": "idle", "command": None, "queue_size": 0}
        con.execute("DELETE FROM body_commands WHERE id = ?", (row["id"],))
        con.commit()

    command = json.loads(row["command_json"])
    return {
        "status": "ok",
        "command": command,
        "queue_size": _body_queue_size(),
    }


@mcp.tool(
    name="body_command_peek",
    description="Liste les commandes corps en attente sans les retirer.",
)
def body_command_peek(limit: int = 10) -> Dict[str, Any]:
    limit = max(1, min(int(limit), 50))
    with _connect_db() as con:
        rows = con.execute(
            """
            SELECT command_json
            FROM body_commands
            ORDER BY created_at ASC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return {
        "status": "ok",
        "commands": [json.loads(row["command_json"]) for row in rows],
        "queue_size": _body_queue_size(),
    }


@mcp.tool(
    name="body_command_enqueue",
    description=(
        "Ajoute une commande brute a la file HTTP de la Raspberry: "
        "set_expression, motor_gesture, screen_text ou status_ping."
    ),
)
def body_command_enqueue(action: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Compatibilite avec POST /api/body/enqueue du pont Raspberry de reference."""
    action = str(action or "").strip()
    allowed = {"set_expression", "motor_gesture", "screen_text", "status_ping"}
    if action not in allowed:
        return {
            "status": "error",
            "message": f"Action corps inconnue: {action}",
            "allowed": sorted(allowed),
        }

    command_params = dict(params) if isinstance(params, dict) else {}
    if action == "set_expression":
        emotion = str(command_params.get("emotion", "neutre")).strip()
        command_params["emotion"] = emotion or "neutre"
    elif action == "motor_gesture":
        gesture = str(command_params.get("gesture", "stop")).strip()
        command_params["gesture"] = gesture or "stop"
    elif action == "screen_text":
        text = " ".join(str(command_params.get("text", "")).split())[:160]
        if not text:
            return {"status": "error", "message": "Le texte ecran est vide."}
        command_params["text"] = text
    else:
        command_params = {}

    transport = _publish_command(action, command_params)
    return {
        "status": "success",
        "action": action,
        "params": command_params,
        "command_id": transport["command"]["id"],
        "queue_size": _body_queue_size(),
        "transport": transport,
    }


@mcp.tool(
    name="body_status_update",
    description="Met a jour le dernier statut connu de la Raspberry ou du controleur Arduino.",
)
def body_status_update(status: Dict[str, Any]) -> Dict[str, Any]:
    previous = _read_body_runtime_status()
    saved_status = _save_body_runtime_status({**previous, **status})
    return {
        "status": "ok",
        "body_status": saved_status,
        "body": _body_connection_state(),
    }


@mcp.tool(
    name="child_profile_get",
    description="Lit le profil local d'un enfant: prénom, âge, langue, intérêts et niveau éducatif.",
)
def child_profile_get(child_id: str = DEFAULT_CHILD_ID) -> Dict[str, Any]:
    with _connect_db() as con:
        row = con.execute(
            "SELECT * FROM child_profiles WHERE child_id = ?", (child_id,)
        ).fetchone()
    if not row:
        return {"status": "not_found", "child_id": child_id}
    data = _row_to_dict(row)
    data["interests"] = json.loads(data.pop("interests_json") or "[]")
    return {"status": "ok", "profile": data}


@mcp.tool(
    name="child_profile_update",
    description="Met à jour le profil local de l'enfant. Utiliser pour personnaliser Rafiki selon l'âge, le niveau et les intérêts.",
)
def child_profile_update(
    child_id: str = DEFAULT_CHILD_ID,
    name: str = "enfant",
    age: int = 7,
    language: str = "français simple",
    interests: Optional[List[str]] = None,
    level: str = "débutant",
) -> Dict[str, Any]:
    interests = interests or []
    if age < 3 or age > 15:
        return {"status": "error", "message": "Âge hors périmètre Rafiki pour ce prototype."}
    with _connect_db() as con:
        con.execute(
            """
            INSERT INTO child_profiles
            (child_id, name, age, language, interests_json, level, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(child_id) DO UPDATE SET
                name=excluded.name,
                age=excluded.age,
                language=excluded.language,
                interests_json=excluded.interests_json,
                level=excluded.level,
                updated_at=excluded.updated_at
            """,
            (
                child_id,
                name,
                age,
                language,
                json.dumps(interests, ensure_ascii=False),
                level,
                _now(),
            ),
        )
        con.commit()
    return {"status": "success", "profile": child_profile_get(child_id)["profile"]}


@mcp.tool(
    name="remember_fact",
    description="Enregistre une information durable dans la mémoire locale SQLite de Rafiki.",
)
def remember_fact(
    content: str,
    category: str = "conversation",
    importance: int = 3,
    child_id: str = DEFAULT_CHILD_ID,
) -> Dict[str, Any]:
    if not content.strip():
        return {"status": "error", "message": "content est vide"}
    importance = max(1, min(int(importance), 5))
    created_at = _now()
    with _connect_db() as con:
        cur = con.execute(
            """
            INSERT INTO memory (child_id, category, content, importance, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (child_id, category, content.strip(), importance, created_at),
        )
        con.commit()
        memory_id = cur.lastrowid
    return {
        "status": "success",
        "memory_id": memory_id,
        "child_id": child_id,
        "category": category,
        "importance": importance,
        "created_at": created_at,
    }


@mcp.tool(
    name="search_memory",
    description="Recherche dans la mémoire locale de Rafiki avec une requête textuelle simple.",
)
def search_memory(
    query: str,
    child_id: str = DEFAULT_CHILD_ID,
    limit: int = 5,
) -> Dict[str, Any]:
    query = query.strip()
    limit = max(1, min(int(limit), 20))
    sql = """
        SELECT id, child_id, category, content, importance, created_at
        FROM memory
        WHERE child_id = ? AND content LIKE ?
        ORDER BY importance DESC, id DESC
        LIMIT ?
    """
    with _connect_db() as con:
        rows = con.execute(sql, (child_id, f"%{query}%", limit)).fetchall()
    return {
        "status": "ok",
        "query": query,
        "child_id": child_id,
        "results": [_row_to_dict(row) for row in rows],
    }


@mcp.tool(
    name="speech_say",
    description="Fait parler Rafiki. En simulation, le texte est seulement enregistré; sur Raspberry, brancher Piper ici.",
)
def speech_say(text: str, emotion: str = "neutre", child_id: str = DEFAULT_CHILD_ID) -> Dict[str, Any]:
    text = text.strip()
    if not text:
        return {"status": "error", "message": "text est vide"}
    _RUNTIME_STATE["last_spoken_text"] = {"text": text, "emotion": emotion, "at": _now()}
    parent_event_log(
        event_type="speech",
        summary=f"Rafiki a répondu avec émotion '{emotion}'.",
        severity="info",
        payload={"text": text, "emotion": emotion},
        child_id=child_id,
    )
    return {
        "status": "success",
        "mode": MODE,
        "tts_engine": "simulation_piper_placeholder",
        "spoken_text": text,
        "emotion": emotion,
        "note_raspberry": "Remplacer ce placeholder par un appel Piper CLI ou Python sur Raspberry Pi.",
    }


@mcp.tool(
    name="expression_set",
    description="Change l'expression du visage/écran LED de Rafiki: joie, curiosité, réflexion, surprise, tristesse, neutre.",
)
def expression_set(emotion: str, intensity: float = 0.7) -> Dict[str, Any]:
    allowed = {"joie", "curiosité", "réflexion", "surprise", "tristesse", "neutre", "encouragement"}
    emotion = emotion.lower().strip()
    if emotion not in allowed:
        return {
            "status": "error",
            "message": f"Expression inconnue: {emotion}",
            "allowed": sorted(allowed),
        }
    intensity = max(0.0, min(float(intensity), 1.0))
    _RUNTIME_STATE["last_expression"] = {"emotion": emotion, "intensity": intensity, "at": _now()}
    transport = _publish_command("set_expression", {"emotion": emotion, "intensity": intensity})
    return {"status": "success", "expression": _RUNTIME_STATE["last_expression"], "transport": transport}


@mcp.tool(
    name="motor_gesture",
    description="Déclenche un geste sur l'ESP32-S3: saluer, hocher_tete, tourner_gauche, tourner_droite, danser, stop.",
)
def motor_gesture(gesture: str, speed: float = 0.5, duration_ms: int = 900) -> Dict[str, Any]:
    allowed = {"saluer", "hocher_tete", "tourner_gauche", "tourner_droite", "danser", "stop"}
    gesture = gesture.lower().strip()
    if gesture not in allowed:
        return {"status": "error", "message": f"Geste inconnu: {gesture}", "allowed": sorted(allowed)}
    speed = max(0.0, min(float(speed), 1.0))
    default_durations = {
        "saluer": 900,
        "hocher_tete": 650,
        "tourner_gauche": 700,
        "tourner_droite": 700,
        "danser": 1500,
        "stop": 0,
    }
    duration_ms = max(0, min(int(duration_ms or default_durations.get(gesture, 900)), 3000))
    _RUNTIME_STATE["last_gesture"] = {
        "gesture": gesture,
        "speed": speed,
        "duration_ms": duration_ms,
        "at": _now(),
    }
    transport = _publish_command(
        "motor_gesture",
        {"gesture": gesture, "speed": speed, "duration_ms": duration_ms},
    )
    return {"status": "success", "gesture": _RUNTIME_STATE["last_gesture"], "transport": transport}


@mcp.tool(
    name="screen_text",
    description="Affiche un texte court sur l'ecran du corps Rafiki via l'orchestrateur Raspberry.",
)
def screen_text(text: str) -> Dict[str, Any]:
    text = " ".join(text.strip().split())[:160]
    if not text:
        return {"status": "error", "message": "text est vide"}
    transport = _publish_command("screen_text", {"text": text})
    return {"status": "success", "text": text, "transport": transport}


def _resolve_vision_url() -> Optional[str]:
    state_file = BASE_DIR / "runtime" / "vision_state.json"
    if state_file.exists():
        try:
            data = json.loads(state_file.read_text(encoding="utf-8"))
            url = data.get("vision_url")
            if url:
                return str(url).rstrip("/")
        except Exception:
            pass
    if RAFIKI_VISION_URL:
        return RAFIKI_VISION_URL
    return None


@mcp.tool(
    name="vision_observe",
    description="Observe l'environnement avec la caméra Raspberry Pi et LM Studio vision.",
)
def vision_observe(prompt: str = "Que vois-tu ?", image_path: Optional[str] = None) -> Dict[str, Any]:
    observation: Dict[str, Any] = {
        "mode": MODE,
        "prompt": prompt,
        "created_at": _now(),
    }
    target_path: Optional[Path] = None
    default_candidate = BASE_DIR / "runtime" / "vision_uploads" / "latest_frame.jpg"

    if image_path:
        target_path = Path(image_path).expanduser()
    else:
        # Essayer de récupérer une frame fraîche en direct depuis la caméra Raspberry Pi
        vision_url = _resolve_vision_url()
        if vision_url:
            for ep in ["/capture", "/capture/json", "/snapshot"]:
                try:
                    req = urllib.request.Request(
                        f"{vision_url}{ep}",
                        headers={"Accept": "image/jpeg, application/json, */*", "User-Agent": "RafikiMCP"},
                    )
                    with urllib.request.urlopen(req, timeout=3.0) as resp:
                        content_type = resp.headers.get_content_type()
                        data = resp.read()
                        if content_type == "application/json" or b'"image_base64"' in data:
                            parsed = json.loads(data.decode("utf-8"))
                            raw_b64 = parsed.get("image_base64") or parsed.get("data_uri")
                            if raw_b64:
                                clean_b64 = str(raw_b64).split(",")[-1].strip()
                                binary = base64.b64decode(clean_b64)
                                default_candidate.parent.mkdir(parents=True, exist_ok=True)
                                default_candidate.write_bytes(binary)
                                target_path = default_candidate
                                break
                        elif len(data) > 500:
                            default_candidate.parent.mkdir(parents=True, exist_ok=True)
                            default_candidate.write_bytes(data)
                            target_path = default_candidate
                            break
                except Exception:
                    pass

        if target_path is None and default_candidate.exists():
            target_path = default_candidate

    if target_path and target_path.exists():
        path = target_path
        observation["image_path"] = str(path)
        observation["image_exists"] = True
        observation["file_size_bytes"] = path.stat().st_size
        if RAFIKI_VISION_ENABLED:
            try:
                vision = _observe_image_with_lmstudio(prompt, path)
                observation.update(vision)
                observation["vision_enabled"] = True
            except Exception as exc:
                observation["vision_enabled"] = True
                observation["vision_error"] = str(exc)
                observation["description"] = (
                    "Image reçue, mais l'analyse vision LM Studio a échoué. "
                    "Vérifie que le serveur LM Studio est actif et que le modèle accepte les images."
                )
        else:
            observation["vision_enabled"] = False
            observation["description"] = (
                "Image reçue. Active RAFIKI_VISION_ENABLED=true et charge un modèle vision "
                "dans LM Studio pour analyser réellement l'image."
            )
    else:
        observation["camera_connected"] = False
        observation["description"] = (
            "La caméra de Rafiki n'est pas branchée ou n'a pas transmis d'image. "
            "Je ne peux rien observer visuellement pour l'instant. "
            "Peux-tu me décrire ce que tu as ou ce que tu souhaites me montrer ?"
        )
        observation["objects"] = []
    _RUNTIME_STATE["last_vision"] = observation
    return {"status": "success", "observation": observation}


@mcp.tool(
    name="educational_activity_create",
    description="Crée une petite activité éducative adaptée à l'âge et au thème demandé.",
)
def educational_activity_create(
    topic: str = "",
    age: int = 7,
    level: str = "facile",
    language: str = "français simple",
    activity_type: str = "",
    difficulty: str = "",
) -> Dict[str, Any]:
    topic = topic or activity_type or "calcul"
    level = difficulty or level
    topic_norm = topic.lower().strip()
    if "math" in topic_norm or "calcul" in topic_norm or "addition" in topic_norm:
        activity = {
            "type": "question",
            "title": "Petit calcul",
            "question": "Si tu as 2 mangues et que maman t'en donne encore 3, tu as combien de mangues ?",
            "expected_answer": "5",
            "hint": "Compte 2 puis ajoute 3.",
        }
    elif "lecture" in topic_norm or "français" in topic_norm:
        activity = {
            "type": "lecture",
            "title": "Phrase à compléter",
            "question": "Complète: Le soleil brille dans le ____.",
            "expected_answer": "ciel",
            "hint": "On le voit au-dessus de nous.",
        }
    else:
        activity = {
            "type": "curiosité",
            "title": f"Découvrons: {topic}",
            "question": f"Dis-moi une chose que tu connais déjà sur {topic}.",
            "expected_answer": "réponse ouverte",
            "hint": "Tu peux répondre avec tes mots.",
        }
    return {
        "status": "success",
        "age": age,
        "level": level,
        "language": language,
        "activity": activity,
    }


@mcp.tool(
    name="evaluate_child_answer",
    description="Évalue simplement la réponse de l'enfant et propose un encouragement.",
)
def evaluate_child_answer(
    question: str,
    expected_answer: str,
    child_answer: str,
) -> Dict[str, Any]:
    expected = expected_answer.strip().lower()
    answer = child_answer.strip().lower()
    if expected in {"réponse ouverte", "ouverte", "open"}:
        correct = bool(answer)
    else:
        correct = expected == answer or expected in answer
    feedback = (
        "Bravo, tu as bien répondu !"
        if correct
        else f"Tu es proche. La bonne réponse attendue était: {expected_answer}. On réessaie ensemble."
    )
    return {
        "status": "success",
        "correct": correct,
        "feedback": feedback,
        "question": question,
        "expected_answer": expected_answer,
        "child_answer": child_answer,
    }


@mcp.tool(
    name="parent_event_log",
    description="Ajoute un événement au journal parent: apprentissage, alerte, parole, émotion, routine, erreur.",
)
def parent_event_log(
    event_type: str,
    summary: str,
    severity: str = "info",
    payload: Optional[Dict[str, Any]] = None,
    child_id: str = DEFAULT_CHILD_ID,
) -> Dict[str, Any]:
    if severity not in {"info", "success", "warning", "critical"}:
        severity = "info"
    created_at = _now()
    with _connect_db() as con:
        cur = con.execute(
            """
            INSERT INTO parent_events
            (child_id, event_type, summary, severity, payload_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                child_id,
                event_type.strip(),
                summary.strip(),
                severity,
                json.dumps(payload or {}, ensure_ascii=False),
                created_at,
            ),
        )
        con.commit()
        event_id = cur.lastrowid
    return {
        "status": "success",
        "event_id": event_id,
        "child_id": child_id,
        "event_type": event_type,
        "severity": severity,
        "created_at": created_at,
    }


@mcp.tool(
    name="parent_report_get",
    description="Retourne les derniers événements du journal parent pour le suivi éducatif et comportemental.",
)
def parent_report_get(child_id: str = DEFAULT_CHILD_ID, limit: int = 10) -> Dict[str, Any]:
    limit = max(1, min(int(limit), 50))
    with _connect_db() as con:
        rows = con.execute(
            """
            SELECT id, child_id, event_type, summary, severity, payload_json, created_at
            FROM parent_events
            WHERE child_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (child_id, limit),
        ).fetchall()
    events = []
    for row in rows:
        item = _row_to_dict(row)
        item["payload"] = json.loads(item.pop("payload_json") or "{}")
        events.append(item)
    return {"status": "ok", "child_id": child_id, "events": events}


@mcp.tool(
    name="routine_suggest",
    description="Suggère une routine simple: apprendre, pause, histoire, révision ou calme.",
)
def routine_suggest(moment: str = "maintenant", child_id: str = DEFAULT_CHILD_ID) -> Dict[str, Any]:
    profile = child_profile_get(child_id).get("profile", {})
    age = profile.get("age", 7)
    return {
        "status": "success",
        "moment": moment,
        "routine": [
            {"step": 1, "duration_min": 2, "activity": "salutation et vérification de l'humeur"},
            {"step": 2, "duration_min": 5, "activity": f"activité éducative courte adaptée à {age} ans"},
            {"step": 3, "duration_min": 2, "activity": "encouragement et résumé pour le parent"},
        ],
    }


@mcp.tool(
    name="cloud_fallback_request",
    description="Prépare une demande cloud pour une question complexe. Par défaut, le cloud est désactivé en simulation.",
)
def cloud_fallback_request(question: str, reason: str = "question complexe") -> Dict[str, Any]:
    if not CLOUD_ENABLED:
        return {
            "status": "disabled",
            "message": "Fallback cloud désactivé. Répondre avec les connaissances locales ou expliquer la limite.",
            "question": question,
            "reason": reason,
        }
    # Placeholder volontaire: sur la vraie architecture, appeler ici FastAPI cloud.
    return {
        "status": "prepared",
        "api_url": CLOUD_API_URL,
        "question": question,
        "reason": reason,
        "note": "Brancher ici requests/httpx vers FastAPI cloud lorsque le backend sera disponible.",
    }


if __name__ == "__main__":
    _mqtt_connect_if_needed()
    mcp.run()
