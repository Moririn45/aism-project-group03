"""Modelo FALSO usado nos testes, para correrem em segundos e sem o Ollama.

Devolve sempre a mesma aula para cada tópico. As decisões que se testam (Planeador,
Avaliador, persistência e recuperação) não dependem do texto da aula.
"""
import re

from llm import LLMError


class FakeLLM:
    def __init__(self, broken=False, unavailable=False):
        self.model = "modelo-falso"
        self.broken = broken            # True: devolve sempre uma resposta inválida
        self.unavailable = unavailable  # True: check() falha como se o Ollama estivesse desligado
        self.calls = 0
        self.failures = 0
        self.seconds = 0.0

    def check(self):
        if self.unavailable:
            raise LLMError("O servidor do Ollama não responde (teste)")

    def ask_json(self, system, prompt):
        self.calls += 1
        if self.broken:
            self.failures += 1
            raise LLMError("a resposta não contém um objeto JSON")
        if "equivalente" in prompt:
            return {"correta": "Resposta do aluno: três quartos" in prompt}
        topic = re.search(r'tópico "([^"]+)"', prompt).group(1)
        return {"explicacao": f"Explicação de {topic}.",
                "exemplo": {"enunciado": f"Exemplo de {topic}.", "resolucao": ["Passo 1.", "Passo 2."]},
                "perguntas": [{"enunciado": f"Primeira pergunta sobre {topic}.", "resposta": "3/4"},
                              {"enunciado": f"Segunda pergunta sobre {topic}.", "resposta": 12}]}
