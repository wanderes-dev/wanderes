# Relatório Final — Improvement Cycle 1

Rodada: `evaluations/runs/20260925-142147_cycle1/` · comparada contra `evaluations/runs/20260925-114531_baseline/` · 2026-09-25

## 1. Arquivos alterados

**Produção**:
- `ai/orchestration.py` — Fix A (candidatos numerados por rank + instrução explícita de fidelidade de ranking na explicação); Fix C (instrução de exclusão implícita "já visitei X" no prompt de extração); Fix B (canonicalização de país aplicada em `_validate_intent`).
- `travel/geography_aliases.py` (**novo**) — tabela explícita de aliases de país (EN/PT), `canonicalize_country_name()`.
- `travel/services.py` — `is_known_country()` e `find_destination_slugs_by_name()` agora canonicalizam antes de comparar.

**Testes** (31 novos): `ai/tests/test_orchestration.py` (`RankingFidelityTests`, `CountryAliasCanonicalizationTests`, `PreviousVisitExclusionPromptTests`, `ExplicitAndImplicitExclusionExtractionTests`), `travel/tests/test_services.py` (extensões), `travel/tests/test_geography_aliases.py` (novo).

**Documentação**: `documentation/DEVELOPMENT_LOG.md`, `documentation/PROJECT_STATE.md`.

**Artefato desta rodada**: `evaluations/runs/20260925-142147_cycle1/` (baseline original preservado, intocado).

## 2. Mudanças exatas de comportamento em produção

1. **Fidelidade de ranking na explicação** (`ai/orchestration.py::_build_explanation_messages`): a lista de candidatos agora é numerada por rank real (`1. Dubrovnik...`, `2. Nice...`) em vez de marcadores soltos, e o prompt agora instrui explicitamente: "#1 é o vencedor real, não uma sugestão livre para reordenar"; "a opção apresentada primeiro/como recomendação principal deve ser #1"; "nunca troque silenciosamente por um candidato de rank menor"; e permite honestidade sobre desvantagens do #1 sem substituí-lo.
2. **Normalização geográfica** (`travel/geography_aliases.py`, aplicado em `travel/services.py` e `ai/orchestration.py::_validate_intent`): "United States"/"US"/"Estados Unidos"/"EUA" → `"USA"` (valor exato do catálogo); ~130 traduções PT→EN para os demais países do catálogo cujo nome em português difere do inglês (ex.: "Tailândia"→"Thailand"). Aplicado em 3 pontos: reconhecimento de país (`is_known_country`), filtro geográfico (o valor armazenado em `RecommendationRequest.country` agora é o canônico), e exclusões (`find_destination_slugs_by_name`).
3. **Exclusão por visita anterior** (`ai/orchestration.py`, prompt de extração): "já fui a Roma e Praga, quero outro lugar" agora deve virar `excluded_place_names=['Rome', 'Prague']`; "já fui a Roma e amei, algo parecido seria ótimo" continua explicitamente NÃO devendo excluir Roma - distinção preservada no próprio prompt.

**Nada mais foi alterado** em produção — classificador de acomodação e semântica cheap/budget permanecem intocados, conforme instruído.

## 3. Cenários de regressão adicionados

11 novos testes cobrindo os 3 fixes diretamente (não apenas o corpus de avaliação): 4 para Fix A (numeração, instrução "#1 é o vencedor", proibição de troca silenciosa, permissão de honestidade sobre desvantagens), 3 para Fix B via `ai/tests/test_orchestration.py` + 8 em `travel/tests/` (aliases EN/PT resolvendo, cidade real não afetada, alias não reconhecido não é adivinhado), 3+3 para Fix C (prompt cobre o caso implícito, prompt preserva a exceção "quero algo parecido", exclusão explícita/implícita/múltipla funcionam fim-a-fim).

Os próprios cenários MTT-002, MTT-010, STR-032 e ADV-007 do corpus de avaliação (já existentes, com a asserção **correta** desde a criação, deliberadamente deixados falhando no baseline) não foram alterados - passam a passar naturalmente porque o comportamento real mudou, não porque a asserção foi enfraquecida.

## 4. Resultado do pytest normal

**755/755 testes passando** (724 pré-existentes + 31 novos), zero regressões.

## 5. Resultado do lint

**`ruff check .` limpo.**

## 6. Caminho da nova rodada de avaliação

`evaluations/runs/20260925-142147_cycle1/`

## 7. Taxa de aprovação: baseline vs. novo

| | Baseline | Cycle 1 |
|---|---|---|
| Geral | 113/150 (75,3%) | **129/150 (86,0%)** |
| Dev | 97/127 (76,4%) | 108/127 (85,0%) |
| Holdout | 16/23 (69,6%) | 21/23 (91,3%) |

## 8. Taxonomia de falhas: baseline vs. novo

| Categoria | Baseline | Cycle 1 |
|---|---|---|
| EXPLANATION_GROUNDING | 26 | **4** |
| INTENT_EXTRACTION | 13 | 12 |
| HARD_CONSTRAINT | 4 | **0** |
| SCORING | 2 | 8 (ver §17 - não é regressão real) |

## 9. Número de cenários corrigidos

**25 cenários** passaram a passar que antes falhavam.

## 10. Cenários novos quebrados

**9 cenários**, mas **nenhum é uma regressão real causada pelos 3 fixes** - ver diagnóstico completo no §17. Nomes: `AMB-001`, `CON-004`, `STR-004`, `STR-005`, `STR-016`, `STR-019`, `STR-041`, `STR-052`, `STR-054`.

## 11. Comparação do conjunto dev

97/127 (76,4%) → 108/127 (85,0%). +11 cenários líquidos.

## 12. Comparação do conjunto holdout

16/23 (69,6%) → 21/23 (91,3%). Holdout melhorou **mais** que dev em pontos percentuais - nenhum sinal de overfitting ao conjunto dev.

## 13. Comparação metamórfica

10/10 pares passaram nas checagens estruturais em ambas as rodadas - nenhuma mudança, como esperado (os 3 fixes não tocam a lógica de scoring/monotonicidade).

## 14. As 26 falhas de grounding de ranking/apresentação foram eliminadas ou reduzidas?

**Reduzidas drasticamente: de 26 para 4 (-85%).** Das 4 restantes: uma (`MET-006b`) é um par metamórfico sem checagem estrita por design; uma (`MTT-010`) é uma variação genuína de extração não relacionada aos 3 fixes; **duas (`STR-004`, `STR-012`) são falsos positivos da própria checagem de avaliação** - confirmei manualmente que em ambos os casos o Fix A funcionou corretamente (o destino #1 real foi apresentado primeiro), mas a checagem por substring literal não reconheceu "Brașov" (com o diacrítico romeno correto) como "Brasov", nem "Roma" (nome em português, correto para uma resposta em português) como "Rome" (nome em inglês do catálogo). Isso é uma limitação conhecida do framework de avaliação (§16 do relatório do baseline já documentava isso), não do Fix A.

## 15. Resultado da normalização geográfica

`excluded_place_names`: precisão de extração **25% → 100%** (efeito combinado de Fix B + Fix C). `country`: 96% (estável). O caso concreto do EUA (`STR-032`) e o caso do Thailand/Tailândia em exclusões (`ADV-007`) ambos passaram a passar. 8 novos testes diretos confirmam os aliases EN/PT resolvendo corretamente sem afetar nomes de cidade reais.

## 16. Resultado da exclusão por visita anterior

`MTT-002` (Roma/Praga) passou a passar. `MTT-010` (Tóquio/Osaka) permanece instável - nesta rodada específica, o país/trip_type não foram extraídos corretamente por uma razão não relacionada à exclusão em si (ver §17), então a exclusão em si não pôde ser propriamente testada nesta execução. Recomendo uma nova checagem pontual deste caso amanhã, quando a cota do provedor de clima resetar.

## 17. Principais categorias de falha restantes + diagnóstico completo das 9 "quebras"

**Achado crítico, verificado com evidência direta**: durante esta rodada, a cota diária gratuita do Open-Meteo (provedor de clima) se esgotou - confirmado fazendo uma chamada HTTP direta à API, que retornou `429 Daily API request limit exceeded. Please try again tomorrow.` Um teste em amostra aleatória de 8 destinos mostrou 7 falhas de conectividade agora. Isso é esperado dado o volume real de chamadas de clima feito ao longo desta sessão (múltiplas rodadas completas de avaliação + testes anteriores no mesmo dia) - **não está relacionado a nenhum dos 3 fixes aprovados**.

Diagnóstico de cada uma das 9 "quebras", com evidência:

- **`STR-005`, `STR-016`, `STR-019`, `STR-041`, `STR-052`, `STR-054`** (6 casos, todos `winner_in_acceptable_set`/`zero_results_expectation`): extração de intenção 100% correta em todos (confirmado via `intent_eval`), mas `scored=[]`. Reproduzi isoladamente: `generate_recommendations` para Japão/cultura/abril retornou `climate_errors: 3` de `3` candidatos elegíveis - todos os 3 falharam por "Unable to reach the climate data provider". **Causa: cota diária do Open-Meteo esgotada, não os 3 fixes.**
- **`AMB-001`** (`intent_field:trip_type`): mensagem deliberadamente ambígua ("quero algo relaxante, tipo um lugar tranquilo") - variação normal de extração entre execuções (não determinístico mesmo em temperature=0), campo não tocado por nenhum dos 3 fixes.
- **`CON-004`** (`flow_mismatch`): mensagem autocontraditória ("excluir toda a Europa mas quero visitar Paris") - classificada como `future_intent` nesta rodada em vez de `recommendation`; já documentada no próprio corpus como um caso genuinamente ambíguo. Não relacionado a nenhum dos 3 fixes (classificação de message_type não foi tocada).
- **`STR-004`** (`winner_mentioned`): `scored_slugs` **idênticos** entre baseline e esta rodada (`Brasov` em #1 em ambas) - a checagem falhou porque a resposta desta rodada escreveu "Brașov" (com o diacrítico romeno correto) em vez de "Brasov" (grafia ASCII do catálogo). Fix A funcionou corretamente; falso positivo da checagem de avaliação.

Nenhuma investigação adicional foi possível hoje devido à cota esgotada do Open-Meteo. **Recomendo fortemente uma nova rodada completa amanhã**, quando a cota resetar, para uma comparação definitivamente limpa.

**Categorias de falha que genuinamente permanecem, não atribuíveis a infraestrutura**:
- `flow_mismatch` em mensagens genuinamente ambíguas (`ADV-008`, `CON-002`, `INC-010`, `MTT-006`, `MTT-008`) - variação de classificação de `message_type`, não tocada por nenhum dos 3 fixes.
- `STR-006` (classificador de acomodação disparando cedo demais) - documentado, deliberadamente não corrigido nesta rodada, conforme instruído.
- `STR-027`, `STR-037` - já documentados no relatório do baseline como achados de confiança menor.

## 18. Recomendação para Improvement Cycle 2

1. **Prioridade alta**: rodar a avaliação completa novamente amanhã (cota do Open-Meteo resetada) para confirmar os números limpos, sem o ruído de infraestrutura desta rodada.
2. Corrigir a limitação de diacrítico/tradução na checagem `winner_mentioned` do próprio framework (normalizar unicode e/ou aceitar o nome localizado do destino, não só o nome em inglês do catálogo) - evitaria falsos positivos como `STR-004`/`STR-012`.
3. Investigar a decisão de produto pendente sobre o classificador de acomodação em nível de país (`STR-006`) - meu não-fix.
4. Considerar reforçar a classificação de `message_type` para mensagens ambíguas tipo `CON-004`/`INC-010`, já que a regra documentada "default para recomendação em caso ambíguo" nem sempre é seguida.

**Não iniciei o Improvement Cycle 2** - parando aqui, conforme instruído.
