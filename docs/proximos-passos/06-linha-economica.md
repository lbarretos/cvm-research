# Etapa 6: Linha econômica por empresa (camada L1)

## Avaliação atual

As contas criadas pela empresa (`N`) são 27,8% das linhas do plano padrão, e o código delas não é
confiável entre filings.

**ITR do 3T × DFP do mesmo ano** (Jaccard de código | nome):

| | Todas as linhas | Linhas N | Mesmo código N com nome diferente |
|---|---|---|---|
| BPA | 0,971 | 0,882 | 0% |
| BPP | 0,981 | 0,846 | 0% |
| DRE | 0,938 | 0,762 | 0% |
| **DFC** | **0,385** | **0,283** | **52,5%** |
| DVA | 0,957 | 0,333 | 16,7% |

**DFP(Y) × DFP(Y−1)** (Jaccard mediano das linhas N): BPA 0,947, BPP 0,923, **DFC 0,843** (0,67 em 2011;
0,91 em 2025), DRE e DVA 1,0. Na DFC, 69% dos filings reusam ao menos um código N do ano anterior para
outra linha.

O casamento por nome **já existe** (`check_text_stability.match_filings`, escada estável → renumerado →
reformulação → ambíguo, com trava de polaridade). Mas é calculado na hora pelo visualizador (`encadear`)
e para cada par pela Camada 6. O LLM não tem acesso a ele: uma consulta por `cd_conta` que junte ITR e DFP
na DFC erra em metade dos casos.

## Proposta

| # | Ação |
|---|---|
| 6.1 | Tabela `linha_empresa(cnpj, tipo_doc, linha_id, fonte, data_referencia, cd_conta, casamento, score)`, gravada pelo tratamento com o mesmo `encadear` do visualizador. Isso inclui reatar pelo par (código, nome) depois de buraco na série, e **não** encadear par `ambiguo` |
| 6.2 | `linha_id` estável entre execuções (hash de cnpj + tipo_doc + primeira aparição), para as decisões humanas da fila `par_ambiguo` ficarem presas a ele |
| 6.3 | Tabela de decisões `linha_decisao(cnpj, tipo_doc, cd_a, data_a, cd_b, data_b, decisao, autor, em)`, lida pelo encadeamento. Resolve o item do `TODOS.md` sobre a fila `par_ambiguo` |
| 6.4 | O visualizador passa a ler `linha_empresa` em vez de calcular |

## Stress test

Script: [`stress/st6_linha_economica.py`](stress/st6_linha_economica.py). Roda o `match_filings` na base
inteira (plano padrão, 140 empresas) para três tipos de par: ITR 3T → DFP, DFP(Y−1) → DFP(Y) e a sequência
completa ITR/DFP de cada empresa. Nesse último caso também conta quantas linhas econômicas cada empresa
acumula.

**Classificação das linhas N:**

| | Par | Linhas N | estável | renumerado | reformulação | ambíguo | sem par |
|---|---|---|---|---|---|---|---|
| DFC | ITR 3T → DFP | 75.171 | 45,7% | 19,1% | 16,1% | 4,4% | 14,7% |
| DFC | DFP → DFP | 75.219 | 80,5% | 4,8% | 4,9% | 2,0% | 7,9% |
| DFC | sequência | 291.245 | 58,5% | 15,2% | 12,6% | 3,4% | 10,2% |
| DRE | ITR 3T → DFP | 17.813 | 77,8% | 3,3% | 5,1% | 1,3% | 12,6% |
| DRE | sequência | 72.991 | 82,7% | 2,6% | 3,9% | 0,9% | 10,0% |
| BPP | ITR 3T → DFP | 26.925 | 82,7% | 3,5% | 3,2% | 1,1% | 9,5% |
| BPP | sequência | 108.959 | 89,9% | 2,2% | 2,0% | 0,6% | 5,4% |

**Fragmentação** (linhas econômicas acumuladas no histórico ÷ linhas de um filing médio; 1,0 = série
perfeita):

| | p50 | p90 | máx. |
|---|---|---|---|
| BPP | 1,8 | 2,2 | 3,2 |
| DRE | 2,0 | 4,1 | 13,8 |
| **DFC** | **6,0** | **10,5** | **15,0** |

**Custo:** a base inteira em 38 s (DFC), 2 s (DRE) e 6 s (BPP). Cabe no tratamento semanal sem
esforço.

**Leitura do resultado:**
- Na DFC, um terço das linhas entre ITR e DFP só casa **pelo nome** (35,2%). A persistência resolve o erro
  de juntar por código.
- Mas a DFC **fragmenta**: uma empresa típica acumula 6 vezes mais linhas econômicas do que um filing tem.
  Pesam os 10% de "sem par" na sequência (linhas que de fato nascem e morrem, como uma captação pontual ou
  uma aquisição) e a regra conservadora de não encadear `ambiguo`. Uma série longa da DFC por linha
  econômica ainda fica cheia de buracos.
- Em DRE e BPP a fragmentação é baixa (~2): a linha econômica resolve quase tudo.

**Veredito: aprovada para DRE, BPA e BPP; insuficiente sozinha na DFC.** Na DFC, a série comparável no
tempo e entre empresas vem do **conceito** (Etapa 7), que agrega várias linhas econômicas ("Captação BNDES",
"Captação debêntures 5ª emissão" → `capt_divida`). A L1 continua útil na DFC como trilha de auditoria (qual
linha virou qual) e como unidade de rotulagem da Etapa 7: rotular uma linha econômica rotula todos os
filings dela.

**Ajuste que o teste sugeriu:** reatar linhas também pelo nome normalizado com o mesmo pai (não só pelo
par código + nome, como faz o `encadear` hoje) quando a linha some por um ou mais filings e volta. Falta
medir quanto isso reduz o 6,0.

## Critério de pronto

- `linha_empresa` gravada na base inteira em menos de 2 minutos.
- O visualizador mostra o mesmo resultado lendo da tabela e calculando na hora (teste de equivalência).
- Fragmentação da DRE com p90 abaixo de 3.

## Resultado (2026-10-15)

**Entrou** (`scripts/analysis/linha_economica.py`; migração `2026-10-15_linha_economica.sql`; roda no `update_weekly.sh`
depois da Camada 6 e no `bootstrap.sh`):
- **6.1** `linha_empresa`: 2,2 mi de linhas na base inteira (623 mil N e 1,6 mi S). Uma sequência por (empresa, tipo_doc) com
  ITR e DFP em ordem de data, ligada pela escada da Camada 5. Par `ambiguo` **não** encadeia: abre linha nova com o
  candidato em `cd_conta_anterior` e `casamento = 'ambiguo'` (a fila de revisão: 3,9 mil linhas).
- **6.2** `linha_id`: hash de (cnpj, tipo_doc, fonte, data e código da primeira aparição); estável quando chega filing novo
  (teste).
- **6.3** `linha_decisao` e a CLI `--listar-ambiguos` / `--decidir` (`mesma` liga, `diferente` bloqueia, inclusive no
  reatamento por nome). Resolve o item da fila `par_ambiguo` do `TODOS.md` para o encadeamento da linha econômica; a
  fila da Camada 6 (`demonstrativos_trimestrais`) segue lendo só o que ela mesma calcula.
- **Ajuste do stress test**: reatar pelo (pai, nome normalizado) depois de um buraco. Mediu-se em
  `stress/st6_fragmentacao.py`.
- O visualizador passou a importar o mesmo `encadear` (uma só implementação).

**Critérios de pronto:**

| Critério | Resultado |
|---|---|
| `linha_empresa` na base inteira em menos de 2 min | **84 s** |
| Fragmentação da DRE com p90 abaixo de 3 | **2,9** (era 3,0 sem o reatamento por pai) |
| Visualizador lê da tabela, com teste de equivalência | **Não feito** (ver abaixo) |

**Fragmentação das linhas N** (p50 / p90 / máx.), sem e com o reatamento por pai:

| | sem | com |
|---|---|---|
| DRE | 1,8 / 3,0 / 6,5 | 1,7 / 2,9 / 5,9 |
| BPP | 2,3 / 3,8 / 7,1 | 2,3 / 3,5 / 6,9 |
| DFC | 2,9 / 4,4 / 7,7 | 2,6 / 3,8 / 6,5 |

O 6,0 que o stress test deu para a DFC era do `encadear` como estava; com o reatamento por (código, nome) que ele já
tinha mais o por pai, a mediana é 2,6. A DFC continua a mais fragmentada, e o veredito dela (precisa do conceito da
Etapa 7 para uma série comparável) não muda.

**6.4 (visualizador lendo a tabela) ficou de fora, de propósito.** A tabela encadeia ITR e DFP juntos (é o que o LLM precisa:
o par ITR 3T → DFP da DFC); o visualizador encadeia cada fonte à parte. Trocar a fonte do visualizador muda as linhas que
ele mostra, então a "equivalência" pedida no critério não existe sem decidir qual das duas está certa. Dividem agora só o
código do `encadear`.

**Veredito: implementada; critério do visualizador não cumprido (6.4 adiada).**

### 6.4 feita (2026-10-30): o visualizador lê `linha_empresa`

A decisão adiada foi medida. Em 40 empresas sorteadas (DRE, BPP e DFC; ITR e DFP; todos os filings: 385 mil células,
363 mil ligações entre células consecutivas), as duas partições quase coincidem: o visualizador liga e a tabela separa
em 855 ligações (0,24%), e o contrário em 970 (0,27%). As discordâncias, numa amostra de 24, são defensáveis dos dois
lados: a tabela religa renumerações que o visualizador perde ("Dividendos pagos" 6.03.09 → 6.03.12, "IR pago" 6.01.03.03 →
6.01.03.10), porque encadeia passando pelos ITRs e reata depois de buraco; o visualizador liga mesmo código com nome quase
igual que a tabela separa, quando o DFP no meio muda o layout ("Pagamentos de Arrendamentos Mercantil" → "Pagamentos de
Arrendamentos"), e às vezes liga o que não é a mesma coisa ("Juros pagos debêntures" → "… e empréstimos").

Com qualidade equivalente, vence a fonte única: as visões ITR e DFP agrupam as células pelo `linha_id` da tabela, que é o
que o MCP e o LLM usam e que respeita `linha_decisao`. Célula sem `linha_id` vira linha própria; empresa ausente da tabela
(banco anterior à Etapa 6) cai no encadeamento na hora (`encadeamento: "calculado"` na API). A série trimestral continua
com os vínculos da Camada 6. Testes em `tests/test_viewer.py`: a tela equivale ao `linha_id`, a decisão "diferente" separa
a linha na tela, e o fallback. Na Multiplan (ITR, DFC), dividendos 6.03.08 → 6.03.09 → 6.03.06 numa linha só.

**Critério do visualizador: cumprido.**

### Camada 6 lê `linha_decisao` (2026-10-30)

A decisão do analista agora vale também em `demonstrativos_trimestrais`: 'mesma' casa o par (inclusive o ambíguo, que
antes ficava sem valor) e deriva o trimestre com `casamento = 'decisao'`; 'diferente' desfaz o casamento automático. Os
pares que a Camada 6 subtrai (1T → 2T, 3T → DFP) são filings consecutivos na ordem da `linha_empresa`, então a mesma
chave serve. Migração `2026-10-30_trimestrais_decisao.sql` (o CHECK de `casamento` ganha 'decisao'; a tabela é
regerada). Na base real, sem decisões gravadas, a tabela regerada é idêntica à anterior (1,8 mi de linhas, 2 min 53 s).
