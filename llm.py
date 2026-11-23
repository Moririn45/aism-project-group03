"""Cliente do modelo local (Ollama), partilhado pelos três agentes.

O modelo corre no próprio computador: não há chave de API nem dados enviados para fora.
O modelo por defeito é o llama3.2; pode mudar-se com --model ou com a variável OLLAMA_MODEL.
"""
from __future__ import annotations

import json
import os
import time

DEFAULT_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.2")


class LLMError(Exception):
    """O modelo não está disponível ou deu uma resposta que não se consegue usar."""


def parse_json_object(text: str) -> dict:
    """Extrai um objeto JSON da resposta do modelo (às vezes vem com texto à volta)."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise ValueError("a resposta não contém um objeto JSON")
        try:
            data = json.loads(text[start:end + 1])
        except json.JSONDecodeError as error:
            raise ValueError(f"JSON mal formado ({error.msg})") from error
    if not isinstance(data, dict):
        raise ValueError("a resposta não é um objeto JSON")
    return data


class LocalLLM:
    def __init__(self, model: str = DEFAULT_MODEL, temperature: float = 0.4, timeout: float = 300):
        self.model = model
        self.temperature = temperature
        self.timeout = timeout
        self._client = None
        # métricas (aparecem no fim de cada sessão e em logs/metricas.jsonl)
        self.calls = 0
        self.failures = 0
        self.seconds = 0.0

    def check(self) -> None:
        """Confirma que a biblioteca, o servidor e o modelo existem. Se não, explica o que falta."""
        try:
            import ollama
        except ImportError:
            raise LLMError("A biblioteca 'ollama' não está instalada. Corre: pip install -r requirements.txt")
        self._client = ollama.Client(timeout=self.timeout)
        try:
            self._client.list()
        except Exception as error:
            raise LLMError("O servidor do Ollama não responde "
                           f"({type(error).__name__}). Abre a aplicação Ollama ou corre: ollama serve")
        try:
            self._client.show(self.model)
        except Exception:
            raise LLMError(f"O modelo '{self.model}' não está instalado. Corre: ollama pull {self.model}")

    def ask_json(self, system: str, prompt: str) -> dict:
        """Faz UM pedido ao modelo e devolve a resposta como dicionário (pede-se JSON ao Ollama)."""
        if self._client is None:
            self.check()
        self.calls += 1
        start = time.monotonic()
        try:
            response = self._client.chat(
                model=self.model,
                messages=[{"role": "system", "content": system},
                          {"role": "user", "content": prompt}],
                format="json",
                options={"temperature": self.temperature},
            )
            text = response["message"]["content"]
        except Exception as error:
            self.failures += 1
            raise LLMError(f"falha na chamada ao modelo ({type(error).__name__}: {error})") from error
        finally:
            self.seconds += time.monotonic() - start
        try:
            return parse_json_object(text)
        except ValueError as error:
            self.failures += 1
            raise LLMError(str(error)) from error
