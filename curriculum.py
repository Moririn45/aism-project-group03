"""Disciplinas: cada ficheiro subjects/<id>.json tem os tópicos por ordem e as perguntas do diagnóstico."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

SUBJECTS_DIR = Path(__file__).resolve().parent / "subjects"


class CurriculumError(Exception):
    pass


@dataclass(frozen=True)
class Topic:
    name: str
    description: str
    diagnostic: tuple          # perguntas fixas do diagnóstico: ({"enunciado", "resposta"}, ...)


@dataclass(frozen=True)
class Curriculum:
    file_id: str               # nome do ficheiro, ex.: "matematica"
    name: str                  # nome da disciplina, ex.: "Matemática"
    level: str
    topics: tuple

    @property
    def topic_names(self) -> list[str]:
        return [t.name for t in self.topics]

    @property
    def diagnostic_topics(self) -> list[Topic]:
        return [t for t in self.topics if t.diagnostic]

    def topic(self, name: str) -> Topic:
        for t in self.topics:
            if t.name == name:
                return t
        raise CurriculumError(f"o tópico '{name}' não existe em {self.file_id}.json")


def available_subjects() -> list[str]:
    return sorted(p.stem for p in SUBJECTS_DIR.glob("*.json"))


def load_curriculum(file_id: str) -> Curriculum:
    path = SUBJECTS_DIR / f"{file_id}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        topics = tuple(
            Topic(t["nome"], t.get("descricao", ""),
                  tuple({"enunciado": q["enunciado"], "resposta": str(q["resposta"])}
                        for q in t.get("diagnostico", [])))
            for t in data["topicos"])
        curriculum = Curriculum(file_id, data["disciplina"], data.get("nivel", ""), topics)
    except FileNotFoundError:
        raise CurriculumError(f"não existe a disciplina '{file_id}' (ficheiro {path} em falta)")
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as error:
        raise CurriculumError(f"o ficheiro {path.name} está mal formado ({error})")
    if not curriculum.topics or not curriculum.diagnostic_topics:
        raise CurriculumError(f"{path.name} tem de ter tópicos e perguntas de diagnóstico")
    return curriculum
