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
import sqlite3
import sys
import time
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


def _connect_db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


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
        existing = con.execute(
            "SELECT child_id FROM child_profiles WHERE child_id = ?", (DEFAULT_CHILD_ID,)
        ).fetchone()
        if not existing:
            con.execute(
                """
                INSERT INTO child_profiles
                (child_id, name, age, language, interests_json, level, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    DEFAULT_CHILD_ID,
                    "enfant",
                    7,
                    "français simple",
                    json.dumps(["histoires", "jeux", "apprentissage"], ensure_ascii=False),
                    "débutant",
                    _now(),
                ),
            )
        con.commit()


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
        _RUNTIME_STATE["esp32_status"] = payload
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
        "source": "rafiki_mcp",
        "action": action,
        "params": params,
        "created_at": _now(),
    }
    _mqtt_connect_if_needed()
    if MQTT_ENABLED and _mqtt_client is not None:
        try:
            _mqtt_client.publish(MQTT_TOPIC_COMMANDS, json.dumps(command, ensure_ascii=False))
            return {"transport": "mqtt", "topic": MQTT_TOPIC_COMMANDS, "command": command}
        except Exception as exc:
            logger.warning("Publication MQTT impossible: %s", exc)
    return {"transport": "simulation", "topic": None, "command": command}


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
        "esp32_status": _RUNTIME_STATE["esp32_status"],
        "started_at": _RUNTIME_STATE["started_at"],
        "checked_at": _now(),
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
def motor_gesture(gesture: str, speed: float = 0.5) -> Dict[str, Any]:
    allowed = {"saluer", "hocher_tete", "tourner_gauche", "tourner_droite", "danser", "stop"}
    gesture = gesture.lower().strip()
    if gesture not in allowed:
        return {"status": "error", "message": f"Geste inconnu: {gesture}", "allowed": sorted(allowed)}
    speed = max(0.0, min(float(speed), 1.0))
    _RUNTIME_STATE["last_gesture"] = {"gesture": gesture, "speed": speed, "at": _now()}
    transport = _publish_command("motor_gesture", {"gesture": gesture, "speed": speed})
    return {"status": "success", "gesture": _RUNTIME_STATE["last_gesture"], "transport": transport}


@mcp.tool(
    name="vision_observe",
    description="Observe l'environnement. En simulation, renvoie une description fictive; sur Raspberry, brancher caméra + modèle vision.",
)
def vision_observe(prompt: str = "Que vois-tu ?", image_path: Optional[str] = None) -> Dict[str, Any]:
    observation: Dict[str, Any] = {
        "mode": MODE,
        "prompt": prompt,
        "created_at": _now(),
    }
    if image_path:
        path = Path(image_path).expanduser()
        observation["image_path"] = str(path)
        observation["image_exists"] = path.exists()
        if path.exists():
            observation["description"] = "Image reçue. Le module vision réel devra analyser cette image avec Gemma vision ou un modèle local."
            observation["file_size_bytes"] = path.stat().st_size
        else:
            observation["description"] = "Aucun fichier image trouvé au chemin indiqué."
    else:
        observation["description"] = "Simulation: Rafiki voit un enfant devant lui dans un environnement calme."
        observation["objects"] = ["enfant", "table", "cahier"]
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
