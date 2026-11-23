"""Agente 1 — Avaliador (Assessor).

  * Na 1.ª sessão faz um diagnóstico curto, com as perguntas fixas da disciplina.
  * Depois corrige as respostas que o Professor lhe envia e classifica o tópico
    como weak, improving ou solid.
  * É o ÚNICO agente que recebe o ProfileStore e, por isso, o único que escreve no perfil.

Para corrigir, compara primeiro os valores (3/4 = 0,75 = x = 3/4) sem gastar uma chamada
ao modelo. Só nas respostas por extenso pergunta ao modelo se são equivalentes.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timezone
from fractions import Fraction

from agents.messages import ACLMessage
from console import say
from llm import LLMError
from profile_store import apply_event

# ------------------------------------------------------------------ comparar respostas

_NUMBER = re.compile(r"-?\d+(?:\.\d+)?(?:/-?\d+(?:\.\d+)?)?")
_UNITS = ("unidades", "euros", "graus", "cm²", "cm2", "m²", "m2", "cm", "%", "€", "º", "°", "m")
_BLANK = {"", "?", "-", "nao sei", "nsei", "sei la", "nao", "passo"}


def normalize_text(text) -> str:
    text = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode()
    return " ".join(text.lower().strip().rstrip(".!").split())


def is_blank(text) -> bool:
    return normalize_text(text) in _BLANK


def parse_number(text) -> Fraction | None:
    """'3/4', '0,75', 'x = 0.75', '12 cm' e '25%' passam a números exatos (Fraction)."""
    s = str(text).strip().lower().replace("−", "-").replace(" ", "")
    s = s.split("=")[-1]                      # "x=3/4" -> "3/4"
    for unit in _UNITS:
        if s.endswith(unit):
            s = s[: -len(unit)]
            break
    s = s.rstrip(".").replace(",", ".")
    if not _NUMBER.fullmatch(s):
        return None
    try:
        if "/" in s:
            top, bottom = s.split("/")
            return Fraction(top) / Fraction(bottom)
        return Fraction(s)
    except (ValueError, ZeroDivisionError):
        return None


def _has_decimal(text) -> bool:
    return re.search(r"\d[.,]\d", str(text)) is not None


def same_answer(expected, given) -> bool | None:
    """True/False se der para decidir sem o modelo; None se for preciso perguntar ao modelo."""
    a, b = parse_number(expected), parse_number(given)
    if a is not None and b is not None:
        if a == b:
            return True
        if _has_decimal(expected) or _has_decimal(given):   # aceita arredondamentos: 1/3 ~ 0,33
            return abs(a - b) <= Fraction(1, 200)
        return False
    if normalize_text(expected) == normalize_text(given):
        return True
    return None


# ------------------------------------------------------------------ classificar tópicos

def classify_diagnostic(score: int, total: int) -> str:
    """Diagnóstico: tudo certo = já domina; nada certo = fraco; o resto = a melhorar."""
    if score == total:
        return "solid"
    if score == 0:
        return "weak"
    return "improving"


def classify_lesson(previous: str | None, score: int, total: int) -> str:
    """Depois de uma aula: para chegar a solid é preciso acertar tudo em duas sessões diferentes."""
    if score == 0:
        return "weak"
    if score < total:
        return "improving"
    return "solid" if previous in ("improving", "solid") else "improving"


# ------------------------------------------------------------------ agente

EQUIVALENCE_SYSTEM = "És um avaliador rigoroso de respostas de alunos. Respondes apenas com JSON."
EQUIVALENCE_PROMPT = """Pergunta: {question}
Resposta correta: {expected}
Resposta do aluno: {given}

A resposta do aluno é equivalente à resposta correta (o mesmo valor, mesmo que escrito de outra forma)?
Responde apenas com {{"correta": true}} ou {{"correta": false}}."""


class Assessor:
    name = "assessor"

    def __init__(self, store, llm, curriculum):
        self.store = store          # só o Avaliador recebe o ProfileStore (permissão de escrita)
        self.llm = llm
        self.curriculum = curriculum

    # -------------------------------------------------- registo de eventos (history)

    @staticmethod
    def _record(profile: dict | None, kind: str, **fields) -> dict:
        """Cria um evento, aplica-o ao perfil e acrescenta-o ao history."""
        event = {"seq": len(profile["history"]) + 1 if profile else 1, "type": kind,
                 "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), **fields}
        return apply_event(profile, event)

    # -------------------------------------------------- correção

    def check(self, question: str, expected: str, given: str) -> bool:
        if is_blank(given):
            return False
        decided = same_answer(expected, given)
        if decided is not None:
            return decided
        prompt = EQUIVALENCE_PROMPT.format(question=question, expected=expected, given=given)
        for _ in range(2):
            try:
                verdict = self.llm.ask_json(EQUIVALENCE_SYSTEM, prompt).get("correta")
            except LLMError:
                continue
            if isinstance(verdict, bool):
                return verdict
            if isinstance(verdict, str) and verdict.lower() in ("true", "false", "sim", "nao", "não"):
                return verdict.lower() in ("true", "sim")
        say("  (o modelo não conseguiu confirmar esta resposta; conta como errada)")
        return False

    def _correct(self, label: str, question: dict, given: str) -> bool:
        ok = self.check(question["enunciado"], question["resposta"], given)
        say(f"[Avaliador] {label}: {'certa' if ok else 'errada (resposta certa: ' + question['resposta'] + ')'}")
        return ok

    # -------------------------------------------------- diagnóstico (1.ª sessão)

    def diagnose(self, student, learner: str) -> dict:
        cur = self.curriculum
        profile = self._record(None, "start", session=1, learner=learner, subject=cur.name,
                               subject_file=cur.file_id, topics=cur.topic_names)
        n_questions = sum(len(t.diagnostic) for t in cur.diagnostic_topics)
        say(f"\n[Avaliador] Diagnóstico inicial de {cur.name}: {n_questions} perguntas curtas.")
        results, number = {}, 0
        for topic in cur.diagnostic_topics:
            score = 0
            for i, question in enumerate(topic.diagnostic):
                number += 1
                say(f"  Pergunta {number} ({topic.name}): {question['enunciado']}")
                given = student.answer(question, topic.name, "diagnostico", i)
                score += self._correct(f"Pergunta {number}", question, given)
            results[topic.name] = {"score": score, "of": len(topic.diagnostic),
                                   "status": classify_diagnostic(score, len(topic.diagnostic))}
        self._record(profile, "diagnostic", session=1, results=results)
        self.store.save(profile)
        summary = "; ".join(f"{name} {r['score']}/{r['of']} -> {r['status']}" for name, r in results.items())
        say(f"[Avaliador] Resultado do diagnóstico: {summary}. Perfil criado e gravado.")
        return profile

    # -------------------------------------------------- avaliação de uma aula

    def assess(self, message: ACLMessage, profile: dict) -> ACLMessage:
        message.expect("REQUEST", self.name)
        c = message.content
        topic, session = c["topic"], profile["session"]
        old = profile["topics"][topic]["status"]
        say("")
        details, score = [], 0
        for i, (question, given) in enumerate(zip(c["questions"], c["answers"]), 1):
            ok = self._correct(f"Pergunta {i}", question, given)
            score += ok
            details.append({"pergunta": question["enunciado"], "esperada": question["resposta"],
                            "dada": given, "certa": ok})
        new = classify_lesson(old, score, len(details))

        # history: a decisão do Planeador, a avaliação e o fim da sessão (o contador avança)
        self._record(profile, "plan", session=session, topic=topic, mode=c["mode"], reason=c["reason"])
        self._record(profile, "assessment", session=session, topic=topic, score=score, of=len(details),
                     old_status=old, new_status=new, teacher_attempts=c.get("attempts"), answers=details)
        self._record(profile, "session_end", session=session)
        self.store.save(profile)

        say(f"[Avaliador] {topic}: {old or 'novo'} -> {new} ({score}/{len(details)}). "
            f"Perfil gravado; a próxima é a sessão {profile['session']}.")
        return ACLMessage("INFORM", self.name, "planner",
                          {"topic": topic, "score": score, "of": len(details), "old_status": old,
                           "new_status": new, "next_session": profile["session"]},
                          conversation_id=message.conversation_id)
