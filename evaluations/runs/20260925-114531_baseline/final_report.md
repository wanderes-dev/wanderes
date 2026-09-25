# Relatório Final — Framework de Avaliação de Recomendações do Wanderes

Baseline: `evaluations/runs/20260925-114531_baseline/` · 2026-09-25

## 1. Arquivos criados/modificados

**Novo app `evaluations/`** (~30 arquivos, sem models): `scenarios.py`, `invariants.py`, `intent_eval.py`, `grounding.py`, `metamorphic.py`, `trace.py`, `taxonomy.py`, `llm_judge.py`, `runner.py`, `persistence.py`, `compare.py`, `cost.py`, `profiles.py`, `requests.py`, comandos `evaluate_recommendations`/`compare_evaluations`, 15 arquivos de teste (124 testes), `corpus/build_corpus.py` + `scenarios.jsonl` (150 cenários).

**Produção, mudanças mínimas e aditivas**: `recommendations/scoring.py` (`generate_recommendations` ganhou parâmetro opcional `trace`), `ai/orchestration.py` (`stream_travel_recommendation` ganhou parâmetro opcional `intent_sink`) — zero mudança de comportamento quando omitidos, cobertos pelos 600 testes já existentes.

**Documentação**: `documentation/17_EVALUATION_FRAMEWORK.md` (novo), `DECISIONS_PENDING.md` §10, `DEVELOPMENT_LOG.md`, `PROJECT_STATE.md`.

**Artefato do baseline commitado**: `evaluations/runs/20260925-114531_baseline/` (meta.json, results.jsonl, metamorphic.jsonl, summary.md, este arquivo).

## 2. Contagem de cenários

**150 cenários** reais, ancorados no catálogo de 384 destinos: straightforward (55), metamorphic (20), incomplete (15), robustness (18), ambiguous (12), conflicting (10), adversarial (10), multi_turn (10).

## 3. Split dev/holdout

**127 dev / 23 holdout** (~85/15). Iteração/tuning só contra dev; holdout existe para detectar overfitting ao próprio corpus.

## 4. Arquitetura de avaliação

Pipeline avaliado em 3 camadas independentes, espelhando a arquitetura real (`natural language → extração de intenção → scoring determinístico → explicação`):

- **Camada 1** (extração): compara campo-a-campo o que `_extract_intent` realmente extraiu vs. esperado.
- **Camada 2** (scoring/ranking): invariantes determinísticos rodam sem IA nenhuma, direto contra `generate_recommendations`.
- **Camada 3** (explicação): checagens regex/substring de que a resposta da IA nunca inventa preço, disponibilidade, ou avaliação.

Dois modos: **determinístico** (padrão, custo zero) e **pipeline completo** (`--sample`/`--full`, IA real).

## 5. Métricas determinísticas

Exclusões respeitadas, orçamento/temperatura/trip_type nunca violados, ranking ordenado e determinístico para input idêntico, preference_fit/repetition_penalty realmente aplicados, e uma checagem estrutural que nenhum campo de afiliado/aquisição consegue sequer chegar na assinatura de `generate_recommendations`.

## 6. Métricas baseadas em IA

Nenhuma usada neste baseline (`--with-llm-judge` não foi ativado — fica disponível para uma rodada futura opcional). A única métrica "de IA" usada foi a própria extração de intenção real (não um julgamento subjetivo).

## 7. Resultados do baseline

**113/150 passou (75,3%)**. Custo real: **$0,0568**. Todos os 10 pares metamórficos passaram nas checagens estruturais (monotonicidade de orçamento/temperatura/geografia/exclusão se confirma 100%).

## 8. Contagem por taxonomia de falha

| Categoria | Contagem |
|---|---|
| EXPLANATION_GROUNDING | 26 |
| INTENT_EXTRACTION | 13 |
| HARD_CONSTRAINT | 4 |
| SCORING | 2 |

(Total de checagens falhas > 37 cenários falhos porque um cenário pode falhar em mais de uma checagem.)

## 9. 10 falhas representativas

1. **ADV-001/AMB-008/CON-002/...** (26 casos): a explicação da IA monta sua própria tabela "melhores 1-3" a partir dos 10 candidatos recebidos, mas nem sempre inclui o #1 do ranking determinístico — ex.: Dubrovnik era o #1 real, mas a resposta destacou Creta/Busan/Cinque Terre.
2. **STR-032**: "Estados Unidos" pedido em português → IA extrai corretamente `country="United States"`, mas o catálogo guarda `"USA"` → `is_known_country()` falha, cai no fallback genérico mesmo os EUA estando no catálogo com dados reais.
3. **MTT-002**: "já fui pra Roma e Praga antes, quero outro lugar" não vira exclusão — Roma volta a ser recomendada.
4. **MTT-010**: mesmo padrão — "já fui a Tóquio e Osaka" não exclui nenhuma das duas.
5. **ADV-007**: pedido de exclusão em português extrai os nomes em português ("Tailândia") em vez do inglês que o catálogo usa — a exclusão silenciosamente não funcionaria.
6. **STR-006**: "hospedagem barata na tailândia" (um país, não um lugar específico) disparou erroneamente o fluxo de acomodação (pediu número de pessoas) em vez de recomendação.
7. **INC-010**: "in Europe, that's the only thing I've decided" foi classificado como intenção futura, não recomendação ativa — indo contra a própria regra documentada do prompt de "default para recomendação em caso ambíguo".
8. **STR-027**: pedido com dois trip_types igualmente citados ("culture and nature both interest me") ainda assim resultou em um trip_type único sendo fixado, contra a própria regra do prompt.
9. **STR-037**: "fugir do frio" (escapar do frio) não ativou nenhuma âncora de temperatura mínima — frase indireta não reconhecida (achado de confiança mais baixa, comportamento defensável).
10. **CON-005**: orçamento irreal declarado ("50 euros por duas semanas") corretamente não vira `max_cost_of_living` (não existe campo pra valor monetário bruto na mensagem) — comportamento correto, não uma falha real.

## 10. Problemas de qualidade de dados de destino

**Nenhum encontrado nesta passada.** As 150 execuções não expuseram inconsistências reais no catálogo (o único caso que parecia um — STR-038, Capadócia/Pamukkale marcados como "nature" não "culture" — era só uma suposição errada minha ao escrever o cenário; a tag do catálogo está correta e é uma escolha defensável). Vale registrar como limitação: esta passada não fez uma auditoria exaustiva do catálogo, só o que os 150 cenários tocaram organicamente.

## 11. Top 5 propostas de melhoria

Ranqueadas por frequência × severidade × confiança. Nenhuma foi implementada — ficam para revisão e priorização.

1. **[ALTA confiança] Normalização de nome de país (EUA/"United States")** — `travel.services.is_known_country()` faz match exato (`iexact`) contra o valor literal do catálogo (`"USA"`), mas a IA naturalmente extrai `"United States"`. Qualquer pedido mencionando os EUA cai silenciosamente no fallback genérico, mesmo havendo ~15 destinos reais nos EUA no catálogo. **Correção sugerida**: normalizar via um mapa de sinônimos (USA/United States/US/América) ou trocar `iexact` por uma comparação mais tolerante.
2. **[MÉDIA-ALTA confiança, maior frequência: 26/37 falhas] A explicação nem sempre destaca o #1 do ranking determinístico** — a IA monta sua "tabela dos melhores 1-3" com julgamento próprio sobre quais dos 10 candidatos parecem mais relevantes, em vez de ancorar no que a aplicação já rankeou como melhor. Toca diretamente o princípio arquitetural "a IA nunca deve virar o motor de ranking" — mesmo sem re-pontuar, escolher quais destaca já é uma forma de re-priorização implícita. **Decisão de produto necessária**: reforçar o prompt para sempre mencionar o #1 real, ou aceitar que a IA pode reordenar sua apresentação por julgamento (especialmente em pedidos adversariais/impossíveis, onde pode ser desejável).
3. **[MÉDIA-ALTA confiança] Frases de exclusão implícita não são reconhecidas** — "já fui a X, quero outro lugar" não vira `excluded_place_names`, só uma instrução explícita ("excluir X") funciona. Mina diretamente a promessa de personalização/não-repetição.
4. **[MÉDIA confiança] Classificador de `is_accommodation_request` pode disparar cedo demais** — em "hospedagem barata na Tailândia" (um país inteiro, não "um lugar específico"), pediu número de pessoas em vez de recomendar. Risco de regressão pontual num fluxo construído nesta mesma sessão.
5. **[Achado de clareza, não de bug] Âncoras de orçamento "cheap"(→3) vs. "budget/very cheap"(→2) são sutis e fáceis de confundir** — confirmei que o modelo segue essa distinção fielmente (9 dos meus próprios cenários erraram justamente por eu não ter internalizado a diferença), mas a distinção está sub-documentada no prompt/código, risco real de erro futuro de engenharia.

## 12. Custo estimado da avaliação

Baseline completo real: **$0,0568** (150 chamadas de pipeline, modelo gpt-4o-mini). Modo determinístico: **$0** sempre. `--sample 20` ficaria em torno de $0,007-0,008.

## 13. Resultado do pytest normal

**724/724 testes passando** (600 pré-existentes + 124 novos do framework, todos rápidos e sem IA).

## 14. Resultado do lint

**`ruff check .` limpo.**

## 15. Comandos exatos para rodar de novo

```bash
# Determinístico, split dev, custo zero (padrão)
python manage.py evaluate_recommendations

# Pipeline completo, amostra pequena
python manage.py evaluate_recommendations --sample 20

# Baseline completo (os dois splits, todo o corpus)
python manage.py evaluate_recommendations --split all --full --label baseline

# Comparar duas rodadas salvas
python manage.py compare_evaluations 20260925-114531_baseline <nova_rodada>

# Trace de diagnóstico de um cenário específico
python manage.py evaluate_recommendations --trace STR-005
```

## 16. O que essa avaliação ainda não consegue medir com confiança

- **O acumulador de clima/orçamento entre turnos (Redis)** — cenários com `history` usam `history_override`, que força `conv_key=None`, contornando esse mecanismo inteiro. Não testável com o formato atual de cenário.
- **O gate de confirmação de perfil (uma vez por conversa)** — mesma limitação de `conv_key`.
- **Contradição factual em prosa** (ex.: chamar um destino caro de "econômico") — as checagens de grounding são baseadas em regex de frases específicas de fabricação, não checagem semântica de fatos.
- **Custo/tokens reais** — estimado por tamanho de caractere, já que nenhuma chamada de IA usada expõe contagem real de tokens hoje.
- **Dependência de clima ao vivo** — cenários determinísticos com limite de temperatura usam o provedor de clima real (com cache, mas não congelado); sujeito a variação se os dados do Open-Meteo mudarem entre execuções.

---

Nada de produção foi alterado com base nesses achados — só o framework de avaliação em si, conforme pedido explicitamente.
