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

Primeira `rf_fontes.py --verificar` no Mac:

| Fonte | Resultado | Ação |
|---|---|---|
| SND | 4.851 linhas; ISIN, CNPJ, vencimento, remuneração, espécie, agente ≥ 99% | volume e Lei 12.431 a 0%. O cabeçalho real não tem volume (agora quantidade emitida × VN na emissão) e a 12.431 é `Deb. Incent. (Lei 12.431)` (apelido acrescentado) |
| CVM 400/476 | 11.534 ofertas de dívida; sem código, ISIN nem devedor | casar por emissor + emissão + série |
| CVM Resolução 160 | 4.528; sem série nem remuneração; com descrição de garantias, lastro, devedores, rating | colunas novas em `rf_ofertas`; extração por regra (`fonte = 'cvm_oferta'`) |
| ANBIMA debêntures | 1.275 títulos/dia, taxa 94%, PU 97% | ok |
| ANBIMA CRI/CRA | 404 no caminho suposto | desligada até achar a URL |

Consequência: CRI/CRA só entram pela `rf_watchlist.csv` com securitizadora, emissão e série preenchidas à mão.

### Extração por regra em dois termos de securitização reais

O usuário mandou os termos da Virgo 204ª (CRA, devedora JBS, lastro em debêntures, 178 p.) e da Eco 243ª (CRA, devedora FS
Indústria de Biocombustíveis, lastro em CPR-F, 210 p.), da aba de documentos do data.anbima.com.br. A primeira versão da regra:

| Erro | Exemplo | Correção |
|---|---|---|
| endereço como nome | "CEP 05501-900", "Pinheiros" | nome = primeiro segmento com qualificação na cláusula, nunca CEP/rua/bairro |
| devedor e avalista não achados | “Devedora” significa a FS …, CNPJ … | padrão de definição (termo antes do CNPJ) e apelido designado depois (“Fiadora”) |
| partes e garantias de outros títulos | anexo "Histórico de Emissões do Agente Fiduciário" (~78% do texto) | corta o anexo depois de 30% do texto |
| garantias de definição genérica | “Ônus” significa qualquer hipoteca, penhor… | descarta enumeração de ≥ 3 tipos e definições de Ônus/Gravame |
| negação depois do termo | "Coobrigação da Emissora: Não há" | negação antes ou depois |
| garantia do lastro misturada com a do título | aval na CPR-F | `rf_garantias.escopo` (`titulo`/`lastro`) |
| ruído de página e CNPJ quebrado | "CNPJ/MF Página 15 de 341 DocuSign … sob o nº", "0001- 69" | limpeza antes de tudo |

Depois da correção, os trechos dos dois termos (`tests/fixtures/rf/termos_reais.py`) batem 100% com o gabarito (partes,
garantias com escopo, lastro). É um teste de 2 documentos e com os trechos que motivaram as regras: não mede precisão geral.
`stress/st8_extrai_rf.py` roda a extração em PDFs locais para medir em mais termos.

### Primeira carga real no Mac (2026-10-30, à noite)

Banco de produção (146 empresas): `rf_ativos` 4.851 DEB + 2 CRA, `rf_ofertas` 15.816, `rf_taxas` 8.877 linhas em 7 dias,
`rf_partes` 9.719 de cadastro, `rf_grupo` 913 elos; quatro passos do job semanal com saída 0.

| Achado | Efeito | Correção |
|---|---|---|
| `data_br('NaT')` devolvia a string `'NaT'` (o pandas não falha e `NaT.isoformat()` é `'NaT'`) | 13 mil datas `'NaT'` em `rf_ofertas`; a chave da oferta inclui a data, então a recarga duplicou 7.452 ofertas; `ingest_rf_docs` caía nos CRAs (`int('NaT')`) | `data_br`/`texto` tratam NaT; limpeza feita à mão neste banco (único com carga) |
| `devedor_nome` = a qualificação inteira ("JBS S.A., sociedade por ações, …, CEP …") | ficha do CRA ilegível | `nome_antes_do_cnpj`: do último rótulo ("Devedora:") até a vírgula/parêntese/travessão |
| escritura com assunto genérico ("Emissão de Valores Mobiliários") e número por extenso ("DÉCIMA SEXTA EMISSÃO") | escritura da Rumo 16ª não entrava | número por extenso em `_cita_numero`; a capa (1.500 caracteres) promove o documento |
| garantias tiradas de prospecto (relacionamento com os coordenadores), relatório do agente fiduciário e anúncios | RUMOB6, quirografária, com 22 "garantias" (fiança, aval, alienação…) | só escritura, aditamento e termo vão para a extração (`documento_de_emissao`); os outros ficam na busca |
| fichas de outras emissões do agente fiduciário no corpo da escritura (cláusula 8.2 da Ecorodovias) | ERDVB4 com alienação fiduciária e fiança da Holding do Araguaia | `_FICHA_TERCEIROS` tira cada ficha ("Valor Total da Emissão … Enquadramento"/"Inadimplementos no período") |
| "não implicam … qualquer hipoteca, penhor, … ou outro gravame" | penhor na RUMOB6 | `VEDACAO_GENERICA` |
| extração regravada não apagava a anterior | linhas velhas ficavam | apaga as linhas `pdf` do par documento × título antes |

Critério de pronto:
1. **OK**: SND, CVM e ANBIMA debêntures leem (campos-chave ≥ 94%; remuneração da CVM 400/476 14%, mas o SND cobre as
   debêntures). ANBIMA CRI/CRA segue sem fonte pública de arquivo.
2. **Parcial**: RUMOB6 e ERDVB4 com emissão, taxa (7 dias) e a escritura certa ligada. CRA024004SB (3ª série) e
   CRA02300796 (2ª série), séries e ISIN conferidos na página pública do data.anbima.com.br, aparecem com securitizadora,
   emissão e devedor (JBS pela Res. 160; FS sem devedor na CVM 400), **sem taxa e sem termo**: a Res. 160 não passa pelo
   IPE (o IPE da Virgo/Riza para em 2022) e a taxa só existe no data.anbima.com.br.
3. **OK nas duas debêntures**: garantia extraída = quirografária, igual ao SND e à capa; partes do PDF = Pentágono como
   agente fiduciário (emissora vem do cadastro). Antes das correções: 22 e 10 garantias falsas.
4. **OK**: `ingest_rf_cadastro`, `ingest_rf_taxas`, `ingest_rf_docs`, `rf_grupo` com saída 0.

Observações: o diretório público de taxas da ANBIMA guarda só ~6 dias úteis (10-01 a 10-13 dão 404), então a janela de 30
dias se forma semana a semana e uma semana sem job vira buraco. O grupo da Rumo mostra Julia Arduini (3,82%) como
controladora direta porque é o que o FRE 2026 da Rumo declara (Maglev FIP, 20%, vem como não controlador): fiel à fonte.

### Taxa e cadastro de CRI/CRA pelo dataset público da ANBIMA (2026-10-30)

A API do data.anbima.com.br (`data-api.prd.anbima.com.br/web-bff/…`) exige token (`401 token cannot be blank`): não foi
usada. A saída é o dataset público "CRIs e CRAs - Precificação ANBIMA" (Datasets), cujo download passa por um formulário
(nome, e-mail, aceite dos termos), feito pelo usuário. O arquivo é .xlsx com extensão .xls, 20 colunas, os últimos cinco
dias úteis do mercado inteiro (~330 títulos/dia). `ingest_rf_taxas.py --arquivo` grava as taxas e o cadastro.

Primeira carga: 1.283 taxas (CRA 895, CRI 388; 5 dias), 337 CRI/CRA novos em `rf_ativos`, CNPJ da securitizadora por nome
em 221 (o resto tem nome diferente na CVM). CRA024004SB: 9,5877% em 29/10, igual à página do título; CRA02300796 completo
(vencimento, IPCA + 8,9555%). Critério 2 passa a **OK para taxa e emissão**; o termo dos CRAs continua manual
(`ingest_rf_docs.py --arquivo`, PDF da aba Documentos), pois a Resolução 160 não passa pelo IPE.

Limites: o download é manual e semanal (sem URL fixa, não entra no job); semana sem download vira buraco na série de CRI/CRA.
