# Tutor Curricular Pessoal com Memória Persistente

Projeto 13 · Agentes Inteligentes e Sistemas Multiagentes · Grupo 03

Um tutor de Matemática com três agentes (Avaliador, Planeador e Professor) que corre sobre um modelo local no
Ollama. Tudo o que o tutor sabe sobre o aluno fica em `data/profile.json`, por isso o programa pode ser fechado e
reaberto sem perder o progresso, e recupera o perfil se o ficheiro for corrompido ou apagado.

## Grupo

- Bruno Graça (230000972)
- Gonçalo Ferreira (230001170)
- Ricardo Ferreira (230001057)

## Instalação

Precisa de Python 3.10 ou superior e do [Ollama](https://ollama.com/download). Não é preciso conta nem chave de API.

```bash
ollama pull llama3.2
pip install -r requirements.txt
```

## Como correr

```bash
python main.py        # uma sessão do tutor; volta a correr para continuar
python run_demo.py    # demonstração e resultados do relatório (demora alguns minutos)
python -m unittest    # 36 testes (não precisam do Ollama)
```

No Windows, se `python` não for reconhecido, usa `py`.

## O que deve aparecer

Cada execução de `main.py` é uma sessão e o programa termina no fim. Na sessão 3 da demonstração, o Planeador
volta a Frações por causa do diagnóstico da sessão 1:

```
[Planeador] Revejo Frações: está fraco desde a sessão 1 e esta já é a 3.ª sessão (regra das 3 sessões).
```

O `run_demo.py` cria a pasta `logs/`, com um log por sessão e os resultados em `logs/resultados.md`.

## Estrutura

```
main.py            uma sessão: carrega o perfil, chama os três agentes e grava
run_demo.py        experiências do relatório
profile_store.py   gravação segura do perfil, checksum, backup e recuperação
llm.py             ligação ao modelo local (Ollama)
console.py, curriculum.py, students.py   ecrã e logs, leitura da disciplina, aluno
agents/            Avaliador, Planeador, Professor e mensagens entre eles
subjects/          tópicos e perguntas do diagnóstico (dataset)
demo/              aluna simulada e estado final da demonstração
tests/             testes automáticos
logs/              registos das sessões e resultados
```
