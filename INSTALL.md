# CVM Research — Guia de Instalação

Base de dados local de documentos e eventos de empresas abertas brasileiras (CVM/B3).
Banco SQLite · 111 empresas (IBOV + cobertura própria) · dados desde 2010.

---

## Pré-requisitos

| Ferramenta | Verificar | Instalar |
|---|---|---|
| Python 3.10+ | `python3 --version` | [python.org](https://www.python.org/downloads/) |
| Claude Code CLI | `claude --version` | `npm install -g @anthropic-ai/claude-code` |
| Node.js 18+ | `node --version` | [nodejs.org](https://nodejs.org) |

SQLite vem pré-instalado no macOS.

---

## Opção A — Instalar do zero (baixa tudo da CVM)

```bash
git clone https://github.com/lbarretos/cvm-research.git
cd cvm-research

# Criar ambiente Python
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Criar banco e .env
bash setup.sh
echo 'DATABASE_URL=sqlite:///cvm_research.db' > .env

# Configurar MCP no Claude Code
claude mcp add postgres-local -s user -- $(which npx) \
  -y mcp-server-sqlite \
  --db $(pwd)/cvm_research.db

# Popular o banco (30–60 min — baixa ~15 GB de ZIPs da CVM)
cd scripts/ingest && source ../../.venv/bin/activate
python ingest_companies.py
python ingest_ipe.py --desde 2009
python ingest_vlmo.py --desde 2018
python ingest_recompra.py
python ingest_fre.py --desde 2010
python ingest_dfp.py --historico --desde 2010
python ingest_itr.py --desde 2011
```

---

## Opção B — Transferir banco existente (recomendado)

Se você já tem o banco populado em outra máquina, copie dois arquivos:

| Arquivo | Tamanho | Como obter |
|---|---|---|
| `cvm_research.db` | ~1.6 GB | Copiar da máquina de origem |
| `cvm_research_projeto.tar.gz` | ~52 KB | Gerado com `tar -czf` do projeto (sem .venv e .db) |

**Na máquina destino:**

```bash
# 1. Extrair o projeto
tar -xzf cvm_research_projeto.tar.gz
cd cvm-research

# 2. Mover o banco para dentro da pasta
mv /caminho/para/cvm_research.db .

# 3. Criar ambiente Python
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 4. Configurar MCP no Claude Code
claude mcp add postgres-local -s user -- $(which npx) \
  -y mcp-server-sqlite \
  --db $(pwd)/cvm_research.db

# 5. Verificar
claude mcp list   # deve mostrar postgres-local ✓ Connected
```

---

## MCP no Claude desktop app (interface visual)

O Claude desktop app requer configuração no arquivo JSON — não usa `claude mcp add`.

Edite `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "postgres-local": {
      "command": "/caminho/absoluto/do/npx",
      "args": [
        "-y",
        "mcp-server-sqlite",
        "--db",
        "/caminho/absoluto/para/cvm_research.db"
      ]
    }
  }
}
```

Obter os caminhos:
```bash
which npx                  # caminho do npx
pwd                        # rodar de dentro da pasta do projeto
```

Reinicie o app após salvar.

---

## Verificar que está funcionando

Abra o Claude e pergunte:

> *"Quantas linhas tem a tabela ipe_docs?"*

Se responder com número (~134.000), o MCP está funcionando.

---

## Expandir cobertura de empresas

O `watchlist.csv` controla quais empresas são cobertas. Para adicionar:

```bash
cd scripts/ingest && source ../../.venv/bin/activate

# Gerar catálogo B3+CVM (443 empresas ativas)
python catalog.py

# Buscar uma empresa
python catalog.py --search "petrobras"

# Adicionar todas do IBOV (sem tickers assumidos)
python add_companies.py --ibov --dry-run   # preview
python add_companies.py --ibov             # confirmar com "s"

# Sincronizar watchlist → tabela companies
python ingest_companies.py

# Re-ingerir histórico para as novas empresas
python ingest_ipe.py --desde 2009
python ingest_dfp.py --historico --desde 2010
python ingest_itr.py --desde 2011
python ingest_vlmo.py --desde 2018
python ingest_fre.py --desde 2010
```

**Tickers assumidos:** empresas fora de índices recebem ticker `XXXX3` (ON inferido).
Confira a coluna `observacao` no watchlist.csv — corrija antes de rodar os ingestores se necessário.

---

## Atualizar os dados

A CVM publica ZIPs atualizados toda **segunda-feira entre 8h00 e 8h30**.

```bash
cd scripts/ingest && source ../../.venv/bin/activate
python ingest_ipe.py
python ingest_vlmo.py
python ingest_recompra.py
python ingest_fre.py
python ingest_dfp.py
python ingest_itr.py
```

---

## Troubleshooting

| Sintoma | Causa | Solução |
|---|---|---|
| `postgres-local: Connection failed` | npx não encontrado ou caminho errado | Use `$(which npx)` no comando `claude mcp add` |
| `no such table` no Claude.app | Caminho do banco relativo no config JSON | Usar caminho absoluto em `claude_desktop_config.json` |
| `KeyError: 'DATABASE_URL'` | `.env` não existe | `echo 'DATABASE_URL=sqlite:///cvm_research.db' > .env` |
| Banco mostra dados antigos | Ingestores não rodaram após segunda-feira | Rodar scripts de ingestão manualmente |
| `unable to open database file` | Banco em OneDrive com WAL ativo | `sqlite3 cvm_research.db "PRAGMA wal_checkpoint(TRUNCATE);"` |

---

## Exemplos de pesquisa

Com o banco e MCP funcionando, pergunte ao Claude:

- *"Quais foram as deliberações da última AGO da WEG?"*
- *"Houve insider trading na Embraer nos 7 dias antes do último fato relevante?"*
- *"Compare a margem EBIT de WEGE3 e VALE3 de 2020 a 2024"*
- *"Quais programas de recompra estão em andamento hoje?"*
- *"Mostre a evolução da dívida líquida da Petrobras desde 2015"*

O arquivo `CLAUDE.md` documenta o schema completo, queries de exemplo e comportamento esperado para cada tipo de pesquisa.
