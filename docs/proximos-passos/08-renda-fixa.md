# Etapa 8 — Renda fixa: debêntures, CRI e CRA

## Avaliação atual (2026-10-30)

A base não tinha nada de renda fixa estruturado. Dívida aparecia só como linhas da DFC ("Captação de debêntures") e
texto solto no IPE. Pergunta do tipo "quais as garantias do RUMOB6 e quem está por trás do devedor do CRA024004SB?"
não tinha resposta.

## Proposta

Decisões do usuário: só fontes públicas (sem ANBIMA Feed API); cadastro e taxas do mercado inteiro, PDFs sob demanda;
extração estruturada de garantias/partes/lastro a partir do PDF; job semanal; taxas só do último mês.

| Peça | Arquivo |
|---|---|
| Fontes, URLs, apelidos de coluna, `--verificar` | `scripts/ingest/rf_fontes.py` |
| Cadastro (SND + ofertas CVM) → `rf_ativos`, `rf_ofertas`, `rf_partes` | `scripts/ingest/ingest_rf_cadastro.py` |
| Taxas ANBIMA (janela + retenção) → `rf_taxas` | `scripts/ingest/ingest_rf_taxas.py` |
| PDFs dos códigos de `rf_watchlist.csv` → `rf_docs` | `scripts/ingest/ingest_rf_docs.py` |
| Extração por regra → `rf_partes`/`rf_garantias`/`rf_lastro` | `scripts/ingest/extrai_rf.py` |
| Cadeia de controle pelo FRE → `rf_grupo` | `scripts/ingest/rf_grupo.py` |
| MCP: `resolve_bond`, `get_bond`, `search_bonds`, `search_bond_docs`, `read_bond_doc` | `scripts/mcp/cvm_mcp.py` |
| Schema / migração | `schema.sql`, `scripts/migrations/2026-10-30_renda_fixa.sql` |
| Base de teste fictícia | `tests/fixtures/rf/make_test_db.py` |
| Skill | `skills/cvm-research/references/renda-fixa.md` |

Escolhas que merecem registro:
- **Colunas por apelido** (sem acento e sem caixa) e falha alta quando falta coluna obrigatória: os layouts não puderam
  ser vistos na criação. `rf_fontes.py --verificar` mostra a cobertura de cada campo.
- **Extração por regra, sem modelo**: a escritura e o termo de securitização qualificam cada parte da mesma forma
  ("NOME, sociedade…, inscrita no CNPJ nº X (“Fiadora”)"). O termo definido dá o papel; CNPJ sem termo é descartado.
  Garantia por vocabulário com descarte da menção negada. Tudo com `evidencia` e `confianca` < 1.
- **Securitizadora fora do grupo econômico**: ela emite para devedores sem relação entre si; ligar por ela juntaria
  CRAs de grupos diferentes.
- **PDF de CRI/CRA**: só com emissão e série conhecidas (ou o código no assunto) o documento é escolhido sozinho; senão
  a securitizadora tem centenas de termos e o script lista candidatos (`--listar`) e pede `--protocolo`/`--url`.

## Stress test

Não rodado contra dados reais: a sessão de criação não alcançava `dados.cvm.gov.br`, `anbima.com.br` nem
`debentures.com.br` (proxy 403). O que foi testado, com dados sintéticos (31 testes em `tests/test_rf_ingest.py` e
`tests/test_mcp_rf.py`):
- leitura dos três formatos (texto com cabeçalho deslocado, CSV da CVM em ZIP, arquivo '@' em blocos da ANBIMA),
  milhar sem vírgula ('1.650'), '--' como vazio;
- precedência SND × oferta CVM, idempotência dos upserts, falha total = saída ≠ 0;
- janela de taxas: só baixa o que falta, feriado (404) re-tentado, retenção apaga o velho;
- extração: papéis, nomes com "(BRASIL)", negação, CPR-F sem duplicar CPR, securitizadora no CRA;
- grupo: cadeia dentro do FRE e entre FREs, parada em ciclo;
- MCP: seções de `get_bond`, avisos (sem PDF, sem taxa, sem FRE, banco sem migração), orçamento de resposta.

## Critério de pronto

1. `rf_fontes.py --verificar` lê as três fontes com ≥ 90% dos campos-chave preenchidos (código, emissor, vencimento,
   remuneração; taxa indicativa e PU).
2. Os quatro exemplos (`RUMOB6`, `ERDVB4`, `CRA024004SB`, `CRA02300796`) aparecem em `get_bond` com emissão e taxa, e
   com o documento certo ligado (ou candidatos listados, para CRA sem emissão/série).
3. Nas escrituras dos dois títulos de debênture, as partes e garantias extraídas batem com a leitura humana do PDF
   (anotar acertos e erros aqui).
4. Job semanal roda os quatro passos sem falha.

## Resultado (2026-10-30)

Código, migração, operação (job semanal e `bootstrap.sh`), skill e testes prontos; suíte inteira verde. Itens 1–4 do
critério de pronto pendentes da primeira execução com rede (ver `ESTADO.md`, pendência 0).
