# CVM Research — Guia de Instalação

Do clone ao primeiro `SELECT` rodando no Claude: **menos de 5 minutos de trabalho seu**, o restante o Claude Code faz.

---

## Pré-requisitos

| Ferramenta | Verificar | Instalar se não tiver |
|---|---|---|
| Python 3.10+ | `python3 --version` | [python.org](https://www.python.org/downloads/) |
| Claude Code CLI | `claude --version` | `npm install -g @anthropic-ai/claude-code` |
| Node.js 18+ (npx) | `node --version` | [nodejs.org](https://nodejs.org) |

SQLite vem pré-instalado no macOS — nenhuma instalação necessária.

---

## Instalação em 30 segundos

Clone o repositório e abra o Claude Code na pasta:

```bash
git clone https://github.com/lbarretos/cvm-research.git
cd cvm-research
claude
```

Dentro do Claude Code, cole o seguinte prompt:

```
Configure este projeto do zero para mim:

1. Crie o banco SQLite executando `bash setup.sh`
2. Crie o venv Python e instale dependências: `python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt`
3. Crie o arquivo `.env` com: `DATABASE_URL=sqlite:///cvm_research.db`
4. Instale o MCP Python SDK no Python do sistema: `pip3 install "mcp[cli]"`
5. Configure o MCP HTTP no ~/.claude.json apontando para http://localhost:8765/mcp:
   claude mcp remove postgres-local 2>/dev/null || true
   claude mcp add postgres-local -s user --transport http http://localhost:8765/mcp
6. Configure o LaunchAgent para iniciar o servidor MCP automaticamente no login:
   - Crie ~/Library/LaunchAgents/com.cvm-research.mcp.plist apontando para scripts/mcp/cvm_mcp.py na porta 8765
   - Execute: launchctl load ~/Library/LaunchAgents/com.cvm-research.mcp.plist
7. Verifique se o servidor MCP subiu: curl -s http://localhost:8765/mcp
8. Popule o banco com os dados da CVM (pode levar 30-40 minutos):
   cd scripts/ingest && source ../../.venv/bin/activate
   python ingest_companies.py
   python ingest_ipe.py
   python ingest_vlmo.py
   python ingest_recompra.py
   python ingest_fre.py
   python ingest_dfp.py --historico
   python ingest_itr.py --desde 2016
9. Verifique a carga: sqlite3 ../../cvm_research.db "SELECT COUNT(*) FROM ipe_docs;"
   (esperado: ~35.000+ documentos)

Me avise quando cada etapa terminar e se precisar de alguma correção.
```

O Claude Code vai executar tudo e te avisando o progresso. Quando terminar, você pode fechar e reabrir o Claude — o banco estará disponível via MCP em qualquer sessão.

---

## O que foi instalado

Após o setup você terá:

```
cvm-research/
├── cvm_research.db           # ~830 MB — banco SQLite com todos os dados
├── .venv/                    # ambiente Python isolado
├── .env                      # DATABASE_URL configurado
├── logs/cvm_mcp.log          # log do servidor MCP
└── scripts/mcp/cvm_mcp.py   # servidor MCP HTTP (porta 8765)

~/Library/LaunchAgents/
└── com.cvm-research.mcp.plist  # auto-inicia o MCP no login do Mac
```

E no Claude, o MCP `postgres-local` conectado via HTTP:
```bash
claude mcp list
# postgres-local: http://localhost:8765/mcp — ✓ Connected
```

---

## Verificar que tudo funciona

Abra uma nova sessão do Claude Code e pergunte:

> *"Quantas linhas tem a tabela ipe_docs?"*

Se responder com ~35.000, o MCP está funcionando. Se não responder, veja a seção [Troubleshooting do MCP](#troubleshooting-do-mcp) abaixo.

---

## Ajustar o universo de cobertura

Por padrão o projeto cobre 54 empresas definidas em `watchlist.csv`. Para adicionar ou remover empresas:

### Adicionar uma empresa

Você precisa do CNPJ, ticker, código CVM e nome exato conforme aparece no portal RAD da CVM.

**Encontrar o código CVM:**
1. Acesse [rad.cvm.gov.br](https://www.rad.cvm.gov.br/ENET/frmConsultaExternaCVM.aspx)
2. Pesquise pelo nome da empresa
3. O número no campo "Código CVM" é o `codigo_cvm`

**Editar a watchlist:**
```bash
# Abrir o arquivo
open watchlist.csv   # ou editar no seu editor preferido
```

Adicione uma linha no formato:
```
TICK3,XX.XXX.XXX/0001-XX,NNNNN,NOME DA EMPRESA SA,Setor,ATIVO,
```

**Re-ingerir após mudanças na watchlist:**
```bash
source .venv/bin/activate
cd scripts/ingest
python ingest_companies.py    # atualiza a tabela companies (~5s)
python ingest_ipe.py          # baixa documentos da(s) nova(s) empresa(s) (~5 min)
python ingest_vlmo.py         # insider trading
python ingest_recompra.py     # programas de recompra
python ingest_fre.py          # capital, acionistas, remuneração
```

> **Dica:** Ao adicionar uma empresa mid-year, os dados históricos (DFP/ITR antes de 2024) não são baixados automaticamente. Para carga histórica completa: `python ingest_dfp.py --historico && python ingest_itr.py --desde 2016`.

### Remover uma empresa

Altere `status_cvm` para `INATIVO` na watchlist — isso faz o `ingest_companies.py` manter o registro mas impede novos downloads. Para remover completamente:

```sql
-- Executar diretamente no banco (não há cascade automático)
DELETE FROM companies WHERE ticker = 'TICK3';
DELETE FROM ipe_docs WHERE cnpj_companhia = 'XX.XXX.XXX/0001-XX';
-- ... mesma lógica para as demais tabelas
```

### Setores disponíveis

`Mobilidade`, `Infraestrutura`, `Transporte`, `Industrial`, `Educacao`, `Aviacao`, `Agro`, `Saude`, `Turismo`, `Energia`. O campo é livre — use o que fizer sentido para sua cobertura.

---

## Atualizar os dados

A CVM atualiza os arquivos fonte toda segunda-feira entre 8h00 e 8h30.

```bash
source .venv/bin/activate
cd scripts/ingest

# Roda toda semana após segunda-feira 8h30
python ingest_ipe.py
python ingest_vlmo.py
python ingest_recompra.py
python ingest_fre.py
python ingest_dfp.py
python ingest_itr.py
```

Para reprocessar a série histórica completa (use trimestral ou após mudanças na watchlist):
```bash
python ingest_dfp.py --historico
python ingest_itr.py --desde 2016
```

---

## Arquitetura do MCP

### Como funciona no dia a dia

O MCP funciona através de um pequeno servidor Python (`cvm_mcp.py`) que fica rodando em background na sua máquina. Ele abre uma conexão com o banco SQLite local e expõe as queries via HTTP na porta 8765.

**Você não precisa gerenciar nada manualmente.** O LaunchAgent configurado no setup inicia o servidor automaticamente toda vez que você ligar o computador ou fizer login — igual a outros serviços de background do Mac (Dropbox, 1Password, etc.). O servidor fica ativo silenciosamente até você desligar o Mac.

Fluxo no boot:
```
Mac liga → login → LaunchAgent inicia cvm_mcp.py → servidor disponível em localhost:8765
                                                           ↓
                                          Claude se conecta quando você abre uma sessão
```

Para confirmar que está rodando:
```bash
curl http://localhost:8765/mcp    # responde = OK
# ou
pgrep -f cvm_mcp.py               # mostra o PID do processo
```

---

### Por que um servidor HTTP e não `mcp-server-sqlite` direto?

A abordagem mais simples seria usar o pacote npm `mcp-server-sqlite` diretamente, como stdio MCP:

```bash
# Abordagem simples — funciona no Claude Code CLI, mas não no Claude.app
claude mcp add postgres-local -s user -- npx -y mcp-server-sqlite --db ./cvm_research.db
```

Isso funciona no **Claude Code CLI** (terminal). Mas **não funciona no Claude.app** (interface visual) por um motivo específico: o app lança processos MCP através de um wrapper de sandbox chamado `disclaimer` (`/Applications/Claude.app/Contents/Helpers/disclaimer`). Esse sandbox restringe o acesso ao sistema de arquivos dos subprocessos, impedindo que o `mcp-server-sqlite` abra o arquivo `.db`.

O sintoma é sutil: o MCP aparece como `✓ Connected`, mas qualquer query retorna `"no such table"` — o servidor conecta, mas abre um banco vazio em memória em vez do arquivo real.

### A solução: servidor HTTP fora do sandbox

O `scripts/mcp/cvm_mcp.py` é um servidor Python que roda **como processo independente**, fora do `disclaimer`. O Claude se conecta a ele via HTTP (`http://localhost:8765/mcp`) em vez de stdio. Como o processo não é filho do Claude.app, não sofre a restrição do sandbox.

```
Claude.app
    │
    │  HTTP (localhost:8765)
    ▼
cvm_mcp.py  ──── sqlite3 ──── cvm_research.db
(processo independente, sem sandbox)
```

O LaunchAgent (`~/Library/LaunchAgents/com.cvm-research.mcp.plist`) garante que o servidor inicia automaticamente no login — você nunca precisa lembrar de iniciá-lo manualmente.

### Reiniciar o servidor MCP manualmente

```bash
# Matar e reiniciar
bash scripts/mcp/start_mcp.sh

# Ver logs
tail -f logs/cvm_mcp.log

# Verificar se está rodando
curl -s http://localhost:8765/mcp | head -1
```

### Atualizar o banco que o MCP usa

O servidor lê o banco ao receber cada query (sem cache em memória). Após rodar os ingestores, as novas linhas já aparecem automaticamente — não precisa reiniciar o servidor.

Se você mover o banco para outro caminho:
```bash
# Editar o plist ou usar a variável de ambiente
CVM_DB_PATH=/novo/caminho/cvm_research.db bash scripts/mcp/start_mcp.sh
```

---

## Troubleshooting do MCP

### "postgres-local: Connection failed" no `claude mcp list`

O servidor Python não está rodando. Inicie:
```bash
bash scripts/mcp/start_mcp.sh
# Deve imprimir: CVM MCP Server rodando em http://127.0.0.1:8765/mcp
```

Se o LaunchAgent não subiu no login:
```bash
launchctl load ~/Library/LaunchAgents/com.cvm-research.mcp.plist
```

### MCP conecta mas Claude não enxerga as tabelas (`"no such table"`)

Você pode estar usando a configuração stdio antiga com `mcp-server-sqlite`. Verifique:
```bash
claude mcp list
# Se mostrar: npx -y mcp-server-sqlite ...
# É o problema do sandbox. Reconfigure para HTTP:
claude mcp remove postgres-local
claude mcp add postgres-local -s user --transport http http://localhost:8765/mcp
```

### `mcp-server-sqlite` abre banco vazio no Claude.app

Este é o problema do sandbox descrito na seção de Arquitetura. A solução completa é usar o servidor HTTP. Se você vir `"no such table"` com `schema://database` retornando `"No tables found in database"`, confirme que:

1. O servidor Python está rodando: `curl http://localhost:8765/mcp`
2. O `~/.claude.json` aponta para HTTP, não stdio:
```bash
python3 -c "
import json
with open('${HOME}/.claude.json') as f: d = json.load(f)
print(d['mcpServers']['postgres-local'])
"
# Deve mostrar: {'type': 'http', 'url': 'http://localhost:8765/mcp'}
```

### Porta 8765 já em uso

```bash
lsof -i :8765          # ver o que está usando
kill <PID>             # matar
bash scripts/mcp/start_mcp.sh  # reiniciar
```

Ou use outra porta:
```bash
# Editar o plist e trocar 8765 por outra porta
# Atualizar ~/.claude.json para a nova porta
```

---

## Problemas conhecidos

| Sintoma | Causa | Solução |
|---|---|---|
| `mcp-server-sqlite` abre banco vazio | Sandbox do `disclaimer` no Claude.app | Usar servidor HTTP (`cvm_mcp.py`) |
| `unable to open database file` | MCP sem permissão ao CloudStorage/OneDrive | Mover banco para fora do OneDrive ou usar HTTP MCP |
| `extract_pdf.py` falha | Requer Supabase (não migrado para SQLite) | Definir `SUPABASE_URL`/`SUPABASE_KEY` no `.env` |
| Banco mostra dados antigos | Ingestores não rodaram após segunda-feira | Rodar scripts de ingestão manualmente |
| `KeyError: 'DATABASE_URL'` | `.env` não existe | `echo 'DATABASE_URL=sqlite:///cvm_research.db' > .env` |

---

## Próximos passos

Com o banco e o MCP funcionando, abra o Claude e comece a pesquisar:

- *"Quais foram as deliberações da última AGO da WEG?"*
- *"Houve insider trading na Embraer nos 7 dias antes do último fato relevante?"*
- *"Compare a margem EBIT de WEGE3 e EMBR3 de 2020 a 2024"*
- *"Quais programas de recompra estão em andamento hoje?"*

O arquivo `CLAUDE.md` documenta o schema completo, queries de exemplo e o comportamento esperado para cada tipo de pesquisa.
