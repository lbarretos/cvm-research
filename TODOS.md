# Backlog de Desenvolvimento e Próximos Passos (TODOS)

Base consolidada em 2026-11-11 (`cvm_research.db`, ~19 GB, 156 empresas cobertas, 437 testes passando).
Este documento centraliza todas as frentes de trabalho divididas por eixos temáticos objetivos, eliminando ruídos antigos e mantendo o roadmap acionável.

---

## 📌 Eixo 1: Leitura RAG & LLM (Concluído & Procedimento para Extração Posterior)

O pipeline de leitura de demonstrações financeiras (DFs) com preservação de páginas (`\f`), métricas de qualidade (`qualidade`/`texto_qualidade`), busca de notas canônicas (`secoes_notas.py` via `search_docs(secao=...)`) e fallback de OCR em memória (`ocr_fallback.py`) está **100% implementado, testado e validado**.

### Como rodar as extrações pendentes posteriormente (em segundo plano / lotes):

As DFs restantes da watchlist e notas do RAD podem ser extraídas em segundo plano a qualquer momento sem interromper o desenvolvimento dos demais eixos:

```bash
# 1. Extração de demonstrações financeiras pendentes da watchlist com OCR:
python scripts/ingest/extract_pdf.py --so-df --ocr --sem-fts --limite 100

# 2. Re-tentativa de falhas anteriores (após recuperação do portal RAD):
python scripts/ingest/extract_pdf.py --so-df --ocr --sem-fts --retry-failed --limite 100

# 3. Notas trimestrais de empresas sem ITR completo no catálogo IPE (Etapa 9.13):
python scripts/ingest/ingest_notas_explicativas.py --ano 2026 --fonte ITR --limite 20

# 4. Reconstrução única do índice FTS5 ao término dos lotes:
python scripts/ingest/extract_pdf.py --rebuild-fts
```

- [x] **Fallback de OCR seletivo para fontes corrompidas (Etapa 9.8):** Implementado em `ocr_fallback.py` (tesseract + pypdfium2 em memória) e validado em LEVE3/MYPK3 com 433 testes passando.
- [x] **Pipeline de lote para DFs e re-extração (Etapa 9.14):** Flags `--so-df`, `--ocr`, `--max-ocr-paginas`, `--protocolo`, `--reextrair-ruins`, `--reextrair-parciais`, `--reextrair-degradados` e `--sem-fts` operacionais em `extract_pdf.py`.
- [ ] *(Execução sob demanda)* Concluir os lotes acima conforme conveniência operacional (sem bloqueio de roadmap).

---

## 🎯 FOCO ATUAL — Eixo 2: Renda Fixa & Securitização

Este eixo expande a modelagem de crédito e a integração entre a dívida contábil das companhias abertas e os ativos de renda fixa emitidos no mercado.

- [x] **Ingestão e busca de Relatórios de Agente Fiduciário e Ratings:**
  - Em `ipe_docs`, na categoria `"Dados Econômico-Financeiros"`, existem os tipos `"Relatório de Agente Fiduciário"` e `"Relatório de Agência de Rating"` (mais de 4,2 mil relatórios disponíveis na base).
  - Integrado suporte a extração seletiva via `extract_pdf.py --so-credito` (suportando `--ocr`, `--reextrair-ruins` e `--sem-fts`).
  - Integrada camada `'credito'` em `search_docs` e busca complementar automática em `search_bond_docs` e `get_bond.documentos`, permitindo pesquisar *covenants*, índices contratuais (DL/EBITDA, ICSD) e pedidos de *waiver* com leitura via `read_bond_doc` ou `read_doc`.
- [x] **Suporte a empresas não listadas de capital aberto no watchlist:**
  - `add_companies.py` atualizado com `--cnpj`, `--custom-ticker`, `--observacao` e `--yes` (`-y`), permitindo cadastrar empresas Categoria B e Categoria A não listadas na B3 a partir do cadastro oficial CVM.
  - Adicionado segmento `'1'` (Mercado Tradicional B3) em `LISTED_SEGMENTS` em `catalog.py`.
  - Cadastradas e sincronizadas na tabela `companies`: `CRMU` (Caramuru Alimentos, Categoria A), `VLIM` (VLI Multimodal, Categoria B), `MRSA3B` (MRS Logística, Categoria A), `SALT` (Grupo Salta Educação, Categoria A) e `OBTC3` (OranjeBTC, listada B3).
- [x] **Resolução automática de devedores de CRI e CRA:**
  - Módulo `scripts/ingest/rf_devedor_resolucao.py` com dicionário canônico de apelidos corporativos e casamento fonético/estrutural contra `companies`.
  - 100% dos 272 CRIs e CRAs com `devedor_cnpj` nulo resolvidos e sincronizados com `rf_partes`, ligando o instrumento securitizado ao devedor operacional e ao grupo econômico.
- [x] **Análise Holística de Risco de Crédito Corporativo para Investimento Pessoal:**
  - Enriquecimento de `get_bond` e criação da ferramenta MCP `get_credit_summary(termo)` no `scripts/mcp/cvm_mcp.py`.
  - **Métricas do Instrumento:** senioridade jurídica, maturity, duration (DU e anos), precificação ANBIMA com % PU Par (deságio/ágio de capital) e cálculo automático de **gross-up tributário** da Lei 12.431 e CRI/CRA (equivalente bruto CDB a 15% e 22,5% de IR, e taxa líquida PF para títulos tributados).
  - **Fundamentos Contábeis da Devedora:** conexão direta com `vw_balanco`, `vw_dre` e `fato_padronizado` para Caixa & Equivalentes, Dívida CP/LP, Dívida Bruta, Dívida Líquida, Receita U12M, EBITDA U12M, Alavancagem Dívida Líquida / EBITDA, Cobertura de Caixa CP (`Caixa / Dívida CP`) e Cobertura de Juros (ICR).
  - **Covenants & Agente Fiduciário:** extração automática de limites e apurações contratuais a partir dos Relatórios Anuais do Agente Fiduciário em `ipe_docs`.
  - Suporte tanto a códigos de títulos (`BCBF16`, `FSII14`, `24I1980390`) quanto a empresas (`HAPV3`, `MRVE3`, `VLIM`, `CRMU`), retornando o cronograma de vencimentos e o perfil agregado da dívida.
- [ ] **Estruturação de Termos de Securitização CRI/CRA e Escrituras:**
  - Extrair cronogramas de amortização, taxas de remuneração (spread sobre CDI ou cupom de IPCA) e matriz de garantias reais/fianças diretamente das escrituras baixadas em `rf_docs`.
  - Conectar ao MCP `get_bond` para retornar não apenas metadados cadastrais, mas a estrutura completa da dívida.
- [ ] **Reconciliação Passivo Contábil vs. Títulos de Mercado:**
  - Cruzar a seção canônica `divida_emprestimos` das notas explicativas com a tabela `rf_ativos` (debêntures, CRIs, CRAs), gerando a reconciliação automática da dívida bruta por indexador e prazo.

---

## 📌 Eixo 3: Valuation, Análise Fundamentalista & Régua

Este eixo traduz a riqueza de dados estruturados e notas explicativas em modelos financeiros padronizados e métricas analíticas.

- [ ] **Execução completa da régua de avaliação `golden_v2`:**
  - Executar `run_eval.py --golden v2` em paralelo para as 94 perguntas (81 do v1 + 13 do bloco de notas explicativas).
  - Medir e registrar a redução de turnos e tokens por pergunta após a introdução de `search_docs(secao=...)` e a preservação de quebra de página (`\f`).
- [ ] **Conciliação fiscal e cálculo de alíquota efetiva normalizada:**
  - Utilizar a nota canônica `ir_csll` para extrair sistematicamente as adições, exclusões e incentivos fiscais (subvenções de ICMS, SUDENE/SUDAM, Lei do Bem), permitindo modelar o Lucro Líquido normalizado e projetar alíquotas futuras confiáveis.
- [ ] **Automação de planilhas de Valuation / DCF:**
  - Consolidar os geradores de planilhas financeiras (como os modelos já prototipados para Alpargatas e Axia) consumindo diretamente `vw_dre`, `vw_balanco` e `fato_padronizado`, gerando projeções históricas e fórmulas integradas no Excel.

---

## 📌 Infraestrutura & Manutenção da Base

Tarefas periódicas de governança e integridade do banco SQLite local.

- [ ] **Limpeza de tabelas não populadas no schema:**
  - As tabelas `recompra_quantidades` e `recompra_intermediarios` constam no schema mas não recebem dados. Popular a partir dos arquivos brutos da CVM ou remover do `schema.sql` para manter o catálogo limpo.
- [ ] **Auditoria de tickers assumidos (`watchlist.csv`):**
  - Revisar as 34 linhas do `watchlist.csv` assinaladas com flag temporária `auto:assumed` contra o cadastro oficial da B3 e padronizar as entradas.
- [ ] **`VACUUM` e manutenção de disco:**
  - Com o banco em ~19 GB e após grandes batches de extração de texto, planejar execução de `PRAGMA wal_checkpoint(TRUNCATE)` seguido de `VACUUM` quando houver espaço em disco suficiente.

---

## ✅ Histórico Recente de Entregas (Etapa 9 / Eixo 1)

Para referência do que foi finalizado e incorporado à `main` via PR #51:
- **Páginas preservadas com `\f`:** Extratores `extract_pdf.py` e `ingest_notas_explicativas.py` unem páginas com form-feed (ASCII 12). MCP `search_docs` e `read_doc` agora calculam e devolvem a página original exata do PDF.
- **Métrica de qualidade por página:** Módulo `qualidade_texto.py` classifica documentos em `ok`, `parcial` ou `ruim` e armazena metadados em `texto_qualidade`.
- **Segmentador canônico de notas (`secoes_notas.py`):** 13 seções contábeis canônicas (`ir_csll`, `subvencoes`, `divida_emprestimos`, etc.) com taxa de detecção de 91,0% e busca de 10–15 ms sem sobrecarga de espaço em disco.
- **Parâmetro `secao` no MCP:** `search_docs(secao=...)` roteia diretamente para a camada DF e encontra seções específicas sem necessidade de consulta full-text ad-hoc.
- **Conexão com portal RAD:** Diagnóstico de rede concluído com sucesso; `www.rad.cvm.gov.br` confirmado operacional para novos downloads.
- **Flags `--so-df` e `--sem-fts`:** Suporte a ingestão filtrada e eficiente de DFs adicionado a `extract_pdf.py`.
