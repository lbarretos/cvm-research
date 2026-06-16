# CVM Research — Base Local

Base de dados local de documentos e eventos de empresas abertas brasileiras, organizada para pesquisa via Claude.

**Fontes:** IPE · VLMO · Recompra · FRE · DFP/ITR  
**Cobertura:** 111 empresas (IBOV + cobertura própria) · 2010–hoje  
**Banco:** SQLite local (`cvm_research.db`) — sem PostgreSQL, sem Docker, sem cloud  
**Tamanho:** ~1.6 GB · 3.4M+ linhas  
**Atualização:** manual via scripts de ingestão

---

## Pré-requisitos

| Ferramenta | Versão mínima | Verificar |
|---|---|---|
| macOS | 11+ (Big Sur) | `sw_vers -productVersion` |
| Python | 3.10+ | `python3 --version` |
| Node.js + npx | 18+ | `node --version` |
| Claude Code CLI | qualquer | `claude --version` |
| Claude desktop app | qualquer | (opcional, para chat visual) |

> **SQLite** vem instalado no macOS por padrão — nenhuma instalação adicional necessária.

---

## Setup completo

> **Recomendado:** veja o [INSTALL.md](INSTALL.md) para o guia passo a passo com suporte ao Claude Code — do clone ao primeiro SELECT em menos de 5 minutos de trabalho seu.

### Resumo rápido (manual)

```bash
git clone https://github.com/lbarretos/cvm-research.git
cd cvm-research
bash setup.sh
python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
echo "DATABASE_URL=sqlite:///cvm_research.db" > .env
```

Carga inicial (~30–40 min):
```bash
cd scripts/ingest
python ingest_companies.py && python ingest_ipe.py && python ingest_vlmo.py
python ingest_recompra.py && python ingest_fre.py
python ingest_dfp.py --historico --desde 2010 && python ingest_itr.py --desde 2011
```

---

## Configurar MCP no Claude

O MCP permite ao Claude consultar o banco diretamente durante a conversa.

### Claude Code CLI (terminal)

```bash
claude mcp add postgres-local -s user -- $(which npx) \
  -y mcp-server-sqlite \
  --db $(pwd)/cvm_research.db

claude mcp list   # postgres-local: ✓ Connected
```

### Claude desktop app (interface visual)

Edite `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "postgres-local": {
      "command": "/caminho/absoluto/do/npx",
      "args": ["-y", "mcp-server-sqlite", "--db", "/caminho/absoluto/cvm_research.db"]
    }
  }
}
```

Use caminhos absolutos (`which npx` e `pwd`/cvm_research.db). Reinicie o app após salvar.
Veja o [INSTALL.md](INSTALL.md) para o guia completo.

### Verificar

Pergunte ao Claude: *"Quantas linhas tem a tabela ipe_docs?"* — deve responder ~134.000.

---

## Atualização manual da base

> **Cadência da CVM:** os ZIPs do IPE (documentos corporativos) são atualizados **toda segunda-feira entre 8h00 e 8h30**. Para documentos mais recentes, consulte diretamente o portal RAD: `rad.cvm.gov.br`.

Rodar após cada segunda-feira para manter os dados em dia:

```bash
cd scripts/ingest
source ../../.venv/bin/activate

# Semanal (IPE, VLMO, FRE e demonstrativos do ano corrente)
python ingest_ipe.py
python ingest_vlmo.py
python ingest_recompra.py
python ingest_fre.py
python ingest_dfp.py
python ingest_itr.py

# Histórico completo (após adicionar novas empresas)
python ingest_dfp.py --historico --desde 2010
python ingest_itr.py --desde 2011
```

---

## Uso com o Claude

Com o MCP conectado, basta conversar normalmente. O Claude consulta o banco quando necessário.

**Exemplos de perguntas:**

- *"Resumo das últimas AGOs e AGEs da WEG com o que foi deliberado"*
- *"Fatos relevantes da Embraer no último ano — classifica por tipo de impacto"*
- *"Houve compra de ações por insiders da Localiza próximo a algum resultado em 2024?"*
- *"Compare a margem EBIT de WEGE3 e EMBR3 de 2016 a 2024"*
- *"Quais programas de recompra estão vigentes?"*
- *"Quem são os maiores acionistas da Vale hoje?"*

O arquivo `CLAUDE.md` documenta o schema completo, queries de exemplo e o comportamento esperado para cada tipo de pesquisa.

---

## Estrutura do projeto

```
cvm-research/
├── watchlist.csv                   # 111 empresas com CNPJ, ticker e código CVM
├── schema.sql                      # schema SQLite completo (tabelas + views + FTS5)
├── setup.sh                        # cria cvm_research.db a partir de schema.sql
├── CLAUDE.md                       # schema, queries e instruções para o Claude
├── README.md                       # este arquivo
├── requirements.txt                # dependências Python (sem PostgreSQL)
├── .env                            # DATABASE_URL (não commitado)
├── .env.example                    # template do .env
├── scripts/ingest/
│   ├── utils.py                    # conexão SQLite + helpers de conversão
│   ├── catalog.py                  # baixa catálogo B3+CVM → company_catalog.csv
│   ├── add_companies.py            # adiciona empresas do catálogo à watchlist
│   ├── ingest_companies.py         # sincroniza watchlist.csv → tabela companies
│   ├── ingest_ipe.py               # documentos CVM (metadados) — flag: --desde ANO
│   ├── ingest_vlmo.py              # insider trading
│   ├── ingest_recompra.py          # programas de recompra
│   ├── ingest_fre.py               # capital, acionistas, remuneração
│   ├── ingest_dfp.py               # demonstrativos anuais — flags: --historico, --desde ANO
│   ├── ingest_itr.py               # demonstrativos trimestrais — flag: --desde ANO
│   └── extract_pdf.py              # extração de texto de PDFs (SQLite local)
└── .github/workflows/              # desativados — ingestão é manual
```

### Fontes de dados

| Script | Fonte | Tabelas populadas | Cadência |
|---|---|---|---|
| `catalog.py` | B3 API + CVM | `company_catalog.csv` (arquivo) | ao expandir cobertura |
| `add_companies.py` | `company_catalog.csv` | `watchlist.csv` (arquivo) | ao expandir cobertura |
| `ingest_companies.py` | `watchlist.csv` | `companies` | após mudar watchlist |
| `ingest_ipe.py` | IPE ZIPs anuais | `ipe_docs` | semanal (seg após 8h30) |
| `ingest_vlmo.py` | VLMO ZIPs anuais | `vlmo_posicao`, `vlmo_movimentacoes` | semanal |
| `ingest_recompra.py` | Recompra ZIPs | `recompra_programas` | semanal |
| `ingest_fre.py` | FRE ZIPs anuais | `fre_capital_social`, `fre_posicao_acionaria`, `fre_remuneracao_orgao` | mensal |
| `ingest_dfp.py` | DFP ZIPs anuais | `demonstrativos_contabeis` (fonte='DFP') | trimestral |
| `ingest_itr.py` | ITR ZIPs anuais | `demonstrativos_contabeis` (fonte='ITR') | trimestral |

---

## Por que SQLite?

Antes desta versão, o projeto exigia PostgreSQL 16 instalado localmente. Para levar a base para outro computador era preciso instalar o Postgres, criar o banco, rodar 9 migrations e configurar o serviço — uns 20 minutos de setup antes de poder fazer a primeira consulta.

Com SQLite, o banco é um único arquivo (`cvm_research.db`). Python já traz o `sqlite3` na biblioteca padrão. O único requisito externo é o `npx` (para o MCP) — que qualquer desenvolvedor com Node.js já tem.

**Limitações conhecidas vs PostgreSQL:**
- `texto_extraido` (texto extraído de PDFs) não é populado pelos ingestores padrão — requer `extract_pdf.py` rodando separadamente.
- Full-text search usa SQLite FTS5 com sintaxe diferente do `tsvector` PostgreSQL (documentada em `CLAUDE.md`).
- `NULLS NOT DISTINCT` no índice único de `vlmo_movimentacoes` não é suportado — a deduplicação é feita no nível Python, o que é suficiente na prática.

---

## Troubleshooting

**`sqlite3: command not found`**
```bash
# macOS: sqlite3 vem pré-instalado. Se não estiver:
brew install sqlite3
```

**`ModuleNotFoundError`**
```bash
source .venv/bin/activate
pip install -r requirements.txt
```

**`KeyError: 'DATABASE_URL'`**
```bash
# Verificar se o .env existe na raiz do projeto
cat .env   # deve mostrar DATABASE_URL=sqlite:///cvm_research.db
```

**Banco vazio após setup**
```bash
# O banco é criado vazio — rode os ingestores para popular:
cd scripts/ingest && source ../../.venv/bin/activate
python ingest_companies.py && python ingest_ipe.py
# ... (ver seção "Carga inicial" acima)
```

**MCP não conecta**
- Confirme que está configurado: `claude mcp list` — deve mostrar `postgres-local`
- Se não aparecer: `claude mcp add postgres-local -s user -- $(which npx) -y mcp-server-sqlite --db $(pwd)/cvm_research.db`
- No Claude.app: confirme que os caminhos no `claude_desktop_config.json` são absolutos
- Veja troubleshooting completo em [INSTALL.md](INSTALL.md#troubleshooting)

**`extract_pdf.py` falha com `KeyError: 'DATABASE_URL'`**
```bash
# Verificar se o .env existe e tem DATABASE_URL
cat .env   # deve mostrar DATABASE_URL=sqlite:///cvm_research.db
```
