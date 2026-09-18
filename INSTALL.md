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

# Ver o plano antes de gastar horas
bash bootstrap.sh --universo ibov --substituir --desde 2020 --dry-run

# Popular o banco: brutos + camadas de consistência + texto dos PDFs
bash bootstrap.sh --universo ibov --substituir --desde 2020
```

Pelo Claude Code, a mesma coisa em português: *"Monte a base com o universo IBOV, documentos de
2020 para cá."* O [CLAUDE.md](CLAUDE.md) ensina o Claude a montar o comando, mostrar o plano
antes e acompanhar a execução.

### Os três blocos

`bootstrap.sh` é retomável: Ctrl-C e rodar de novo continua de onde parou.

| Bloco | O que roda | IBOV (~78) | Watchlist do repo (147) |
|---|---|---|---|
| Dados brutos | os sete ingestores | 20–40 min | 30–60 min, ~15 GB de ZIPs |
| **Tratamento** | `run_all.py --layer 1,2,3,5,6 --full` | ~4 min | ~8 min |
| Texto dos PDFs | `extract_pdf.py` em laço, depois reconstrói o índice FTS | 6–12 h | 12–24 h, ~170 mil docs |

O bloco de tratamento é o que preenche `demonstrativos_trimestrais`, `consistency_flags` e
`cd_conta_ds_timeline`. **Sem ele o banco responde os dados brutos e nada mais**: as consultas
trimestrais e de reapresentação do [CLAUDE.md](CLAUDE.md) voltam vazias, sem erro que explique
o porquê. Para adiar a parte longa, `--sem-pdf`; para retomá-la depois, `--so-pdf`.

### Cobertura

`--universo` aceita `ibov` (recomendado para começar, ~78 empresas), `ibrx`, `todas` (as ~443
ativas da B3) ou o caminho de um arquivo com a sua lista de tickers. A lista é a melhor opção
quando você já sabe o que quer acompanhar: menos download, menos disco e menos ruído.

```
ticker,empresa
PETR4,Petrobras
VALE3,Vale
WEGE3,WEG
```

CSV com coluna `ticker` (as outras colunas são ignoradas) ou um ticker por linha. `#` começa
comentário; ticker fora do catálogo da B3 é avisado e pulado sem interromper a carga.

O universo é **aditivo**: soma ao `watchlist.csv` e nunca remove. `--substituir` zera o
`watchlist.csv` antes, guardando uma cópia com data no nome. O repositório vem com 147 tickers,
que são o IBOV mais a cobertura própria do autor; use `--substituir` se quiser só o seu recorte.

Depois da carga, dá para crescer a qualquer momento: `bash bootstrap.sh --universo NOVO.csv`
adiciona as empresas e recarrega. Ou, manualmente, `add_companies.py` seguido de
`ingest_companies.py` e dos ingestores (ver a seção "Adicionar empresas" do [CLAUDE.md](CLAUDE.md)).

### Período

`--desde ANO` vale para todas as fontes. Cada uma tem um primeiro ano possível, e pedir antes
disso é ajustado para cima com aviso em vez de falhar:

| Fonte | Primeiro ano | Por quê |
|---|---|---|
| IPE | 2015 | os ZIPs de 2009–2014 vêm sem `Protocolo_Entrega` e são descartados |
| VLMO | 2018 | antes disso não há feed estruturado de insider trading |
| ITR | 2011 | início da série de ITR no portal de dados abertos |
| DFP, FRE | 2010 | início das séries |

Sem `--desde`, cada fonte vai até o início. Para controle por fonte, use as variáveis
`IPE_DESDE`, `VLMO_DESDE`, `FRE_DESDE`, `DFP_DESDE` e `ITR_DESDE`.

### Conferindo

`.venv/bin/python -m pytest tests/ -q`. A suíte inclui testes que leem o banco e recalculam o
tratamento a partir do dado bruto: conferem que cada valor trimestral é mesmo a subtração de
duas linhas equivalentes nos dois filings. Eles pulam sozinhos se o banco não existir, se as
camadas ainda não rodaram ou se a sua cobertura não tem as empresas da amostra.

> ⚠️ A CVM não arquiva versões anteriores dos documentos: cada base guarda a versão que estava
> no ZIP no dia do download. Duas instalações montadas em datas diferentes divergem nos períodos
> reapresentados no intervalo. Ao comparar números com outra máquina, cite a data da carga.

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
```

Depois de mexer no `watchlist.csv`, recarregue com o `bootstrap.sh` em vez de repetir os
ingestores à mão: ele cobre os sete, roda o tratamento e é retomável.

```bash
bash bootstrap.sh --sem-pdf     # brutos + tratamento para a cobertura nova
bash bootstrap.sh --so-pdf      # o texto dos PDFs depois, quando quiser
```

Os ingestores são idempotentes e reprocessam os ZIPs inteiros, então re-rodar para
as empresas novas também atualiza as antigas. Nada é perdido.

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
