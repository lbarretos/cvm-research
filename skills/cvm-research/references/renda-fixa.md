# Renda fixa: debêntures, CRI e CRA

Módulo da Etapa 8. Ferramentas do MCP: `resolve_bond`, `get_bond`, `search_bonds`, `search_bond_docs`, `read_bond_doc`.

## Fluxo

1. `resolve_bond('<código, ISIN, CNPJ ou nome>')` → código. Um CNPJ devolve tudo em que a empresa aparece
   (emissora, devedora, fiadora…).
2. `get_bond('<código>')` → ficha em seções. Leia o `aviso` antes de responder: ele diz quando o PDF não foi lido,
   quando falta taxa e quando o grupo não pôde ser calculado.
3. Para detalhe de cláusula (covenants, vencimento antecipado, cronograma de amortização, condições da garantia):
   `search_bond_docs('<termos>', codigo=...)` e `read_bond_doc(doc_id, offset)`.
4. Comparação entre títulos: `search_bonds(tipo, indexador, vence_de, vence_ate, incentivada, grupo_de, so_com_taxa)`.

## De onde vem cada dado

| Seção | Fonte | Confiável para |
|---|---|---|
| `emissao` | SND (`fonte = 'snd'`, debêntures) ou oferta da CVM (`cvm_oferta`, CRI/CRA) | datas, volume, remuneração, espécie (debênture), Lei 12.431 |
| `ofertas` | CVM dados abertos (ritos 400/476 e Resolução 160) | registro, rito, público-alvo, líder; na 160, descrição oficial de garantias, lastro e devedores, agência de rating |
| `partes` `fonte='cadastro'` | campo publicado (confianca 1) | emissor/securitizadora, devedor (se a CVM informa), agente fiduciário |
| `partes`/`garantias`/`lastro` `fonte='pdf'` ou `'cvm_oferta'` | regra sobre o texto da escritura/termo ou da descrição da oferta na CVM (confianca 0,6–0,8) | indicar o que o documento diz; **citar `evidencia`** |
| `taxas` | ANBIMA, mercado secundário, últimos ~30 dias | preço de referência (taxa indicativa, PU, % PU par, duration) |
| `grupo` | FRE das companhias da base (`rf_grupo`) | cadeia de controle até onde houver FRE |

## Limites do dado (diga ao usuário quando importar)

- **Garantia vazia não é "sem garantia".** As garantias vêm do PDF; se `documentos` está vazio, nada foi lido. O
  campo `especie_garantia` (SND) é a espécie legal da debênture (quirografária, real, flutuante, subordinada), não a
  lista de garantias adicionais. Só `tipo = 'sem_garantia'` com evidência afirma ausência.
- **Extração por regra, precisão medida só em dois termos reais.** Uma parte vem do CNPJ + termo definido
  (“Fiadora”, “Devedora”), na qualificação ou na lista de definições; um CNPJ sem termo definido não vira parte.
  Garantia vem por vocabulário, descartando menção negada ("não contará com…", "Coobrigação: Não há") e listas
  genéricas (definição de “Ônus”). Nos termos da Virgo 204ª e da Eco 243ª ela acerta partes, garantias e lastro;
  em outros documentos, confira o trecho antes de afirmar.
- **CRI/CRA: a garantia costuma ser do lastro, não do título.** `escopo = 'titulo'` é garantia do próprio CRA/CRI;
  `'lastro'` é do instrumento que paga (aval na CPR-F, fiança nas debêntures do lastro). Termo de CRA quase sempre
  diz "Não serão constituídas garantias específicas, reais ou pessoais, sobre os CRA" (`sem_garantia`, escopo
  `titulo`) e o risco fica no **devedor** e em quem garante o lastro. Responda separando os dois. A “Emissora” é a
  securitizadora, que não define grupo econômico e fica fora de `grupo`/`ativos_do_grupo`.
- **CRI/CRA dependem de um download manual.** A CVM não publica o código de negociação; cadastro e taxa de CRI/CRA
  vêm do dataset "CRIs e CRAs - Precificação ANBIMA" (data.anbima.com.br → Datasets, formulário), carregado com
  `python scripts/ingest/ingest_rf_taxas.py --arquivo <xls>` (`fonte = 'anbima'` em `rf_ativos`). Só entram os títulos
  com preço ANBIMA na semana do arquivo; os outros, só por `rf_watchlist.csv` com securitizadora e emissão. Se a taxa
  de um CRI/CRA estiver velha ou ausente, diga a data da última taxa e indique o download, sem inventar dados. **O termo
  de securitização não cita o código de negociação**, só o ISIN por série: sem a série na watchlist, o título fica
  ligado à emissão inteira (todas as séries), e vencimento/remuneração por série ficam em aberto.
- **Taxa indicativa ≠ negócio.** É a taxa de referência calculada pela ANBIMA; títulos sem liquidez podem não ser
  precificados (sem linha em `rf_taxas`). A base guarda só a janela recente (padrão 30 dias), atualizada no job
  semanal: a última data pode ter até uma semana.
- **Recursão em holdings só alcança quem tem FRE na base** (companhias do watchlist). Controlador fechado ou pessoa
  física é o último nível; `controlador_doc` é CNPJ formatado, CPF (11 dígitos) ou `nome:<nome>`.
- **"Ativos do grupo"** = títulos cujas partes (emissor, devedor, fiador, garantidor…) têm um controlador em comum,
  ou são o próprio controlador. É uma ligação societária, não prova de garantia cruzada: para isso, veja `garantias`.
- **Cobertura dos PDFs:** só os códigos de `rf_watchlist.csv` (na raiz). Para acrescentar, informe o comando
  `python scripts/ingest/ingest_rf_docs.py --codigo <CODIGO>`; não rode carga sem o usuário pedir. CRI/CRA de
  securitizadora com centenas de emissões: o script lista candidatos e pede `--protocolo`, `--url` ou `--arquivo`.
  O link do PDF na aba de documentos do data.anbima.com.br é pré-assinado e expira em horas: `--url` lê na hora e
  grava sem o token; se já expirou, baixar o PDF e usar `--arquivo`. Repita `--codigo` para ligar o termo a várias
  séries.

## Colunas que importam

- `rf_ativos`: `codigo` (PK), `tipo` (DEB/CRI/CRA), `emissor_*`, `devedor_*`, `emissao`, `serie`, `data_vencimento`,
  `indexador`, `remuneracao` (texto da fonte), `especie_garantia`, `incentivada_12431`, `fonte`.
- `rf_taxas (codigo, data)`: `taxa_indicativa` (% a.a.; spread sobre o indexador ou % do DI, conforme `indice`),
  `pu`, `pct_pu_par`, `duration_du` (dias úteis), `referencia` (NTN-B, títulos IPCA).
- `rf_partes`, `rf_garantias`, `rf_lastro`: `fonte`, `confianca`, `doc_id`, `evidencia`.
- `rf_grupo (cnpj_origem, nivel, controlador_doc, controlador_nome, percentual, via_cnpj)`.
- `vw_rf_ativo`: título + última taxa.

## Queries prontas

```sql
-- Dívida de mercado de uma empresa (como emissora, devedora ou garantidora)
SELECT DISTINCT a.codigo, a.tipo, p.papel, a.data_vencimento, a.remuneracao, a.taxa_indicativa
FROM vw_rf_ativo a JOIN rf_partes p ON p.codigo = a.codigo
WHERE p.cnpj = '<CNPJ>' ORDER BY a.data_vencimento;

-- Evolução da taxa indicativa (curva do emissor na janela)
SELECT t.data, t.codigo, t.taxa_indicativa, t.duration_du
FROM rf_taxas t JOIN rf_ativos a ON a.codigo = t.codigo
WHERE a.emissor_cnpj = '<CNPJ>' ORDER BY t.codigo, t.data;

-- Variação da taxa na janela (abertura de spread)
SELECT codigo, MIN(data) AS de, MAX(data) AS ate,
       (SELECT taxa_indicativa FROM rf_taxas x WHERE x.codigo = t.codigo ORDER BY data DESC LIMIT 1)
     - (SELECT taxa_indicativa FROM rf_taxas x WHERE x.codigo = t.codigo ORDER BY data LIMIT 1) AS var_pp
FROM rf_taxas t GROUP BY codigo ORDER BY var_pp DESC LIMIT 20;
```

## Resposta

```
### <CÓDIGO> — <tipo> — <emissor> (devedor: <devedor>)

**Emissão** — data, vencimento, volume, remuneração, espécie, 12.431 (fonte)
**Partes** | Papel | Nome | CNPJ | Fonte |
**Garantias e lastro** | Tipo | Prestador | Evidência (trecho) |   ← ou "PDF não lido: <comando>"
**Grupo econômico** — cadeia até o controlador final; outros títulos do grupo
**Taxa ANBIMA** — última taxa, PU, % PU par, duration e variação na janela (data da última taxa)
```
