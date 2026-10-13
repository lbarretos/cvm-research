# CVM Research — Base Local

Base de dados local de documentos e eventos de empresas abertas brasileiras (CVM/B3).
Banco: SQLite local (`cvm_research.db`) · fontes IPE (2015+) + VLMO (2018+) + Recompra + FRE (2010+) + DFP (2010+) / ITR (2011+) + Notas Explicativas (sob demanda).
Cobertura e período são escolhidos na carga (ver a seção seguinte); nesta instalação, confira com
`SELECT COUNT(*) FROM companies` e `SELECT MIN(data_referencia) FROM ipe_docs`.
Montar do zero: `bash bootstrap.sh --universo ibov`. Manter: `bash scripts/update_weekly.sh` (manual)
ou job launchd toda segunda 9h, com recuperação no login e a cada 4 h se a segunda foi perdida
(`scripts/install_weekly_launchd.sh`).

**Roadmap de desenvolvimento:** `docs/proximos-passos/README.md`. São sete etapas numeradas na ordem de
execução (desempenho → avaliação → MCP → texto/RAG → template CVM → linha econômica → taxonomia), cada uma
com avaliação, proposta, stress test e critério de pronto. Ao trabalhar numa etapa, leia o arquivo dela e
atualize o veredito no README ao terminar.

## Montar a base do zero (quando o banco está vazio ou é um clone novo)

Quando o usuário pedir para **montar, construir, replicar ou recriar a base**, ou quando uma
consulta falhar porque as tabelas estão vazias, o caminho é o `bootstrap.sh` na raiz do projeto.
Não monte a sequência de ingestores à mão: o script já cuida da ordem, das camadas de
tratamento e do laço de extração de PDF, e é retomável.

Antes de rodar, resolva duas escolhas com o usuário. São as únicas que mudam o resultado.

**1. Universo de cobertura.** O padrão recomendado para quem está começando é o IBOV, com cerca
de 78 empresas. As opções são `ibov`, `ibrx`, `todas` (as ~443 ativas da B3) ou um arquivo com a
lista de tickers que o usuário quiser. Se ele **anexar ou colar uma tabela** com as empresas
desejadas, salve-a como CSV na raiz do projeto e passe o caminho em `--universo`. O arquivo pode
ser um CSV com coluna `ticker` (as outras colunas são ignoradas) ou um ticker por linha; `#`
começa comentário. Ticker fora do catálogo da B3 é avisado e pulado, sem interromper.

```
ticker,empresa
PETR4,Petrobras
VALE3,Vale
WEGE3,WEG
```

O universo é **aditivo**: soma ao `watchlist.csv` e nunca remove. Para começar limpo, só com o
universo escolhido, acrescente `--substituir`, que faz backup do `watchlist.csv` antes.

**2. Período.** `--desde ANO` vale para todas as fontes. Cada uma tem um primeiro ano possível
(IPE 2015, VLMO 2018, ITR 2011, DFP e FRE 2010); pedir antes disso é ajustado para cima com
aviso, não falha. Sem `--desde`, cada fonte vai até o início. Menos anos significa menos tempo e
menos disco, então pergunte se o usuário não disser.

```bash
bash bootstrap.sh --universo ibov --substituir            # IBOV, série completa
bash bootstrap.sh --universo ibov --desde 2020            # IBOV, de 2020 para cá
bash bootstrap.sh --universo minhas-empresas.csv --desde 2018
bash bootstrap.sh --universo todas --sem-pdf              # cobertura máxima, sem texto de PDF
```

**Sempre rode `--dry-run` primeiro** e mostre o plano ao usuário antes de executar de verdade. A
carga completa leva horas e baixa dezenas de GB; vale confirmar cobertura e período antes.

Três blocos rodam em sequência, e o do meio é o que costuma ser esquecido:

| Bloco | O que faz | Referência (IBOV) |
|---|---|---|
| Dados brutos | os sete ingestores da CVM | 20–40 min |
| **Tratamento** | `run_all.py --layer 1,2,3,5,6 --full` | ~4 min |
| Texto dos PDFs | `extract_pdf.py` em laço, depois reconstrói o FTS | 6–12 h |

Sem o bloco de tratamento, `demonstrativos_trimestrais`, `consistency_flags` e
`cd_conta_ds_timeline` ficam vazias e as consultas trimestrais e de reapresentação deste arquivo
respondem nada, sem erro que explique o porquê. `--sem-pdf` adia a parte longa e `--so-pdf`
retoma depois; a base já é pesquisável nos dados estruturados sem ela, só não tem busca
full-text nem leitura de fatos relevantes.

Ao terminar, confirme com `.venv/bin/python -m pytest tests/ -q`. A suíte inclui testes que
releem o banco e recalculam o tratamento a partir do dado bruto. Depois, a manutenção é
`bash scripts/update_weekly.sh` (ou o job semanal do launchd), que cobre só o ano corrente e o
anterior — para refazer o histórico, `bootstrap.sh` de novo.

⚠️ A CVM não arquiva versões anteriores dos documentos: cada base guarda a versão que estava no
ZIP no dia do download. Duas bases montadas em datas diferentes divergem nos períodos que foram
reapresentados no intervalo. Ao comparar números com outra instalação, cite a data da carga.

---

## Visualizador local

Existe uma tabela navegável das demonstrações em `scripts/viewer/`. Ofereça quando o usuário
quiser **folhear** um demonstrativo inteiro, comparar muitas linhas de uma vez ou conferir um
número na tela; para responder uma pergunta pontual, consultar o banco pelo MCP é mais direto.

```bash
.venv/bin/python scripts/viewer/server.py     # http://127.0.0.1:8765
```

Somente leitura. Três visões: ITR e DFP como reportados, e a série trimestral com 4T (Camada 6).
Cada linha é uma linha econômica, não um `cd_conta`: quando a empresa renumera a conta, a série
segue na mesma linha e a célula mostra o código daquele filing sobrescrito. Aceita `?t=TICKER` na
URL para já abrir numa empresa. A visão trimestral depende da Camada 6 ter rodado.

---

## Acesso ao banco (MCP `cvm-research`)

O Claude consulta o banco pelo MCP `cvm-research` (`scripts/mcp/cvm_mcp.py`, stdio, somente leitura).
Ferramentas: `resolve_company(texto)` (ticker, nome parcial ou CNPJ → até 5 empresas), `query(sql)` (SELECT, até 500 linhas),
`list_tables()` (contagem só nas tabelas; `rows` é null nas views), `describe_table(nome)`. A saída é tabular
(`{colunas, linhas, aviso?}`), cada resposta cabe em 30 mil caracteres (o excesso é cortado com aviso) e todas abortam em 20 s.
Setup e troubleshooting: ver `INSTALL.md`. Verificação rápida: *"Quantas linhas tem a tabela ipe_docs?"* deve responder um número acima de 160.000.

## Como identificar uma empresa

Sempre use CNPJ como chave. `resolve_company` faz isso sem SQL; o equivalente:
```sql
-- Por ticker
SELECT cnpj, nome_cvm FROM companies WHERE ticker = 'WEGE3';

-- Por nome parcial (LIKE no SQLite ignora maiúsculas só em ASCII: acento tem que bater)
SELECT cnpj, ticker, nome_cvm FROM companies WHERE nome_cvm LIKE '%fleury%';
```

## Tabelas e campos principais

### `companies` — watchlist de empresas cobertas
`cnpj (PK), ticker, codigo_cvm, nome_cvm, setor, status_cvm`

### `ipe_docs` — catálogo de documentos corporativos
`protocolo_entrega (PK), cnpj_companhia, data_referencia, data_entrega,`
`categoria, tipo, especie, assunto, link_download,`
`texto_extraido (NULL = não extraído), extracao_falhou, chars_extraidos`

⚠️ Texto com `(cid:N)` que sobrou é de fonte Identity-H (N é índice de glifo, não caractere): ilegível e
invisível ao FTS; mostre o `link_download`. O `(cid:N)` de fonte WinAnsi e o texto lido como StandardEncoding
("Relaçıes", "SuperintendŒncia") são reparados na extração por `utils.repair_pdf_text`
(`repair_text_encoding.py` conserta o que já estava no banco).

**Categorias relevantes:**
- `'Fato Relevante'` — eventos materiais (M&A, guidance, regulatório)
- `'Assembleia'` — `tipo` = `'AGE'`, `'AGO/E'` (assembleia conjunta, a mais comum em abril) ou `'AGO'`; `'AGDEB'` é de
  debenturistas. `especie` diz o documento: `'Proposta da Administração'` (proposto), `'Ata'`/`'Sumário das Decisões'`
  (aprovado), `'Mapa final de votação'`, `'Edital de Convocação'`, `'Boletim de voto a distância'`
- `'Comunicado ao Mercado'` — comunicados gerais
- `'Aviso aos Acionistas'`
- `'Dados Econômico-Financeiros'` — o `tipo` diz o documento:
  - `'Press-release'` — **release de resultados** trimestral (não existe categoria `'Resultado'`)
  - `'Relatório de Análise Gerencial'` — MD&A (poucas empresas)
  - `'Demonstrações Financeiras Intermediárias'` / `'Demonstrações Financeiras Anuais Completas'` — PDF
    do ITR/DFP com notas explicativas; antes de rodar `ingest_notas_explicativas.py`, veja se já está aqui
  - também `'Relatório de Agência de Rating'`, `'Relatório de Agente Fiduciário'`, `'Laudo de Avaliação'`

### `vlmo_movimentacoes` — movimentações de valores mobiliários por insiders
`cnpj_companhia, data_referencia, tipo_cargo, tipo_movimentacao,`
`tipo_ativo, caracteristica (ON/PN), quantidade, preco_unitario, volume`

**tipo_cargo relevantes:** `'Conselho de Administração ou Vinculado'`, `'Diretor ou Vinculado'`, `'Controlador ou Vinculado'`
**tipo_movimentacao de mercado:** compras `'Compra à vista'`, `'Compra à termo'`, `'Compra'`; vendas `'Venda à vista'`,
`'Venda à termo'`, `'Venda'`. **Não são operações:** `'Saldo Inicial'`/`'Saldo Final'` (posição), `'Posse'`/`'Desligamento/saída'`
(o insider entra ou sai do cargo), aluguel (`'Contratação/Devolução de empréstimo'`), planos de remuneração e eventos
societários (`'Desdobramento/bonificação'`, `'Subscrição'`).

`'Saldo Inicial'` tem `data_movimentacao` NULL. Bancos carregados antes de 30/09/2026 guardavam uma cópia desses saldos
por recarga do VLMO (até 6×): somar quantidade de saldo dava múltiplos do real. Corrigir com
`sqlite3 cvm_research.db < scripts/migrations/2026-09-30_vlmo_mov_uniq_nulls.sql`.

### `vlmo_posicao` — posição consolidada de valores mobiliários (por documento)
`protocolo_entrega (PK), cnpj_companhia, data_referencia, categoria, tipo, link_download`

### `recompra_programas` — programas de recompra de ações
`id_programa (PK), cnpj_companhia, finalidade_compra, data_deliberacao,`
`motivo, data_final_prazo, situacao ('Em Andamento'/'Encerrado')`

⚠️ `recompra_quantidades` e `recompra_intermediarios` existem no schema mas estão **vazias** — o ingestor ainda não as popula. Não use.

### `fre_capital_social` — composição do capital social (histórico)
`cnpj_companhia, data_referencia, tipo_capital, data_autorizacao_aprovacao,`
`valor_capital, quantidade_acoes_ordinarias, quantidade_acoes_preferenciais, quantidade_total_acoes`

### `fre_remuneracao_orgao` — remuneração dos administradores por órgão
`cnpj_companhia, data_referencia, orgao_administracao, numero_membros,`
`numero_membros_remunerados, valor_maior_remuneracao, valor_menor_remuneracao, valor_medio_remuneracao`

### `fre_posicao_acionaria` — principais acionistas e cadeia de controle
`cnpj_companhia, data_referencia, versao, id_acionista, id_acionista_relacionado, acionista, cpf_cnpj_acionista, acionista_controlador,`
`percentual_acao_ordinaria_circulacao, percentual_acao_preferencial_circulacao, percentual_total_acoes_circulacao`

⚠️ A tabela mistura dois níveis, como o CSV `posicao_acionaria` do FRE:
- `id_acionista_relacionado IS NULL` — acionista **direto** da companhia listada (inclui as linhas "Outros" e
  "Ações Tesouraria"); o percentual é sobre o capital da companhia.
- `id_acionista_relacionado` preenchido — a linha descreve quem detém o acionista cujo `id_acionista` é esse valor
  (holding da cadeia de controle, em quantos níveis houver); o percentual é sobre o capital **dessa holding**.
  Ex.: na WEG (FRE 2026), "WPA Participações 50,088%" é direto; "ANNE MARIE WERNINGHAUS 33,333%" é a fatia dela na
  Diether Werninghaus Administradora, que está três níveis abaixo da WPA (WPA → G Werninghaus → Diether → Anne Marie).
- A cadeia tem vários níveis e a mesma pessoa aparece em mais de um (Anne Marie também é direta, com 0,000%), sempre
  com `id_acionista` diferente. Não agrupe por nome sem filtrar o nível.

Nunca ordene ou some percentuais sem filtrar o nível. Para "maiores acionistas" use **`vw_acionistas_diretos`**:
só linhas diretas, no FRE mais recente de cada empresa (maior `data_referencia` e, nela, maior `versao`). Para
subir a cadeia, junte `id_acionista_relacionado` com `id_acionista` do mesmo `(cnpj_companhia, data_referencia, versao)`.
Banco anterior à coluna: `sqlite3 cvm_research.db < scripts/migrations/2026-09-29_fre_acionista_relacionado.sql`,
`sqlite3 cvm_research.db < schema.sql` e `python ingest_fre.py --desde 2010` (a migração esvazia a tabela).

### `demonstrativos_contabeis` — DFP (anual) e ITR (trimestral) estruturados
`cnpj_companhia, fonte ('DFP'/'ITR'), tipo_doc ('BPA'/'BPP'/'DRE'/'DFC_MI'/'DVA'),`
`data_referencia, versao, ordem_exercicio ('Último'/'Penúltimo'),`
`dt_ini_exerc, dt_fim_exerc, cd_conta, ds_conta, vl_conta (em R$ — já normalizado MIL×1000),`
`st_conta_fixa ('S' = conta padrão CVM, 'N' = criada pela empresa)`

**Lucro por ação (DRE `3.99` e descendentes, ON/PN)** está em **R$/ação**, sem a escala MIL: a CVM publica o LPA
assim em qualquer escala. Bancos carregados antes de 30/09/2026 tinham o LPA ×1000 (Petrobras DFP 2025 = 8.540 em vez
de 8,54); corrigir com `sqlite3 cvm_research.db < scripts/migrations/2026-09-30_lpa_escala.sql` e rodar o tratamento
(`run_all.py --layer 1,2,3,5,6 --full`). Algumas empresas digitam o LPA errado na própria fonte (VIVA3 ITR 2019–2020
traz o lucro total, centenas de milhões): valor de LPA acima de R$ 1.000 é erro da CVM, não conversão; não corrija.

**Views prontas (preferir sobre query direta):**
- `vw_dre` — DRE resumida: `receita_liquida, custo_bens_servicos, resultado_bruto, ebit, resultado_financeiro, ebt, lucro_liquido, plano_contas`
- `vw_balanco` — BPA + BPP: `ativo_total, ativo_circulante, caixa, divida_curto_prazo, divida_longo_prazo, patrimonio_liquido, plano_contas`
- `vw_dre_financeiro` — DRE de banco: `receita_intermediacao, despesa_intermediacao, resultado_bruto_intermediacao,
  outras_receitas_despesas_operacionais, lair, ir_cs, lucro_liquido, lucro_controladora`
- `vw_dre_seguradora` — DRE de seguradora: `receita_operacoes, despesa_operacoes, resultado_bruto, despesas_administrativas,
  outras_receitas_despesas_operacionais, equivalencia_patrimonial, ebit, resultado_financeiro, ebt, ir_cs, lucro_liquido, lucro_controladora`
- `vw_plano_contas` — plano de cada filing: `cnpj_companhia, fonte, data_referencia, plano_contas ('padrao'/'banco'/'seguradora')`

**Períodos no ITR:** no 2T e 3T a DRE tem duas linhas por conta — trimestre isolado
(`dt_ini_exerc` = início do trimestre) e acumulado no ano (`dt_ini_exerc` = início do
exercício). `vw_dre` devolve o trimestre isolado; `vw_dre_acumulada` devolve o acumulado.
DFC_MI e DVA só têm acumulado no ITR. BPA/BPP têm `dt_ini_exerc` NULL (posição na data).
Ao consultar `demonstrativos_contabeis` direto para DRE de ITR, filtre `dt_ini_exerc`,
senão as linhas dobram.

⚠️ **Plano de contas.** Bancos e seguradoras publicam a DRE e o balanço em outro plano, com os mesmos códigos
significando outra coisa (no banco, 3.05 é o LAIR e o lucro é 3.09 ou 3.11). `vw_plano_contas` classifica cada filing
pelo nome da conta fixa 3.01 — **não** por `companies.setor`: B3SA3, ITSA4, CXSE3 e PSSA3 são `'Financeiro'` e usam o
plano padrão. Nesta base: `banco` = ITUB4, BBAS3, BBDC4, BPAC11; `seguradora` = IRBR3, BBSE3.
- `vw_dre` / `vw_dre_acumulada`: fora do plano padrão todas as colunas de valor vêm NULL (a linha do filing fica, com
  `plano_contas` dizendo o porquê). Use `vw_dre_financeiro` ou `vw_dre_seguradora` (mesmo período de `vw_dre`: trimestre
  isolado no ITR; não há versão acumulada).
- `vw_dre_financeiro`: dois layouts de banco. 9 linhas (ITUB4, BPAC11; BBAS3/BBDC4 até 2019) com lucro em 3.09; 11 linhas
  (BBAS3/BBDC4 desde 2020), em que 3.09 é o lucro antes das participações nos lucros (3.10) e o lucro é 3.11. A view
  escolhe pela presença de 3.11.
- `vw_dre_seguradora`: 13 linhas; `ebit` = 3.07, `ebt` = 3.09, `lucro_liquido` = 3.13. BBSE3 é holding: receita e custo
  vêm 0 e o resultado está em equivalência patrimonial. IRBR3 publica `3.13.01` = 0 desde 2023 (não abre controladora e
  não controladores), então `lucro_controladora` = 0 ali; use `lucro_liquido`.
- `vw_balanco`: `ativo_total` vale em todos os planos. Banco: o resto vem NULL (1.01 é "Caixa e Equivalentes", o passivo
  é aberto por instrumento e o PL é 2.07 ou 2.08 conforme o ano — consulte `demonstrativos_contabeis`). Seguradora:
  circulante, caixa e PL valem; `divida_*` vem NULL (2.01.04/2.02.01 são provisões técnicas e exigível a longo prazo).

Diagnóstico: `SELECT DISTINCT c.ticker, p.plano_contas FROM vw_plano_contas p JOIN companies c ON c.cnpj = p.cnpj_companhia WHERE p.plano_contas <> 'padrao'`.
Banco anterior a estas views: `sqlite3 cvm_research.db < scripts/migrations/2026-09-30_vw_plano_contas.sql` (só views).

**`filings`** — versão vigente e plano de contas de cada documento: `(cnpj_companhia, fonte, tipo_doc, data_referencia) → versao,
plano_contas, dt_ini_min, dt_ini_max, n_linhas`. As views de DRE e balanço leem dela (por isso respondem em milissegundos, não
em 25 s). É reconstruída no fim de `ingest_dfp`/`ingest_itr` e no início de `run_all.py` (`python scripts/ingest/filings.py`
faz à mão): **depois de gravar em `demonstrativos_contabeis` por fora dos ingestores, reconstrua-a**, senão as views mostram
a versão antiga. Banco anterior à tabela: `sqlite3 cvm_research.db < scripts/migrations/2026-10-05_filings_views.sql`
(cria e preenche `filings` e troca as views, ~10 s) e, para as consultas do IPE por `data_entrega`,
`sqlite3 cvm_research.db < scripts/migrations/2026-10-05_ipe_indices.sql`. Compactação e `page_size`:
`bash scripts/compactar_banco.sh` (só mostra o plano sem `--executar`).

### `notas_explicativas` — texto completo do ITR/DFP (com notas explicativas)
`cnpj_companhia, fonte ('ITR'/'DFP'), data_referencia, versao,`
`numero_sequencial_documento, link_download, texto_extraido (NULL = não extraído),`
`extracao_falhou, chars_extraidos`

Diferença para `demonstrativos_contabeis`: aquela tabela só tem os quadros
padronizados (BPA/BPP/DRE/DFC_MI/DVA); esta tem o **PDF completo do documento**,
incluindo notas explicativas (movimentação de Imobilizado/Intangível/Direito de
Uso, provisões, etc.) — dado que não existe em nenhum feed estruturado da CVM.
Populada sob demanda via `ingest_notas_explicativas.py` (não faz parte do fluxo
semanal automático — ver script para detalhes). **Cobertura é mínima**: antes de
consultar, verifique com `SELECT cnpj_companhia, fonte, data_referencia FROM notas_explicativas`
se a empresa/período já foi ingerido; se não, informe o comando para ingerir. Busca full-text via
`notas_explicativas_fts` (mesmo padrão de `ipe_docs_fts`).

⚠️ Diferente dos demais ingestores (que baixam ZIPs anuais de `dados.cvm.gov.br`),
este busca cada documento individualmente em `rad.cvm.gov.br` (o portal de
consulta de documentos da CVM, não o feed de dados abertos) — mais lento e mais
sensível a rate limit, por isso o `time.sleep(0.5)` entre documentos e o
`--limite` default de 20. Além disso, ao contrário de `demonstrativos_contabeis`
(que guarda as versões presentes no ZIP da CVM no dia da carga — em geral só a mais recente), aqui só a versão mais recente é mantida — uma
reapresentação (nova `versao`) descarta o `texto_extraido` da versão anterior.

### `consistency_flags` — achados de consistência dos demonstrativos (metadados, não valores)
`run_id, layer, check_type, classificacao, severity ('info'/'warn'/'error'), cnpj_companhia, tipo_doc,`
`cd_conta (NULL = resumo do par de documentos), cd_conta_pai, ds_conta, periodo_ini ('NA' em BPA/BPP), periodo_fim,`
`fonte_ref, data_ref, ordem_ref (filing baseline), fonte_cmp, data_cmp, ordem_cmp (filing comparado),`
`valor_ref, valor_cmp, diff_abs (cmp − ref), diff_rel, detalhe (JSON)`

Gerada por `scripts/analysis/`. As Camadas 1, 2 e 3 rodam no job semanal (`update_weekly.sh`) logo após
`ingest_dfp`/`ingest_itr`, na base inteira; também podem ser rodadas à mão por empresa.
Nunca altera `demonstrativos_contabeis`: o valor publicado pela CVM fica intacto e aqui ficam os metadados.
A tabela guarda **a última execução de cada escopo** `(layer, check_type, cnpj[, tipo_doc])`; o histórico
de execuções está em `consistency_runs` (`run_id, layer, check_type, escopo, started_at, finished_at,
total_checked, total_flagged, script_args`).

**Camada 1 (`layer = 1`, `check_type = 'hierarchy_sum'`)** — dentro de cada (documento, `ordem_exercicio`,
período), cada conta-pai presente é comparada à soma dos filhos diretos (tolerância `max(R$ 1.000, 1% × |pai|)`).
É o teste de regressão da ingestão: a flag guarda o documento em `fonte_ref/data_ref/ordem_ref` (`*_cmp` NULL),
`valor_ref` = pai, `valor_cmp` = soma dos filhos, `diff_abs = valor_cmp − valor_ref`.
- `nao_detalhado` (`info`): pai preenchido, todos os filhos 0/NULL — a empresa não abriu a conta; o pai é confiável.
- `pai_vazio` (`warn`): pai 0/NULL com filho preenchido — sintoma de ingestão parcial.
- `divergencia` (`error`): pai e filhos preenchidos e a soma não fecha.
- `divergencia_formula` (`error`): fórmula fixa de nível 2 não fecha (DRE `3.03 = 3.01 + 3.02` … `3.11 = 3.09 + 3.10`;
  DFC `6.05 = 6.01 + … + 6.04`); não é checada no setor `Financeiro` (COSIF). `detalhe = {"regra": "formula", "formula", "termos"}`.
- Exceções: DFC `6.05 = 6.05.02 − 6.05.01` (`detalhe.regra = 'saldo'`); DRE `3.99` (lucro por ação) ignorada.

Para rodar: `cd scripts/analysis && python run_all.py --layer 1 --cnpj <CNPJ>` (`--layer 1,2` roda as duas).

**Camada 2 (`layer = 2`, `check_type = 'cross_period'`)** — o mesmo período aparece em até 5 filings
(BPA 31/12/Y: DFP(Y) Último, ITR 1T/2T/3T(Y+1) Penúltimo, DFP(Y+1) Penúltimo). O baseline é sempre o
filing mais antigo (o original, como reportado na época) e cada filing posterior é comparado a ele:
- `reapresentacao` (`warn`): a conta-total do tipo_doc (`1`, `2`, `3.01`/`3.11`, `6.05`, "Valor Adicionado
  Total a Distribuir") diverge acima da tolerância `max(R$ 1.000, 1% × |ref|)`; todas as linhas
  divergentes do par herdam a classe.
- `reclassificacao` (`info`): totais batem, mas alguma sublinha diverge (mudou de conta).
- Linha que existe só num dos filings **não** gera flag aqui (é a Camada 3); só entra nas contagens do
  resumo do par (`detalhe = {"linhas_comuns", "linhas_divergentes", "linhas_exclusivas_ref",
  "linhas_exclusivas_cmp", "total_disponivel"}`).

**Camada 3 (`layer = 3`, `check_type = 'granularity'`)** — nos mesmos pares da Camada 2, explica as linhas que existem
só num dos filings (`valor_ref` **ou** `valor_cmp` preenchido; `detalhe.exclusivo_em`), pai a pai, nesta ordem:
- `renumerado` (`info`): mesmo nome normalizado e mesmo `st_conta_fixa` em código diferente (`detalhe.casamento = 'nome'`,
  `cd_ref`/`cd_cmp`; uma flag por par casado, `cd_conta = cd_ref`), ou exclusivas dos dois lados com a mesma soma (`'valor'`).
- `zero_padding` (`info`): |valor| < R$ 1.000 — conta padrão publicada vazia.
- `reclassificado_em_outros` (`warn`): a soma das exclusivas fecha com o delta das linhas "Outros"/"Demais" do pai.
- `reclassificado_em_irmao` (`warn`): o pai não mudou; o valor foi absorvido por um irmão nomeado (`detalhe.irmaos_alterados`).
- `divergencia_nao_explicada` (`error`): o valor saiu do pai (`detalhe.pai_ref`/`pai_cmp`) — mudou de pai ou é parte de
  uma reapresentação (conferir a Camada 2 do mesmo par).
Exclusivas cujo pai também é exclusivo não geram flag (só `detalhe.filhos_de_pai_exclusivo` no resumo do par).

Para rodar: `cd scripts/analysis && python run_all.py --layer 2,3 --cnpj <CNPJ>` (ou `--full` para a base).

### `cd_conta_ds_timeline` — trilha temporal de cada linha (pai + nome) entre filings (Camada 5)
`run_id, cnpj_companhia, tipo_doc, fonte, data_referencia (filing atual), cd_conta, ds_conta, st_conta_fixa, cd_conta_pai,`
`ds_conta_norm, data_referencia_anterior, cd_conta_anterior, ds_conta_anterior, similarity_score, classificacao`

Filings consecutivos da mesma fonte (`ordem_exercicio = 'Último'`), comparados de cima para baixo na hierarquia
(pai renumerado leva os filhos junto). Uma linha por mudança; `estavel` **não é gravada**:
- `primeira_ocorrencia`: todas as linhas do primeiro filing da sequência.
- `renumerado` (`similarity_score = 1`): mesmo nome normalizado em código diferente — `cd_conta_anterior` diz de onde veio.
- `reformulacao` (score ≥ 0,75) e `ambiguo` (0,55 < score < 0,75; também vira flag `layer = 5` em `consistency_flags`,
  fila de revisão): nome parecido (difflib com token-sort sobre texto normalizado), só em linhas `st_conta_fixa = 'N'`.
  Par com **sentido contábil oposto** é sempre `ambiguo`, por mais alto que seja o score: só o verbo muda em
  "Captação"/"Pagamento de debêntures" (0,756) e "Aumento"/"Redução de capital social" (0,800), e são linhas contrárias.
- `nova` / `removida`: sem par. `removida` fica no filing em que sumiu, com `cd_conta`/`ds_conta` da linha antiga
  (o código pode ter sido reutilizado por outra linha no mesmo filing — renumeração em cascata).
Contas `S` (padrão CVM) com o mesmo código são estáveis mesmo que o nome mude — o que **não** vale entre versões do plano
de contas (a CVM re-letrou o plano dos bancos em 2017). Por isso a Camada 6 casa com `codigo_fixo_confiavel=False` e não
reaproveita esta trilha. Para rodar: `run_all.py --layer 5 --cnpj <CNPJ>`.

### `demonstrativos_trimestrais` — valor de cada trimestre da DRE/DFC_MI/DVA, por conta e por safra (Camada 6)
`run_id, cnpj_companhia, tipo_doc ('DRE'/'DFC_MI'/'DVA'), safra ('original'/'reapresentado'), exercicio_ini, dt_ini_exerc, dt_fim_exerc,`
`trimestre (1–4, posição no exercício social), cd_conta, ds_conta, cd_conta_b, casamento, vl_publicado, vl_derivado,`
`origem ('publicado'/'derivado'), vl_final, flag,`
`fonte_a, data_a, ordem_a (filing do acumulado do trimestre), fonte_b, data_b, ordem_b (filing do acumulado anterior; NULL no 1T)`

**Use `vl_final`** (e `origem` para saber de onde veio). `safra = 'original'` usa só colunas `Último` (o que o mercado viu na época);
`'reapresentado'` usa só colunas `Penúltimo` dos filings do exercício seguinte. **Nunca subtrai safras diferentes.**
- DRE 1T–3T: `vl_publicado` é a linha trimestral isolada do ITR (`origem = 'publicado'`); `vl_derivado = acum(Qn) − acum(Qn−1)` serve de conferência.
- DRE 4T, DFC_MI e DVA (todos os trimestres): só derivado (`4T = DFP − acum(3T)`).
- **`cd_conta_b` e `casamento`**: qual linha do filing anterior foi subtraída e como ela foi encontrada. O mesmo `cd_conta`
  costuma ser **outra linha** no filing anterior — a empresa renumera as contas que cria (`st_conta_fixa = 'N'`) entre
  trimestres e o DFP usa um layout diferente do ITR. O casamento usa a escada da Camada 5: `estavel` (mesmo código e mesmo
  nome), `renumerado` (mesmo nome normalizado, código diferente), `reformulacao` (similaridade ≥ 0,75 **e** sem inversão
  de sentido contábil — "Captação" e "Pagamento de debêntures" têm score 0,756 e nunca casam). Para auditar um número,
  compare `cd_conta` no filing A com `cd_conta_b` no filing B, no dado bruto.
- `flag`: `reapresentacao_intra_ano` (publicado ≠ derivado, ou 6.05 do 4T da DFC ≠ variação do saldo final de caixa; também em `consistency_flags` `layer = 6`),
  `par_ambiguo` (o único candidato a par tem similaridade entre 0,55 e 0,75 — o valor **não** é calculado de propósito, e a
  flag de linha em `consistency_flags` traz `cd_conta_b`, `ds_conta_b` e `score` para revisão),
  `linha_sem_par` (a linha não tem correspondente no acumulado anterior — `vl_derivado` NULL), `sem_anterior`/`sem_3t` (buraco na série — NULL),
  `reclassificacao_entre_filings` (ver abaixo), `componente_reapresentado` (um dos dois filings tem `reapresentacao` na Camada 2).
  `sem_dfp` só em `consistency_flags` (não há linha de 4T).
- `reclassificacao_entre_filings` (`warn`): minuendo e subtraendo foram publicados em **layouts diferentes** para a linha. O
  código e o nome são os mesmos (`casamento = 'estavel'`), mas o conteúdo mudou de linha entre um documento e outro, e a
  subtração mistura os dois. Ex.: Vale 4T24 original, em que o ITR 3T24 trazia R$ 11,756 bi em 3.04.04 e o DFP 2024 já no
  layout novo, com o valor em 3.04.03: o 4T sai −11,756 bi em 3.04.04 e com 11,756 bi a mais em 3.04.03. O total (3.04)
  fecha. Evidência na Camada 2: na safra original, a linha do subtraendo é `reclassificacao` contra a sua versão Penúltimo
  (com o mesmo nome nas duas, para não confundir com renumeração) e a do minuendo não diverge da sua. Na safra reapresentado,
  marca as linhas dos mesmos dois documentos (o 4T23 reapresentado da Vale usa o DFP 2024 e o ITR 3T24) que divergem entre
  versões. Vale para toda linha derivada (DRE 4T, DFC/DVA 2T–4T), não para a DRE 1T–3T publicada. Sem versão posterior do
  minuendo (o 4T do exercício mais recente) não há como saber e não há flag. Resumo por trimestre em `consistency_flags`
  (`layer = 6`, `cd_conta` NULL, `detalhe.linhas`). Na base de 2026-09-30: ~9 mil linhas de 1,8 milhão, 630 delas
  no 4T original da DRE. Banco anterior à flag: `sqlite3 cvm_research.db < scripts/migrations/2026-09-30_trimestrais_reclassificacao.sql`,
  `sqlite3 cvm_research.db < schema.sql` e `run_all.py --layer 6 --full` (a Camada 6 se recusa a rodar sem a migração).
- `3.99` (lucro por ação) não está na tabela: não é aditivo. Exercício social fora do calendário: `trimestre` é a posição no exercício, não o trimestre-calendário.
Para rodar: `run_all.py --layer 6 --cnpj <CNPJ>` (depende da Camada 2 já executada). `--sim-alto`/`--sim-baixo` movem os
limiares do casamento (padrão 0,75 e 0,55).

---

## Receitas de SQL e comportamento de pesquisa

Movidas para a skill versionada em `skills/cvm-research/` (`references/receitas-sql.md`, `SKILL.md`): consultas
prontas por tema (assembleias, fatos relevantes, insiders, recompra, acionistas, DRE/balanço, camadas 1–6, FTS)
e as regras de como responder (texto NULL, reapresentação, 4T, bancos). A skill é o que o Claude lê numa sessão
de pesquisa; este arquivo guarda o que serve ao desenvolvimento.

Para a skill valer neste diretório: `ln -s ../../skills/cvm-research .claude/skills/cvm-research`
(o `.claude/` é ignorado pelo git; `setup.sh` faz isso).

## Defasagem dos dados

**IPE (documentos corporativos):** a CVM atualiza os ZIPs anuais **semanalmente, toda segunda-feira entre 8h00 e 8h30**. Documentos divulgados após a última atualização (ex: fatos relevantes publicados durante a semana) só estarão disponíveis na base após a próxima segunda-feira.

Se um documento recente não aparecer na base, informar ao usuário:
- A base tem delay de até 7 dias para metadados do IPE
- O documento pode ser consultado diretamente no portal da CVM: `https://www.rad.cvm.gov.br/ENET/frmConsultaExternaCVM.aspx`
- Rodar `python ingest_ipe.py` após a segunda-feira atualiza a base

**VLMO / FRE / Recompra / DFP / ITR / consistência (Camadas 1, 2, 3, 5 e 6):** entram no mesmo job semanal (`scripts/update_weekly.sh`). Para forçar agora: `bash scripts/update_weekly.sh`. Logs em `logs/update_*.log`.

## Anomalias conhecidas: `data_referencia` no futuro em `ipe_docs`

Existem registros em `ipe_docs` com `data_referencia` posterior à data atual. **Não filtre isso de forma genérica** (ex: `WHERE data_referencia <= date('now')`) — a maioria é legítima:

- **~96% dos casos** (categorias `Calendário de Eventos Corporativos` e `Assembleia`) são documentos que citam datas de eventos *futuros* por natureza: um calendário de eventos corporativos lista datas de divulgações ainda não ocorridas; uma convocação de assembleia é publicada com a data da própria assembleia, que ainda vai acontecer. Isso é dado correto, não erro.
- **Uma fração pequena é erro de digitação na fonte da CVM**, confirmado comparando o CSV oficial (`https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/IPE/DADOS/ipe_cia_aberta_<ano>.zip`) diretamente — o erro já vem no `Data_Referencia` da CVM, inclusive embutido no `Protocolo_Entrega` gerado pelo sistema deles (ex: protocolo `001023IPE07072121...` para uma data `2121-07-07`, quando a `data_entrega` real foi `2021-07-30`). **Não é bug do `ingest_ipe.py`** (ele usa `pd.to_datetime` puro, sem lógica de correção de ano) — é erro de digitação no momento do registro do documento na CVM.

**Como distinguir um caso legítimo de um erro real:** compare `data_referencia` com `data_entrega` (que é sempre confiável — é o timestamp de recebimento pela CVM). Gap de 0–1 ano é normal (evento agendado para o mesmo ano ou o seguinte). Gap ≥ 9 anos é sinal de erro de digitação na fonte:

```sql
SELECT data_referencia, data_entrega, cnpj_companhia, categoria, protocolo_entrega,
  (CAST(substr(data_referencia,1,4) AS INTEGER) - CAST(substr(data_entrega,1,4) AS INTEGER)) AS gap_anos
FROM ipe_docs
WHERE data_referencia > date('now')
  AND (CAST(substr(data_referencia,1,4) AS INTEGER) - CAST(substr(data_entrega,1,4) AS INTEGER)) >= 9
ORDER BY gap_anos DESC;
```

Quando aparecer um novo caso assim (gap ≥ 9 anos): não tentar "corrigir" o ano automaticamente (não há offset consistente — já vimos +100, +71, +16, +9 anos no mesmo padrão de erro), apenas reportar ao usuário citando `data_entrega` como a data confiável e, se necessário, o `link_download` para conferência manual no portal da CVM.

## Monitorar uso do banco
```sql
SELECT COUNT(*) AS total_docs FROM ipe_docs;
```

## Conexão e atualização manual

**Banco:** SQLite local (`cvm_research.db`) via MCP `cvm-research`. Setup completo em `INSTALL.md`; setup rápido: `bash setup.sh`.

### Atualização dos dados

**Carga inicial (banco vazio):** `bash bootstrap.sh` — brutos com histórico completo, as cinco
camadas de consistência e o texto dos PDFs em laço. Retomável. É o único caminho que deixa
`demonstrativos_trimestrais`, `consistency_flags` e `cd_conta_ds_timeline` preenchidas; os
ingestores sozinhos só trazem o dado bruto.

**Manutenção:** automática com `bash scripts/install_weekly_launchd.sh` (segunda 9h, e no login e a
cada 4 h enquanto a semana não tiver uma execução sem falhas; `--status` mostra o último sucesso e o
último log), ou `bash scripts/update_weekly.sh` à mão. O job semanal atualiza só o ano
corrente e o anterior; para refazer o histórico use o `bootstrap.sh`. Passo a passo:

```bash
cd scripts/ingest
source ../../.venv/bin/activate

python ingest_ipe.py        # metadados de documentos
python ingest_vlmo.py       # insider trading
python ingest_recompra.py   # programas de recompra
python ingest_fre.py        # dados de capital, acionistas, remuneração
python ingest_dfp.py        # demonstrativos anuais (ano corrente e anterior)
python ingest_itr.py        # demonstrativo trimestral (ano corrente)

# Histórico completo — rode uma vez ao migrar ou adicionar novas empresas
python ingest_ipe.py   --desde 2015   # IPE útil a partir de 2015 (ZIPs 2009–2014 vêm sem protocolo → 0 docs)
python ingest_dfp.py   --historico --desde 2010   # DFP desde 2010
python ingest_itr.py   --desde 2011   # ITR desde 2011
python ingest_vlmo.py  --desde 2018   # VLMO estruturado disponível desde 2018
# Notas explicativas: sem --historico por padrão — cada PDF tem dezenas de MB
# e centenas de empresas × anos vira um volume grande. Rodar sob demanda por
# empresa/ano quando precisar de um dado que só existe em nota (ex: quebra de
# depreciação por classe de ativo), como em:
#   python ingest_notas_explicativas.py --cnpj <CNPJ> --ano <ANO> --fonte ITR
python ingest_fre.py   --desde 2010   # FRE desde 2010

# Tratamento — obrigatório depois de qualquer carga histórica. Sem isto,
# demonstrativos_trimestrais, consistency_flags e cd_conta_ds_timeline ficam vazias.
cd ../analysis && python run_all.py --layer 1,2,3,5,6 --full   # ~8 min nas 145 empresas
```

O `.env` na raiz do projeto deve ter:
```
DATABASE_URL=sqlite:///cvm_research.db
```

**Extração de texto de PDFs:** `extract_pdf.py` funciona diretamente com o banco SQLite.
Para popular `texto_extraido`, rode `python extract_pdf.py` com o DATABASE_URL configurado.

### Adicionar empresas à watchlist

O `watchlist.csv` controla quais empresas são ingeridas. Para expandir a cobertura:

```bash
cd scripts/ingest
source ../../.venv/bin/activate

# 1. Gerar/atualizar o catálogo B3+CVM (company_catalog.csv na raiz do projeto)
python catalog.py

# 2. Buscar uma empresa por nome ou ticker
python catalog.py --search "petrobras"

# 3. Adicionar empresas ao watchlist.csv
python add_companies.py --ibov          # Todas as empresas do IBOV atual
python add_companies.py --ibov --dry-run  # Preview sem gravar
python add_companies.py --all           # Todas as ~443 empresas B3 ativas
python add_companies.py --ticker VALE3  # Uma empresa específica
python add_companies.py --setor "Saude" # Por setor CVM (parcial, case-insensitive)
python add_companies.py --ibov --skip-assumed  # Pula tickers inferidos (sufixo 3)

# 4. Sincronizar watchlist.csv → tabela companies
python ingest_companies.py
```

O caminho mais curto para os passos 3 e 4 é o `bootstrap.sh`, que também aceita a lista de
tickers direto e já roda o tratamento depois (ver "Montar a base do zero" no topo):

```bash
bash bootstrap.sh --universo ibov                    # soma o IBOV ao watchlist
bash bootstrap.sh --universo minhas-empresas.csv     # soma a lista do usuário
```

**Recarregar os dados para a cobertura nova:** `bash bootstrap.sh --sem-pdf` e depois
`bash bootstrap.sh --so-pdf`. Os ingestores reprocessam os ZIPs inteiros, então a recarga
atualiza as empresas antigas junto e nada é perdido. Só não esqueça do tratamento: sem ele as
tabelas derivadas ficam desatualizadas em relação à cobertura nova.

**Tickers assumidos:** empresas fora do IBOV recebem ticker com sufixo "3" (ON).
Checar coluna `observacao` no watchlist.csv para linhas com `auto:assumed` e corrigir
o ticker se necessário antes de rodar `ingest_companies.py`.

## Skill routing

When the user's request matches an available skill, invoke it via the Skill tool. When in doubt, invoke the skill.

Key routing rules:
- Product ideas/brainstorming → invoke /office-hours
- Strategy/scope → invoke /plan-ceo-review
- Architecture → invoke /plan-eng-review
- Design system/plan review → invoke /design-consultation or /plan-design-review
- Full review pipeline → invoke /autoplan
- Bugs/errors → invoke /investigate
- QA/testing site behavior → invoke /qa or /qa-only
- Code review/diff check → invoke /code-review
- Visual polish → invoke /design-review
- Ship/deploy/PR → invoke /ship or /land-and-deploy
- Save progress → invoke /context-save
- Resume context → invoke /context-restore
