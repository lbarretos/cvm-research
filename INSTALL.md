# CVM Research — Guia de Instalação

Base de dados local de documentos e eventos de empresas abertas brasileiras (CVM/B3).
SQLite · 145 empresas · IPE desde 2015, demonstrativos desde 2010 · ~12 GB populado.

---

## Pré-requisitos

| Ferramenta | Verificar | Instalar |
|---|---|---|
| Python 3.10+ | `python3 --version` | [python.org](https://www.python.org/downloads/) ou `brew install python` |
| Claude Code CLI | `claude --version` | `npm install -g @anthropic-ai/claude-code` |

SQLite vem pré-instalado no macOS. Node.js não é necessário.

**Onde colocar o projeto.** Fora de pastas sincronizadas (OneDrive, iCloud Drive, Dropbox): o banco tem ~12 GB e muda toda semana. Prefira uma pasta como `~/Projects/cvm-research`. Se ficar em `~/Documents`, `~/Desktop` ou `~/Downloads`, o macOS bloqueia o job automático do launchd até você dar Acesso Total ao Disco ao `/bin/bash` (ver Troubleshooting).

---

## Opção A — Instalar do zero (baixa tudo da CVM)

```bash
git clone https://github.com/lbarretos/cvm-research.git
cd cvm-research

# Ambiente Python
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

# Banco vazio + .env
bash setup.sh
echo 'DATABASE_URL=sqlite:///cvm_research.db' > .env

# MCP no Claude Code (caminhos absolutos, gravados no ~/.claude.json)
claude mcp add cvm-research -s user -- "$(pwd)/.venv/bin/python" "$(pwd)/scripts/mcp/cvm_mcp.py"

# Popular o banco: brutos + camadas de consistência + texto dos PDFs
bash bootstrap.sh
```

`bootstrap.sh` é retomável (Ctrl-C e rodar de novo continua de onde parou) e faz três blocos:

| Bloco | O que roda | Tempo de referência |
|---|---|---|
| Dados brutos | os sete ingestores com o histórico completo | 30–60 min, ~15 GB de ZIPs |
| Tratamento | `run_all.py --layer 1,2,3,5,6 --full` | ~8 min |
| Texto dos PDFs | `extract_pdf.py` em laço até não sobrar pendente, depois reconstrói o índice FTS | 12–24 h, ~170 mil documentos |

O bloco de tratamento é o que preenche `demonstrativos_trimestrais`, `consistency_flags` e
`cd_conta_ds_timeline`. **Sem ele o banco responde os dados brutos e nada mais**: as queries
trimestrais e de reapresentação do [CLAUDE.md](CLAUDE.md) voltam vazias.

Para adiar a parte longa e já começar a pesquisar, `bash bootstrap.sh --sem-pdf` e depois
`bash bootstrap.sh --so-pdf` quando quiser. Menos histórico, mais rápido:
`IPE_DESDE=2020 DFP_DESDE=2018 ITR_DESDE=2018 bash bootstrap.sh`.

Confira o resultado com `.venv/bin/python -m pytest tests/ -q`: a suíte inclui testes que leem
o banco e recalculam o tratamento a partir do dado bruto (pulam sozinhos se o banco não existir
ou se as camadas ainda não rodaram).

---

## Opção B — Copiar um banco já populado (recomendado)

Copie a pasta do projeto **sem `.venv`** (ela não é relocável: os scripts `pip`/`python` dela gravam o caminho absoluto de origem) mais o arquivo `cvm_research.db`. Na máquina destino:

```bash
cd cvm-research
rm -rf .venv                                   # se veio junto por engano
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
echo 'DATABASE_URL=sqlite:///cvm_research.db' > .env
sqlite3 cvm_research.db "PRAGMA quick_check;"  # deve responder "ok" (demora alguns minutos)
claude mcp add cvm-research -s user -- "$(pwd)/.venv/bin/python" "$(pwd)/scripts/mcp/cvm_mcp.py"
claude mcp list                                # cvm-research: ✓ Connected
```

Se a pasta for **movida** dentro da mesma máquina, os mesmos passos valem: recriar a `.venv`, registrar o MCP de novo (`claude mcp remove cvm-research -s user` antes) e reinstalar o job semanal com `bash scripts/install_weekly_launchd.sh`, pois todos gravam o caminho absoluto.

---

## MCP

O servidor é `scripts/mcp/cvm_mcp.py` (Python, stdio, somente leitura). O Claude sobe o processo sob demanda; nada fica rodando em background. Ferramentas: `query(sql)`, `list_tables()`, `describe_table(nome)`.

### Claude Code (terminal)

```bash
claude mcp add cvm-research -s user -- "$(pwd)/.venv/bin/python" "$(pwd)/scripts/mcp/cvm_mcp.py"
claude mcp list        # cvm-research: ✓ Connected
```

### Claude desktop app

Edite `~/Library/Application Support/Claude/claude_desktop_config.json` com caminhos absolutos (`pwd` na raiz do projeto):

```json
{
  "mcpServers": {
    "cvm-research": {
      "command": "/caminho/absoluto/cvm-research/.venv/bin/python",
      "args": ["/caminho/absoluto/cvm-research/scripts/mcp/cvm_mcp.py"]
    }
  }
}
```

Reinicie o app após salvar.

### Modo HTTP (opcional)

Para clientes que só falam streamable-http: `.venv/bin/python scripts/mcp/cvm_mcp.py --http --port 8765` e configure `{"type": "http", "url": "http://localhost:8765/mcp"}`. Nesse modo o processo precisa estar rodando; prefira stdio.

### Verificar

Pergunte ao Claude: *"Quantas linhas tem a tabela ipe_docs?"* — deve responder um número acima de 160.000.

---

## Atualizar os dados

A CVM publica os ZIPs atualizados toda **segunda-feira entre 8h00 e 8h30**.

```bash
bash scripts/update_weekly.sh                       # manual, tudo de uma vez
bash scripts/install_weekly_launchd.sh --run-now    # agenda no launchd (segunda 9h) e roda agora
bash scripts/install_weekly_launchd.sh --status     # estado e último log
```

Notas explicativas (PDF completo do ITR/DFP) não entram no semanal; ingira sob demanda:

```bash
cd scripts/ingest && source ../../.venv/bin/activate
python ingest_notas_explicativas.py --cnpj <CNPJ> --ano 2026 --fonte ITR
```

---

## Expandir cobertura de empresas

O `watchlist.csv` controla quais empresas são cobertas.

```bash
cd scripts/ingest && source ../../.venv/bin/activate

python catalog.py                          # catálogo B3+CVM (~443 empresas ativas)
python catalog.py --search "petrobras"     # buscar uma empresa
python add_companies.py --ibov --dry-run   # preview
python add_companies.py --ibov             # confirmar com "s"
python add_companies.py --ticker VALE3     # uma empresa

python ingest_companies.py                 # watchlist → tabela companies

# Re-ingerir histórico para as novas empresas
python ingest_ipe.py --desde 2015
python ingest_dfp.py --historico --desde 2010
python ingest_itr.py --desde 2011
python ingest_vlmo.py --desde 2018
python ingest_fre.py --desde 2010
```

**Tickers assumidos:** empresas fora do IBOV recebem ticker `XXXX3` (ON inferido) e a coluna `observacao` do watchlist fica com `auto:assumed`. Confira e corrija antes de rodar os ingestores.

---

## Troubleshooting

| Sintoma | Causa | Solução |
|---|---|---|
| `cvm-research: ✗ Failed to connect` | Caminho da `.venv` ou do script mudou, ou `mcp` não instalado na venv | `claude mcp remove cvm-research -s user` e registrar de novo; `.venv/bin/pip install -r requirements.txt` |
| `ERRO: banco não encontrado` no log do MCP | `cvm_research.db` não está na raiz do projeto | `bash setup.sh` ou copiar o banco; ou exportar `CVM_DB_PATH` |
| `launchd.err.log`: `Operation not permitted` | Projeto em `~/Documents`, `~/Desktop` ou `~/Downloads` (pasta protegida pelo TCC) | Ajustes do Sistema → Privacidade e Segurança → Acesso Total ao Disco → adicionar `/bin/bash`; ou mover o projeto para fora dessas pastas e reinstalar o job |
| `pip`/`python` da venv apontam para outra pasta | Venv copiada de outro local | `rm -rf .venv && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt` |
| `KeyError: 'DATABASE_URL'` | `.env` não existe | `echo 'DATABASE_URL=sqlite:///cvm_research.db' > .env` |
| Banco mostra dados antigos | Update semanal não rodou | `bash scripts/update_weekly.sh` e conferir `logs/update_*.log` |
| `database is locked` | Ingestor rodando ao mesmo tempo | Esperar o `update_weekly.sh` terminar (lock em `logs/.update_weekly.lock`) |
| `unable to open database file` | Banco em pasta sincronizada com WAL ativo | Mover o projeto para fora do OneDrive/iCloud |

---

## Exemplos de pesquisa

- *"Quais foram as deliberações da última AGO da WEG?"*
- *"Houve insider trading na Embraer nos 7 dias antes do último fato relevante?"*
- *"Compare a margem EBIT de WEGE3 e VALE3 de 2020 a 2024"*
- *"Quais programas de recompra estão em andamento hoje?"*
- *"Mostre a evolução da dívida líquida da Petrobras desde 2015"*

O `CLAUDE.md` documenta o schema completo, queries de exemplo e o comportamento esperado para cada tipo de pesquisa.
