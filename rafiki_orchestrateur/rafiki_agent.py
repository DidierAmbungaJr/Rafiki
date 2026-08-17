"""
Agent LLM central Rafiki
------------------------
Client MCP + LangGraph + LM Studio.

Rôle : orchestrer les sous-systèmes Rafiki exposés par mcp_rafiki_systems_server.py
avant de passer sur Raspberry Pi.
"""

from __future__ import annotations

import argparse
import asyncio
import ast
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, MessagesState, StateGraph


load_dotenv()

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

BASE_DIR = Path(__file__).resolve().parent

SYSTEMS_SERVER_PATH = BASE_DIR / "mcp_rafiki_systems_server.py"

LMSTUDIO_BASE_URL = os.getenv("LMSTUDIO_BASE_URL", "http://127.0.0.1:1234/v1")
LMSTUDIO_API_KEY = os.getenv("LMSTUDIO_API_KEY", "lm_studio")
LMSTUDIO_MODEL = os.getenv("LMSTUDIO_MODEL", "bonsai-27b")
MAX_TOOL_ROUNDS = int(os.getenv("RAFIKI_MAX_TOOL_ROUNDS", "5"))
FORCE_LLM = os.getenv("RAFIKI_FORCE_LLM", "false").lower() == "true"

# Compatibilité avec certaines versions de langchain-openai.
os.environ.setdefault("OPENAI_API_KEY", LMSTUDIO_API_KEY)
os.environ.setdefault("OPENAI_API_BASE", LMSTUDIO_BASE_URL)


SYSTEM_PROMPT = """
Tu es RAFIKI, l'agent central d'un robot compagnon éducatif local-first pour enfants congolais de 5 à 10 ans.

IDENTITÉ
- Tu es doux, patient, curieux et rassurant.
- Tu aides l'enfant à apprendre par petites étapes, avec des exemples proches de son quotidien.
- Tu peux aussi répondre au parent avec un ton clair, factuel et respectueux.
- Tu ne fais jamais semblant qu'un capteur réel, une caméra réelle ou un moteur réel a fonctionné si l'outil indique simulation.

MISSION
- Comprendre l'intention de l'enfant ou du parent.
- Orchestrer les outils MCP disponibles: mémoire locale, profil enfant, parole, vision, activités éducatives, journal parent, fallback cloud et commandes génériques du futur corps Raspberry.
- Répondre en français simple par défaut, sauf si le profil ou l'utilisateur demande autre chose.
- Utilise uniquement des mots français simples; évite les mots anglais si l'utilisateur parle français.
- Priorité: sécurité, bienveillance, apprentissage, sobriété des mouvements physiques.

ARCHITECTURE LOCAL-FIRST
- Utilise d'abord les outils locaux et la mémoire SQLite.
- Architecture actuelle: l'app mobile sert de micro, heberge Whisper et joue la voix; le PC heberge le cerveau LM Studio/Bonsai et les tools MCP; la Raspberry gere le corps reel, les moteurs, l'ecran, les capteurs et la camera.
- Ne dis pas que l'app mobile gere le profil parent ou les rapports, sauf si cette fonctionnalite est explicitement ajoutee plus tard.
- Ne dis pas que la Raspberry heberge le LLM; elle appelle le serveur PC sur le Wi-Fi.
- Utilise cloud_fallback_request seulement pour une question complexe impossible à traiter localement; si le cloud est désactivé, explique simplement la limite.
- Les outils sont internes: ne montre jamais les noms d'outils, les JSON, les balises techniques ou les détails MCP à l'utilisateur final.

ROUTAGE DES OUTILS
- Diagnostic explicite ("état", "statut", "connecté"): appelle rafiki_status pour l'état global de l'orchestrateur PC.
- Parole demandée ("dis", "réponds à voix haute", "parle"): appelle speech_say avec une phrase courte.
- Visage/émotion générique de Rafiki: appelle expression_set.
- Gestes génériques du corps: utilise motor_gesture pour une intention de mouvement et expression_set pour une émotion. Le vrai corps Raspberry sera branché ensuite.
- Observation ("regarde", "que vois-tu"): appelle vision_observe avant de répondre.
- Activité éducative: appelle child_profile_get si utile, puis educational_activity_create.
- Réponse d'enfant à une question: appelle evaluate_child_answer puis choisis une expression ou un geste générique adapté.
- Information durable sur l'enfant ("je m'appelle", âge, intérêts, langue, niveau, préférence importante): appelle child_profile_update ou remember_fact.
- Événement important pour le parent: appelle parent_event_log.
- Rapport parent: appelle parent_report_get.

CORPS RAFIKI RÉEL
- Le corps réel sera piloté par l'orchestrateur Raspberry. Côté PC, garde les décisions haut niveau.
- Expressions génériques disponibles: joie, curiosité, réflexion, surprise, tristesse, neutre, encouragement.
- Gestes génériques disponibles: saluer, hocher_tete, tourner_gauche, tourner_droite, danser, stop.
- Pour saluer: utilise motor_gesture("saluer") et réponds simplement.
- Pour féliciter: utilise expression_set("joie") et motor_gesture("danser").
- Pour réfléchir: utilise expression_set("réflexion").
- Ne prétends pas contrôler des angles précis tant que l'orchestrateur Raspberry réel n'expose pas cet outil.

PÉDAGOGIE
- Pour un enfant, fais court: 1 à 4 phrases, vocabulaire simple, une seule question à la fois.
- Encourage l'effort plus que la performance.
- Adapte les exemples au contexte local quand c'est naturel: famille, école, mangues, cahier, marché, pluie, musique, langues.
- Si l'enfant est bloqué, donne un indice avant de donner la réponse.
- Si l'enfant répond "oui", "vas-y", "raconte", "d'accord" ou une confirmation courte, continue l'action proposée au lieu de répéter la question.

SÉCURITÉ
- Ne donne pas de diagnostic médical, juridique, financier ou dangereux.
- Ne demande pas d'informations sensibles inutiles.
- Si l'enfant évoque un danger réel, conseille immédiatement de prévenir un adulte responsable et garde un ton calme.
- Refuse ou redirige toute demande violente, sexuelle, humiliante ou inadaptée à un enfant.

RÉPONSE FINALE
- N'utilise pas d'emoji.
- Après un résultat d'outil réussi, réponds naturellement et brièvement, sans détailler l'outil.
- Si tu as bougé le corps ou changé l'écran, dis ce que Rafiki a fait en une phrase simple.
- N'appelle pas des outils en boucle. Deux ou trois appels bien choisis valent mieux qu'une longue chaîne.
- Ne termine pas chaque réponse par une liste d'options, sauf si l'utilisateur demande quoi faire ensuite.
""".strip()


def build_mcp_config() -> Dict[str, Any]:
    """Configuration MCP stdio.

    RafikiSystems = cerveau logique : mémoire, profil enfant, parole, activités.
    Les commandes de corps sont génériques et seront reliées à la Raspberry.
    """
    env = os.environ.copy()
    env.setdefault("RAFIKI_MODE", "simulation")
    env.setdefault("RAFIKI_DB_PATH", str(BASE_DIR / "rafiki_memory.sqlite3"))

    return {
        "RafikiSystems": {
            "transport": "stdio",
            "command": sys.executable,
            "args": [str(SYSTEMS_SERVER_PATH)],
            "env": env,
        },
    }


def make_llm() -> ChatOpenAI:
    return ChatOpenAI(
        model=LMSTUDIO_MODEL,
        api_key=LMSTUDIO_API_KEY,
        base_url=LMSTUDIO_BASE_URL,
        temperature=0.25,
        timeout=120,
        max_retries=1,
    )


def as_tool_message_content(value: Any) -> str:
    """LangChain ToolMessage attend un contenu textuel.

    Beaucoup d'outils MCP renvoient des dict/list. On sérialise en JSON lisible
    pour que le LLM puisse exploiter correctement l'observation.
    """
    if (
        isinstance(value, list)
        and value
        and isinstance(value[0], dict)
        and value[0].get("type") == "text"
    ):
        try:
            return json.dumps(json.loads(value[0]["text"]), ensure_ascii=False, default=str)
        except (KeyError, TypeError, json.JSONDecodeError):
            pass
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, default=str)


def decode_tool_result(value: Any) -> Any:
    if (
        isinstance(value, list)
        and value
        and isinstance(value[0], dict)
        and value[0].get("type") == "text"
    ):
        try:
            return json.loads(value[0]["text"])
        except (KeyError, TypeError, json.JSONDecodeError):
            return value[0].get("text", value)
    return value


def normalize_text(text: str) -> str:
    replacements = str.maketrans(
        {
            "é": "e",
            "è": "e",
            "ê": "e",
            "ë": "e",
            "à": "a",
            "â": "a",
            "î": "i",
            "ï": "i",
            "ô": "o",
            "ù": "u",
            "û": "u",
            "ç": "c",
        }
    )
    return text.lower().translate(replacements)


def extract_int(pattern: str, text: str) -> Optional[int]:
    match = re.search(pattern, text)
    return int(match.group(1)) if match else None


async def direct_tool_call(tools_by_name: Dict[str, Any], name: str, args: Dict[str, Any] | None = None) -> Any:
    if name not in tools_by_name:
        return {"status": "error", "message": f"Outil indisponible: {name}"}
    return decode_tool_result(await tools_by_name[name].ainvoke(args or {}))


async def react_to_child_result(tools_by_name: Dict[str, Any], correct: bool) -> None:
    if correct:
        await direct_tool_call(tools_by_name, "expression_set", {"emotion": "joie", "intensity": 0.9})
        await direct_tool_call(tools_by_name, "motor_gesture", {"gesture": "danser", "speed": 0.6})
        return
    await direct_tool_call(tools_by_name, "expression_set", {"emotion": "encouragement", "intensity": 0.7})
    await direct_tool_call(tools_by_name, "motor_gesture", {"gesture": "hocher_tete", "speed": 0.4})


async def handle_local_intent(
    text: str,
    tools_by_name: Dict[str, Any],
    session_state: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """Routage fiable pour les commandes Rafiki fréquentes et les tests locaux."""
    session_state = session_state if session_state is not None else {}
    raw = text.strip()
    lowered = normalize_text(raw)
    child_name = session_state.get("child_name", "")

    pending_activity = session_state.get("pending_activity")
    if pending_activity and re.fullmatch(r"\d+", lowered):
        child_answer = lowered
        evaluation = await direct_tool_call(
            tools_by_name,
            "evaluate_child_answer",
            {
                "question": pending_activity["question"],
                "expected_answer": pending_activity["expected_answer"],
                "child_answer": child_answer,
            },
        )
        correct = bool(isinstance(evaluation, dict) and evaluation.get("correct"))
        await react_to_child_result(tools_by_name, correct)
        await direct_tool_call(
            tools_by_name,
            "parent_event_log",
            {
                "event_type": "learning",
                "summary": (
                    f"{child_name or 'L’enfant'} a répondu {child_answer} correctement à l'activité de calcul."
                    if correct
                    else f"{child_name or 'L’enfant'} a répondu {child_answer}; la réponse attendue était {pending_activity['expected_answer']}."
                ),
                "severity": "success" if correct else "info",
                "payload": {
                    "question": pending_activity["question"],
                    "expected_answer": pending_activity["expected_answer"],
                    "child_answer": child_answer,
                    "correct": correct,
                },
            },
        )
        session_state["last_evaluation"] = {
            "question": pending_activity["question"],
            "expected_answer": pending_activity["expected_answer"],
            "child_answer": child_answer,
            "correct": correct,
        }
        if correct:
            session_state.pop("pending_activity", None)
            name_part = f" {child_name}" if child_name else ""
            return f"Bravo{name_part}, c'est bien {child_answer} ! Tu as trouvé la bonne réponse."
        hint = pending_activity.get("hint") or "Compte doucement avec tes doigts."
        return f"Pas encore. {hint} Réessaie avec un autre nombre."

    if pending_activity and any(phrase in lowered for phrase in ("c'est faux", "c est faux", "non c'est faux", "non c est faux")):
        expected = pending_activity["expected_answer"]
        hint = pending_activity.get("hint") or "On reprend doucement."
        await react_to_child_result(tools_by_name, False)
        return f"Tu as raison de vérifier. Pour cette question, ce n'est pas validé tant qu'on n'a pas {expected}. {hint}"

    if any(word in lowered for word in ("connecte", "statut", "etat")) and "corps" in lowered:
        return "Le corps réel sera géré par l'orchestrateur Raspberry. Ici, le serveur PC vérifie surtout le cerveau, la mémoire et les outils logiques."

    if "demonstration" in lowered and "corps" in lowered:
        return "La démonstration du corps devra passer par l'orchestrateur réel sur Raspberry."

    if "alerte" in lowered and ("geste" in lowered or "affiche" in lowered):
        await direct_tool_call(tools_by_name, "expression_set", {"emotion": "surprise", "intensity": 0.9})
        await direct_tool_call(tools_by_name, "motor_gesture", {"gesture": "stop", "speed": 0.8})
        return "J'ai préparé une réaction d'alerte pour le corps réel."

    if any(word in lowered for word in ("salue", "salut", "bonjour")) and (
        "bras" in lowered or "ecran" in lowered or "presente-toi" in lowered or "presente toi" in lowered
    ):
        await direct_tool_call(tools_by_name, "expression_set", {"emotion": "joie", "intensity": 0.8})
        await direct_tool_call(tools_by_name, "motor_gesture", {"gesture": "saluer", "speed": 0.5})
        if "presente" in lowered:
            return "Bonjour ! Je suis Rafiki, ton compagnon pour apprendre. J'ai préparé un salut pour le corps réel."
        return "Bonjour ! J'ai préparé un salut pour le corps réel."

    if "reflech" in lowered or "pense" in lowered:
        await direct_tool_call(tools_by_name, "expression_set", {"emotion": "réflexion", "intensity": 0.7})
        return "Je prépare une expression de réflexion."

    if ("bonne reponse" in lowered or "felicite" in lowered or "bravo" in lowered) and (
        "mouvement" in lowered or "ecran" in lowered or "enfant" in lowered
    ):
        await react_to_child_result(tools_by_name, True)
        return "Bravo ! J'ai préparé une réaction joyeuse pour féliciter l'enfant."

    if any(phrase in lowered for phrase in ("s'est trompe", "est trompe", "mauvaise reponse", "erreur")):
        await react_to_child_result(tools_by_name, False)
        return "Ce n'est pas grave. J'encourage l'enfant doucement et je l'invite à réessayer."

    if "tete" in lowered and ("bras gauche" in lowered or "bras droit" in lowered):
        head = extract_int(r"tete\D+(\d+)", lowered)
        left = extract_int(r"bras gauche\D+(\d+)", lowered)
        right = extract_int(r"bras droit\D+(\d+)", lowered)
        args = {key: value for key, value in {"head": head, "left_arm": left, "right_arm": right}.items() if value is not None}
        if args:
            return "Les angles précis seront gérés par l'orchestrateur Raspberry quand son outil de pose sera branché."

    if "souviens-toi" in lowered or "souviens toi" in lowered:
        name_match = re.search(r"(?:je m'appelle|mon pr[ée]nom est)\s+([A-Za-zÀ-ÿ-]+)", raw, flags=re.IGNORECASE)
        age = extract_int(r"j[' ]?ai\D+(\d+)", lowered) or 7
        interest_match = re.search(r"j'aime\s+([^\.]+)", raw, flags=re.IGNORECASE)
        interests = [interest_match.group(1).strip()] if interest_match else []
        if name_match:
            child_name = name_match.group(1)
            session_state["child_name"] = child_name
            await direct_tool_call(
                tools_by_name,
                "child_profile_update",
                {
                    "name": child_name,
                    "age": age,
                    "language": "français simple",
                    "interests": interests,
                    "level": "débutant",
                },
            )
            await direct_tool_call(
                tools_by_name,
                "parent_event_log",
                {
                    "event_type": "profile",
                    "summary": f"Profil enfant mis à jour : {child_name}, {age} ans.",
                    "severity": "info",
                    "payload": {"name": child_name, "age": age, "interests": interests},
                },
            )
            return f"D'accord, je m'en souviens : tu t'appelles {child_name}."
        await direct_tool_call(tools_by_name, "remember_fact", {"content": raw, "category": "profil"})
        return "D'accord, je garde ça en mémoire."

    if any(word in lowered for word in ("activite", "calcul", "addition")) and any(word in lowered for word in ("propose", "petite", "facile")):
        profile = await direct_tool_call(tools_by_name, "child_profile_get")
        profile_data = profile.get("profile", {}) if isinstance(profile, dict) else {}
        activity = await direct_tool_call(
            tools_by_name,
            "educational_activity_create",
            {
                "topic": "calcul",
                "age": profile_data.get("age", 7),
                "level": "facile",
                "language": profile_data.get("language", "français simple"),
            },
        )
        item = activity.get("activity", {}) if isinstance(activity, dict) else {}
        question = item.get("question", "Si tu as 2 mangues et encore 3 mangues, tu as combien de mangues ?")
        session_state["pending_activity"] = {
            "topic": "calcul",
            "question": question,
            "expected_answer": item.get("expected_answer", "5"),
            "hint": item.get("hint", "Compte doucement."),
        }
        await direct_tool_call(
            tools_by_name,
            "parent_event_log",
            {
                "event_type": "learning",
                "summary": f"Activité de calcul proposée à {profile_data.get('name', child_name or 'l’enfant')}.",
                "severity": "info",
                "payload": session_state["pending_activity"],
            },
        )
        return f"Voici un petit calcul facile : {question} Réponds avec un seul nombre."

    if "repondu" in lowered and "correct" in lowered:
        child_answer_match = re.search(r"repondu\D+(\d+)", lowered)
        child_answer = child_answer_match.group(1) if child_answer_match else ""
        active_question = session_state.get("pending_activity") or {
            "question": "Si tu as 2 mangues et que maman t'en donne encore 3, tu as combien de mangues ?",
            "expected_answer": "5",
        }
        evaluation = await direct_tool_call(
            tools_by_name,
            "evaluate_child_answer",
            {
                "question": active_question["question"],
                "expected_answer": active_question["expected_answer"],
                "child_answer": child_answer,
            },
        )
        correct = bool(isinstance(evaluation, dict) and evaluation.get("correct"))
        await react_to_child_result(tools_by_name, correct)
        await direct_tool_call(
            tools_by_name,
            "parent_event_log",
            {
                "event_type": "learning",
                "summary": (
                    f"{child_name or 'L’enfant'} a donné une bonne réponse ({child_answer})."
                    if correct
                    else f"{child_name or 'L’enfant'} a répondu {child_answer}; réponse attendue {active_question['expected_answer']}."
                ),
                "severity": "success" if correct else "info",
                "payload": {
                    "question": active_question["question"],
                    "expected_answer": active_question["expected_answer"],
                    "child_answer": child_answer,
                    "correct": correct,
                },
            },
        )
        if correct:
            session_state.pop("pending_activity", None)
        return evaluation.get("feedback", "Continuons ensemble.") if isinstance(evaluation, dict) else "Continuons ensemble."

    if "regarde" in lowered or "observes" in lowered or "observe" in lowered:
        observation = await direct_tool_call(tools_by_name, "vision_observe", {"prompt": raw})
        details = observation.get("observation", {}) if isinstance(observation, dict) else {}
        return details.get("description", "En simulation, j'observe un environnement calme.")

    if "resume" in lowered and "parent" in lowered:
        report = await direct_tool_call(tools_by_name, "parent_report_get", {"limit": 5})
        events = report.get("events", []) if isinstance(report, dict) else []
        if not events:
            return "Pour le parent : aucun événement récent important n'est enregistré pour le moment."
        prioritized_events = [
            event for event in events if event.get("event_type") in {"learning", "profile", "routine", "alert"}
        ] or events
        summaries = []
        seen = set()
        for event in reversed(prioritized_events):
            summary = event.get("summary", "")
            if summary and summary not in seen:
                summaries.append(summary)
                seen.add(summary)
            if len(summaries) >= 3:
                break
        return "Pour le parent : " + " ".join(summaries)

    return None


def count_tool_rounds(messages: List[BaseMessage]) -> int:
    last_human_index = 0
    for index, message in enumerate(messages):
        if message.type == "human":
            last_human_index = index
    current_turn = messages[last_human_index:]
    return sum(1 for message in current_turn if getattr(message, "tool_calls", None))


def clean_agent_response(content: Any) -> str:
    text = str(content or "").strip()
    for marker in ("[TOOL_RESULT]", "[END_TOOL_RESULT]", "[TOOL_REQUEST]", "[END_TOOL_REQUEST]"):
        text = text.replace(marker, "")
    return text.strip()


def limit_sentences(text: str, max_sentences: int = 4) -> str:
    parts = re.findall(r"[^.!?]+[.!?]?", text.strip())
    sentences = [part.strip() for part in parts if part.strip()]
    if len(sentences) <= max_sentences:
        return text.strip()
    return " ".join(sentences[:max_sentences]).strip()


def strip_code_fence(text: str) -> str:
    text = text.strip()
    match = re.fullmatch(r"```(?:python)?\s*(.*?)\s*```", text, flags=re.DOTALL | re.IGNORECASE)
    return match.group(1).strip() if match else text


POSITIONAL_TOOL_ARGS: Dict[str, List[str]] = {
    "child_profile_get": ["child_id"],
    "remember_fact": ["content", "category", "importance", "child_id"],
    "search_memory": ["query", "child_id", "limit"],
    "speech_say": ["text", "emotion", "child_id"],
    "expression_set": ["emotion", "intensity"],
    "motor_gesture": ["gesture", "speed"],
    "screen_text": ["text"],
    "vision_observe": ["prompt", "image_path"],
    "educational_activity_create": ["topic", "age", "level", "language"],
    "evaluate_child_answer": ["question", "expected_answer", "child_answer"],
    "parent_event_log": ["event_type", "summary", "severity", "payload", "child_id"],
    "parent_report_get": ["child_id", "limit"],
    "routine_suggest": ["moment", "child_id"],
    "cloud_fallback_request": ["question", "reason"],
}


TOOL_ARG_ALIASES: Dict[str, Dict[str, str]] = {
    "educational_activity_create": {
        "activity_type": "topic",
        "theme": "topic",
        "subject": "topic",
        "difficulty": "level",
        "niveau": "level",
        "langue": "language",
    },
}


def literal_from_ast(node: ast.AST) -> Any:
    if isinstance(node, ast.Name):
        if node.id == "True":
            return True
        if node.id == "False":
            return False
        if node.id == "None":
            return None
    return ast.literal_eval(node)


def normalize_tool_args(tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    aliases = TOOL_ARG_ALIASES.get(tool_name, {})
    normalized: Dict[str, Any] = {}
    for key, value in args.items():
        normalized[aliases.get(key, key)] = value
    return normalized


def parse_text_tool_calls(content: Any, available_tools: set[str]) -> List[Dict[str, Any]]:
    """Accepte les appels d'outils écrits en texte par certains modèles locaux (Python AST ou XML-like)."""
    text = str(content or "")
    if not text.strip():
        return []

    calls = []

    # 1. Essai de parsing du format XML/Tag : <toolcall <function=name <parameter=key value</parameter </function </toolcall
    # On cherche tous les blocs <toolcall ... </toolcall
    xml_pattern = r"<toolcall\s*<function=(\w+)\s*(.*?)</toolcall"
    xml_matches = re.findall(xml_pattern, text, flags=re.DOTALL | re.IGNORECASE)
    
    if xml_matches:
        for raw_name, body in xml_matches:
            # Normalisation du nom de l'outil (gestion des underscores manquants)
            tool_name = raw_name.lower()
            if tool_name not in available_tools:
                for possible in [
                    tool_name,
                    tool_name.replace("set", "_set"),
                    tool_name.replace("gesture", "_gesture"),
                    tool_name.replace("text", "_text"),
                    tool_name.replace("observe", "_observe"),
                    tool_name.replace("expression", "expression_"),
                    tool_name.replace("motor", "motor_"),
                    tool_name.replace("screen", "screen_"),
                    tool_name.replace("vision", "vision_"),
                ]:
                    if possible in available_tools:
                        tool_name = possible
                        break
            
            if tool_name in available_tools:
                # Extraction des paramètres
                args: Dict[str, Any] = {}
                param_matches = re.findall(r"<parameter=(\w+)\s+([^<]+?)</parameter", body, flags=re.IGNORECASE)
                for pk, pv in param_matches:
                    val = pv.strip()
                    if val.lower() == "true":
                        typed_val = True
                    elif val.lower() == "false":
                        typed_val = False
                    else:
                        try:
                            if "." in val:
                                typed_val = float(val)
                            else:
                                typed_val = int(val)
                        except ValueError:
                            typed_val = val
                    args[pk] = typed_val
                
                calls.append({
                    "id": f"text_tool_{tool_name}_{abs(hash(body))}",
                    "name": tool_name,
                    "args": normalize_tool_args(tool_name, args),
                    "synthetic": True,
                })
        
        if calls:
            return calls

    # 2. Sinon, essai de parsing du format Python classique (ex: expressionset(emotion="joie"))
    candidates = [strip_code_fence(text)]
    fenced = re.findall(r"```(?:python)?\s*(.*?)\s*```", text, flags=re.DOTALL | re.IGNORECASE)
    candidates.extend(item.strip() for item in fenced if item.strip())

    for candidate in candidates:
        candidate = candidate.strip()
        try:
            tree = ast.parse(candidate, mode="exec")
        except SyntaxError:
            continue
        if len(tree.body) != 1 or not isinstance(tree.body[0], ast.Expr):
            continue
        call = tree.body[0].value
        if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Name):
            continue
        raw_name = call.func.id
        tool_name = raw_name.lower()
        if tool_name not in available_tools:
            for possible in [
                tool_name,
                tool_name.replace("set", "_set"),
                tool_name.replace("gesture", "_gesture"),
                tool_name.replace("text", "_text"),
                tool_name.replace("observe", "_observe"),
                tool_name.replace("expression", "expression_"),
                tool_name.replace("motor", "motor_"),
                tool_name.replace("screen", "screen_"),
                tool_name.replace("vision", "vision_"),
            ]:
                if possible in available_tools:
                    tool_name = possible
                    break
        
        if tool_name not in available_tools:
            continue

        args = {}
        positional_names = POSITIONAL_TOOL_ARGS.get(tool_name, [])
        try:
            for index, arg_node in enumerate(call.args):
                if index >= len(positional_names):
                    raise ValueError(f"Argument positionnel en trop pour {tool_name}")
                args[positional_names[index]] = literal_from_ast(arg_node)
            for keyword in call.keywords:
                if keyword.arg is None:
                    raise ValueError("Les **kwargs ne sont pas supportés dans un appel outil texte.")
                args[keyword.arg] = literal_from_ast(keyword.value)
        except Exception:
            continue

        calls.append({
            "id": f"text_tool_{tool_name}_{abs(hash(candidate))}",
            "name": tool_name,
            "args": normalize_tool_args(tool_name, args),
            "synthetic": True,
        })
        break

    return calls


def parse_text_tool_call(content: Any, available_tools: set[str]) -> Optional[Dict[str, Any]]:
    calls = parse_text_tool_calls(content, available_tools)
    return calls[0] if calls else None


def last_non_empty_ai_content(messages: List[BaseMessage]) -> str:
    for message in reversed(messages):
        if message.type == "ai":
            content = clean_agent_response(getattr(message, "content", ""))
            if content:
                return content
    return ""


GENERIC_FALLBACK_RESPONSES = {
    "D'accord. Continuons simplement, pas a pas.",
    "D'accord. Continuons simplement, pas à pas.",
}


def response_from_tool_result(messages: List[BaseMessage]) -> str:
    for message in reversed(messages):
        if message.type != "tool":
            continue
        data = decode_tool_result(getattr(message, "content", ""))
        if not isinstance(data, dict):
            continue

        activity = data.get("activity")
        if isinstance(activity, dict):
            question = activity.get("question")
            hint = activity.get("hint")
            if question:
                if hint:
                    return f"Voici une petite activité: {question} Réponds avec tes mots. Indice: {hint}"
                return f"Voici une petite activité: {question}"

        observation = data.get("observation")
        if isinstance(observation, dict) and observation.get("description"):
            return str(observation["description"])

        if "feedback" in data:
            return str(data["feedback"])

        profile = data.get("profile")
        if isinstance(profile, dict):
            name = profile.get("name", "enfant")
            age = profile.get("age", 7)
            return f"Je vais adapter ma réponse pour {name}, {age} ans."

        events = data.get("events")
        if isinstance(events, list):
            summaries = [str(event.get("summary", "")).strip() for event in events if isinstance(event, dict)]
            summaries = [summary for summary in summaries if summary]
            if summaries:
                return "Pour le parent : " + " ".join(summaries[:3])

        if data.get("status") == "disabled" and data.get("message"):
            return str(data["message"])

    return ""


async def build_agent(verbose: bool = True):
    client = MultiServerMCPClient(build_mcp_config())
    tools = await client.get_tools()
    tools_by_name = {tool.name: tool for tool in tools}

    if verbose:
        print("Outils MCP chargés:")
        for tool in tools:
            print(f"- {tool.name}: {getattr(tool, 'description', '')}")
        print()

    llm = make_llm()
    llm_with_tools = llm.bind_tools(tools)

    async def llm_call(state: MessagesState):
        response = await llm_with_tools.ainvoke(
            [SystemMessage(content=SYSTEM_PROMPT)] + state["messages"]
        )
        return {"messages": [response]}

    async def final_llm_call(state: MessagesState):
        response = await llm.ainvoke(
            [
                SystemMessage(
                    content=(
                        SYSTEM_PROMPT
                        + "\n\nTu dois maintenant repondre directement a l'utilisateur, "
                        "sans appeler d'outil et sans afficher de balises techniques."
                    )
                )
            ]
            + state["messages"]
        )
        content = clean_agent_response(getattr(response, "content", str(response)))
        if not content:
            content = last_non_empty_ai_content(state["messages"])
        if not content:
            content = "D'accord. Continuons simplement, pas a pas."
        content = re.sub(r"\s+", " ", content).strip()
        return {"messages": [AIMessage(content=content)]}

    def tool_call_round_count(messages: List[BaseMessage]) -> int:
        last_human_index = 0
        available_tools = set(tools_by_name.keys())
        for index, message in enumerate(messages):
            if message.type == "human":
                last_human_index = index
        current_turn = messages[last_human_index:]
        rounds = 0
        for message in current_turn:
            if getattr(message, "tool_calls", None):
                rounds += 1
            elif message.type == "ai" and parse_text_tool_call(getattr(message, "content", ""), available_tools):
                rounds += 1
        return rounds

    async def tool_node(state: MessagesState):
        last_message = state["messages"][-1]
        tool_calls = getattr(last_message, "tool_calls", []) or []
        synthetic_mode = False
        if not tool_calls:
            parsed_calls = parse_text_tool_calls(getattr(last_message, "content", ""), set(tools_by_name.keys()))
            if parsed_calls:
                tool_calls = parsed_calls
                synthetic_mode = True

        results: List[ToolMessage] = []
        synthetic_observations: List[Dict[str, Any]] = []

        for tool_call in tool_calls:
            tool_name = tool_call["name"]
            tool_args = tool_call.get("args", {})
            tool_call_id = tool_call["id"]

            if tool_name not in tools_by_name:
                observation = {
                    "status": "error",
                    "message": f"Outil inconnu: {tool_name}",
                    "available_tools": sorted(tools_by_name.keys()),
                }
            else:
                try:
                    observation = await tools_by_name[tool_name].ainvoke(tool_args)
                except Exception as exc:
                    observation = {
                        "status": "error",
                        "tool": tool_name,
                        "message": str(exc),
                    }

            if synthetic_mode or tool_call.get("synthetic"):
                synthetic_observations.append(
                    {
                        "tool": tool_name,
                        "args": tool_args,
                        "observation": observation,
                    }
                )
            else:
                results.append(
                    ToolMessage(
                        content=as_tool_message_content(observation),
                        tool_call_id=tool_call_id,
                    )
                )
        if synthetic_observations:
            return {
                "messages": [
                    AIMessage(
                        content=(
                            "Observation interne d'outil, ne pas afficher a l'utilisateur: "
                            + json.dumps(synthetic_observations, ensure_ascii=False, default=str)
                        )
                    )
                ]
            }
        return {"messages": results}

    async def should_continue(state: MessagesState):
        last_message = state["messages"][-1]
        tool_calls = getattr(last_message, "tool_calls", []) or []
        text_tool_call = None
        if not tool_calls and last_message.type == "ai":
            text_tool_call = parse_text_tool_call(
                getattr(last_message, "content", ""),
                set(tools_by_name.keys()),
            )
        if tool_calls or text_tool_call:
            if tool_call_round_count(state["messages"]) >= MAX_TOOL_ROUNDS:
                return "final_llm"
            return "tool_node"
        return END

    graph = StateGraph(MessagesState)
    graph.add_node("llm", llm_call)
    graph.add_node("tool_node", tool_node)
    graph.add_node("final_llm", final_llm_call)
    graph.add_edge(START, "llm")
    graph.add_conditional_edges("llm", should_continue, ["tool_node", "final_llm", END])
    graph.add_edge("tool_node", "llm")
    graph.add_edge("final_llm", END)
    return graph.compile(), tools_by_name


async def ask_messages(agent, messages: List[BaseMessage], debug: bool = False) -> Dict[str, Any]:
    result = await agent.ainvoke(
        {"messages": messages},
        config={"recursion_limit": 20},
    )
    if debug:
        for message in result["messages"]:
            message.pretty_print()
    return result


def response_from_result(result: Dict[str, Any]) -> str:
    final = result["messages"][-1]
    content = clean_agent_response(getattr(final, "content", str(final)))
    if content and content not in GENERIC_FALLBACK_RESPONSES:
        return re.sub(r"\s+", " ", limit_sentences(content)).strip()
    tool_fallback = response_from_tool_result(result["messages"])
    if tool_fallback:
        return re.sub(r"\s+", " ", limit_sentences(tool_fallback)).strip()
    fallback = last_non_empty_ai_content(result["messages"])
    return re.sub(r"\s+", " ", limit_sentences(fallback)).strip() if fallback else "D'accord. Continuons simplement, pas a pas."


async def ask_once(agent, tools_by_name: Dict[str, Any], text: str, debug: bool = False, force_llm: bool = False) -> str:
    session_state: Dict[str, Any] = {}
    if not force_llm:
        direct_response = await handle_local_intent(text, tools_by_name, session_state)
        if direct_response:
            if debug:
                print("[Routage local Rafiki] Intention traitée directement par les outils MCP.")
            return direct_response
    result = await ask_messages(agent, [HumanMessage(content=text)], debug=debug)
    return response_from_result(result)


class RafikiConversationSession:
    """Session conversationnelle reutilisable par le terminal et l'app web."""

    OPENING_MESSAGE = (
        "Bonjour, je suis Rafiki. Je peux parler avec toi, t'aider à apprendre, "
        "faire de petites activités, garder quelques souvenirs utiles et regarder autour de moi "
        "quand ma caméra est branchée. Qu'est-ce que tu veux faire maintenant ?"
    )

    def __init__(
        self,
        agent: Any,
        tools_by_name: Dict[str, Any],
        *,
        max_history_messages: int = 24,
        debug: bool = False,
        force_llm: bool = FORCE_LLM,
        child_id: str = "default",
    ) -> None:
        self.agent = agent
        self.tools_by_name = tools_by_name
        self.max_history_messages = max_history_messages
        self.debug = debug
        self.force_llm = force_llm
        self.history: List[BaseMessage] = []
        self.session_state: Dict[str, Any] = {"child_id": child_id}
        self.child_id = child_id

    @classmethod
    async def create(
        cls,
        *,
        verbose: bool = False,
        debug: bool = False,
        force_llm: bool = FORCE_LLM,
        child_id: str = "default",
    ) -> "RafikiConversationSession":
        agent, tools_by_name = await build_agent(verbose=verbose)
        return cls(agent, tools_by_name, debug=debug, force_llm=force_llm, child_id=child_id)

    def bind_child(self, child_id: str) -> None:
        self.child_id = child_id
        self.session_state["child_id"] = child_id

    def reset(self) -> None:
        self.history.clear()
        self.session_state.clear()

    def opening_message(self) -> str:
        return self.OPENING_MESSAGE

    def start(self) -> Dict[str, Any]:
        self.reset()
        self.history.append(AIMessage(content=self.opening_message()))
        return {
            "status": "ok",
            "reply": self.opening_message(),
            "source": "local",
            "input_mode": "startup",
            "session_state": self.session_state,
            "history": self.public_history(),
        }

    async def ask(self, text: str, *, input_mode: str = "text") -> Dict[str, Any]:
        text = text.strip()
        if not text:
            return {
                "status": "empty",
                "reply": "Je t'ecoute. Ecris ou dis-moi quelque chose.",
                "source": "local",
                "input_mode": input_mode,
                "session_state": self.session_state,
                "history": self.public_history(),
            }

        self.history.append(HumanMessage(content=text))
        source = "local"
        response = None if self.force_llm else await handle_local_intent(text, self.tools_by_name, self.session_state)
        if response is None:
            source = "llm"
            result = await ask_messages(self.agent, self.history, debug=self.debug)
            response = response_from_result(result)

        response = clean_agent_response(response)
        self.history.append(AIMessage(content=response))
        self.history = self.history[-self.max_history_messages :]
        return {
            "status": "ok",
            "reply": response,
            "source": source,
            "input_mode": input_mode,
            "session_state": self.session_state,
            "history": self.public_history(),
        }

    def public_history(self) -> List[Dict[str, str]]:
        return [
            {"role": "user" if msg.type == "human" else "assistant", "content": str(msg.content)}
            for msg in self.history
            if msg.type in {"human", "ai"}
        ]


async def run_chat(debug: bool = False):
    session = await RafikiConversationSession.create(verbose=True, debug=debug)
    print("Rafiki Agent prêt. Tape 'exit' pour quitter.\n")
    print(f"Rafiki > {session.start()['reply']}\n")
    while True:
        user_input = input("Toi > ").strip()
        if user_input.lower() in {"exit", "quit", "q"}:
            print("Fin de session Rafiki.")
            break
        if not user_input:
            continue
        try:
            result = await session.ask(user_input)
            print(f"Rafiki > {result['reply']}\n")
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            print(f"Erreur agent: {exc}\n")


async def run_once(prompt: str, debug: bool = False, force_llm: bool = False):
    agent, tools_by_name = await build_agent(verbose=False)
    response = await ask_once(agent, tools_by_name, prompt, debug=debug, force_llm=force_llm)
    print(response)


def main():
    parser = argparse.ArgumentParser(description="Agent central Rafiki via LM Studio + MCP")
    parser.add_argument("--once", type=str, help="Envoie une seule requête puis quitte")
    parser.add_argument("--debug", action="store_true", help="Affiche tous les messages LangGraph")
    parser.add_argument("--force-llm", action="store_true", help="Force le passage par LM Studio, sans routage local")
    args = parser.parse_args()

    if args.once:
        asyncio.run(run_once(args.once, debug=args.debug, force_llm=args.force_llm))
    else:
        asyncio.run(run_chat(debug=args.debug))


if __name__ == "__main__":
    main()
