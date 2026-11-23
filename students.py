"""O aluno: uma pessoa ao teclado (HumanStudent) ou um aluno simulado (SimulatedStudent).

O aluno simulado lê de um ficheiro JSON que perguntas acerta. Assim, as demonstrações e os
testes tomam sempre as mesmas decisões, mesmo que o LLM gere aulas diferentes em cada execução.
"""
from __future__ import annotations

import json
from pathlib import Path

import console
from agents.assessor import parse_number


class StudentError(Exception):
    pass


class HumanStudent:
    simulated = False

    def __init__(self):
        self.name = None
        self.subject = None
        self.session = None

    def answer(self, question: dict, topic: str, phase: str, index: int) -> str:
        return console.ask("  A tua resposta: ")


def wrong_answer(expected: str) -> str:
    """Uma resposta errada plausível: o valor certo mais 1 (ou "não sei", se não for um número)."""
    value = parse_number(expected)
    if value is None:
        return "não sei"
    value += 1
    return str(value.numerator) if value.denominator == 1 else f"{value.numerator}/{value.denominator}"


class SimulatedStudent:
    simulated = True

    def __init__(self, path: str | Path):
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            self.name = data["nome"]
        except (OSError, json.JSONDecodeError, KeyError) as error:
            raise StudentError(f"não foi possível ler o aluno simulado {path} ({error})")
        self.subject = data.get("disciplina")
        self.diagnostic = data.get("diagnostico", {})     # {"Frações": [false, false], ...}
        self.lessons = data.get("aulas", {})              # {"por_defeito": [true, true], "4": [...]}
        self.interrupt_at = data.get("interromper_na_pergunta")
        self.session = None

    def _plan(self, topic: str, phase: str) -> list[bool]:
        if phase == "diagnostico":
            return self.diagnostic.get(topic, [True, True])
        return self.lessons.get(str(self.session), self.lessons.get("por_defeito", [True, True]))

    def answer(self, question: dict, topic: str, phase: str, index: int) -> str:
        if phase == "aula" and self.interrupt_at == index + 1:
            console.say("  (o aluno simulado fecha o programa a meio da aula)")
            raise KeyboardInterrupt
        plan = self._plan(topic, phase)
        correct = plan[index] if index < len(plan) else True
        given = str(question["resposta"]) if correct else wrong_answer(question["resposta"])
        console.say(f"  Resposta do aluno (simulado): {given}")
        return given
