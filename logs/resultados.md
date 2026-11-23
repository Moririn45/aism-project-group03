# Resultados da demonstração

Modelo: `llama3.2` · gerado em 2026-11-23 19:59

## E1 · Três sessões com memória

| Sessão | Decisão do Planeador | Estado no fim da sessão |
|---|---|---|
| 1 | Avanço para Equações: é o próximo tópico novo (Frações está fraco, mas esta é só a 1.ª sessão; revejo-o na sessão 3). | Números inteiros: solid, Frações: weak, Equações: improving, Funções: -, Percentagens: -, Teorema de Pitágoras: - |
| 2 | Avanço para Funções: é o próximo tópico novo (Frações está fraco, mas esta é só a 2.ª sessão; revejo-o na sessão 3). | Números inteiros: solid, Frações: weak, Equações: improving, Funções: improving, Percentagens: -, Teorema de Pitágoras: - |
| 3 | Revejo Frações: está fraco desde a sessão 1 e esta já é a 3.ª sessão (regra das 3 sessões). | Números inteiros: solid, Frações: improving, Equações: improving, Funções: improving, Percentagens: -, Teorema de Pitágoras: - |

## E2 · Com memória vs. sem memória (3 sessões)

| Métrica | Sem memória (linha de base) | Com memória (o nosso sistema) |
|---|---|---|
| Diagnósticos feitos | 3 | 1 |
| Perguntas de diagnóstico feitas | 12 | 4 |
| Tópicos novos ensinados | 1 | 2 |
| Aulas repetidas do mesmo tópico novo | 2 | 0 |
| Sessão 3 revê Frações (reflete a sessão 1) | não | sim |

## E3 · Recuperação de falhas

| Cenário | Falha | Sessão jogada | Tópico | Sessões perdidas | Ficheiros isolados | Sem erro |
|---|---|---|---|---|---|---|
| corrupcao | profile.json cortado a meio | 3 | Frações | 0 | profile.corrupt.json | sim |
| adulteracao | Frações mudado para solid sem atualizar o checksum | 3 | Frações | 0 | profile.corrupt.json | sim |
| remocao | profile.json apagado | 3 | Frações | 0 | - | sim |
| remocao_com_backup | profile.json e profile.bak.json apagados | 3 | Frações | 0 | - | sim |
| corrupcao_sem_journal | profile.json cortado e history.jsonl apagado | 2 | Funções | 1 | profile.corrupt.json | sim |
| tudo_corrompido | perfil, backup e journal com lixo | 1 | Equações | 2 | history.corrupt.jsonl, profile.bak.corrupt.json, profile.corrupt.json | sim |
| interrupcao | programa fechado a meio da aula da sessão 2 | 3 | Frações | 0 | - | sim |
| modelo_inexistente | --model com um modelo que não existe | - | - | 0 | - | sim |

## E4 · Testes unitários

36 testes · todos passaram · 0.642 s

## E5 · Modelo local

| Métrica | Valor |
|---|---|
| Sessões executadas (todas as experiências) | 16 |
| Sessões concluídas | 14 |
| Tempo médio por sessão (s) | 12.39 |
| Tempo máximo por sessão (s) | 15.52 |
| Tempo médio no modelo por sessão (s) | 10.73 |
| Chamadas ao modelo por sessão (média) | 1 |
| Aulas válidas à 1.ª tentativa (%) | 100.0 |
| Tentativas do Professor por aula (média) | 1 |
| Aulas que falharam as 3 tentativas | 0 |
| Respostas inválidas do modelo (total) | 0 |

## Verificações

- OK  Sessão 1 avança para Equações
- OK  Sessão 2 avança para Funções
- OK  Sessão 3 revê Frações por causa da sessão 1
- OK  Sem memória, a sessão 3 não revê Frações
- OK  Nenhum cenário de falha terminou com erro sem tratamento
- OK  Corrupção, adulteração e remoção: a sessão 3 revê Frações
- OK  Testes unitários passaram
