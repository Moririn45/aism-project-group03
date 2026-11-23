"""Demonstração e experiências do relatório (precisa do Ollama a correr).

Cada sessão corre num PROCESSO SEPARADO (`python main.py ...`), por isso o programa fecha
mesmo entre sessões e nenhum estado passa em memória de uma para a outra.

  E1  3 sessões da aluna simulada Ana, COM memória           -> logs/sessao_1..3.log
  E2  as mesmas 3 sessões SEM memória (linha de base): apaga-se a pasta de dados antes de cada sessão
  E3  testes de recuperação: corrupção, adulteração, remoção, perda do backup e do journal,
      tudo estragado, interrupção a meio da aula e modelo inexistente
  E4  testes unitários (python -m unittest)
  E5  métricas do modelo local (tempo por sessão, chamadas, tentativas do Professor)

No fim escreve logs/resultados.md e logs/resultados.json (os números das tabelas do relatório).
Uso:  python run_demo.py            (ou: python run_demo.py --model qwen2.5)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import time
from pathlib import Path

import console
from llm import DEFAULT_MODEL, LLMError, LocalLLM

ROOT = Path(__file__).resolve().parent
DEMO = ROOT / "demo"
STATE = DEMO / "estado"                 # estado da demonstração principal (E1)
WORK = DEMO / "estado_testes"           # cópias usadas nos testes de recuperação (E2, E3)
LOGS = ROOT / "logs"
ANA = DEMO / "aluno_ana.json"
ANA_STOPS = DEMO / "aluno_ana_interrompe.json"
ENV = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}


# ------------------------------------------------------------------ utilitários

def run_session(data_dir: Path, log_dir: Path, model: str, student: Path = ANA) -> dict:
    rel = lambda p: os.path.relpath(p, ROOT)        # caminhos curtos nos logs
    cmd = [sys.executable, "main.py", "--data-dir", rel(data_dir), "--log-dir", rel(log_dir),
           "--simulate", rel(student), "--model", model]
    start = time.monotonic()
    proc = subprocess.run(cmd, cwd=ROOT, env=ENV, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    return {"code": proc.returncode, "out": proc.stdout + proc.stderr,
            "seconds": round(time.monotonic() - start, 1)}


def read_profile(data_dir: Path) -> dict | None:
    try:
        return json.loads((data_dir / "profile.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def last_plan(profile: dict | None) -> dict:
    plans = [e for e in (profile or {}).get("history", []) if e["type"] == "plan"]
    return plans[-1] if plans else {}


def fresh(path: Path) -> Path:
    shutil.rmtree(path, ignore_errors=True)
    return path


def step(text: str) -> None:
    print(text, flush=True)


# ------------------------------------------------------------------ E1 e E2

def experiment_memory(model: str) -> list[dict]:
    step("\nE1 · 3 sessões com memória (processos separados)")
    rows = []
    for n in (1, 2, 3):
        r = run_session(STATE, LOGS, model)
        if r["code"] != 0:
            raise SystemExit(f"A sessão {n} falhou (código {r['code']}). Vê logs/sessao_{n}.log.\n{r['out'][-1500:]}")
        profile = read_profile(STATE)
        plan = last_plan(profile)
        rows.append({"session": n, "topic": plan["topic"], "mode": plan["mode"], "reason": plan["reason"],
                     "state": {k: v["status"] for k, v in profile["topics"].items()},
                     "seconds": r["seconds"]})
        shutil.copytree(STATE, fresh(WORK / f"_apos_sessao_{n}"))
        step(f"  sessão {n}: {plan['reason']}  ({r['seconds']} s)")
    return rows


def experiment_baseline(model: str) -> list[dict]:
    step("\nE2 · as mesmas 3 sessões SEM memória (a pasta de dados é apagada antes de cada sessão)")
    rows = []
    folder = WORK / "sem_memoria"
    for n in (1, 2, 3):
        fresh(folder)
        r = run_session(folder, LOGS / "sem_memoria" / f"execucao_{n}", model)
        profile = read_profile(folder)
        plan = last_plan(profile)
        rows.append({"run": n, "code": r["code"], "topic": plan.get("topic"), "mode": plan.get("mode"),
                     "diagnostic": any(e["type"] == "diagnostic" for e in profile["history"]) if profile else False,
                     "seconds": r["seconds"]})
        step(f"  execução {n}: diagnóstico outra vez; Planeador -> {plan.get('topic')}  ({r['seconds']} s)")
    return rows


def compare(memory: list[dict], baseline: list[dict]) -> list[dict]:
    def stats(topics, modes, diagnostics):
        new = [t for t, m in zip(topics, modes) if m == "avancar"]
        return {"diagnosticos": diagnostics,
                "perguntas_diagnostico": diagnostics * 4,
                "topicos_novos": len(set(new)),
                "aulas_repetidas": len(new) - len(set(new)),
                "fracoes_revistas_s3": topics[2] == "Frações" and modes[2] == "rever"}
    mem = stats([r["topic"] for r in memory], [r["mode"] for r in memory], 1)
    base = stats([r["topic"] for r in baseline], [r["mode"] for r in baseline],
                 sum(r["diagnostic"] for r in baseline))
    labels = [("diagnosticos", "Diagnósticos feitos"),
              ("perguntas_diagnostico", "Perguntas de diagnóstico feitas"),
              ("topicos_novos", "Tópicos novos ensinados"),
              ("aulas_repetidas", "Aulas repetidas do mesmo tópico novo"),
              ("fracoes_revistas_s3", "Sessão 3 revê Frações (reflete a sessão 1)")]
    return [{"metric": label, "baseline": base[key], "system": mem[key]} for key, label in labels]


# ------------------------------------------------------------------ E3

def truncate(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    path.write_text(text[: len(text) // 2], encoding="utf-8")


def tamper(path: Path) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    data["topics"]["Frações"]["status"] = "solid"          # muda o estado sem atualizar o checksum
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def garbage(*paths: Path) -> None:
    for p in paths:
        p.write_text("isto já não é um perfil", encoding="utf-8")


SCENARIOS = [
    # nome, descrição da falha, estado de partida, falha, sessão que devia correr, tópico esperado
    ("corrupcao", "profile.json cortado a meio", 2,
     lambda d: truncate(d / "profile.json"), 3, "Frações"),
    ("adulteracao", "Frações mudado para solid sem atualizar o checksum", 2,
     lambda d: tamper(d / "profile.json"), 3, "Frações"),
    ("remocao", "profile.json apagado", 2,
     lambda d: (d / "profile.json").unlink(), 3, "Frações"),
    ("remocao_com_backup", "profile.json e profile.bak.json apagados", 2,
     lambda d: [(d / f).unlink() for f in ("profile.json", "profile.bak.json")], 3, "Frações"),
    ("corrupcao_sem_journal", "profile.json cortado e history.jsonl apagado", 2,
     lambda d: (truncate(d / "profile.json"), (d / "history.jsonl").unlink()), 3, "Frações"),
    ("tudo_corrompido", "perfil, backup e journal com lixo", 2,
     lambda d: garbage(d / "profile.json", d / "profile.bak.json", d / "history.jsonl"), 3, "Frações"),
]


def experiment_recovery(model: str) -> list[dict]:
    step("\nE3 · testes de recuperação (partem do estado gravado no fim da sessão 2)")
    rows = []
    for name, fault_text, start_after, fault, expected_session, expected_topic in SCENARIOS:
        folder = fresh(WORK / name)
        shutil.copytree(WORK / f"_apos_sessao_{start_after}", folder)
        fault(folder)
        r = run_session(folder, LOGS / "testes" / name, model)
        profile = read_profile(folder)
        plan = last_plan(profile)
        played = plan.get("session")
        notes = [line.split("] ", 1)[1] for line in r["out"].splitlines()
                 if line.startswith(("[recuperação]", "[aviso]"))]
        rows.append({"scenario": name, "fault": fault_text, "code": r["code"], "played_session": played,
                     "expected_session": expected_session, "topic": plan.get("topic"),
                     "sessions_lost": (expected_session - played) if played else None,
                     "isolated": sorted(p.name for p in folder.glob("*corrupt*")),
                     "notes": notes,
                     "handled": r["code"] == 0 and profile is not None,
                     "same_decision": plan.get("topic") == expected_topic and played == expected_session})
        step(f"  {name}: sessão {played} -> {plan.get('topic')} · perdidas: {rows[-1]['sessions_lost']} "
             f"· {'sem erro' if r['code'] == 0 else 'código ' + str(r['code'])}")

    # interrupção a meio da aula (parte do fim da sessão 1)
    folder = fresh(WORK / "interrupcao")
    shutil.copytree(WORK / "_apos_sessao_1", folder)
    before = (folder / "profile.json").read_bytes()
    r1 = run_session(folder, LOGS / "testes" / "interrupcao", model, student=ANA_STOPS)
    unchanged = (folder / "profile.json").read_bytes() == before
    run_session(folder, LOGS / "testes" / "interrupcao", model)
    r3 = run_session(folder, LOGS / "testes" / "interrupcao", model)
    plan = last_plan(read_profile(folder))
    rows.append({"scenario": "interrupcao", "fault": "programa fechado a meio da aula da sessão 2",
                 "code": r1["code"], "played_session": plan.get("session"), "expected_session": 3,
                 "topic": plan.get("topic"), "sessions_lost": 0 if unchanged else None, "isolated": [],
                 "notes": ["perfil intacto; a sessão 2 repetiu-se"] if unchanged else ["o perfil mudou!"],
                 "handled": r1["code"] == 130 and unchanged and r3["code"] == 0,
                 "same_decision": plan.get("topic") == "Frações"})
    step(f"  interrupcao: perfil intacto = {unchanged}; depois, sessão {plan.get('session')} -> {plan.get('topic')}")

    # modelo inexistente: o programa explica o que falta e não toca no perfil
    folder = fresh(WORK / "modelo_inexistente")
    shutil.copytree(WORK / "_apos_sessao_2", folder)
    before = (folder / "profile.json").read_bytes()
    r = run_session(folder, LOGS / "testes" / "modelo_inexistente", "modelo-que-nao-existe")
    unchanged = (folder / "profile.json").read_bytes() == before
    rows.append({"scenario": "modelo_inexistente", "fault": "--model com um modelo que não existe",
                 "code": r["code"], "played_session": None, "expected_session": None, "topic": None,
                 "sessions_lost": 0 if unchanged else None, "isolated": [],
                 "notes": [line for line in r["out"].splitlines() if line.startswith("[erro]")],
                 "handled": r["code"] == 2 and unchanged, "same_decision": None})
    step(f"  modelo_inexistente: código {r['code']}, perfil intacto = {unchanged}")
    return rows


# ------------------------------------------------------------------ E4 e E5

def experiment_unit_tests() -> dict:
    step("\nE4 · testes unitários")
    proc = subprocess.run([sys.executable, "-m", "unittest"], cwd=ROOT, env=ENV, capture_output=True,
                          text=True, encoding="utf-8", errors="replace")
    ran = re.search(r"Ran (\d+) tests? in ([\d.]+)s", proc.stderr)
    result = {"tests": int(ran.group(1)) if ran else 0, "seconds": float(ran.group(2)) if ran else None,
              "ok": proc.returncode == 0, "tail": proc.stderr.strip().splitlines()[-1:]}
    step(f"  {result['tests']} testes, {'todos passaram' if result['ok'] else 'HÁ FALHAS'}")
    return result


def llm_metrics() -> dict:
    rows = []
    for path in LOGS.rglob("metricas.jsonl"):
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    ok = [r for r in rows if r.get("outcome") == "ok"]
    attempts = [r.get("teacher_attempts") or 0 for r in ok]

    def mean(values):
        return round(statistics.mean(values), 2) if values else None

    return {"model": ok[0]["model"] if ok else None,
            "sessions": len(rows),
            "sessions_ok": len(ok),
            "lessons_failed": sum(r.get("outcome") == "aula_falhou" for r in rows),
            "mean_session_seconds": mean([r["duration_s"] for r in ok]),
            "max_session_seconds": max((r["duration_s"] for r in ok), default=None),
            "mean_llm_seconds": mean([r["llm_seconds"] for r in ok]),
            "mean_llm_calls": mean([r["llm_calls"] for r in ok]),
            "first_try_lessons_pct": round(100 * attempts.count(1) / len(attempts), 1) if attempts else None,
            "mean_teacher_attempts": mean(attempts),
            "llm_failures": sum(r.get("llm_failures", 0) for r in rows)}


# ------------------------------------------------------------------ relatório em Markdown

def yes(value) -> str:
    if isinstance(value, bool):
        return "sim" if value else "não"
    return "-" if value is None else str(value)


def write_report(results: dict) -> None:
    md = ["# Resultados da demonstração", "",
          f"Modelo: `{results['model']}` · gerado em {time.strftime('%Y-%m-%d %H:%M')}", "",
          "## E1 · Três sessões com memória", "",
          "| Sessão | Decisão do Planeador | Estado no fim da sessão |", "|---|---|---|"]
    for r in results["memory"]:
        state = ", ".join(f"{k}: {v or '-'}" for k, v in r["state"].items())
        md.append(f"| {r['session']} | {r['reason']} | {state} |")
    md += ["", "## E2 · Com memória vs. sem memória (3 sessões)", "",
           "| Métrica | Sem memória (linha de base) | Com memória (o nosso sistema) |", "|---|---|---|"]
    for r in results["comparison"]:
        md.append(f"| {r['metric']} | {yes(r['baseline'])} | {yes(r['system'])} |")
    md += ["", "## E3 · Recuperação de falhas", "",
           "| Cenário | Falha | Sessão jogada | Tópico | Sessões perdidas | Ficheiros isolados | Sem erro |",
           "|---|---|---|---|---|---|---|"]
    for r in results["recovery"]:
        md.append(f"| {r['scenario']} | {r['fault']} | {r['played_session'] or '-'} | {r['topic'] or '-'} | "
                  f"{r['sessions_lost'] if r['sessions_lost'] is not None else '-'} | "
                  f"{', '.join(r['isolated']) or '-'} | {yes(r['handled'])} |")
    u = results["unit_tests"]
    m = results["llm"]
    md += ["", "## E4 · Testes unitários", "", f"{u['tests']} testes · {'todos passaram' if u['ok'] else 'HÁ FALHAS'}"
           f" · {u['seconds']} s", "",
           "## E5 · Modelo local", "",
           "| Métrica | Valor |", "|---|---|",
           f"| Sessões executadas (todas as experiências) | {m['sessions']} |",
           f"| Sessões concluídas | {m['sessions_ok']} |",
           f"| Tempo médio por sessão (s) | {m['mean_session_seconds']} |",
           f"| Tempo máximo por sessão (s) | {m['max_session_seconds']} |",
           f"| Tempo médio no modelo por sessão (s) | {m['mean_llm_seconds']} |",
           f"| Chamadas ao modelo por sessão (média) | {m['mean_llm_calls']} |",
           f"| Aulas válidas à 1.ª tentativa (%) | {m['first_try_lessons_pct']} |",
           f"| Tentativas do Professor por aula (média) | {m['mean_teacher_attempts']} |",
           f"| Aulas que falharam as 3 tentativas | {m['lessons_failed']} |",
           f"| Respostas inválidas do modelo (total) | {m['llm_failures']} |", "",
           "## Verificações", ""]
    md += [f"- {'OK ' if ok else 'FALHOU'} {text}" for text, ok in results["checks"]]
    (LOGS / "resultados.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    (LOGS / "resultados.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")


# ------------------------------------------------------------------ main

def main() -> int:
    console.setup_utf8()
    parser = argparse.ArgumentParser(description="Gera os logs e os resultados do relatório.")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"modelo do Ollama (por defeito: {DEFAULT_MODEL})")
    args = parser.parse_args()
    try:
        LocalLLM(args.model).check()
    except LLMError as error:
        print(f"[erro] {error}\nA demonstração precisa do Ollama a correr.")
        return 2
    print(f"Demonstração com o modelo {args.model}. Pode demorar alguns minutos.")
    for path in (STATE, WORK, LOGS):
        fresh(path)
    LOGS.mkdir(parents=True)

    started = time.monotonic()
    memory = experiment_memory(args.model)
    baseline = experiment_baseline(args.model)
    recovery = experiment_recovery(args.model)
    unit = experiment_unit_tests()
    results = {"model": args.model, "memory": memory, "baseline": baseline,
               "comparison": compare(memory, baseline), "recovery": recovery,
               "unit_tests": unit, "llm": llm_metrics()}
    results["checks"] = [
        ("Sessão 1 avança para Equações", memory[0]["topic"] == "Equações"),
        ("Sessão 2 avança para Funções", memory[1]["topic"] == "Funções"),
        ("Sessão 3 revê Frações por causa da sessão 1", memory[2]["topic"] == "Frações" and memory[2]["mode"] == "rever"),
        ("Sem memória, a sessão 3 não revê Frações", baseline[2]["topic"] != "Frações"),
        ("Nenhum cenário de falha terminou com erro sem tratamento", all(r["handled"] for r in recovery)),
        ("Corrupção, adulteração e remoção: a sessão 3 revê Frações",
         all(r["same_decision"] for r in recovery if r["scenario"] in
             ("corrupcao", "adulteracao", "remocao", "remocao_com_backup", "interrupcao"))),
        ("Testes unitários passaram", unit["ok"]),
    ]
    results["total_seconds"] = round(time.monotonic() - started, 1)
    write_report(results)
    print("\nVerificações:")
    for text, ok in results["checks"]:
        print(f"  {'OK    ' if ok else 'FALHOU'} {text}")
    print(f"\nFeito em {results['total_seconds']} s. Resultados em logs/resultados.md; logs das sessões em logs/.")
    return 0 if all(ok for _, ok in results["checks"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
