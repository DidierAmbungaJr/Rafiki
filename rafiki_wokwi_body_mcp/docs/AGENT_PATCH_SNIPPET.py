# Ajoute ce bloc dans ton dictionnaire MultiServerMCPClient({...})
# à côté de ton serveur Rafiki principal.

"RafikiBodyWokwi": {
    "transport": "stdio",
    "command": "uv",
    "args": [
        "run",
        "--with", "fastmcp",
        "--with", "paho-mqtt",
        "fastmcp",
        "run",
        "C:\\Users\\ODC\\Desktop\\Didier\\agent-llm\\mcp_rafiki_body_server.py"
    ]
}

# Et ajoute cette partie dans ton SystemMessage :
"""
Tu peux contrôler le corps de Rafiki via les outils MCP du serveur RafikiBodyWokwi.
Quand l'enfant réussit, utilise une expression joyeuse et un geste de célébration.
Quand Rafiki réfléchit, affiche l'expression thinking et fais un petit geste de réflexion.
Quand il salue, utilise le geste greet.
Quand il y a une alerte ou une erreur importante, utilise l'expression alert.
Ne bouge pas les servos de manière excessive : privilégie les gestes prédéfinis.
"""
