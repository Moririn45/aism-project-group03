"""Persistência do perfil do aluno (o "caderno" do tutor).

Tudo o que o tutor sabe sobre o aluno vive em profile.json. Esta classe:
  * grava de forma ATÓMICA (ficheiro temporário + os.replace), para o ficheiro nunca ficar meio escrito;
  * guarda um CHECKSUM SHA-256, para detetar um ficheiro corrompido ou adulterado;
  * copia a versão anterior para profile.bak.json antes de cada escrita (BACKUP);
  * mantém um JOURNAL (history.jsonl), com um evento por linha, ao qual só se acrescentam linhas;
  * no arranque, valida tudo e RECUPERA o perfil se for preciso.

Ficheiros na pasta de dados (por defeito, data/):
  profile.json            perfil atual
  profile.bak.json        versão anterior do perfil
  history.jsonl           journal com todos os eventos (cópia do "history" do perfil)
  *.corrupt*.json(l)      ficheiros inválidos, isolados para análise (nunca se apagam)

O perfil é sempre o resultado de aplicar os eventos do history por ordem (função apply_event).
É isso que permite reconstruí-lo a partir do journal.

Regra de escrita: só o Avaliador (Assessor) recebe uma instância de ProfileStore.
Só se usa a biblioteca padrão: json, pathlib, hashlib e os.replace.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path

STATUSES = ("weak", "improving", "solid")
FIELDS = {"learner": str, "subject": str, "subject_file": str, "session": int,
          "topics": dict, "history": list}


class StoreError(Exception):
    """Erro de disco (sem permissões, disco cheio...). O perfil em disco fica como estava."""


# --------------------------------------------------------------------------- eventos

def apply_event(profile: dict | None, event: dict) -> dict:
    """Aplica um evento do history ao perfil e devolve o perfil atualizado.

    É a ÚNICA função que muda o estado do aluno. O Avaliador usa-a durante a sessão
    e o ProfileStore usa-a para reconstruir o perfil a partir do journal, por isso
    os dois caminhos dão sempre o mesmo resultado.
    """
    kind = event.get("type")
    if kind == "start":
        profile = {
            "learner": event["learner"],
            "subject": event["subject"],
            "subject_file": event["subject_file"],
            "session": 1,
            "topics": {name: {"status": None, "last_seen": None} for name in event["topics"]},
            "history": [],
        }
    elif profile is None:
        raise ValueError("o history não começa com um evento 'start'")
    elif kind == "diagnostic":
        for name, result in event["results"].items():
            profile["topics"][name] = {"status": result["status"], "last_seen": event["session"]}
    elif kind == "assessment":
        profile["topics"][event["topic"]] = {"status": event["new_status"],
                                             "last_seen": event["session"]}
    elif kind == "session_end":
        profile["session"] = event["session"] + 1
    elif kind != "plan":  # "plan" (decisão do Planeador) fica registado, mas não muda o estado
        raise ValueError(f"tipo de evento desconhecido: {kind!r}")
    profile["history"].append(event)
    return profile


def replay(events: list[dict]) -> dict:
    """Reconstrói um perfil do zero, aplicando os eventos por ordem."""
    profile = None
    for event in events:
        profile = apply_event(profile, copy.deepcopy(event))
    if profile is None:
        raise ValueError("não há eventos")
    return profile


# --------------------------------------------------------------------------- ProfileStore

class ProfileStore:
    def __init__(self, data_dir: str | Path = "data"):
        self.dir = Path(data_dir)
        self.path = self.dir / "profile.json"
        self.backup = self.dir / "profile.bak.json"
        self.journal = self.dir / "history.jsonl"
        self.notes: list[str] = []          # o que aconteceu no arranque (vai para o ecrã e o log)
        self._journal_events: list[dict] | None = None
        self._journal_ok = True

    # ------------------------------------------------------------ checksum e validação

    @staticmethod
    def compute_checksum(profile: dict) -> str:
        """SHA-256 do perfil sem o campo checksum, num formato canónico (chaves ordenadas)."""
        body = {key: value for key, value in profile.items() if key != "checksum"}
        raw = json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()

    @classmethod
    def problem_with(cls, data) -> str | None:
        """Devolve o motivo pelo qual o perfil é inválido, ou None se estiver tudo bem."""
        if not isinstance(data, dict):
            return "não é um objeto JSON"
        for key, kind in FIELDS.items():
            value = data.get(key)
            if not isinstance(value, kind) or (kind is int and isinstance(value, bool)):
                return f"campo '{key}' em falta ou com o tipo errado"
        if data["session"] < 1:
            return "número de sessão inválido"
        for name, topic in data["topics"].items():
            if not isinstance(topic, dict) or topic.get("status") not in (*STATUSES, None):
                return f"estado inválido no tópico '{name}'"
            seen = topic.get("last_seen")
            if seen is not None and (not isinstance(seen, int) or isinstance(seen, bool)):
                return f"last_seen inválido no tópico '{name}'"
        if data.get("checksum") != cls.compute_checksum(data):
            return "o checksum não corresponde ao conteúdo (ficheiro adulterado ou corrompido)"
        return None

    def _read(self, path: Path) -> tuple[dict | None, str, str | None]:
        """Lê e valida um ficheiro de perfil. Devolve (perfil, "", texto) ou (None, motivo, texto)."""
        if not path.exists():
            return None, "não existe", None
        try:
            raw = path.read_text(encoding="utf-8")
            data = json.loads(raw)
        except UnicodeDecodeError:
            return None, "o ficheiro não é texto UTF-8", None
        except json.JSONDecodeError as error:
            return None, f"JSON inválido na linha {error.lineno}", None
        problem = self.problem_with(data)
        return (None, problem, raw) if problem else (data, "", raw)

    # ------------------------------------------------------------ arranque (load + recuperação)

    def load(self) -> dict | None:
        """Carrega e valida o perfil, recuperando-o se for preciso.

        Ordem (Figura 3 do relatório):
          1. profile.json válido (JSON + campos + checksum)  -> usa-o;
          2. inválido -> isola-o em profile.corrupt.json e restaura profile.bak.json;
          3. sem backup válido -> reconstrói o perfil a partir do journal (history.jsonl);
          4. se o journal tiver eventos mais recentes do que o perfil restaurado, repõe-nos;
          5. nada válido -> devolve None (o Avaliador repete o diagnóstico e avisa o aluno).
        Em self.notes fica a descrição de tudo o que aconteceu.
        """
        self.notes = []
        try:
            return self._load()
        except OSError as error:
            raise StoreError(f"não foi possível ler a pasta {self.dir}: {error}") from error

    def _load(self) -> dict | None:
        self.dir.mkdir(parents=True, exist_ok=True)
        self._remove_leftover_tmp()
        had_files = any(p.exists() for p in (self.path, self.backup, self.journal))
        changed = False

        # 1) profile.json
        profile, problem, _ = self._read(self.path)
        if profile is None:
            if self.path.exists():
                self.notes.append(f"profile.json inválido ({problem}); isolado em {self._isolate(self.path)}.")
            elif had_files:
                self.notes.append("profile.json não existe (foi apagado).")
            # 2) backup
            profile, problem, _ = self._read(self.backup)
            if profile is not None:
                changed = True
                self.notes.append("Restaurado o último backup válido "
                                  f"(profile.bak.json, sessão {profile['session']}).")
            elif self.backup.exists():
                self.notes.append(f"O backup também é inválido ({problem}); "
                                  f"isolado em {self._isolate(self.backup)}.")

        # 3) e 4) journal
        events = self._read_journal()
        if profile is None and events:
            try:
                profile = replay(events)
                changed = True
                self.notes.append(f"Perfil reconstruído a partir do journal (history.jsonl, {len(events)} eventos).")
            except (KeyError, TypeError, ValueError) as error:
                self.notes.append(f"O journal não permite reconstruir o perfil ({error}).")
                profile = None
        elif profile is not None:
            missing = self._events_after(profile, events)
            if missing:
                for event in missing:
                    profile = apply_event(profile, copy.deepcopy(event))
                changed = True
                self.notes.append(f"Repostos {len(missing)} eventos do journal que o backup ainda não tinha "
                                  f"(o perfil ficou em dia: sessão {profile['session']}).")

        # 5) nada para recuperar
        if profile is None:
            if had_files:
                self.notes.append("Não há nada válido para recuperar: o diagnóstico vai ser repetido.")
            return None

        if changed:
            self.save(profile)          # grava o perfil recuperado (e sincroniza o journal)
        else:
            self._sync_journal(profile)
        return profile

    @staticmethod
    def _events_after(profile: dict, events: list[dict]) -> list[dict]:
        """Eventos do journal que vêm depois do history do perfil (se o journal bater certo com ele)."""
        history = profile["history"]
        if len(events) <= len(history) or events[:len(history)] != history:
            return []
        return events[len(history):]

    def _remove_leftover_tmp(self) -> None:
        for leftover in self.dir.glob("*.tmp"):
            leftover.unlink()
            self.notes.append(f"Removido {leftover.name}, de uma gravação interrompida "
                              "(o ficheiro anterior ficou intacto).")

    # ------------------------------------------------------------ gravação

    def save(self, profile: dict) -> None:
        """Grava o perfil: temporário -> backup da versão anterior -> os.replace -> journal."""
        profile["checksum"] = self.compute_checksum(profile)
        text = json.dumps(profile, ensure_ascii=False, indent=2) + "\n"
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_name(self.path.name + ".tmp")
            self._write_file(tmp, text)                       # 1) escreve tudo num temporário
            current, problem, raw = self._read(self.path)
            if current is not None:
                self._write_atomic(self.backup, raw)          # 2) a versão anterior passa a backup
            elif self.path.exists():                          #    (se foi estragada a meio, não)
                self.notes.append(f"profile.json foi estragado durante a sessão ({problem}); "
                                  f"isolado em {self._isolate(self.path)}.")
            os.replace(tmp, self.path)                        # 3) troca atómica
            self._sync_journal(profile)                       # 4) eventos novos vão para o journal
        except OSError as error:
            raise StoreError(f"não foi possível gravar o perfil em {self.dir}: {error}") from error

    # ------------------------------------------------------------ journal

    def _read_journal(self) -> list[dict]:
        """Lê o journal até à primeira linha inválida (uma linha cortada por uma falha, por exemplo)."""
        events: list[dict] = []
        self._journal_ok = True
        if self.journal.exists():
            try:
                lines = self.journal.read_text(encoding="utf-8").splitlines()
            except UnicodeDecodeError:
                lines, self._journal_ok = [], False
            for line in lines:
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    self._journal_ok = False
                    break
                if not isinstance(event, dict) or event.get("seq") != len(events) + 1:
                    self._journal_ok = False
                    break
                events.append(event)
        self._journal_events = events
        return events

    def _sync_journal(self, profile: dict) -> None:
        """Garante que o journal tem exatamente os eventos do history do perfil."""
        if self._journal_events is None:
            self._read_journal()
        history = profile["history"]
        known = self._journal_events
        if self._journal_ok and known == history[:len(known)]:
            new = history[len(known):]
            if new:
                with open(self.journal, "a", encoding="utf-8") as f:
                    for event in new:
                        f.write(json.dumps(event, ensure_ascii=False) + "\n")
                    f.flush()
                    os.fsync(f.fileno())
        else:
            if self.journal.exists():
                self.notes.append("O journal não batia certo com o perfil; "
                                  f"isolado em {self._isolate(self.journal)} e reescrito.")
            self._write_atomic(self.journal,
                               "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in history))
        self._journal_events = copy.deepcopy(history)
        self._journal_ok = True

    # ------------------------------------------------------------ utilitários de ficheiros

    @staticmethod
    def _write_file(path: Path, text: str) -> None:
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())            # garante que os bytes chegaram ao disco

    def _write_atomic(self, path: Path, text: str) -> None:
        tmp = path.with_name(path.name + ".tmp")
        self._write_file(tmp, text)
        os.replace(tmp, path)

    def _isolate(self, path: Path) -> str:
        """Move um ficheiro inválido para *.corrupt*.json(l). Nunca apaga nem substitui nada."""
        stem = path.name.split(".")[0]                       # "profile" ou "history"
        ext = ".jsonl" if path.suffix == ".jsonl" else ".json"
        label = "bak.corrupt" if path == self.backup else "corrupt"
        dest = path.with_name(f"{stem}.{label}{ext}")
        n = 1
        while dest.exists():
            dest = path.with_name(f"{stem}.{label}-{n}{ext}")
            n += 1
        os.replace(path, dest)
        return dest.name
