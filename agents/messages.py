"""Mensagens entre agentes, ao estilo FIPA-ACL (performativa, emissor, recetor, conteúdo).

Os agentes não se chamam uns aos outros: cada um devolve uma mensagem e o ciclo da sessão
(main.py) entrega-a ao agente seguinte. Assim, a comunicação é explícita e fica no log:

  Planeador --INFORM (tópico + justificação)--> Professor
  Professor --REQUEST (avaliar 2 respostas)---> Avaliador
  Avaliador --INFORM (novo estado do tópico)--> Planeador   (que o lê do perfil na sessão seguinte)
"""
from __future__ import annotations

from dataclasses import dataclass

from console import say

PERFORMATIVES = ("INFORM", "REQUEST")
NAMES = {"planner": "Planeador", "teacher": "Professor", "assessor": "Avaliador"}


@dataclass(frozen=True)
class ACLMessage:
    performative: str        # INFORM = "fica a saber que..."; REQUEST = "faz isto por mim"
    sender: str
    receiver: str
    content: dict
    conversation_id: str = ""  # identifica a sessão (ex.: "sessao-3")

    def __post_init__(self):
        if self.performative not in PERFORMATIVES:
            raise ValueError(f"performativa desconhecida: {self.performative}")
        if self.sender not in NAMES or self.receiver not in NAMES:
            raise ValueError("emissor ou recetor desconhecido")

    def expect(self, performative: str, receiver: str) -> None:
        """Cada agente confirma que a mensagem é mesmo para ele e do tipo certo."""
        if self.performative != performative or self.receiver != receiver:
            raise ValueError(f"{NAMES[receiver]} esperava {performative} e recebeu "
                             f"{self.performative} para {NAMES.get(self.receiver, self.receiver)}")

    def summary(self) -> str:
        c = self.content
        if "answers" in c:
            return f"avaliar {len(c['answers'])} respostas sobre {c['topic']}"
        if "new_status" in c:
            return f"{c['topic']}: {c['old_status'] or 'novo'} -> {c['new_status']} ({c['score']}/{c['of']})"
        return f"tópico={c.get('topic')}, modo={c.get('mode')}"


def deliver(message: ACLMessage) -> ACLMessage:
    """Entrega a mensagem: regista-a no ecrã e no log e devolve-a ao ciclo da sessão."""
    say(f"  [mensagem] {NAMES[message.sender]} -> {NAMES[message.receiver]} · "
        f"{message.performative} · {message.summary()}")
    return message
