-- FRE: capital social (valor e quantidade de ações)
CREATE TABLE IF NOT EXISTS fre_capital_social (
    id                          BIGSERIAL PRIMARY KEY,
    cnpj_companhia              TEXT NOT NULL,
    nome_companhia              TEXT,
    data_referencia             DATE,
    versao                      INT,
    id_documento                BIGINT,
    id_capital_social           BIGINT,
    tipo_capital                TEXT,   -- 'Capital Emitido', 'Capital Subscrito'
    data_autorizacao_aprovacao  DATE,
    valor_capital               NUMERIC(22,2),
    quantidade_acoes_ordinarias BIGINT,
    quantidade_acoes_preferenciais BIGINT,
    quantidade_total_acoes      BIGINT,
    created_at                  TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (cnpj_companhia, data_referencia, versao, id_capital_social)
);

CREATE INDEX IF NOT EXISTS idx_fre_cap_cnpj ON fre_capital_social (cnpj_companhia, data_referencia DESC);

-- FRE: posição acionária (maiores acionistas)
CREATE TABLE IF NOT EXISTS fre_posicao_acionaria (
    id                                      BIGSERIAL PRIMARY KEY,
    cnpj_companhia                          TEXT NOT NULL,
    nome_companhia                          TEXT,
    data_referencia                         DATE,
    versao                                  INT,
    id_documento                            BIGINT,
    id_acionista                            BIGINT,
    acionista                               TEXT,
    tipo_pessoa_acionista                   TEXT,   -- 'PF', 'PJ'
    cpf_cnpj_acionista                      TEXT,
    quantidade_acao_ordinaria_circulacao    BIGINT,
    percentual_acao_ordinaria_circulacao    NUMERIC(10,6),
    quantidade_acao_preferencial_circulacao BIGINT,
    percentual_acao_preferencial_circulacao NUMERIC(10,6),
    quantidade_total_acoes_circulacao       BIGINT,
    percentual_total_acoes_circulacao       NUMERIC(10,6),
    nacionalidade                           TEXT,
    residente_exterior                      TEXT,
    acionista_controlador                   TEXT,   -- 'S'/'N'
    participante_acordo_acionistas          TEXT,
    data_composicao_capital_social          DATE,
    created_at                              TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (cnpj_companhia, data_referencia, versao, id_acionista)
);

CREATE INDEX IF NOT EXISTS idx_fre_acionist_cnpj       ON fre_posicao_acionaria (cnpj_companhia, data_referencia DESC);
CREATE INDEX IF NOT EXISTS idx_fre_acionist_controlador ON fre_posicao_acionaria (acionista_controlador);

-- FRE: remuneração dos órgãos de administração (max/min/média)
CREATE TABLE IF NOT EXISTS fre_remuneracao_orgao (
    id                          BIGSERIAL PRIMARY KEY,
    cnpj_companhia              TEXT NOT NULL,
    nome_companhia              TEXT,
    data_referencia             DATE,
    versao                      INT,
    id_documento                BIGINT,
    data_inicio_exercicio       DATE,
    data_fim_exercicio          DATE,
    orgao_administracao         TEXT,   -- 'Conselho de Administração', 'Diretoria Estatutária'
    numero_membros              NUMERIC(6,2),
    numero_membros_remunerados  NUMERIC(6,2),
    valor_maior_remuneracao     NUMERIC(18,2),
    valor_menor_remuneracao     NUMERIC(18,2),
    valor_medio_remuneracao     NUMERIC(18,2),
    observacao                  TEXT,
    created_at                  TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (cnpj_companhia, data_referencia, versao, id_documento, orgao_administracao, data_fim_exercicio)
);

CREATE INDEX IF NOT EXISTS idx_fre_rem_cnpj ON fre_remuneracao_orgao (cnpj_companhia, data_referencia DESC);
