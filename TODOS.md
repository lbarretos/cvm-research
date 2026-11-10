# Backlog de Desenvolvimento e Próximos Passos (TODOS)

Base consolidada em 2026-11-09 (`cvm_research.db`, ~19 GB, 151 empresas cobertas, 428 testes passando).
Este documento centraliza todas as frentes futuras de trabalho divididas por eixos temáticos objetivos, eliminando o ruído de anotações antigas ou suposições desatualizadas (como quedas temporárias de portal ou branches já mesclados).

---

## 📌 Eixo 1: Leitura RAG & LLM (Conclusão do Bloco D & Operação)

Este eixo aprimora a camada de leitura de texto dos documentos pelo MCP e LLM, focando na cobertura de demonstrações financeiras (DFs).

- [ ] **Extração em lote das DFs pendentes da watchlist (Etapa 9.14):**
  - Agora que o portal RAD está plenamente operacional, rodar a extração das DFs restantes da watchlist:
    ```bash
    python scripts/ingest/extract_pdf.py --so-df --ocr --sem-fts --limite 100
    ```
  - Executar em lotes controlados para respeitar o rate-limit do portal CVM, reconstruindo o índice FTS5 uma única vez ao término (`python scripts/ingest/extract_pdf.py --rebuild-fts`).
- [x] **Reextração seletiva e fallback de OCR para fontes corrompidas (Etapa 9.8):**
  - Implementado em `scripts/ingest/ocr_fallback.py` (renderização via `pypdfium2` em memória + OCR via `tesseract stdin stdout` sem I/O de disco).
  - Integrado a `extract_pdf.py` (`--ocr`, `--max-ocr-paginas`, `--protocolo`, `--reextrair-ruins`) e `ingest_notas_explicativas.py`.
  - Validado em casos reais de fontes corrompidas Identity-H (LEVE3 e MYPK3), recuperando páginas corrompidas com `(cid:N)` e permitindo a detecção imediata de notas canônicas (`search_docs(secao='ir_csll')`).
  - Suíte de testes unitários em `tests/test_ocr_fallback.py` com 100% de aprovação.
- [ ] **Cobertura de notas explicativas trimestrais via RAD (Etapa 9.13):**
  - Cerca de 37 empresas da watchlist não possuem ITR com notas completas na entrega padrão do IPE.
  - Executar `scripts/ingest/ingest_notas_explicativas.py` em lote para capturar os relatórios do portal RAD dessas empresas nos trimestres recentes (2025–2026), mantendo compatibilidade direta com `search_docs(camada='df', secao=...)`.

---

## 📌 Eixo 2: Renda Fixa & Securitização

Este eixo expande a modelagem de crédito e a integração entre a dívida contábil das companhias abertas e os ativos de renda fixa emitidos no mercado.

- [ ] **Ingestão e busca de Relatórios de Agente Fiduciário e Ratings:**
  - Em `ipe_docs`, na categoria `"Dados Econômico-Financeiros"`, existem os tipos `"Relatório de Agente Fiduciário"` e `"Relatório de Agência de Rating"`.
  - Integrar a extração desses relatórios aos fluxos de consulta (`search_bond_docs` e `search_docs`), possibilitando auditoria de cumprimento de *covenants*, índices financeiros exigidos e ocorrência de pedidos de *waiver*.
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
