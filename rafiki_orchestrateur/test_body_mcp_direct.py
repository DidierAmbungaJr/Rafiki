"""Test direct du serveur MCP body sans LLM.
Lance d'abord la simulation Wokwi, puis exécute :
python test_body_mcp_direct.py
"""

import time
import importlib.util
from pathlib import Path

server_path = Path(__file__).with_name("mcp_rafiki_body_server.py")
spec = importlib.util.spec_from_file_location("mcp_rafiki_body_server", server_path)
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)  # type: ignore

print("Attente du statut Wokwi...")
print(server.rafiki_wait_for_body(8))

print("Expression happy...")
print(server.rafiki_set_expression("happy", "Bonjour !", True))
time.sleep(1)

print("Geste greet...")
print(server.rafiki_gesture("greet", 1))
time.sleep(2)

print("Pose directe...")
print(server.rafiki_set_pose(head=70, left_arm=120, right_arm=60))
time.sleep(1)

print("Statut final...")
print(server.rafiki_body_status())
