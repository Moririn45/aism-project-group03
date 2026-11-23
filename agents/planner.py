"""Agente 2 — Planeador (Curriculum Planner).

Recebe uma CÓPIA do perfil (só lê, não o pode alterar) e escolhe o próximo tópico com uma
regra explícita, sem LLM, para que a decisão seja previsível e fácil de testar:

  1. REVER      se um tópico fraco (weak) já vai na 3.ª sessão desde que foi visto, revê-o;
  2. AVANÇAR    caso contrário, passa ao próximo tópico novo (pela ordem da disciplina);
  3. PRATICAR   se já não há tópicos novos, pratica o menos dominado e visto há mais tempo;
  4. CONSOLIDAR se todos estão solid, volta ao que foi visto há mais tempo.

Justifica sempre a escolha numa linha.
"""
from __future__ import annotations

from agents.messages import ACLMessage
from console import say

REVIEW_WINDOW = 3     # "regra das 3 sessões"


def sessions_counted(current: int, last_seen: int) -> int:
    """Sessões contadas desde que o tópico foi visto, incluindo essa e a atual.

    Exemplo: visto na sessão 1 e estamos na sessão 3 -> 3 sessões (1, 2 e 3) -> revê-se.
    """
    return current - last_seen + 1


def choose_topic(profile: dict, order: list[str]) -> dict:
    """Aplica a regra e devolve {"topic", "mode", "reason", "status", "session"}."""
    session = profile["session"]
    topics = profile["topics"]
    order = [name for name in order if name in topics]
    if not order:
        raise ValueError("a disciplina não tem tópicos")

    def last(name):
        return topics[name]["last_seen"]

    def decision(name, mode, reason):
        return {"topic": name, "mode": mode, "reason": reason,
                "status": topics[name]["status"], "session": session}

    weak = [n for n in order if topics[n]["status"] == "weak" and last(n) is not None]
    due = [n for n in weak if sessions_counted(session, last(n)) >= REVIEW_WINDOW]

    # 1. rever: o tópico fraco há mais tempo (em empate, o primeiro na ordem da disciplina)
    if due:
        name = min(due, key=last)
        return decision(name, "rever",
                        f"Revejo {name}: está fraco desde a sessão {last(name)} e esta já é a "
                        f"{sessions_counted(session, last(name))}.ª sessão (regra das {REVIEW_WINDOW} sessões).")

    # 2. avançar: o primeiro tópico que ainda não foi visto
    new = [n for n in order if last(n) is None]
    if new:
        reason = f"Avanço para {new[0]}: é o próximo tópico novo"
        if weak:
            w = min(weak, key=last)
            reason += (f" ({w} está fraco, mas esta é só a {sessions_counted(session, last(w))}.ª sessão; "
                       f"revejo-o na sessão {last(w) + REVIEW_WINDOW - 1})")
        return decision(new[0], "avancar", reason + ".")

    # 3. praticar: primeiro os weak, depois os improving; dentro de cada, o visto há mais tempo
    rank = {"weak": 0, "improving": 1}
    pending = [n for n in order if topics[n]["status"] != "solid"]
    if pending:
        name = min(pending, key=lambda n: (rank[topics[n]["status"]], last(n)))
        return decision(name, "praticar",
                        f"Pratico {name}: já vimos todos os tópicos e este ainda está "
                        f"{topics[name]['status']} (visto pela última vez na sessão {last(name)}).")

    # 4. consolidar: tudo solid
    name = min(order, key=last)
    return decision(name, "consolidar",
                    f"Consolido {name}: todos os tópicos estão solid e este é o que não vemos "
                    f"há mais tempo (sessão {last(name)}).")


class Planner:
    name = "planner"

    def __init__(self, curriculum):
        self.curriculum = curriculum      # repara: o Planeador não recebe o ProfileStore

    def plan(self, profile_copy: dict) -> ACLMessage:
        decision = choose_topic(profile_copy, self.curriculum.topic_names)
        say(f"[Planeador] {decision['reason']}")
        return ACLMessage("INFORM", self.name, "teacher", decision,
                          conversation_id=f"sessao-{decision['session']}")
