# Demonstrações financeiras (DFP/ITR)

Conteúdo: tabelas e views, trimestres com 4T, reapresentações e as camadas de consistência, notas
explicativas.

## Qual tabela usar

| Pergunta | Fonte |
|---|---|
| Receita, EBIT, lucro de um período | `vw_dre` (trimestre isolado no ITR, ano no DFP) / `vw_dre_acumulada` |
| Ativo, caixa, dívida, PL | `vw_balanco` |
| Série trimestral, 4T, DFC ou DVA por trimestre | `demonstrativos_trimestrais` (Camada 6) |
| Conta que não está nas views | `demonstrativos_contabeis` filtrando `cd_conta` |
| "Esse número foi reapresentado?" | `consistency_flags` layer 2 (e 3) |
| A soma do quadro fecha? | `consistency_flags` layer 1 |
| Histórico de uma conta criada pela empresa | `cd_conta_ds_timeline` (Camada 5) |
| Dado que só existe em nota (imobilizado por classe, provisões…) | `notas_explicativas` |

Valores em R$ (já normalizados de milhar); lucro por ação (`3.99.*`) em R$/ação.

**Qual lucro.** "Lucro líquido" tem duas linhas: consolidado (`3.11`) e atribuído aos sócios da
controladora (`3.11.01`, o que entra no lucro por ação e é o número do release). Mostre o atribuído
como padrão e o consolidado quando os não controladores forem relevantes.

**Consolidado ou individual.** A base guarda o consolidado quando a empresa publica os dois.

### Bancos e seguradoras (outro plano de contas)

Os mesmos códigos significam outra coisa (no banco, 3.05 é o LAIR e o lucro é 3.09 ou 3.11,
conforme o layout). `vw_plano_contas` classifica cada filing (`'padrao'`/`'banco'`/`'seguradora'`)
pelo nome da conta 3.01, não por `companies.setor`. Fora do plano padrão, `vw_dre` devolve a linha
com os valores NULL e `plano_contas` dizendo o porquê.

- Banco (ITUB4, BBAS3, BBDC4, BPAC11): `vw_dre_financeiro` — `receita_intermediacao`,
  `despesa_intermediacao`, `resultado_bruto_intermediacao`, `lair`, `ir_cs`, `lucro_liquido`,
  `lucro_controladora`. A view já escolhe entre os dois layouts de banco.
- Seguradora (IRBR3, BBSE3): `vw_dre_seguradora`. A BBSE3 é holding (resultado na equivalência); a
  IRBR3 não abre `lucro_controladora` desde 2023: use `lucro_liquido`.
- Nenhuma das duas tem versão acumulada; para série com 4T use `demonstrativos_trimestrais`, que
  funciona em qualquer plano (escolha as contas pelo mapa da view correspondente).

"Receita" de banco não equivale a receita líquida: diga que usou a receita de intermediação (bruta).

## `demonstrativos_contabeis`

`cnpj_companhia, fonte ('DFP'/'ITR'), tipo_doc ('BPA'/'BPP'/'DRE'/'DFC_MI'/'DVA'), data_referencia,
versao, ordem_exercicio ('Último'/'Penúltimo'), dt_ini_exerc, dt_fim_exerc, cd_conta, ds_conta,
vl_conta, st_conta_fixa ('S' = conta padrão CVM, 'N' = criada pela empresa)`

- No ITR de 2T/3T a DRE vem duas vezes: trimestre isolado (`dt_ini_exerc` = início do trimestre)
  e acumulado (`dt_ini_exerc` = início do exercício). Filtre `dt_ini_exerc`, senão as linhas dobram.
- DFC_MI e DVA só vêm acumuladas no ITR. BPA/BPP têm `dt_ini_exerc` NULL.
- `ordem_exercicio = 'Último'` é o período do próprio filing; `'Penúltimo'` é a coluna comparativa,
  que já pode estar reapresentada.
- Guarda as versões **que estavam no ZIP da CVM no dia da carga**, que costuma ser só a mais
  recente (o DFP 2024 da Vale só tem a versão 3). Reentregas do mesmo filing (v1 → v3) não são
  comparáveis pela base, e a "safra original" pode já ser uma versão corrigida. Para o vigente,
  use `MAX(versao)`.

```sql
SELECT cd_conta, ds_conta, vl_conta
FROM demonstrativos_contabeis d
WHERE cnpj_companhia = '<CNPJ>' AND fonte = 'DFP' AND tipo_doc = 'DRE'
  AND data_referencia = '<AAAA-12-31>' AND ordem_exercicio = 'Último'
  AND versao = (SELECT MAX(versao) FROM demonstrativos_contabeis
                WHERE cnpj_companhia = d.cnpj_companhia AND fonte = 'DFP'
                  AND tipo_doc = 'DRE' AND data_referencia = d.data_referencia)
ORDER BY cd_conta;
```

**Antes de somar sublinhas** (abrir o ativo circulante, por exemplo), veja se o pai tem
`nao_detalhado` na Camada 1: a empresa publicou só o total e os filhos são zero.

## Série trimestral: `demonstrativos_trimestrais` (Camada 6)

Use `vl_final`. `safra = 'original'` é o que o mercado viu na época (colunas `Último`);
`'reapresentado'` vem das colunas `Penúltimo` do exercício seguinte. Não misture safras.

- DRE 1T–3T: `origem = 'publicado'` (linha trimestral do ITR). DRE 4T, DFC_MI e DVA: `origem =
  'derivado'` (acumulado menos acumulado anterior; 4T = DFP − 3T acumulado).
- `trimestre` é a posição no exercício social, não o trimestre-calendário.
- `3.99` (lucro por ação) não está na tabela: não é aditivo.
- `flag` diz quando desconfiar: `reapresentacao_intra_ano` (publicado ≠ derivado; mostre os dois),
  `par_ambiguo` (valor não calculado de propósito; candidato em `consistency_flags` layer 6),
  `linha_sem_par` / `sem_anterior` / `sem_3t` (buraco, valor NULL), `componente_reapresentado`.
- Em contas criadas pela empresa (`st_conta_fixa = 'N'`), `cd_conta_b` e `casamento` dizem qual
  linha do filing anterior entrou na subtração; cite ao apresentar o número.
- `flag = 'reclassificacao_entre_filings'`: o minuendo e o subtraendo foram publicados em layouts
  diferentes para aquela linha (Vale 4T24: `3.04.04` = −R$ 11,8 bi, impairment movido para
  `3.04.03` no DFP). O total do pai está certo; a sublinha não. Não apresente o valor como está:
  mostre o pai, ou use a safra `reapresentado`, que compara layouts iguais.

### "O 4T foi reapresentado?"

O 4T vem de dois filings (DFP e ITR 3T), então há dois lados a checar na Camada 2: o período anual
(`periodo_fim = 'AAAA-12-31'`) e o 9M (`periodo_fim = 'AAAA-09-30'`, `periodo_ini` no início do
exercício). Ausência de linha-resumo pode significar "bateu" ou "o par não foi comparado"; para
confirmar, compare a safra `original` com a `reapresentado` em `demonstrativos_trimestrais`.

```sql
SELECT exercicio_ini, trimestre, dt_fim_exerc,
       MAX(CASE WHEN cd_conta = '3.01' THEN vl_final END) AS receita,
       MAX(CASE WHEN cd_conta = '3.11' THEN vl_final END) AS lucro,
       GROUP_CONCAT(DISTINCT CASE WHEN cd_conta IN ('3.01','3.11') THEN flag END) AS flags
FROM demonstrativos_trimestrais
WHERE cnpj_companhia = '<CNPJ>' AND tipo_doc = 'DRE' AND safra = 'original'
GROUP BY 1, 2, 3 ORDER BY dt_fim_exerc DESC LIMIT 8;

-- FCO trimestral (a CVM só publica a DFC acumulada)
SELECT dt_fim_exerc, trimestre, vl_final, flag
FROM demonstrativos_trimestrais
WHERE cnpj_companhia = '<CNPJ>' AND tipo_doc = 'DFC_MI' AND cd_conta = '6.01' AND safra = 'original'
ORDER BY dt_fim_exerc DESC LIMIT 8;
```

## Reapresentações e consistência: `consistency_flags`

Metadados; nunca alteram o valor publicado. `cd_conta` NULL = resumo do par de filings.
`detalhe` é JSON (`json_extract`).

| Camada | `check_type` | Classificações |
|---|---|---|
| 1 | `hierarchy_sum` (dentro do documento) | `nao_detalhado` (info), `pai_vazio` (warn), `divergencia` / `divergencia_formula` (error) |
| 2 | `cross_period` (mesmo período em filings diferentes; baseline = o mais antigo) | `reapresentacao` (warn: total mudou), `reclassificacao` (info: total igual, sublinha mudou) |
| 3 | `granularity` (linha só num dos filings) | `renumerado`, `zero_padding`, `reclassificado_em_outros`, `reclassificado_em_irmao`, `divergencia_nao_explicada` |
| 5 | `text_stability` | `ambiguo` (fila de revisão de nomes parecidos) |
| 6 | desacúmulo trimestral | `reapresentacao_intra_ano`, `par_ambiguo`, `sem_dfp` |

```sql
-- Quais períodos foram reapresentados, e em qual filing
SELECT tipo_doc, periodo_fim, fonte_ref || ' ' || data_ref AS original,
       fonte_cmp || ' ' || data_cmp AS comparado, classificacao,
       json_extract(detalhe, '$.linhas_divergentes') AS linhas_divergentes
FROM consistency_flags
WHERE cnpj_companhia = '<CNPJ>' AND layer = 2 AND cd_conta IS NULL
ORDER BY periodo_fim DESC, data_cmp;

-- Linha a linha: original × reapresentado
SELECT cd_conta, ds_conta, valor_ref AS original, valor_cmp AS reapresentado,
       diff_abs, ROUND(diff_rel * 100, 2) AS diff_pct, classificacao
FROM consistency_flags
WHERE cnpj_companhia = '<CNPJ>' AND layer = 2 AND tipo_doc = 'DRE'
  AND periodo_fim = '<AAAA-12-31>' AND cd_conta IS NOT NULL
ORDER BY cd_conta;
```

Sem linhas para a empresa: a camada não rodou para ela (`run_all.py --layer 2 --cnpj <CNPJ>`).
Sem flags num período com filings pareados: os valores bateram dentro da tolerância
(`max(R$ 1.000, 1%)`).

Conta que "sumiu" entre dois filings: Camada 3. `renumerado` dá o código novo;
`reclassificado_*` diz para onde foi o valor; `divergencia_nao_explicada` pede olhar a Camada 2
do mesmo par.

## Trilha de contas: `cd_conta_ds_timeline` (Camada 5)

Uma linha por mudança entre filings consecutivos (`estavel` não é gravada): `primeira_ocorrencia`,
`renumerado` (mesmo nome, código novo; `cd_conta_anterior`), `reformulacao` (nome parecido),
`ambiguo`, `nova`, `removida`. Para montar série longa de uma conta `st_conta_fixa = 'N'`, siga
`cd_conta_anterior` em vez de fixar o código.

## Notas explicativas

`notas_explicativas`: PDF completo do ITR/DFP com notas, sob demanda, cobertura pequena. Antes
de consultar:

```sql
SELECT fonte, data_referencia, texto_extraido IS NOT NULL AS tem_texto
FROM notas_explicativas WHERE cnpj_companhia = '<CNPJ>' ORDER BY data_referencia DESC;
```

Busca: `notas_explicativas_fts` (mesmo padrão do `ipe_docs_fts`; junte por `n.id = f.rowid`).
Se o período não estiver lá, veja primeiro o PDF da DF em `ipe_docs` (`categoria = 'Dados
Econômico-Financeiros'`, `tipo` = `'Demonstrações Financeiras Intermediárias'` ou `'... Anuais
Completas'`), que costuma já ter texto. Só então ofereça ingerir (comando em `manutencao.md`).
Só a versão mais recente do documento é mantida.

## Visualizador

Para folhear um demonstrativo inteiro, ofereça o visualizador local
(`.venv/bin/python scripts/viewer/server.py` → `http://127.0.0.1:8765/?t=<TICKER>`), com ITR,
DFP e a série trimestral. Para pergunta pontual, a query é mais direta.
