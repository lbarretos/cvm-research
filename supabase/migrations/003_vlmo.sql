-- VLMO: posição consolidada por empresa/período
CREATE TABLE IF NOT EXISTS vlmo_posicao (
    protocolo_entrega   TEXT PRIMARY KEY,
    cnpj_companhia      TEXT NOT NULL,
    nome_companhia      TEXT,
    data_referencia     DATE,
    versao              INT,
    codigo_cvm          TEXT,
    categoria           TEXT,
    tipo                TEXT,
    data_entrega        DATE,
    tipo_apresentacao   TEXT,
    motivo_reapresentacao TEXT,
    link_download       TEXT,
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_vlmo_pos_cnpj ON vlmo_posicao (cnpj_companhia, data_referencia DESC);

-- VLMO: movimentações detalhadas (insiders, controladores, conselho)
CREATE TABLE IF NOT EXISTS vlmo_movimentacoes (
    id                      BIGSERIAL PRIMARY KEY,
    cnpj_companhia          TEXT NOT NULL,
    nome_companhia          TEXT,
    data_referencia         DATE,
    versao                  INT,
    tipo_empresa            TEXT,   -- 'Companhia', 'Controlada'
    empresa                 TEXT,
    tipo_cargo              TEXT,   -- 'Conselho de Administração', 'Diretoria', 'Controlador'
    tipo_movimentacao       TEXT,   -- 'Saldo Inicial', 'Compra', 'Venda', 'Saldo Final'
    descricao_movimentacao  TEXT,
    tipo_operacao           TEXT,   -- 'Crédito', 'Débito'
    tipo_ativo              TEXT,   -- 'Ações', 'Opções'
    caracteristica          TEXT,   -- 'ON', 'PN'
    intermediario           TEXT,
    data_movimentacao       DATE,
    quantidade              BIGINT,
    preco_unitario          NUMERIC(18,6),
    volume                  NUMERIC(20,2),
    created_at              TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_vlmo_mov_cnpj      ON vlmo_movimentacoes (cnpj_companhia, data_referencia DESC);
CREATE INDEX IF NOT EXISTS idx_vlmo_mov_cargo      ON vlmo_movimentacoes (tipo_cargo);
CREATE INDEX IF NOT EXISTS idx_vlmo_mov_tipo       ON vlmo_movimentacoes (tipo_movimentacao);
