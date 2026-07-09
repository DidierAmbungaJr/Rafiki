"""Test du flux enfant <-> Rafiki pour les activités éducatives.

Ce test cible le scénario conversationnel, pas seulement les outils isolés :
- mémoriser le profil enfant ;
- proposer une activité de calcul ;
- évaluer une mauvaise réponse courte ;
- garder la question ouverte ;
- accepter ensuite la bonne réponse ;
- produire un résumé parent utile.

Lancer depuis rafiki_orchestrateur :
python test_rafiki_educational_flow.py
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict

from rafiki_agent import build_agent, handle_local_intent


async def ask(tools_by_name: Dict[str, Any], session_state: Dict[str, Any], text: str) -> str:
    response = await handle_local_intent(text, tools_by_name, session_state)
    if response is None:
        raise AssertionError(f"Le routage éducatif n'a pas traité: {text!r}")
    print(f"\nToi > {text}")
    print(f"Rafiki > {response}")
    return response


async def main() -> None:
    _agent, tools_by_name = await build_agent(verbose=False)
    session_state: Dict[str, Any] = {}

    response = await ask(
        tools_by_name,
        session_state,
        "Mon prénom est Amani, j'ai 7 ans et j'aime les animaux. Souviens-toi de ça.",
    )
    assert "Amani" in response
    assert session_state.get("child_name") == "Amani"

    response = await ask(
        tools_by_name,
        session_state,
        "Propose-moi une petite activité de calcul facile.",
    )
    assert "mangues" in response
    assert session_state.get("pending_activity", {}).get("expected_answer") == "5"

    response = await ask(tools_by_name, session_state, "4")
    assert "Pas encore" in response
    assert session_state.get("pending_activity"), "La question doit rester ouverte après une erreur."

    response = await ask(tools_by_name, session_state, "5")
    assert "Bravo" in response
    assert "pending_activity" not in session_state

    response = await ask(tools_by_name, session_state, "Prépare un petit résumé pour le parent.")
    assert "parent" in response.lower()
    assert "Amani" in response or "calcul" in response or "répondu" in response

    print("\nOK - Flux éducatif enfant/LLM/corps validé.")


if __name__ == "__main__":
    asyncio.run(main())
