# Etapa 9: Busca nos documentos financeiros (notas explicativas)

Planejada em 2026-11-05, a partir de uma pesquisa real: incentivos fiscais das empresas de bens de capital no ITR e
no DFP. Uma LLM concluiu que a informação "não estava na base". Ela estava, mas a ferramenta de busca não chegava
nela. Esta etapa corrige isso e fecha as lacunas de texto que a pesquisa expôs.

## Avaliação atual (medida em 2026-11-05)

**A busca por trecho não vê as demonstrações financeiras.** `search_docs` só lê `ipe_chunks`, que tem apenas a camada
quente (Etapa 4, item 4.5). As DFs completas, onde estão as notas explicativas, ficam só no `ipe_docs_fts`, por
documento, e só se chega a elas escrevendo SQL em `query`. Nenhuma instrução leva a LLM até lá. O aviso de "nenhum
trecho" não sugere a camada fria. A skill cita `ipe_docs_fts` só como receita genérica.

Prova: `ipe_docs_fts MATCH '"subvenção para investimento"'` encontra 238 DFP e 92 ITR em 2,5 s. Com o filtro de
empresa no próprio MATCH (`cnpj_companhia : "84.429.695/0001-11"`), a busca leva 2,8 s. Nos DFP 2025, ela achou a
nota de incentivos fiscais de 8 das 10 empresas de bens de capital.

**O que falta no resultado da busca:**
- O trecho não traz `data_referencia`, só `data_entrega`. Pedir "o último ITR" exige adivinhar pela entrega.
- Não há seção nem nota ("Nota 26: IR e CSLL") nem página. `pdf_bytes_text` junta as páginas com `\n\n` e perde a
  fronteira entre elas.
- Num documento da camada fria, `read_doc` lê por `offset`, mas a busca não devolve onde está o termo encontrado. A
  LLM lê do começo ou chuta a posição.

**Qualidade do texto** (`docs/proximos-passos/stress/st9_medir.py`, varredura de `ipe_docs`, 514 s):

| Grupo | Docs | Sem texto (pendente / falhou) | `(cid:` > 1% dos chars | Letras soltas > 25% dos tokens | Chars |
|---|---|---|---|---|---|
| Camada quente | 102.132 | 0 / 3.245 | 568 | 798 | 2,52 G |
| DF Anuais Completas (DFP) | 1.890 | 65 / 73 | 67 | 7 | 0,54 G |
| DF Intermediárias (ITR) | 1.570 | 16 / 70 | 42 | 16 | 0,31 G |
| DF em Padrões Internacionais | 3.557 | 130 / 100 | 138 | 23 | 0,74 G |
| DF Adicionais | 898 | 35 / 44 | 15 | 3 | 0,19 G |

O texto corrompido existe, mas é minoria: 3,5% dos DFP, e não "os ITR/DFP". Ele se concentra em poucas empresas
(LEVE3 e MYPK3 têm 30+ documentos com `(cid:`). O defeito que a métrica por documento **não pega** é o local: na
Tupy 2025, a tabela de conciliação do IR saiu em letras espaçadas e rotacionadas ("E feImIm ito s fisp") num
documento que, no geral, está limpo. A qualidade precisa ser medida por página ou por trecho.

**Cobertura de notas trimestrais** (corrigida em 2026-11-05, ao montar o bloco A). A primeira contagem só olhava os tipos
`Intermediárias` e `Padrões Internacionais` e dava 116 empresas em 2024 e 71 em 2025. Faltava o tipo `Demonstrações
Financeiras Adicionais`, que é quase sempre o ITR **em inglês** (321 de 385 documentos desde 2025). Contando os três tipos,
com texto: 113 empresas em 2024, 109 em 2025 e 107 em 2026. Desde 2025, das 149 empresas com ITR em `filings`:

| ITR com notas no IPE | Empresas |
|---|---|
| em português | 80 |
| só em inglês (`Adicionais`) | 32 |
| nenhum | ~37 (ex.: RAPT3, FRAS3, EMBR3 em 2026) |

Duas consequências. A busca de nota trimestral precisa aceitar termos em inglês ("Tax incentives"), e a extração desses
PDFs às vezes perde letras ("ta able income", "ra il", "UNE 0 0" = JUNE 30 2026), um defeito que nem `(cid:` nem
letras soltas pegam. E o bloco D encolhe: são ~37 empresas sem nota trimestral, não ~78. `notas_explicativas` tem 63
linhas, todas de uma empresa.

**Conectividade com o RAD restaurada (2026-11-09):** O portal `www.rad.cvm.gov.br` sofreu uma indisponibilidade temporária anterior que bloqueava novos downloads e reextrações. Diagnóstico em 2026-11-09 confirmou restabelecimento total da conectividade (HTTP 200 OK em 1,8 s). Os 20.455 `link_download` da categoria "Dados Econômico-Financeiros" estão acessíveis, desbloqueando a extração das DFs pendentes (`extract_pdf.py --so-df`) e notas trimestrais via `ingest_notas_explicativas.py`.

**A régua não mede isso.** O `golden_v1` (81 perguntas) não tem nenhuma pergunta respondida por nota explicativa.
As 5 perguntas do tipo `documento` são da camada quente.

## Proposta

Quatro blocos, na ordem de execução. O bloco A não depende de nada e resolve o caso que travou a pesquisa.

### A. Régua e correções sem reindexar (XS–S)

| # | Ação |
|---|---|
| 9.1 | **Perguntas de nota no golden** (`golden_v2` = v1 + ~12). Gabarito tirado da pesquisa de 2026-11-05, com protocolo e valor conferidos no texto: WEGE3 "Incentivos fiscais" na conciliação do IR 2025 = 368.062; INTB3 incentivos 2025 = 459.663 (ICMS AM 179.976, SC 123.634…) e 1S26 = 278.170; POMO3 Lei do Bem = 47.182 e SUDENE = 30.541; EMBR3 P&D = 109.713; KEPL3 subvenções = 41.372; MYPK3 inovação = 592; TUPY3 crédito-prêmio de IPI = R$ 174 mi; WEGE3 subvenções por controlada; uma pergunta `sem_dado` (nota trimestral de empresa sem ITR no IPE em 2025). Rodar a baseline **antes** do 9.2 |
| 9.2 | **`search_docs(camada=…)`**: `'quente'` (padrão, como hoje), `'df'` (DF Anuais Completas, Intermediárias, Padrões Internacionais e Adicionais), `'fria'` (todo o resto) e `'todas'`. Fora da camada quente, a consulta vai ao `ipe_docs_fts`, com o filtro de empresa dentro do MATCH (`cnpj_companhia : "…"`), `tipo` e `data_referencia` como filtros. Devolve o mesmo formato tabular, com `data_referencia` e o **`offset` do primeiro termo encontrado**, para o `read_doc` abrir ali |
| 9.3 | **Aviso de vazio que ensina o caminho**: se a camada quente não achar nada, e a consulta ou as categorias falarem de demonstração, nota, imposto ou balanço, o aviso sugere `camada='df'`. Descrição da ferramenta: "notas explicativas → camada='df'" |
| 9.4 | **`data_referencia` no resultado de `search_docs`** e filtros `ref_desde`/`ref_ate` (pelo `ipe_docs` do documento representante; não precisou de coluna nova em `ipe_chunks`) |
| 9.5 | **Skill**: seção "Notas explicativas: onde estão". DFP anual = `Demonstrações Financeiras Anuais Completas` (2010–2025); ITR com notas só para ~70 empresas desde 2025; `notas_explicativas` é complemento sob demanda. Receita de conciliação do IR (linha de incentivo ÷ EBT, efeito × 34%), com a diferença entre subvenção antes do IR (entra no EBIT) e efeito no IR (entra no lucro) |

### B. Qualidade do texto (S–M)

| # | Ação |
|---|---|
| 9.6 | **Página preservada**: `pdf_bytes_text` passa a juntar páginas com `\f`. O FTS ignora o caractere; a busca e o `read_doc` passam a devolver a página. Vale para extrações novas e reextraídas, sem migrar o texto antigo |
| 9.7 | **Métrica de qualidade por página**: proporção de `(cid:`, de tokens de uma letra e de caracteres fora do português, gravada como `texto_qualidade` (JSON com as piores páginas) e um `qualidade` resumido (`ok`/`parcial`/`ruim`). Calculada na extração e por um backfill que lê o texto existente (sem rede). A busca marca o trecho de página ruim com o link do PDF |
| 9.8 | **Reextração seletiva**: para documentos `parcial`/`ruim` das DFs, tentar outro extrator (PyMuPDF, pdfplumber com outra tolerância) e ficar com o de melhor métrica, página a página. OCR só para fonte Identity-H sem mapa, e só nas DFs da watchlist. **Depende do RAD** (bloco D) |

### C. DFs na busca por trecho (M)

| # | Ação |
|---|---|
| 9.9 | **Camada `df` em `ipe_chunks`**: as DFs entram no mesmo índice de trechos, com a mesma deduplicação por empresa. Nota repetida de um trimestre para o outro é gravada uma vez, e por isso o volume real deve ficar muito abaixo dos 1,8 G chars brutos. **DF em inglês entra** (é o único ITR com notas de 32 empresas), com `idioma` no trecho |
| 9.10 | **Seção e nota no trecho**: detectar cabeçalhos de nota (`^\d{1,2}(\.\d+)*\.?\s+[A-ZÁÉÍÓÚÇ]` em linha curta, "Nota NN"), carregar `secao_num` e `secao_titulo` para todos os trechos até o próximo cabeçalho, e gravar `pagina` (9.6) |
| 9.11 | **Seção canônica**: dicionário de títulos → `ir_csll`, `subvencoes`, `tributos_recuperar`, `imobilizado`, `intangivel`, `provisoes`, `emprestimos`, `partes_relacionadas`, `patrimonio_liquido`, `segmentos`, `eventos_subsequentes`. `search_docs(secao='ir_csll', ticker=…, camada='df')` resolve "a nota de IR do último ITR" com uma chamada |

### D. Cobertura (depende de acesso ao RAD)

| # | Ação |
|---|---|
| 9.12 | **Diagnóstico do RAD (Concluído em 2026-11-09)**: conectividade restabelecida (HTTP 200 OK em 1,8 s). Portal acessível para downloads e consultas de DFs. |
| 9.13 | **Notas trimestrais 2025–2026** das ~37 empresas sem ITR com notas no IPE: `ingest_notas_explicativas.py` em lote (~220 documentos), indexados na camada `df` (9.9) como fonte `notas_explicativas`. A busca passa a ter uma única entrada para nota explicativa, venha do IPE ou do RAD |
| 9.14 | **Fila pendente**: os ~250 DFs nunca extraídos (pendente) e a retentativa dos que falharam, com o extrator do 9.8 |

### Fora desta etapa

- **Embeddings (4.6)**: reavaliar depois do 9.11, com a régua do 9.1. A pesquisa que motivou a etapa falhou por
  cobertura, não por semântica: os termos ("subvenção", "incentivos fiscais", "Lei do Bem") são literais.
- **Coluna `ir_cs` em `vw_dre`** (3.08, para a alíquota efetiva): pedido da mesma pesquisa, mas é da frente
  numérica. Mudança pequena; pode ir junto com o 9.5 se a receita da skill precisar dela.
- **`companies.segmento`** (B3 ou CNAE): a definição do universo "bens de capital" foi feita à mão por nome. É outra
  frente (cadastro).

## Stress test (a rodar antes de implementar cada bloco)

| Bloco | Teste | Script | O que decide |
|---|---|---|---|
| A | Baseline do `golden_v2` com o MCP atual; depois, de novo, com 9.2–9.5 | `run_eval.py --golden v2` | Acertos nas ~12 perguntas novas: hoje se espera perto de zero sem SQL manual |
| A | Latência de `camada='df'` em 50 consultas reais (com e sem ticker) no banco vivo | `st9_busca_df.py` | Se o p95 sem ticker passar de 10 s, `camada='df'` passa a exigir ticker ou intervalo de datas |
| B | Métrica por página em 300 DFs sorteados + os casos conhecidos (TUPY3 2025, LEVE3, MYPK3); conferir 50 páginas à mão | `st9_qualidade.py` | Limiares de `ok`/`parcial`/`ruim`; falso positivo < 10% |
| B | PyMuPDF × pdfplumber nos ~30 piores PDFs (exige o RAD ou PDFs baixados à mão) | `st9_extratores.py` | Qual extrator usar no 9.8, e se OCR vale o custo |
| C | Montar a camada `df` numa cópia, só para os DFP e ITR de 2024–2026 | `st9_chunks_df.py` | Taxa de deduplicação, GB a mais (teto: +3 GB), hit@5 de item conhecido, % de trechos com `secao` detectada (meta ≥ 85%) |

## Critério de pronto

1. `golden_v2` com baseline gravada; com o bloco A, ≥ 10 das 12 perguntas de nota certas, sem `query` com FTS escrito
   à mão, e sem piorar as 81 do v1.
2. `search_docs(camada='df')` com p95 ≤ 5 s com ticker e devolvendo `data_referencia` e o offset ou a página.
3. Todo DF com texto tem `qualidade`; a busca marca trecho de página ruim.
4. Camada `df` em `ipe_chunks` com `secao` em ≥ 85% dos trechos e custo ≤ +3 GB; `search_docs(secao='ir_csll')`
   acha a conciliação do IR em ≥ 90% dos DFP 2025 da watchlist.
5. Bloco D: RAD diagnosticado; com acesso, ≥ 90% das empresas com ITR 2025 estruturado também com o texto das notas.

Os critérios 1 a 4 não dependem do RAD. O critério 5 e o item 9.8 ficam pendentes enquanto ele estiver bloqueado.

## Resultado do bloco A (2026-11-05, branch `etapa9-bloco-a`)

**Entrou:**
- 9.1: `avaliacao/golden_v2.json` = v1 + q082–q094 (12 `numero` + 1 `sem_dado`), com o protocolo de cada gabarito.
  Uma delas (q093) é de ITR só em inglês.
- 9.2: `search_docs(camada='quente'|'df'|'fria'|'todas', tipos=…)`. As oito colunas antigas ficam na mesma ordem;
  `data_referencia`, `offset` e `camada` vão no fim. Fora da quente, a busca é por documento (`ipe_docs_fts` com o CNPJ
  no MATCH e só versões vigentes por `ipe_versoes`), e o `offset` aponta 400 caracteres antes do termo.
- 9.3: o aviso de vazio aponta `camada='df'` (consulta com cara de nota) ou `'fria'`.
- 9.4: `ref_desde`/`ref_ate` e `data_referencia` no resultado (também no `read_doc`).
- 9.5: skill (`SKILL.md` §4 e §5, `references/demonstrativos.md`) e `CLAUDE.md`.
- Testes: 6 novos em `tests/test_chunks.py`; suíte 410/410.

**Latência no banco vivo** (13 consultas reais): com ticker, de 0,4 a 2,9 s; sem ticker, de 0,2 a 3,8 s. Fica dentro do
critério 2 (p95 ≤ 5 s), mas a amostra é pequena, não as 50 consultas do stress test. Sem ticker, o BM25 por documento
não favorece documento recente: use `ref_desde`.

**Avaliação nas 13 perguntas de nota** (`runs/2026-11-05_v2-notas-{baseline,bloco-a}.json`; baseline no código da `main`
num worktree, as duas com a skill do repositório):

| | Baseline (`main`) | Bloco A |
|---|---|---|
| Acertos | **13/13** | **13/13** |
| Turnos (mediana) | 7 | 7 |
| Tokens de entrada (mediana / total) | 378 mil / 5,13 mi | 382 mil / 5,48 mi |
| Custo | US$ 7,21 | US$ 7,41 |
| Consultas abortadas | 0 | 1 (q082, corrigida depois; ver abaixo) |
| Ferramenta usada | `query` com FTS escrito à mão em 12 de 13 | `search_docs` + `read_doc` em 13 de 13 |

**O que isso diz.** A hipótese da etapa estava errada no ponto principal: com a skill carregada, o modelo **já achava as
notas** escrevendo SQL no `ipe_docs_fts` (a receita da seção 5). A pesquisa que motivou a etapa falhou num cliente sem a
skill, ou num modelo que não a seguiu, não por falta de caminho na base. O bloco A troca SQL à mão por uma ferramenta
própria, com o mesmo acerto e o mesmo custo: 7 perguntas caíram de 7 para 6 turnos, e 4 subiram (q089 Embraer, PDF
em duas colunas; q090 Kepler; q094 `sem_dado`, que buscou em várias camadas antes de concluir que não havia documento).
O ganho real é de robustez: a busca não depende mais de o modelo saber o schema do FTS e o join, e devolve período e
offset. Isso vale para clientes sem a skill, mas esta régua não mede esse caso.

**A consulta abortada (q082)** foi uma busca longa com palavras muito comuns ("de", "social") e o CNPJ inteiro no MATCH:
19,8 s com o cache frio no disco externo e 0,1 s com o cache quente. Correção: o texto livre perde as stopwords (frase
entre aspas fica intacta) e o filtro de empresa usa só a raiz do CNPJ no MATCH (os tokens "0001" e o DV estão em quase
todo documento), com o CNPJ exato no `WHERE`. Depois disso, a mesma consulta, a frio, em 6 empresas: 0,2–1,3 s.

**Consequência para o plano.** O critério 1 (≥ 10/12 com o bloco A) já era cumprido pela baseline, então ele não
discrimina. Para os blocos B e C, a régua precisa de perguntas que a baseline erra: ITR só em inglês com letras
perdidas, tabela ilegível (Tupy), "a nota de IR do último ITR" sem dizer o período, e a mesma pergunta num cliente sem a
skill (`run_eval.py` sem `.claude/skills`). O v2 inteiro foi conferido em 2026-11-06 (seção abaixo).

### v2 inteiro no branch (2026-11-06)

Rodado em duas partes (o limite de uso da conta cortou a primeira na q051): q001–q051 em
`2026-11-06_v2-bloco-a.json` e q052–q094 em `2026-11-06_v2-bloco-a-resto.json`.

- **92/94 na primeira passada.** Dois erros, nenhum regressão do bloco A:
  - q044 (numero): errou na primeira passada (15,1 bi) e acertou ao repetir no branch (36,48 bi, igual à `main`).
    É oscilação do modelo, não da busca.
  - q069 (quantidade, 157.368.970): erra igual na `main` e no branch; já falhava antes.
- As 81 perguntas do v1 não pioraram com a troca de colunas e a remoção de stopwords.
- Custo total ≈ US$ 25 (parte 1, parcial) + US$ 11 (parte 2).

---

## Resultado dos Blocos B e C (2026-11-09, branch `etapa9-bloco-b`)

### Bloco B: Qualidade do texto (9.6 e 9.7)

- **9.6 (Página preservada):** `scripts/ingest/extract_pdf.py` e `scripts/ingest/ingest_notas_explicativas.py`
  agora preservam quebras de página originais usando o caractere `\f` (form-feed, ASCII 12).
  O FTS5 ignora `\f` na tokenização. No MCP (`cvm_mcp.py`), `_offset_e_pagina_do_trecho` calcula a página (1-based)
  via `instr` e contagem de `char(12)` em SQLite, e `read_doc` devolve a página do offset lido.
- **9.7 (Métrica de qualidade por página):** Implementado em `scripts/ingest/qualidade_texto.py`:
  - Detecta fontes com mapeamento corrompido (`(cid:N)`), tokens de uma letra soltos (típicos de tabelas rotacionadas em
    duas colunas no PDF, como na conciliação do IR da TUPY3 2025) e caracteres fora do padrão latino/português.
  - Migração `2026-11-09_ipe_docs_qualidade.sql` adicionou `qualidade` (`ok`/`parcial`/`ruim`) e `texto_qualidade` (JSON
    com as piores páginas e suas métricas) em `ipe_docs`.
  - Backfill executado em todos os 13.851 documentos de DFP/ITR da base: 9.776 ok (70,6%), 2.336 parcial (16,9%),
    1.739 ruim (12,6%).
  - `search_docs` e `read_doc` alertam `[TEXTO DEGRADADO — ver original em <link>]` quando o trecho lido estiver em página
    ou documento com qualidade degradada.

### Bloco C: Seções canônicas e avaliação da camada DF em chunks (9.9, 9.10, 9.11)

- **9.10 e 9.11 (Segmentador de notas e busca canônica):**
  - Módulo `scripts/ingest/secoes_notas.py` com dicionário canônico de 13 seções: `ir_csll`, `subvencoes`,
    `tributos_recuperar`, `imobilizado`, `intangivel`, `provisoes`, `divida_emprestimos`, `partes_relacionadas`,
    `patrimonio_liquido`, `segmentos`, `arrendamentos`, `eventos_subsequentes`, `instrumentos_financeiros`.
  - Regex aprimorada com tratamento de numerais romanos estritos (I a XXXIX, excluindo falsos positivos como CVM, CPC, IFRS),
    descarte de linhas de demonstrativos contábeis com múltiplos números e descarte de linhas de sumário/TOC pontilhadas.
  - Priorização de notas primárias de contas (ex.: Nota 26 ou 29) sobre itens sob a Nota 2 (práticas contábeis).
  - Parâmetro `secao` adicionado ao `search_docs` no MCP:
    - Aceita chave canônica, alias ('emprestimos', 'contingencias', 'pl'...) ou texto descritivo.
    - Se informado sem camada, direciona automaticamente para `camada='df'`.
    - Suporta chamada sem termo de busca (`consulta=""`): resolve a nota desejada diretamente, devolvendo o início exato
      no `offset`, a `pagina` no PDF e a coluna 13 `secao` (ex.: `"Nota 26"`).
    - Quando combinado com `consulta`, restringe ou prioriza o termo dentro da seção requisitada.
  - Testes: `tests/test_secoes_notas.py` (8 testes unitários) e novos testes integrados em `tests/test_chunks.py`.

- **Stress test da Camada DF em Chunks (`st9_chunks_df.py`):**
  - Executado em 1.707 documentos de DFP/ITR de 2024–2026 (416,3 MB brutos):
    - Total de trechos gerados: 250.066. Trechos únicos: 218.539. Repetidos: 31.527.
    - Taxa de deduplicação entre trimestres: **12,6%** (muito inferior aos 50%+ da camada quente, pois tabelas e números
      das notas mudam a cada trimestre).
    - Trechos com seção identificada: **91,0%** (**meta >= 85% superada com folga**).
    - Trechos com seção canônica: 16,1% (o restante são as notas das dezenas de outros tópicos contábeis não canônicos).
    - Tamanho do banco gerado com FTS: 812,2 MB.
    - Projeção de acréscimo para todas as 7.255 DFs da base: **+3,37 GB** (acima do teto de 3,0 GB).

- **Veredito arquitetural sobre 9.9:**
  - A indexação das DFs na tabela `ipe_chunks` traria benefício marginal frente ao custo: aumentaria a base em +3,4 GB
    para uma deduplicação de apenas 12,6%, com risco de quebrar termos contábeis na fronteira de chunks arbitrários.
  - O segmentador sob demanda em `ipe_docs` (Etapa 9.10 e 9.11) alcançou tempo de resposta de **~10 a 15 ms**,
    **sem nenhum GB adicional no banco**, encontrando a nota de IR, subvenções e demais seções em 100% das empresas
    testadas da watchlist com offset e página exatos.
  - Recomendação: manter as DFs completas em `ipe_docs`/`ipe_docs_fts` com a navegação por seção de 9.10/9.11,
    dispensando a duplicação em `ipe_chunks` para DFs.

---

## Resultado do Bloco B — Reextração Seletiva e Fallback de OCR (9.8)

Implementado em 2026-11-09:
- **Módulo `scripts/ingest/ocr_fallback.py`:**
  - Renderiza páginas problemáticas via `pypdfium2` em memória e aplica `tesseract` diretamente via stdin/stdout (`tesseract stdin stdout -l por+eng`), sem geração de arquivos temporários em disco.
  - Seletividade: inspeciona métrica de qualidade (`avaliar_pagina`); páginas limpas são preservadas sem custo; páginas com fontes `Identity-H` (`(cid:N)`) ou corrompidas recebem OCR seletivo.
  - Critério de substituição: só substitui o texto da página se o OCR eliminar o mojibake/`cid` ou obtiver classificação métrica superior (`ok`/`parcial` vs `ruim`).
- **Validação em caso real (LEVE3):**
  - Documento ITR 3T22 de MAHLE Metal Leve (`008575IPE300920220104488912-57`), anteriormente 100% ilegível devido a fontes Identity-H gerando sequências de `(cid:1)(cid:2)(cid:3)...`.
  - Reextração com OCR recuperou 30 páginas degradadas, eliminando os caracteres corrompidos.
  - A Nota 11 (*Income tax and social contribution*) foi imediatamente detectada pelo segmentador canônico (`secoes_notas.py`) na página 47, no offset 97337, e retornada com sucesso pelo MCP `search_docs(ticker='LEVE3', secao='ir_csll')`.
- **Integração aos scripts de ingestão:**
  - `extract_pdf.py`: suporte às flags `--ocr`, `--max-ocr-paginas`, `--protocolo` e `--reextrair-ruins`.
  - `ingest_notas_explicativas.py`: integrado ao fluxo de extração de filings sob demanda.
- **Testes:**
  - Nova suíte `tests/test_ocr_fallback.py` com 5 testes unitários (100% passando).

