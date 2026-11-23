"""Tutor Curricular Pessoal com Memória Persistente — ciclo de UMA sessão.

Cada execução de `python main.py` é uma sessão:
  1. verifica o modelo local (Ollama);
  2. carrega e valida o perfil (e recupera-o, se for preciso);
     se não houver perfil, o Avaliador faz o diagnóstico inicial;
  3. o Planeador escolhe o tópico e justifica a escolha;
  4. o Professor dá a aula e recolhe as duas respostas;
  5. o Avaliador classifica as respostas, atualiza o perfil e grava-o;
  6. o contador de sessão avança e o programa termina.

Nenhum estado em memória passa de uma sessão para a outra: tudo vem do disco (data/profile.json).
"""
from __future__ import annotations

import argparse
import copy
import json
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

import console
from agents.assessor import Assessor
from agents.messages import deliver
from agents.planner import Planner
from agents.teacher import LessonError, Teacher
from console import say
from curriculum import CurriculumError, available_subjects, load_curriculum
from llm import DEFAULT_MODEL, LLMError, LocalLLM
from profile_store import ProfileStore, StoreError
from students import HumanStudent, SimulatedStudent, StudentError

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_NO_MODEL = 2
EXIT_STORAGE = 3
EXIT_LESSON = 4
EXIT_INTERRUPTED = 130


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Tutor curricular com memória persistente (uma sessão por execução).")
    p.add_argument("--data-dir", default="data", help="pasta do perfil do aluno (por defeito: data)")
    p.add_argument("--log-dir", default="logs", help="pasta dos registos das sessões (por defeito: logs)")
    p.add_argument("--model", default=DEFAULT_MODEL, help=f"modelo do Ollama (por defeito: {DEFAULT_MODEL})")
    p.add_argument("--subject", help="disciplina de um aluno novo (ficheiro em subjects/, ex.: matematica)")
    p.add_argument("--simulate", metavar="FICHEIRO", help="usa um aluno simulado (ex.: demo/aluno_ana.json)")
    return p.parse_args(argv)


def choose_subject(args, student) -> str:
    if args.subject:
        return args.subject
    if student.subject:
        return student.subject
    options = available_subjects()
    if len(options) == 1:
        return options[0]
    for i, name in enumerate(options, 1):
        say(f"  {i}. {name}")
    choice = console.ask("Escolhe a disciplina (número): ")
    return options[int(choice) - 1] if choice.isdigit() and 0 < int(choice) <= len(options) else options[0]


def show_state(profile: dict, session: int) -> None:
    say(f"\nEstado de {profile['learner']} no fim da sessão {session}:")
    say(f"  {'Tópico':<24}{'Estado':<12}Visto pela última vez")
    for name, topic in profile["topics"].items():
        seen = topic["last_seen"]
        say(f"  {name:<24}{topic['status'] or '-':<12}{'sessão ' + str(seen) if seen else '-'}")


def write_metrics(log_dir: Path, metrics: dict) -> None:
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        with open(log_dir / "metricas.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(metrics, ensure_ascii=False) + "\n")
    except OSError:
        pass   # as métricas são opcionais: nunca podem fazer falhar a sessão


def run_session(args, llm, metrics: dict) -> int:
    say("=" * 72)
    say("Tutor Curricular Pessoal com Memória Persistente")
    say("=" * 72)

    # 1. Modelo local. Se não estiver disponível, sai sem tocar no perfil.
    try:
        llm.check()
    except LLMError as error:
        say(f"[erro] {error}")
        say("O perfil não foi alterado. Resolve o problema e volta a correr o programa.")
        metrics["outcome"] = "modelo_indisponivel"
        return EXIT_NO_MODEL
    say(f"[arranque] Modelo local: {llm.model} (Ollama).")

    # 2. Perfil: carregar, validar e, se for preciso, recuperar.
    store = ProfileStore(args.data_dir)
    profile = store.load()
    shown = 0

    def show_store_notes():         # mostra o que o ProfileStore fez (no arranque ou ao gravar)
        nonlocal shown
        for note in store.notes[shown:]:
            say(f"[recuperação] {note}")
        shown = len(store.notes)

    show_store_notes()
    metrics["recovery"] = list(store.notes)
    session = profile["session"] if profile else 1
    console.open_log(Path(args.log_dir) / f"sessao_{session}.log")
    log_header = f"--- {datetime.now().isoformat(timespec='seconds')} · pasta de dados: {args.data_dir}"
    console.log_only(log_header)

    student = SimulatedStudent(args.simulate) if args.simulate else HumanStudent()
    curriculum = load_curriculum(profile["subject_file"] if profile else choose_subject(args, student))
    assessor = Assessor(store, llm, curriculum)     # o único que recebe o store
    planner = Planner(curriculum)
    teacher = Teacher(llm, curriculum)

    if profile is None:
        if store.notes:
            say("[aviso] Não foi possível recuperar o perfil: o diagnóstico vai ser repetido.")
        else:
            say("[arranque] Não há perfil guardado: aluno novo.")
        name = student.name or console.ask("Como te chamas? ") or "Aluno"
        profile = assessor.diagnose(student, name)
        show_store_notes()
    else:
        say(f"[arranque] Perfil de {profile['learner']} válido (sessão {session}). A continuar onde ficou.")

    metrics.update(session=session, learner=profile["learner"])
    say(f"\n--- Sessão {session} · {profile['learner']} · {profile['subject']} ---")
    student.session = session

    # 3 a 5. Os agentes trocam mensagens; o ciclo entrega cada uma ao agente seguinte.
    plan = deliver(planner.plan(copy.deepcopy(profile)))   # o Planeador só recebe uma cópia
    request = deliver(teacher.teach(plan, student))
    result = deliver(assessor.assess(request, profile))
    show_store_notes()

    show_state(profile, session)
    say(f"\nFim da sessão {session}. Próxima: sessão {profile['session']}. "
        "O programa termina aqui; volta a correr `python main.py` para continuar.")
    metrics.update(outcome="ok", topic=result.content["topic"], mode=plan.content["mode"],
                   score=result.content["score"], of=result.content["of"],
                   new_status=result.content["new_status"], teacher_attempts=request.content["attempts"])
    return EXIT_OK


def main(argv=None, llm=None) -> int:
    console.setup_utf8()
    console.reset()
    args = parse_args(argv)
    llm = llm or LocalLLM(args.model)
    started = time.monotonic()
    metrics = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "data_dir": str(args.data_dir), "outcome": "erro"}
    try:
        return run_session(args, llm, metrics)
    except LessonError as error:
        say(f"\n[erro] {error}.")
        say("A sessão não conta: o perfil ficou como estava e esta sessão repete-se na próxima execução.")
        metrics["outcome"] = "aula_falhou"
        return EXIT_LESSON
    except (KeyboardInterrupt, EOFError):
        say("\n[interrompido] Sessão interrompida antes do fim. O perfil não foi alterado; "
            "esta sessão repete-se na próxima execução.")
        metrics["outcome"] = "interrompida"
        return EXIT_INTERRUPTED
    except StoreError as error:
        say(f"\n[erro] {error}. O ficheiro do perfil que estava no disco não foi alterado.")
        metrics["outcome"] = "erro_disco"
        return EXIT_STORAGE
    except (CurriculumError, StudentError) as error:
        say(f"\n[erro] {error}.")
        metrics["outcome"] = "erro_configuracao"
        return EXIT_ERROR
    except Exception as error:      # rede de segurança: nunca termina com um erro sem tratamento
        say(f"\n[erro inesperado] {type(error).__name__}: {error}. O perfil gravado no disco não foi alterado.")
        console.log_only(traceback.format_exc())
        return EXIT_ERROR
    finally:
        metrics.update(duration_s=round(time.monotonic() - started, 2), model=llm.model,
                       llm_calls=llm.calls, llm_failures=llm.failures, llm_seconds=round(llm.seconds, 2))
        write_metrics(Path(args.log_dir), metrics)
        console.close_log()


if __name__ == "__main__":
    raise SystemExit(main())
