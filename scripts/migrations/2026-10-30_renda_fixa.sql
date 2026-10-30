-- Etapa 8 (docs/proximos-passos/08-renda-fixa.md): tabelas de renda fixa (debêntures, CRI, CRA).
-- Só cria tabelas, índices e uma view; não mexe em nada existente. Idempotente.
--
-- Uso (na raiz do projeto):
--   sqlite3 cvm_research.db < scripts/migrations/2026-10-30_renda_fixa.sql
--   cd scripts/ingest && ../../.venv/bin/python rf_fontes.py --verificar     # confere os layouts das fontes
--   ../../.venv/bin/python ingest_rf_cadastro.py && ../../.venv/bin/python ingest_rf_taxas.py --dias 30
--   ../../.venv/bin/python ingest_rf_docs.py && ../../.venv/bin/python rf_grupo.py
-- Banco novo: schema.sql já traz tudo isto.
.bail on

-- ── Renda fixa: debêntures, CRI e CRA (Etapa 8) ──────────────────────────────
-- Fontes públicas (ver scripts/ingest/rf_fontes.py): características das debêntures no SND,
-- ofertas registradas na CVM (dados abertos), taxas indicativas da ANBIMA e PDFs (escritura,
-- termo de securitização) sob demanda. Diferente do resto da base, a cobertura não segue o
-- watchlist.csv: cadastro e taxas são do mercado inteiro; PDFs, só dos códigos em rf_watchlist.csv.
-- CNPJs ficam no formato 00.000.000/0000-00, como em companies.cnpj.

-- Um título por código de negociação (B3/CETIP): RUMOB6, CRA024004SB.
CREATE TABLE IF NOT EXISTS rf_ativos (
    codigo              TEXT PRIMARY KEY,
    isin                TEXT,
    tipo                TEXT NOT NULL,          -- 'DEB', 'CRI', 'CRA' ou 'OUTRO'
    emissor_cnpj        TEXT,                   -- no CRI/CRA, a securitizadora
    emissor_nome        TEXT,
    devedor_cnpj        TEXT,                   -- CRI/CRA: devedor do lastro, quando a fonte informa
    devedor_nome        TEXT,
    emissao             TEXT,
    serie               TEXT,
    data_emissao        TEXT,
    data_vencimento     TEXT,
    valor_emissao       REAL,                   -- R$
    quantidade          REAL,
    valor_nominal       REAL,                   -- R$ por título, na emissão
    indexador           TEXT,                   -- DI, IPCA, IGP-M, PRE…
    remuneracao         TEXT,                   -- como a fonte escreve: 'DI + 1,2000%', '108% do DI'
    especie_garantia    TEXT,                   -- debênture: quirografária, real, flutuante, subordinada
    incentivada_12431   INTEGER,                -- 1 = Lei 12.431 (isenta para PF)
    agente_fiduciario   TEXT,
    situacao            TEXT,
    fonte               TEXT NOT NULL,          -- 'snd', 'cvm_oferta', 'manual', 'teste'
    atualizado_em       TEXT,
    created_at          TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_rf_ativos_emissor ON rf_ativos (emissor_cnpj);
CREATE INDEX IF NOT EXISTS idx_rf_ativos_devedor ON rf_ativos (devedor_cnpj);
CREATE INDEX IF NOT EXISTS idx_rf_ativos_isin    ON rf_ativos (isin);

-- Ofertas registradas na CVM (rito 400/476 e Resolução 160). `codigo` só vem quando a CVM informa
-- o código de negociação; senão casa-se com rf_ativos por emissor + emissão + série.
-- `chave` junta os campos que identificam a linha (vários podem ser NULL; ver ingest_rf_cadastro.py).
CREATE TABLE IF NOT EXISTS rf_ofertas (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    chave               TEXT NOT NULL UNIQUE,
    fonte               TEXT NOT NULL,          -- 'cvm_distrib' (400/476) ou 'cvm_160'
    numero_registro     TEXT,
    codigo              TEXT,
    isin                TEXT,
    tipo_ativo          TEXT,                   -- como a CVM escreve (Debêntures, CRI, CRA…)
    emissor_cnpj        TEXT,
    emissor_nome        TEXT,
    devedor_cnpj        TEXT,
    devedor_nome        TEXT,
    emissao             TEXT,
    serie               TEXT,
    data_registro       TEXT,
    data_emissao        TEXT,
    data_vencimento     TEXT,
    valor_total         REAL,
    quantidade          REAL,
    remuneracao         TEXT,
    rito                TEXT,
    publico_alvo        TEXT,
    lider_nome          TEXT,
    incentivada_12431   INTEGER,
    created_at          TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_rf_ofertas_emissor ON rf_ofertas (emissor_cnpj, data_registro DESC);
CREATE INDEX IF NOT EXISTS idx_rf_ofertas_codigo  ON rf_ofertas (codigo);

-- Taxas indicativas da ANBIMA (mercado secundário), uma linha por título e dia útil. É preço de
-- referência calculado pela ANBIMA, não negócio fechado. O job guarda só a janela recente (--reter).
CREATE TABLE IF NOT EXISTS rf_taxas (
    codigo              TEXT NOT NULL,
    data                TEXT NOT NULL,
    tipo                TEXT,                   -- 'DEB', 'CRI', 'CRA'
    indice              TEXT,                   -- indexador/correção como a ANBIMA escreve
    taxa_compra         REAL,                   -- % a.a. (spread ou % do DI, conforme `indice`)
    taxa_venda          REAL,
    taxa_indicativa     REAL,
    desvio_padrao       REAL,
    intervalo_min       REAL,
    intervalo_max       REAL,
    pu                  REAL,
    pct_pu_par          REAL,
    duration_du         REAL,                   -- dias úteis
    referencia          TEXT,                   -- NTN-B de referência (IPCA)
    created_at          TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (codigo, data)
);
CREATE INDEX IF NOT EXISTS idx_rf_taxas_data ON rf_taxas (data);

-- Documentos do título (escritura, aditamentos, termo de securitização, relatório do agente
-- fiduciário…), com o texto extraído do PDF. Um documento serve a várias séries: rf_doc_ativo.
CREATE TABLE IF NOT EXISTS rf_docs (
    doc_id              TEXT PRIMARY KEY,       -- protocolo do IPE ou 'url:<sha256 do link>'
    origem              TEXT NOT NULL,          -- 'ipe', 'url'
    cnpj_remetente      TEXT,
    categoria           TEXT,
    tipo                TEXT,
    especie             TEXT,
    assunto             TEXT,
    data_entrega        TEXT,
    link_download       TEXT,
    texto_extraido      TEXT,
    extraido_em         TEXT,
    extracao_falhou     INTEGER DEFAULT 0,
    chars_extraidos     INTEGER,
    regras_em           TEXT,                   -- quando extrai_rf.py leu o texto (NULL = pendente)
    created_at          TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS rf_doc_ativo (
    doc_id              TEXT NOT NULL,
    codigo              TEXT NOT NULL,
    PRIMARY KEY (doc_id, codigo)
);
CREATE INDEX IF NOT EXISTS idx_rf_doc_ativo_codigo ON rf_doc_ativo (codigo);

-- Mesmo padrão de ipe_docs_fts: conteúdo externo, reconstruído por ingest_rf_docs.py.
CREATE VIRTUAL TABLE IF NOT EXISTS rf_docs_fts USING fts5(
    doc_id,
    assunto,
    texto_extraido,
    content='rf_docs',
    content_rowid='rowid'
);

-- Partes do título. fonte 'cadastro' (campo publicado pela fonte, confianca 1) ou 'pdf' (extraída
-- por regra de um documento: doc_id e o trecho em `evidencia`, confianca < 1).
-- papel: emissor, securitizadora, devedor, fiador, avalista, garantidor, cedente, coobrigado,
-- agente_fiduciario. `chave` = codigo|papel|cnpj (ou nome normalizado)|fonte.
CREATE TABLE IF NOT EXISTS rf_partes (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    chave               TEXT NOT NULL UNIQUE,
    codigo              TEXT NOT NULL,
    papel               TEXT NOT NULL,
    cnpj                TEXT,
    nome                TEXT,
    fonte               TEXT NOT NULL,
    doc_id              TEXT,
    evidencia           TEXT,
    confianca           REAL,
    created_at          TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_rf_partes_codigo ON rf_partes (codigo);
CREATE INDEX IF NOT EXISTS idx_rf_partes_cnpj   ON rf_partes (cnpj);

-- Garantias. tipo: alienacao_fiduciaria, cessao_fiduciaria, fianca, aval, hipoteca, penhor,
-- fundo_reserva, subordinacao, coobrigacao, garantia_flutuante, quirografaria, sem_garantia.
-- Ausência de linha = nada encontrado (PDF não lido, ou a regra não achou), não "sem garantia".
CREATE TABLE IF NOT EXISTS rf_garantias (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    chave               TEXT NOT NULL UNIQUE,   -- codigo|tipo|fonte|doc_id
    codigo              TEXT NOT NULL,
    tipo                TEXT NOT NULL,
    descricao           TEXT,
    prestador_cnpj      TEXT,
    prestador_nome      TEXT,
    fonte               TEXT NOT NULL,
    doc_id              TEXT,
    evidencia           TEXT,
    confianca           REAL,
    created_at          TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_rf_garantias_codigo ON rf_garantias (codigo);

-- Lastro do CRI/CRA (o crédito que paga o título): CPR-F, CDCA, CCB, nota comercial, debênture,
-- contratos imobiliários… extraído por regra do termo de securitização.
CREATE TABLE IF NOT EXISTS rf_lastro (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    chave               TEXT NOT NULL UNIQUE,   -- codigo|tipo_lastro|fonte|doc_id
    codigo              TEXT NOT NULL,
    tipo_lastro         TEXT NOT NULL,
    devedor_cnpj        TEXT,
    devedor_nome        TEXT,
    descricao           TEXT,
    fonte               TEXT NOT NULL,
    doc_id              TEXT,
    evidencia           TEXT,
    confianca           REAL,
    created_at          TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_rf_lastro_codigo ON rf_lastro (codigo);

-- Cadeia de controle de cada CNPJ que aparece num título (emissor, devedor, garantidor…), subindo
-- pelo FRE: controladores diretos da companhia, as holdings da cadeia (id_acionista_relacionado) e,
-- quando o controlador também é companhia da base, o FRE dele (Rumo → Cosan → …). Só alcança quem
-- tem FRE na base; um controlador fechado é o último nível. Reconstruída por rf_grupo.py.
CREATE TABLE IF NOT EXISTS rf_grupo (
    cnpj_origem         TEXT NOT NULL,
    nivel               INTEGER NOT NULL,       -- 1 = controlador direto
    controlador_doc     TEXT NOT NULL,          -- CNPJ/CPF como no FRE, ou 'nome:<nome>' sem documento
    controlador_nome    TEXT,
    tipo_pessoa         TEXT,
    percentual          REAL,                   -- % do capital total de `via_cnpj` (ou da holding de cima)
    via_cnpj            TEXT,                   -- companhia cujo FRE descreve o elo
    via_data_fre        TEXT,
    PRIMARY KEY (cnpj_origem, controlador_doc)
);
CREATE INDEX IF NOT EXISTS idx_rf_grupo_controlador ON rf_grupo (controlador_doc);

-- Título com a última taxa indicativa disponível.
CREATE VIEW IF NOT EXISTS vw_rf_ativo AS
SELECT a.codigo, a.tipo, a.isin, a.emissor_cnpj, a.emissor_nome, a.devedor_cnpj, a.devedor_nome,
       a.emissao, a.serie, a.data_emissao, a.data_vencimento, a.valor_emissao, a.indexador, a.remuneracao,
       a.especie_garantia, a.incentivada_12431, a.agente_fiduciario, a.situacao, a.fonte,
       t.data AS taxa_data, t.taxa_indicativa, t.pu, t.pct_pu_par, t.duration_du
FROM rf_ativos a
LEFT JOIN rf_taxas t
  ON  t.codigo = a.codigo
  AND t.data = (SELECT MAX(data) FROM rf_taxas WHERE codigo = a.codigo);
