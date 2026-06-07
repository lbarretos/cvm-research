# CVM Research — Base Local

Base de dados local de documentos e eventos de empresas abertas brasileiras, organizada para pesquisa via Claude.

**Fontes:** IPE · VLMO · Recompra · FRE · DFP/ITR  
**Cobertura:** 56 empresas da watchlist (B3) · 2016–hoje  
**Banco:** SQLite local (`cvm_research.db`) — sem PostgreSQL, sem Docker, sem cloud  
**Tamanho:** ~830 MB · 1,2M+ linhas  
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

## Setup completo (primeira vez)

### 1. Clonar o repositório

```bash
git clone https://github.com/lbarretos/cvm-research.git
cd cvm-research
```

### 2. Criar o banco SQLite

```bash
bash setup.sh
# Saída esperada:
# === CVM Research — Setup do banco SQLite ===
# Banco 'cvm_research.db' criado.
# === Tabelas criadas ===
# companies  demonstrativos_contabeis  fre_capital_social  ipe_docs  ...
# ✅ Banco pronto.
```

### 3. Configurar ambiente Python

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Criar o arquivo `.env` na raiz do projeto:

```bash
echo "DATABASE_URL=sqlite:///cvm_research.db" > .env
```

### 4. Carga inicial dos dados (~30–40 min)

```bash
cd scripts/ingest

python ingest_companies.py          # watchlist (~5s)
python ingest_ipe.py                # metadados IPE 2021–hoje (~5 min)
python ingest_vlmo.py               # insider trading 2021–hoje (~3 min)
python ingest_recompra.py           # programas de recompra (~30s)
python ingest_fre.py                # capital, acionistas, remuneração (~8 min)
python ingest_dfp.py --historico    # demonstrativos anuais 2016–hoje (~10 min)
python ingest_itr.py --desde 2016   # trimestrais 2016–hoje (~15 min)
```

Para verificar a carga:
```bash
sqlite3 cvm_research.db "
SELECT name AS tabela FROM sqlite_master WHERE type='table' ORDER BY name;
SELECT COUNT(*) AS total_docs FROM ipe_docs;
"
```

---

## Configurar MCP no Claude

O MCP (Model Context Protocol) permite ao Claude acessar o banco diretamente durante a conversa. Precisa ser configurado uma vez em cada interface.

### Encontrar o caminho do npx

```bash
which npx
# Exemplos comuns:
# /usr/local/bin/npx           (instalação padrão Node)
# ~/.fnm/node-versions/v24.14.0/installation/bin/npx  (fnm)
# ~/.nvm/versions/node/v20.0.0/bin/npx                (nvm)
# /opt/homebrew/bin/npx        (Homebrew)
```

Guarde esse caminho e o caminho absoluto do banco:
```bash
which npx          # caminho do npx
pwd                # raiz do projeto → append /cvm_research.db
```

---

### Opção A — Claude Code (terminal)

```bash
claude mcp add postgres-local -s user -- \
  $(which npx) \
  -y mcp-server-sqlite \
  --db $(pwd)/cvm_research.db
```

Verificar se conectou:
```bash
claude mcp list
# Deve mostrar: postgres-local: ... ✓ Connected
```

---

### Opção B — Claude desktop app (chat visual)

Editar o arquivo de configuração do app:

**Localização:** `~/Library/Application Support/Claude/claude_desktop_config.json`

Adicionar a chave `mcpServers` ao JSON existente:

```json
{
  "mcpServers": {
    "postgres-local": {
      "command": "/CAMINHO/COMPLETO/DO/npx",
      "args": [
        "-y",
        "mcp-server-sqlite",
        "--db",
        "/CAMINHO/ABSOLUTO/cvm_research.db"
      ]
    }
  }
}
```

> **Importante:** use caminhos absolutos. O Claude desktop não herda o PATH do shell.
> Exemplo: `"/Users/seu-usuario/cvm-research/cvm_research.db"` — nunca `~` ou caminhos relativos.

Após editar, **reinicie o Claude desktop** (Cmd+Q → reabrir).

---

### Verificar se o MCP está funcionando

Tanto no Claude Code quanto no Claude desktop, faça uma pergunta de teste:

> *"Quais tabelas existem no banco e quantas linhas tem cada uma?"*

O Claude deve responder com a lista de tabelas e contagens diretamente do banco. Se não aparecer:

```bash
# 1. Banco existe?
ls -lh cvm_research.db

# 2. npx funciona?
npx --version

# 3. MCP server funciona?
npx -y mcp-server-sqlite --db ./cvm_research.db
# Deve imprimir: SQLite MCP Server running on stdio
```

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

# Trimestral (reprocessa série histórica completa)
python ingest_dfp.py --historico
python ingest_itr.py --desde 2016
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
├── watchlist.csv                   # 56 empresas com CNPJ, ticker e código CVM
├── schema.sql                      # schema SQLite completo (tabelas + views + FTS5)
├── setup.sh                        # cria cvm_research.db a partir de schema.sql
├── CLAUDE.md                       # schema, queries e instruções para o Claude
├── README.md                       # este arquivo
├── requirements.txt                # dependências Python (sem PostgreSQL)
├── .env                            # DATABASE_URL (não commitado)
├── .env.example                    # template do .env
├── supabase/migrations/            # schema legado (referência para cloud/Supabase)
├── scripts/ingest/
│   ├── utils.py                    # conexão SQLite + helpers de conversão
│   ├── ingest_companies.py         # watchlist
│   ├── ingest_ipe.py               # documentos CVM (metadados) — flag: --desde ANO
│   ├── ingest_vlmo.py              # insider trading
│   ├── ingest_recompra.py          # programas de recompra
│   ├── ingest_fre.py               # capital, acionistas, remuneração
│   ├── ingest_dfp.py               # demonstrativos anuais — flags: --historico, --desde ANO
│   ├── ingest_itr.py               # demonstrativos trimestrais — flag: --desde ANO
│   └── extract_pdf.py              # extração de texto de PDFs (requer Supabase)
└── .github/workflows/              # desativados — ingestão é manual
```

### Fontes de dados

| Script | Fonte CVM | Tabelas populadas | Cadência |
|---|---|---|---|
| `ingest_companies.py` | `watchlist.csv` | `companies` | quando watchlist mudar |
| `ingest_ipe.py` | IPE ZIPs anuais | `ipe_docs` | semanal (seg após 8h30) |
| `ingest_vlmo.py` | VLMO ZIPs anuais | `vlmo_posicao`, `vlmo_movimentacoes` | semanal |
| `ingest_recompra.py` | Recompra ZIPs | `recompra_programas`, `recompra_quantidades` | semanal |
| `ingest_fre.py` | FRE ZIPs anuais | `fre_capital_social`, `fre_posicao_acionaria`, `fre_remuneracao_orgao` | mensal |
| `ingest_dfp.py` | DFP ZIPs anuais | `demonstrativos_contabeis` (fonte='DFP') | trimestral |
| `ingest_itr.py` | ITR ZIPs anuais | `demonstrativos_contabeis` (fonte='ITR') | trimestral |

---

## Por que SQLite?

Antes desta versão, o projeto exigia PostgreSQL 16 instalado localmente. Para levar a base para outro computador era preciso instalar o Postgres, criar o banco, rodar 9 migrations e configurar o serviço — uns 20 minutos de setup antes de poder fazer a primeira consulta.

Com SQLite, o banco é um único arquivo (`cvm_research.db`). Python já traz o `sqlite3` na biblioteca padrão. O único requisito externo é o `npx` (para o MCP) — que qualquer desenvolvedor com Node.js já tem.

**Limitações conhecidas vs PostgreSQL:**
- `texto_extraido` (texto extraído de PDFs) não é re-ingerido automaticamente — requer `extract_pdf.py` com Supabase. Guarde suas credenciais `SUPABASE_URL`/`SUPABASE_KEY` se quiser recuperar o conteúdo.
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

**MCP não conecta no Claude desktop**
- Confirme que os caminhos são absolutos (sem `~`)
- Confirme que `cvm_research.db` existe: `ls -lh cvm_research.db`
- Confirme que o JSON está válido (sem vírgulas extras)
- Reinicie o Claude desktop completamente (Cmd+Q → reabrir)

**`extract_pdf.py` falha com erro sobre SQLite**
```
ERRO: extract_pdf.py requer Supabase. Defina SUPABASE_URL e SUPABASE_KEY no .env.
```
Este script usa a API REST do Supabase diretamente. Para extração de PDFs, adicione `SUPABASE_URL` e `SUPABASE_KEY` ao `.env` (mantendo também o `DATABASE_URL`).
