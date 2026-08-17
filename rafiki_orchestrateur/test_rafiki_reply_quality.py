"""Tests rapides de la qualité de la réponse parlée de Rafiki.

Ils ne demandent ni LM Studio ni la Raspberry. Ils protègent la dernière ligne
de défense entre un petit modèle local et la voix entendue par l'enfant.

Lancer depuis rafiki_orchestrateur :
python -m unittest -v test_rafiki_reply_quality.py
"""

from __future__ import annotations

import asyncio
import unittest

from rafiki_agent import (
    RafikiConversationSession,
    SYSTEM_PROMPT,
    clean_agent_response,
    handle_local_intent,
    load_conversation_prompt,
    local_conversation_fallback,
    normalize_text,
)


class FakeTool:
    def __init__(self, result):
        self.result = result
        self.calls = []

    async def ainvoke(self, args=None):
        self.calls.append(args or {})
        return self.result


class RafikiReplyQualityTests(unittest.TestCase):
    def test_prompt_par_defaut_sans_enfant(self) -> None:
        prompt = load_conversation_prompt()
        self.assertIn("compagnon d'apprentissage", prompt)
        self.assertIn("Aucun enfant n'est encore enregistré", prompt)

    def test_prompt_avec_enfant_injecte(self) -> None:
        prompt = load_conversation_prompt({"child_name": "Amani", "child_profile": {"name": "Amani", "age": 8}})
        self.assertIn("Amani", prompt)
        self.assertIn("8 ans", prompt)

    def test_prompt_orchestrateur_contient_des_regles_actionnables(self) -> None:
        self.assertIn("PROTOCOLE DE DÉCISION", SYSTEM_PROMPT)
        self.assertIn("Ne dis jamais que tu vois", SYSTEM_PROMPT)
        self.assertIn("zéro à trois outils", SYSTEM_PROMPT)

    def test_nettoie_raisonnement_balises_et_emojis(self) -> None:
        raw = (
            "Analyse: je dois répondre à l'enfant.\n"
            "REPONSE: [JOIE] Salut ! Le ciel paraît bleu parce que l'air diffuse beaucoup de lumière bleue. 🌟"
        )
        reply = clean_agent_response(raw)
        self.assertEqual(
            reply,
            "Salut ! Le ciel paraît bleu parce que l'air diffuse beaucoup de lumière bleue.",
        )

    def test_normalisation_accepte_les_accents(self) -> None:
        self.assertEqual(normalize_text("Réfléchis à l'été"), "reflechis a l'ete")

    def test_fallback_local_informe_de_la_connexion(self) -> None:
        state = {}
        reply = local_conversation_fallback("Bonjour", state)
        self.assertIn("LM Studio", reply)

    def test_changement_enfant_reinitialise_la_conversation(self) -> None:
        session = RafikiConversationSession(None, {}, None, child_id="amani")
        session.session_state["child_name"] = "Amani"
        session.bind_child("bintou")
        self.assertEqual(session.child_id, "bintou")
        self.assertEqual(session.session_state, {"child_id": "bintou"})

    def test_audience_parent_detectee(self) -> None:
        session_state = {}
        asyncio.run(handle_local_intent("Bonjour je suis le papa", {}, session_state))
        self.assertEqual(session_state.get("audience"), "parent")


if __name__ == "__main__":
    unittest.main(verbosity=2)
