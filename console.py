"""Saída para o ecrã e para o registo (log) da sessão.

Tudo o que aparece no ecrã fica também no log da sessão (logs/sessao_N.log).
Até se saber o número da sessão, as linhas ficam guardadas e são escritas quando o log abre.
"""
from __future__ import annotations

import sys
from pathlib import Path

_log = None
_buffer: list[str] = []


def setup_utf8() -> None:
    """Evita erros com acentos no terminal do Windows."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def reset() -> None:
    global _log
    close_log()
    _buffer.clear()


def _write(text: str) -> None:
    if _log is not None:
        _log.write(text + "\n")
        _log.flush()
    else:
        _buffer.append(text)


def say(text: str = "") -> None:
    """Mostra uma linha no ecrã e escreve-a no log."""
    print(text, flush=True)
    _write(text)


def log_only(text: str) -> None:
    """Escreve só no log (por exemplo, detalhes de um erro)."""
    _write(text)


def ask(prompt: str) -> str:
    """Pede uma resposta ao aluno e regista a pergunta e a resposta no log."""
    answer = input(prompt)
    _write(prompt + answer)
    return answer.strip()


def open_log(path: Path) -> None:
    global _log
    close_log()
    path.parent.mkdir(parents=True, exist_ok=True)
    _log = open(path, "a", encoding="utf-8")
    for line in _buffer:
        _log.write(line + "\n")
    _buffer.clear()
    _log.flush()


def close_log() -> None:
    global _log
    if _log is not None:
        _log.close()
        _log = None
