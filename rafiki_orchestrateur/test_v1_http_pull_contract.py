"""Smoke test V1: mobile/server chat -> body command queue -> Raspberry HTTP pull.

Lancer depuis la racine du repo:
python rafiki_orchestrateur/test_v1_http_pull_contract.py
"""

from __future__ import annotations

import base64
import os
import sys
import tempfile
from uuid import uuid4
from pathlib import Path
from typing import Any, Callable, Dict

from fastapi.testclient import TestClient

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

TEST_DB_PATH = Path(tempfile.gettempdir()) / f"rafiki_memory_contract_{uuid4().hex}.sqlite3"
os.environ.setdefault("RAFIKI_MODE", "simulation")
os.environ.setdefault("RAFIKI_MQTT_ENABLED", "false")
os.environ["RAFIKI_DB_PATH"] = str(TEST_DB_PATH)

if TEST_DB_PATH.exists():
    TEST_DB_PATH.unlink()

import mcp_rafiki_systems_server as systems  # noqa: E402
from rafiki_agent import handle_local_intent  # noqa: E402
from rafiki_app import app, state  # noqa: E402


class LocalTool:
    def __init__(self, func: Callable[..., Dict[str, Any]]) -> None:
        self.func = func

    async def ainvoke(self, args: Dict[str, Any] | None = None) -> Dict[str, Any]:
        return self.func(**(args or {}))


class LocalContractSession:
    def __init__(self) -> None:
        self.force_llm = False
        self.child_id = "default"
        self.session_state: Dict[str, Any] = {"child_id": self.child_id}
        self.tools_by_name = {
            "rafiki_status": LocalTool(systems.rafiki_status),
            "body_command_next": LocalTool(systems.body_command_next),
            "body_command_peek": LocalTool(systems.body_command_peek),
            "body_command_enqueue": LocalTool(systems.body_command_enqueue),
            "body_status_update": LocalTool(systems.body_status_update),
            "expression_set": LocalTool(systems.expression_set),
            "motor_gesture": LocalTool(systems.motor_gesture),
        }

    def bind_child(self, child_id: str) -> None:
        self.child_id = child_id
        self.session_state = {"child_id": child_id}

    async def ask(self, text: str, *, input_mode: str = "text") -> Dict[str, Any]:
        await self.tools_by_name["expression_set"].ainvoke({"emotion": "joie", "intensity": 0.8})
        await self.tools_by_name["motor_gesture"].ainvoke({"gesture": "saluer", "speed": 0.5, "duration_ms": 900})
        reply = "Bonjour ! Je suis Rafiki."
        return {
            "status": "ok",
            "reply": reply,
            "source": "local_contract_test",
            "input_mode": input_mode,
            "session_state": self.session_state,
            "history": [],
        }


def main() -> None:
    state.sessions.clear()
    state.sessions["test_session"] = LocalContractSession()
    client = TestClient(app)

    health = client.get("/api/health")
    assert health.status_code == 200, health.text
    assert health.json()["status"] == "ok"

    chat = client.post(
        "/api/chat",
        json={
            "message": "Rafiki, salue l'enfant avec ton ecran et ton bras.",
            "input_mode": "voice_mobile",
            "child_id": "test_child",
            "parent_id": "test_parent",
            "session_id": "test_session",
            "child_profile": {"name": "Amani", "age": 7},
            "parental_controls": {"safe_mode": True},
        },
    )
    assert chat.status_code == 200, chat.text
    payload = chat.json()
    assert payload["status"] == "ok"
    assert payload["reply"]

    first_pull = client.get("/api/body/next?session_id=test_session")
    assert first_pull.status_code == 200, first_pull.text
    first_command = first_pull.json()["command"]
    assert first_command["target"] == "body"
    assert first_command["action"] == "set_expression"
    assert first_command["params"]["emotion"] == "joie"

    second_pull = client.get("/api/body/next?session_id=test_session")
    assert second_pull.status_code == 200, second_pull.text
    second_command = second_pull.json()["command"]
    assert second_command["target"] == "body"
    assert second_command["action"] == "motor_gesture"
    assert second_command["params"]["gesture"] == "saluer"

    status = client.post(
        "/api/body/status?session_id=test_session",
        json={
            "status": {
                "connected": True,
                "last_command_id": second_command["id"],
                "serial_commands": ["B1"],
            }
        },
    )
    assert status.status_code == 200, status.text
    assert status.json()["status"] == "ok"
    body = status.json()["body"]
    assert body["connected"] is True
    assert body["state"] == "connected"

    # Endpoints compatibles avec le pont Raspberry de reference.
    bridge_health = client.get("/health")
    assert bridge_health.status_code == 200, bridge_health.text
    assert bridge_health.json()["status"] == "online"
    assert bridge_health.json()["bridge"]["body_pull_client_online"] is True

    bridge = client.get("/api/bridge/status?session_id=test_session")
    assert bridge.status_code == 200, bridge.text
    assert bridge.json()["body"]["connected"] is True

    current_body_status = client.get("/api/body/status?session_id=test_session")
    assert current_body_status.status_code == 200, current_body_status.text
    assert current_body_status.json()["online"] is True

    # Vide les commandes restantes avant de verifier l'injection manuelle.
    while client.get("/api/body/next?session_id=test_session").json()["command"]:
        pass
    enqueued = client.post(
        "/api/body/enqueue?session_id=test_session",
        json={"action": "screen_text", "params": {"text": "Bonjour Pi"}},
    )
    assert enqueued.status_code == 200, enqueued.text
    assert enqueued.json()["status"] == "enqueued"
    manual_pull = client.get("/api/body/next?session_id=test_session")
    assert manual_pull.status_code == 200, manual_pull.text
    assert manual_pull.json()["command"]["action"] == "screen_text"
    assert manual_pull.json()["command"]["params"]["text"] == "Bonjour Pi"

    # Pont vision compatible avec le client/pousseur Raspberry du depot source.
    registered = client.post(
        "/api/vision/register",
        json={"vision_url": "http://192.0.2.10:8000"},
    )
    assert registered.status_code == 200, registered.text
    assert registered.json()["status"] == "registered"
    image_base64 = base64.b64encode(b"rafiki-test-camera-frame").decode("ascii")
    uploaded = client.post(
        "/api/vision/upload",
        json={
            "image_base64": image_base64,
            "width": 1,
            "height": 1,
            "camera_type": "ov5647",
        },
    )
    assert uploaded.status_code == 200, uploaded.text
    assert uploaded.json()["status"] == "received"
    latest = client.get("/api/vision/latest")
    assert latest.status_code == 200, latest.text
    assert latest.json()["image_base64"] == image_base64
    vision_status = client.get("/api/vision/status")
    assert vision_status.status_code == 200, vision_status.text
    assert vision_status.json()["status"]["connected"] is True

    # Le statut doit rester lisible même si l'outil est servi par un autre
    # processus MCP, donc sans l'état Python en mémoire de cet appel.
    systems._RUNTIME_STATE["esp32_status"] = {}
    systems_status = systems.rafiki_status()
    assert systems_status["body"]["connected"] is True

    print("OK - Contrat V1 HTTP pull valide.")


if __name__ == "__main__":
    main()
