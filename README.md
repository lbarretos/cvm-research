# CVM Research — Base Local

Base de dados local de documentos e eventos de empresas abertas brasileiras, organizada para pesquisa via Claude.

**Fontes:** IPE · VLMO · Recompra · FRE · DFP/ITR  
**Cobertura:** 56 empresas da watchlist (B3) · 2016–hoje  
**Banco:** PostgreSQL 16 local (sem Docker, sem cloud)  
**Tamanho:** ~830 MB · 1,2M+ linhas  
**Atualização:** manual via scripts de ingestão

---

## Pré-requisitos

| Ferramenta | Versão mínima | Verificar |
|---|---|---|
| macOS | — | — |
| [Homebrew](https://brew.sh) | qualquer | `brew --version` |
| Python | 3.10+ | `python3 --version` |
| Node.js + npx | 18+ | `node --version` |
| Claude Code CLI | qualquer | `claude --version` |
| Claude desktop app | qualquer | (opcional, para chat visual) |

---

## Setup completo (primeira vez)

### 1. Clonar o repositório

```bash
git clone https://github.com/lbarretos/cvm-research.git
cd cvm-research
```

### 2. Instalar PostgreSQL 16

```bash
brew install postgresql@16
brew services start postgresql@16
echo 'export PATH="/opt/homebrew/opt/postgresql@16/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc

# Verificar que está rodando
psql --version   # deve mostrar "psql (PostgreSQL) 16.x"
```

### 3. Criar banco e rodar migrations

```bash
createdb cvm_research

# Rodar todas as migrations em ordem
for f in supabase/migrations/001_companies.sql \
          supabase/migrations/002_ipe.sql \
          supabase/migrations/003_vlmo.sql \
          supabase/migrations/004_recompra.sql \
          supabase/migrations/005_fre.sql \
          supabase/migrations/007_drop_cpf_acionista.sql \
          supabase/migrations/008_demonstrativos.sql \
          supabase/migrations/009_vlmo_mov_uniq.sql; do
  echo "Rodando $f..."
  psql cvm_research < "$f"
done

# Verificar tabelas criadas (deve listar 11 tabelas)
psql cvm_research -c "\dt"
```

> **006_rls.sql** é ignorado — RLS (segurança por linha) não é necessário localmente.

### 4. Configurar ambiente Python

```bash
# Criar e ativar virtualenv (use python3.10+ ou superior)
python3 -m venv .venv
source .venv/bin/activate

# Instalar dependências
pip install -r requirements.txt
```

Criar o arquivo `.env` na raiz do projeto:

```bash
echo "DATABASE_URL=postgresql://localhost/cvm_research" > .env
```

### 5. Carga inicial dos dados (~30–40 min)

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
psql cvm_research -c "
SELECT relname AS tabela, n_live_tup AS linhas
FROM pg_stat_user_tables ORDER BY n_live_tup DESC;
SELECT pg_size_pretty(pg_database_size('cvm_research')) AS tamanho;
"
```

---

## Configurar MCP no Claude

O MCP (Model Context Protocol) permite ao Claude acessar o banco diretamente durante a conversa. Precisa ser configurado uma vez em cada interface que for usar.

### Encontrar o caminho do npx

```bash
which npx
# Exemplos comuns:
# /usr/local/bin/npx           (instalação padrão Node)
# ~/.fnm/node-versions/v24.14.0/installation/bin/npx  (fnm)
# ~/.nvm/versions/node/v20.0.0/bin/npx                (nvm)
# /opt/homebrew/bin/npx        (Homebrew)
```

Guarde esse caminho — vai precisar nos passos abaixo.

---

### Opção A — Claude Code (terminal)

```bash
claude mcp add postgres-local -s user -- \
  $(which npx) \
  -y @modelcontextprotocol/server-postgres \
  postgresql://localhost/cvm_research
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
        "@modelcontextprotocol/server-postgres",
        "postgresql://localhost/cvm_research"
      ]
    }
  },
  ... resto da configuração existente ...
}
```

> **Importante:** substituir `/CAMINHO/COMPLETO/DO/npx` pelo caminho obtido com `which npx` acima. O Claude desktop não herda o PATH do shell, então o caminho deve ser absoluto.

Exemplo com fnm:
```json
"command": "/Users/seu-usuario/.fnm/node-versions/v24.14.0/installation/bin/npx"
```

Exemplo com instalação padrão Node:
```json
"command": "/usr/local/bin/npx"
```

Após editar, **reinicie o Claude desktop** (Cmd+Q → reabrir).

---

### Verificar se o MCP está funcionando

Tanto no Claude Code quanto no Claude desktop, faça uma pergunta de teste:

> *"Quais tabelas existem no banco e quantas linhas tem cada uma?"*

O Claude deve responder com a lista de tabelas e contagens diretamente do banco local. Se o banco não aparecer, verifique:

```bash
# 1. PostgreSQL está rodando?
brew services list | grep postgresql
# Se "stopped": brew services start postgresql@16

# 2. Banco existe?
psql -l | grep cvm_research

# 3. npx funciona?
npx --version

# 4. MCP server funciona?
$(which npx) -y @modelcontextprotocol/server-postgres postgresql://localhost/cvm_research
# Deve imprimir algo e não dar erro imediato
```

---

## Atualização manual da base

Rodar periodicamente para manter os dados em dia:

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

> **PostgreSQL precisa estar rodando** para a ingestão funcionar. Se o Mac reiniciou:
> ```bash
> brew services start postgresql@16
> ```

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
├── watchlist.csv                   # 56 empresas com CNPJ e código CVM
├── CLAUDE.md                       # schema, queries e instruções para o Claude
├── README.md                       # este arquivo
├── requirements.txt                # dependências Python
├── .env                            # DATABASE_URL (não commitado)
├── .env.example                    # template do .env
├── supabase/migrations/            # schema SQL para setup local
│   ├── 001_companies.sql
│   ├── 002_ipe.sql
│   ├── ...
│   └── 009_vlmo_mov_uniq.sql
├── scripts/ingest/
│   ├── utils.py                    # conexão DB + helpers de conversão
│   ├── ingest_companies.py         # watchlist
│   ├── ingest_ipe.py               # documentos CVM (metadados)
│   ├── ingest_vlmo.py              # insider trading
│   ├── ingest_recompra.py          # programas de recompra
│   ├── ingest_fre.py               # capital, acionistas, remuneração
│   ├── ingest_dfp.py               # demonstrativos anuais (--historico / --desde ANO)
│   ├── ingest_itr.py               # demonstrativos trimestrais (--desde ANO)
│   ├── extract_pdf.py              # extração de texto de PDFs (requer Supabase)
│   └── migrate_texto_supabase.py   # migração one-time Supabase→local (já executado)
└── .github/workflows/              # desativados — ingestão é manual
```

---

## Troubleshooting

**`createdb: error: database "cvm_research" already exists`**
```bash
dropdb cvm_research && createdb cvm_research
```

**`psql: command not found`**
```bash
export PATH="/opt/homebrew/opt/postgresql@16/bin:$PATH"
```

**`ModuleNotFoundError: No module named 'psycopg2'`**
```bash
source .venv/bin/activate
pip install -r requirements.txt
```

**`KeyError: 'DATABASE_URL'`**
```bash
# Verificar se o .env existe na raiz do projeto
cat .env   # deve mostrar DATABASE_URL=postgresql://localhost/cvm_research
```

**MCP não conecta no Claude desktop**
- Confirme que o caminho do `npx` é absoluto (sem `~`)
- Confirme que o JSON está válido (sem vírgulas extras)
- Reinicie o Claude desktop completamente (Cmd+Q)
- Verifique que o PostgreSQL está rodando: `brew services list | grep postgresql`
