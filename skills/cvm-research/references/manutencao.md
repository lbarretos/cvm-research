# Manutenção da base

Todos os comandos rodam na raiz do projeto `/Users/lucasbarreto/Documents/Coding/cvm-research`
com o Python do venv (`.venv/bin/python`). O MCP é só leitura; carga e extração são por Bash.
Peça confirmação antes de qualquer comando que baixe dados: são ZIPs anuais inteiros da CVM.

## Empresa que não está na base (onboarding)

1. Confirme que é companhia aberta e ache o ticker:
   ```bash
   cd scripts/ingest && ../../.venv/bin/python catalog.py --search "sabesp"
   ```
   Se não aparecer no catálogo, não é companhia listada na B3 (ou o catálogo está velho:
   `catalog.py` sem argumentos o regenera). Para empresa aberta sem ação listada, a busca manual
   é no RAD: `https://www.rad.cvm.gov.br/ENET/frmConsultaExternaCVM.aspx`.

2. Adicione e carregue. Caminho curto, que também roda o tratamento:
   ```bash
   bash bootstrap.sh --universo <arquivo_com_o_ticker.csv> --desde 2020 --dry-run   # mostre o plano
   bash bootstrap.sh --universo <arquivo_com_o_ticker.csv> --desde 2020 --sem-pdf
   ```
   O arquivo pode ter um ticker por linha. O universo soma ao `watchlist.csv`, nunca remove.
   Os ingestores reprocessam os ZIPs para todas as empresas do watchlist, então leva de 20 a 60
   minutos mesmo para uma empresa só.

   Passo a passo manual, se preferir:
   ```bash
   cd scripts/ingest
   ../../.venv/bin/python add_companies.py --ticker SBSP3
   ../../.venv/bin/python ingest_companies.py
   ../../.venv/bin/python ingest_ipe.py --desde 2020
   ../../.venv/bin/python ingest_vlmo.py --desde 2020
   ../../.venv/bin/python ingest_recompra.py
   ../../.venv/bin/python ingest_fre.py --desde 2020
   ../../.venv/bin/python ingest_dfp.py --historico --desde 2020
   ../../.venv/bin/python ingest_itr.py --desde 2020
   cd ../analysis && ../../.venv/bin/python run_all.py --layer 1,2,3,5,6 --cnpj "<CNPJ>"
   ```
   Sem o `run_all.py`, `demonstrativos_trimestrais` e `consistency_flags` ficam vazias para a
   empresa, e as consultas de trimestre e reapresentação voltam vazias sem erro.

3. Extraia o texto dos documentos que interessam (próxima seção) e retome a pesquisa.

## Extrair texto de PDFs do IPE

```bash
cd scripts/ingest
../../.venv/bin/python extract_pdf.py --cnpj "<CNPJ>" --categoria "Fato Relevante" --limite 100
../../.venv/bin/python extract_pdf.py --cnpj "<CNPJ>" --limite 200          # todas as categorias
../../.venv/bin/python extract_pdf.py --cnpj "<CNPJ>" --retry-failed        # tenta de novo as que falharam
../../.venv/bin/python extract_pdf.py --rebuild-fts                         # obrigatório no fim
```

O índice `ipe_docs_fts` é de conteúdo externo e não se atualiza sozinho: sem `--rebuild-fts`, o
texto novo existe em `ipe_docs.texto_extraido` mas a busca FTS não o encontra.

Sem `--categoria`, o extrator pega as categorias prioritárias: Fato Relevante, Assembleia,
Comunicado ao Mercado, Aviso aos Acionistas, Reunião da Administração e os Press-releases de
Dados Econômico-Financeiros. Para outras (DFs em PDF, laudos), passe `--categoria`; com ela,
`--tipo` restringe o tipo (ex.: `--categoria "Dados Econômico-Financeiros" --tipo "Press-release"`).
Não há filtro por `especie`: para ler só a Proposta e a Ata de uma AGO, use
`--categoria "Assembleia"` com `--limite` e aceite que virão boletins e mapas junto.

## Notas explicativas (sob demanda)

```bash
cd scripts/ingest
../../.venv/bin/python ingest_notas_explicativas.py --cnpj "<CNPJ>" --ano 2025 --fonte DFP
../../.venv/bin/python ingest_notas_explicativas.py --cnpj "<CNPJ>" --ano 2026 --fonte ITR --limite 20
```

Busca documento a documento no RAD (lento, sujeito a rate limit). Cada PDF tem dezenas de MB.

## Atualização semanal

A CVM publica os ZIPs do IPE às segundas, entre 8h e 8h30. O job `scripts/update_weekly.sh`
(launchd, segunda 9h; `bash scripts/install_weekly_launchd.sh --status` mostra o último log)
atualiza ano corrente e anterior de todas as fontes e roda as Camadas 1, 2, 3, 5 e 6. Para forçar:
`bash scripts/update_weekly.sh`. Logs em `logs/update_*.log`.

Para saber quão atual está a base:
```sql
SELECT MAX(data_entrega) FROM ipe_docs;
SELECT MAX(started_at) FROM consistency_runs;
```

O job roda às segundas 9h, no login e a cada 4 h enquanto não houver sucesso desde a última
segunda; espera a rede antes de baixar. Só grava `logs/.ultimo_sucesso` quando nenhuma etapa falha.
Se `MAX(data_entrega)` estiver mais de 9 dias atrás, algo impediu isso. Causas já vistas:
- **`database is locked`**: outro processo gravando no banco ao mesmo tempo (migração, reparo,
  `run_all.py` manual). Some sozinho na próxima tentativa.
- **Rede fora** por tempo maior que a espera do script.

Diagnóstico: `bash scripts/install_weekly_launchd.sh --status` (mostra o último sucesso) e o fim do
último `logs/update_*.log` ("Concluído" ou "Concluído com falhas (...)"). Informe o usuário e
ofereça rodar `bash scripts/update_weekly.sh`, sem disparar sozinho.

## Montar a base do zero

Quando o banco estiver vazio ou for um clone novo: `bootstrap.sh`. Pergunte ao usuário o
universo (`ibov`, `ibrx`, `todas` ou arquivo de tickers) e o período (`--desde ANO`), rode
`--dry-run` e mostre o plano antes. Detalhes no `CLAUDE.md` do projeto. A carga completa leva
horas (a extração de PDFs, de 6 a 24 h) e ocupa até ~12 GB.

A CVM não arquiva versões antigas: duas bases montadas em datas diferentes divergem nos períodos
reapresentados no intervalo. Ao comparar com outra instalação, cite a data da carga.
