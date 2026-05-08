-- Programas de recompra de ações
CREATE TABLE IF NOT EXISTS recompra_programas (
    id_programa                     BIGINT PRIMARY KEY,
    cnpj_companhia                  TEXT NOT NULL,
    nome_companhia                  TEXT,
    quantidade_acoes_ordinarias     BIGINT,
    quantidade_acoes_preferenciais  BIGINT,
    finalidade_compra               TEXT,
    data_deliberacao                DATE,
    motivo                          TEXT,
    data_final_prazo                DATE,
    situacao                        TEXT,   -- 'Vigente', 'Encerrado'
    created_at                      TIMESTAMPTZ DEFAULT NOW(),
    updated_at                      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_recompra_cnpj ON recompra_programas (cnpj_companhia, data_deliberacao DESC);

-- Quantidades executadas por período
CREATE TABLE IF NOT EXISTS recompra_quantidades (
    id              BIGSERIAL PRIMARY KEY,
    id_programa     BIGINT REFERENCES recompra_programas(id_programa),
    cnpj_companhia  TEXT NOT NULL,
    data_referencia DATE,
    tipo_ativo      TEXT,
    quantidade      BIGINT,
    preco_medio     NUMERIC(18,6),
    volume          NUMERIC(20,2),
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_recompra_qtd_cnpj ON recompra_quantidades (cnpj_companhia, data_referencia DESC);

-- Intermediários utilizados
CREATE TABLE IF NOT EXISTS recompra_intermediarios (
    id              BIGSERIAL PRIMARY KEY,
    id_programa     BIGINT REFERENCES recompra_programas(id_programa),
    cnpj_companhia  TEXT NOT NULL,
    intermediario   TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
