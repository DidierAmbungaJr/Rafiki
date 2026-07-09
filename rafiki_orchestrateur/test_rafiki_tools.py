"""
Tests locaux du serveur MCP Rafiki, sans LM Studio.
À lancer avant de tester l'agent LLM.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict

from dotenv import load_dotenv
from langchain_mcp_adapters.client import MultiServerMCPClient

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
SERVER_PATH = BASE_DIR / "mcp_rafiki_systems_server.py"


def mcp_config() -> Dict[str, Any]:
    env = os.environ.copy()
    env.setdefault("RAFIKI_MODE", "simulation")
    env.setdefault("RAFIKI_MQTT_ENABLED", "false")
    env.setdefault("RAFIKI_DB_PATH", str(BASE_DIR / "rafiki_memory_test.sqlite3"))
    return {
        "RafikiSystems": {
            "transport": "stdio",
            "command": sys.executable,
            "args": [str(SERVER_PATH)],
            "env": env,
        }
    }


async def call(tools_by_name, name: str, args: Dict[str, Any] | None = None):
    args = args or {}
    print(f"\n>>> {name}({json.dumps(args, ensure_ascii=False)})")
    result = await tools_by_name[name].ainvoke(args)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    if (
        isinstance(result, list)
        and result
        and isinstance(result[0], dict)
        and result[0].get("type") == "text"
    ):
        try:
            return json.loads(result[0]["text"])
        except (KeyError, TypeError, json.JSONDecodeError):
            pass
    return result


async def main():
    client = MultiServerMCPClient(mcp_config())
    tools = await client.get_tools()
    tools_by_name = {tool.name: tool for tool in tools}

    print("Outils disponibles:")
    for tool in tools:
        print("-", tool.name)

    required = {
        "rafiki_status",
        "child_profile_get",
        "child_profile_update",
        "remember_fact",
        "search_memory",
        "speech_say",
        "expression_set",
        "motor_gesture",
        "vision_observe",
        "educational_activity_create",
        "evaluate_child_answer",
        "parent_event_log",
        "parent_report_get",
        "routine_suggest",
        "cloud_fallback_request",
    }
    missing = required - set(tools_by_name)
    if missing:
        raise RuntimeError(f"Outils manquants: {sorted(missing)}")

    await call(tools_by_name, "rafiki_status")
    await call(
        tools_by_name,
        "child_profile_update",
        {
            "child_id": "test",
            "name": "Amani",
            "age": 7,
            "language": "français simple",
            "interests": ["mathématiques", "histoires", "animaux"],
            "level": "débutant",
        },
    )
    await call(tools_by_name, "child_profile_get", {"child_id": "test"})
    await call(
        tools_by_name,
        "remember_fact",
        {
            "child_id": "test",
            "category": "préférence",
            "content": "Amani aime les histoires avec des animaux.",
            "importance": 4,
        },
    )
    await call(tools_by_name, "search_memory", {"child_id": "test", "query": "animaux"})
    await call(tools_by_name, "expression_set", {"emotion": "joie", "intensity": 0.8})
    await call(tools_by_name, "motor_gesture", {"gesture": "saluer", "speed": 0.5})
    await call(tools_by_name, "vision_observe", {"prompt": "Regarde autour de toi"})
    activity = await call(
        tools_by_name,
        "educational_activity_create",
        {"topic": "addition", "age": 7, "level": "facile"},
    )
    await call(
        tools_by_name,
        "evaluate_child_answer",
        {
            "question": activity["activity"]["question"],
            "expected_answer": activity["activity"]["expected_answer"],
            "child_answer": "5",
        },
    )
    await call(
        tools_by_name,
        "speech_say",
        {"child_id": "test", "text": "Bravo Amani, tu as bien travaillé !", "emotion": "joie"},
    )
    await call(tools_by_name, "parent_report_get", {"child_id": "test", "limit": 5})

    print("\nOK - Tous les tests MCP locaux sont passes.")


if __name__ == "__main__":
    asyncio.run(main())
