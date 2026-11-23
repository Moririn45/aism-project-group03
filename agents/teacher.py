"""Agente 3 — Professor (Teacher).

Recebe do Planeador o tópico a ensinar, pede ao modelo local uma mini-aula (explicação,
um exemplo resolvido e duas perguntas práticas), mostra-a ao aluno, recolhe as duas
respostas e envia-as ao Avaliador. Não lê nem escreve o perfil.
"""
from __future__ import annotations

import textwrap

from agents.messages import ACLMessage
from console import say
from llm import LLMError

ATTEMPTS = 3   # se o modelo devolver uma aula mal formada, tenta outra vez (até 3 vezes)

SYSTEM = ("És um professor de {subject} ({level}), paciente e claro. Escreves em português de Portugal. "
          "Respondes sempre e apenas com um objeto JSON válido.")

PROMPT = """Prepara uma mini-aula sobre o tópico "{topic}" ({description}).
{situation}

Devolve um objeto JSON com exatamente esta estrutura:
{{
  "explicacao": "explicação simples do tópico, em 2 a 4 frases",
  "exemplo": {{"enunciado": "um exercício", "resolucao": "a resolução passo a passo"}},
  "perguntas": [
    {{"enunciado": "pergunta prática 1", "resposta": "resposta curta"}},
    {{"enunciado": "pergunta prática 2", "resposta": "resposta curta"}}
  ]
}}

Regras:
- exatamente 2 perguntas, diferentes do exemplo;
- cada "resposta" é curta e exata: um número inteiro, uma fração (por exemplo 3/4) ou um decimal;
- o enunciado das perguntas não pode conter a resposta."""

SITUATION = {
    "avancar": "É um tópico novo para o aluno.",
    "rever": "É uma revisão: o aluno teve dificuldades neste tópico. Começa pelo essencial e usa números simples.",
    "praticar": "O aluno já viu este tópico, mas ainda não o domina. Dá prática de dificuldade média.",
    "consolidar": "O aluno já domina este tópico. Faz uma consolidação rápida, um pouco mais desafiante.",
}
MODE_LABEL = {"avancar": "tópico novo", "rever": "revisão", "praticar": "prática", "consolidar": "consolidação"}


class LessonError(Exception):
    """O modelo não conseguiu preparar uma aula válida em nenhuma das tentativas."""


def _text(value, field: str) -> str:
    if isinstance(value, list):                     # às vezes a resolução vem como lista de passos
        value = " ".join(str(v) for v in value)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        value = str(value)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"falta o campo '{field}'")
    return value.strip()


def validate_lesson(data) -> dict:
    """Confirma que a aula tem tudo o que é preciso e devolve-a num formato limpo."""
    if not isinstance(data, dict):
        raise ValueError("a aula não é um objeto JSON")
    example = data.get("exemplo")
    if not isinstance(example, dict):
        raise ValueError("falta o exemplo resolvido")
    questions = data.get("perguntas")
    if not isinstance(questions, list) or len(questions) < 2:
        raise ValueError("a aula tem de ter 2 perguntas")
    clean = []
    for i, q in enumerate(questions[:2], 1):
        if not isinstance(q, dict):
            raise ValueError(f"a pergunta {i} está mal formada")
        clean.append({"enunciado": _text(q.get("enunciado"), f"perguntas[{i}].enunciado"),
                      "resposta": _text(q.get("resposta"), f"perguntas[{i}].resposta")})
    return {"explicacao": _text(data.get("explicacao"), "explicacao"),
            "exemplo": {"enunciado": _text(example.get("enunciado"), "exemplo.enunciado"),
                        "resolucao": _text(example.get("resolucao"), "exemplo.resolucao")},
            "perguntas": clean}


def _show(label: str, text: str) -> None:
    say(textwrap.fill(f"{label}: {text}", width=92, initial_indent="  ", subsequent_indent="    "))


class Teacher:
    name = "teacher"

    def __init__(self, llm, curriculum):
        self.llm = llm                     # o Professor usa o modelo, mas não recebe o ProfileStore
        self.curriculum = curriculum
        self.attempts_used = 0

    def prepare(self, topic_name: str, mode: str) -> dict:
        topic = self.curriculum.topic(topic_name)
        system = SYSTEM.format(subject=self.curriculum.name, level=self.curriculum.level)
        prompt = PROMPT.format(topic=topic.name, description=topic.description,
                               situation=SITUATION[mode])
        for attempt in range(1, ATTEMPTS + 1):
            self.attempts_used = attempt
            try:
                return validate_lesson(self.llm.ask_json(system, prompt))
            except (LLMError, ValueError) as error:
                say(f"  (tentativa {attempt}/{ATTEMPTS} falhou: {error})")
        raise LessonError(f"o modelo não preparou uma aula válida em {ATTEMPTS} tentativas")

    def teach(self, message: ACLMessage, student) -> ACLMessage:
        message.expect("INFORM", self.name)
        c = message.content
        say(f"\n[Professor] Aula sobre {c['topic']} ({MODE_LABEL[c['mode']]}). A preparar com o modelo local...")
        lesson = self.prepare(c["topic"], c["mode"])
        _show("Explicação", lesson["explicacao"])
        _show("Exemplo resolvido", lesson["exemplo"]["enunciado"])
        _show("Resolução", lesson["exemplo"]["resolucao"])
        say("  Agora é a tua vez.")
        answers = []
        for i, question in enumerate(lesson["perguntas"]):
            _show(f"Pergunta {i + 1}", question["enunciado"])
            answers.append(student.answer(question, c["topic"], "aula", i))
        return ACLMessage("REQUEST", self.name, "assessor",
                          {"topic": c["topic"], "mode": c["mode"], "reason": c["reason"],
                           "questions": lesson["perguntas"], "answers": answers,
                           "attempts": self.attempts_used},
                          conversation_id=message.conversation_id)
