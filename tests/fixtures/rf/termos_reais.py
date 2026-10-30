"""
Trechos de dois termos de securitização reais, para testar a extração por regra (extrai_rf.py) contra o texto
como ele sai do PDF: layout em duas colunas embaralhado, ruído de página no meio da qualificação, CNPJ quebrado,
definições genéricas e o anexo com o histórico de emissões do agente fiduciário.

Origem: PDFs da página dos títulos no data.anbima.com.br, lidos em 2026-10-30 com pdfplumber e espaços
normalizados. Só trechos curtos; o documento inteiro tem ~450 mil caracteres.
- VIRGO_204: Termo de Securitização da 204ª emissão da Virgo Companhia de Securitização (CRA, 4 séries,
  lastreados em debêntures da JBS S.A.), 26/04/2024.
- ECO_243: Termo de Securitização da 243ª emissão da Eco Securitizadora de Direitos Creditórios do Agronegócio
  (CRA, 2 séries, lastreados em CPR-Financeira da FS Indústria de Biocombustíveis Ltda.), 24/03/2023.

Os trechos marcados [RECONSTRUÍDO] não foram copiados: o nome vem da capa do mesmo documento, o CEP/bairro e o
pedaço a partir de "inscrita no CNPJ" são o que a leitura do PDF mostrou (a regra antiga tirava "CEP 05501-900",
"Pinheiros" e "CEP 05.419-001" como nome), e o resto do endereço foi trocado por "[omitida]". No anexo, os dados
da outra emissão estão neutralizados ("[OUTRA SECURITIZADORA]"); o CNPJ 02.332.886/0011-78 é o que a regra antiga
tirou dali. O resto é literal.

GABARITO_* é a leitura humana dos mesmos trechos.
"""

VIRGO_204 = " ".join([
    # capa e índice (literal)
    "TERMO DE SECURITIZAÇÃO DE DIREITOS CREDITÓRIOS DO AGRONEGÓCIO para emissão de CERTIFICADOS DE RECEBÍVEIS DO "
    "AGRONEGÓCIO DAS 1ª (PRIMEIRA), 2ª (SEGUNDA), 3ª (TERCEIRA) E 4ª (QUARTA) SÉRIES DA 204ª (DUCENTÉSIMA QUARTA) "
    "EMISSÃO DA VIRGO COMPANHIA DE SECURITIZAÇÃO Companhia Securitizadora - CVM Nº 728 CNPJ/MF nº 08.769.451/0001-08 "
    "Rua Gerivatiba, nº 207, 16º andar, conjunto 162 CEP 05501-900, São Paulo - SP celebrado entre a Securitizadora e "
    "VÓRTX DISTRIBUIDORA DE TÍTULOS E VALORES MOBILIÁRIOS LTDA. como Agente Fiduciário LASTREADOS EM DIREITOS "
    "CREDITÓRIOS DO AGRONEGÓCIO DEVIDOS PELA JBS S.A. 26 de abril de 2024",
    # qualificação das partes [RECONSTRUÍDO até "inscrita no CNPJ"]
    "Pelo presente instrumento particular, as partes abaixo qualificadas: VIRGO COMPANHIA DE SECURITIZAÇÃO, sociedade "
    "por ações com registro de companhia securitizadora perante a CVM, com sede na Cidade de São Paulo, Estado de São "
    "Paulo, na Rua Gerivatiba, nº 207, 16º andar, conjunto 162, CEP 05501-900, inscrita no CNPJ/MF sob o "
    "nº 08.769.451/0001-08, neste ato representada na forma de seu estatuto social (\"Emissora\" ou \"Securitizadora\"); "
    "e VÓRTX DISTRIBUIDORA DE TÍTULOS E VALORES MOBILIÁRIOS LTDA., instituição financeira, com sede na Cidade de São "
    "Paulo, Estado de São Paulo, na Rua [omitida], Pinheiros, inscrita no "
    "CNPJ/MF sob o nº 22.610.500/0001-88, neste ato representada na forma de seu contrato social (\"Agente "
    "Fiduciário\");",
    # definição de Devedora em duas colunas embaralhadas, com o rodapé no meio (literal)
    "\"Destinação de Recursos\": a destinação dos recursos captados com a emissão das Debêntures; \"Devedora\", "
    "“Devedora a JBS S.A., sociedade por ações, com registro de companhia Original”, \"JBS\" ou aberta categoria “A” "
    "perante a CVM sob o nº 20.575, em fase “Companhia”: operacional, com sede na cidade de São Paulo, estado de São "
    "Paulo, na Avenida Marginal Direita do Tietê, nº 500, 3º andar, bloco I, Bairro Vila Jaguara, CEP 05118-100, "
    "inscrita no CNPJ/MF Página 15 de 341 DocuSign Envelope ID: B9ED68B8-3255-42E6-B76D-F8C8F54F77E4 sob o nº "
    "02.916.265/0001-60; \"Dia Útil\" ou \"Dias significa qualquer dia exceto sábado, domingo ou feriado nacional;",
    # lastro: debêntures da Devedora (literal)
    "\"Debêntures 1ª Série\": as debêntures simples, não conversíveis em ações, da espécie Página 14 de 341 DocuSign "
    "Envelope ID: B9ED68B8-3255-42E6-B76D-F8C8F54F77E4 quirografária, da 1ª (primeira) série da 11ª (décima primeira) "
    "emissão da Devedora, emitidas, para colocação privada perante a Securitizadora, nos termos da Escritura de "
    "Emissão, representativas dos Direitos Creditórios do Agronegócio 1ª Série;",
    # definição genérica de Ônus, em duas colunas (literal)
    "\"Ônus\" e o verbo qualquer hipoteca, penhor, alienação fiduciária, cessão fiduciária, correlato \"Onerar\": "
    "usufruto, fideicomisso, promessa de venda, opção de compra, direito de preferência;",
    # fiança da JBS depois da assunção de dívida (literal; "pre" de "prestação" completado)
    "(iv) obtenção, pela JBS, de todas as aprovações societárias, necessárias à época, para realizar (a) a Assunção de "
    "Dívida, (b) a outorga de Fiança (conforme definido abaixo) no âmbito da emissão das Debêntures; e (v) prestação "
    "de fiança pela JBS (que passará a ser designada como “Fiadora” ou “Coobrigada”) em favor da Securitizadora, "
    "obrigando-se como fiadora e principal responsável pelo fiel, pontual e integral cumprimento de todas as "
    "Obrigações Originais, da Escritura de Emissão e dos demais Documentos da Operação, conforme aplicável, que, após "
    "a Assunção da Dívida, passarão a ser devidas pela Seara, na qualidade de Nova Devedora, no âmbito da emissão das "
    "Debêntures da Escritura de Emissão.",
    # características dos CRA (literal)
    "(xviii) Garantia Flutuante: Não haverá garantia flutuante e não existe qualquer tipo de regresso contra o "
    "patrimônio da Emissora; (xix) Garantias: Não haverá garantias específicas, reais ou pessoais, sobre os CRA; "
    "Página 58 de 341 DocuSign Envelope ID: B9ED68B8-3255-42E6-B76D-F8C8F54F77E4 (xx) Coobrigação da Emissora: Não "
    "haverá; (xxi) Ambiente de Depósito para Distribuição, Negociação e Liquidação Financeira: B3;",
])

GABARITO_VIRGO_204 = {
    "partes": {
        ("securitizadora", "08.769.451/0001-08"): "VIRGO COMPANHIA DE SECURITIZAÇÃO",
        ("agente_fiduciario", "22.610.500/0001-88"): "VÓRTX DISTRIBUIDORA DE TÍTULOS E VALORES MOBILIÁRIOS LTDA.",
        ("devedor", "02.916.265/0001-60"): "JBS S.A.",
        ("fiador", "02.916.265/0001-60"): "JBS S.A.",   # designada depois pelo apelido "JBS"; nome da definição
    },
    # tipo → escopo
    "garantias": {"sem_garantia": "titulo", "fianca": "lastro", "quirografaria": "lastro"},
    "lastro": {"debenture"},
}

ECO_243 = " ".join([
    # capa e índice (literal)
    "Termo de Securitização de Direitos Creditórios do Agronegócio para emissão de Certificados de Recebíveis do "
    "Agronegócio, da 1ª (Primeira) e da 2ª (Segunda) Séries, da 243ª (ducentésima quadragésima terceira) Emissão da "
    "Eco Securitizadora de Direitos Creditórios do Agronegócio S.A. como Securitizadora celebrado com Oliveira Trust "
    "Distribuidora de Títulos e Valores Mobiliários S.A. como Agente Fiduciário com Lastro em Créditos do Agronegócio "
    "devidos pela FS Indústria de Biocombustíveis Ltda. Datado de 24 de março de 2023 Índice 1. Definições, Prazos e "
    "Autorização ........ 3 7. Resgate Antecipado Total dos CRA, Amortização Extraordinária dos CRA e Vencimento "
    "Antecipado das CPR-Financeiras ........ 79 8. Garantias e Ordem de Pagamentos ........ 90 Anexo VIII - "
    "Histórico de Emissões do Agente Fiduciário ........ 156 Anexo IX – FATORES DE RISCOS ........ 157",
    # qualificação das partes [RECONSTRUÍDO até "inscrita no CNPJ"]
    "Pelo presente instrumento particular: ECO SECURITIZADORA DE DIREITOS CREDITÓRIOS DO AGRONEGÓCIO S.A., sociedade "
    "por ações, com sede na Cidade de São Paulo, Estado de São Paulo, na Rua [omitida], "
    "CEP 05.419-001, inscrita no CNPJ/MF sob o nº 10.753.164/0001-43, neste ato "
    "representada nos termos de seu estatuto social (“Emissora” ou “Securitizadora”); e OLIVEIRA TRUST DISTRIBUIDORA "
    "DE TÍTULOS E VALORES MOBILIÁRIOS S.A., instituição financeira, atuando por sua filial na Cidade de São Paulo, "
    "na Rua [omitida], CEP 04.534-004, inscrita no CNPJ/MF sob o nº "
    "36.113.876/0004-34, neste ato representada nos termos de seu estatuto social (“Agente Fiduciário”);",
    # definições (literal)
    "“Aval” significa a garantia prestada pela Avalista, conforme descrito na Cláusula 14 da CPR-Financeira e na "
    "Cláusula 8.2 deste Termo de Securitização. “Avalista” significa a FS I INDÚSTRIA DE ETANOL S.A., sociedade por "
    "ações, com sede na Cidade de Lucas do Rio Verde, no Estado do Mato Grosso, na Estrada Linha 01-A, 900 metros do "
    "km 7 da Avenida das Indústrias, s/n, Sala Iowa tana, CEP 78455-000, inscrita no CNPJ/MF sob o nº 46.710.597/0001- "
    "69. “Aviso ao Mercado” significa o “Aviso ao Mercado da Distribuição Pública em 2 (duas) Séries da 243ª "
    "(ducentésima quadragésima terceira) Emissão”.",
    "“Devedora” significa a FS Indústria de Biocombustíveis Ltda., sociedade empresária limitada, com sede na Cidade "
    "de Lucas do Rio Verde, Estado do Mato Grosso, na Estrada Linha 01-A, 900 metros do km 7 da Avenida das "
    "Indústrias, s/n, Distrito Industrial Senador Atílio Fontana, CEP 78455- 000, inscrita no CNPJ/MF sob o nº "
    "20.003.699/0001-50. “Dia Útil” ou “Dias Úteis” significa (i) com relação a qualquer obrigação pecuniária, "
    "qualquer dia exceto sábado, domingo ou feriado declarado nacional.",
    "“Ônus” significa qualquer garantia real, security interest, cessão ou alienação fiduciária, bloqueio, penhora, "
    "penhor, hipoteca, usufruto, vinculação de bens, concessão de privilégio, preferência ou prioridade.",
    "“CPR-Financeira Segunda” significa a Cédula de Produto Rural Financeira Nº 2/2023, a ser emitida pela Devedora "
    "em 17 de abril de 2023, nos termos da Lei 8.929, em favor da Emissora, representativa dos Créditos do Agronegócio.",
    # características dos CRA (literal)
    "(xxiv) Garantia: Não serão constituídas garantias específicas, reais ou pessoais, sobre os CRA, os quais gozam "
    "das garantias que integram as CPR-Financeiras. As CPR- Financeiras contam com o Aval prestado pela Avalista, nos "
    "termos das CPR-Financeiras. (xxv) Garantia Flutuante: Não há garantia flutuante e não existe qualquer tipo de "
    "regresso contra o patrimônio da Emissora. (xxvi) Coobrigação da Emissora: Não há. (xxvii) Ambiente para "
    "Depósito, Distribuição, Negociação, Custódia Eletrônica e Liquidação Financeira: B3.",
    "(xxxviii) Nível de Subordinação: não há. Distribuição dos CRA 4.2. Os CRA serão objeto de distribuição pública.",
    # anexo com outras emissões do agente fiduciário (literal até "Madeira em Pé"; depois [RECONSTRUÍDO] e
    # neutralizado): nada daqui é deste título
    "****** Anexo VIII - Histórico de Emissões do Agente Fiduciário Emissora: ECO SECURITIZADORA DE DIREITOS "
    "CREDITORIOS DO AGRONEGOCIO SA Ativo: CRI Série: 1 Emissão: 1 Status: ATIVO "
    "Inadimplementos no período: Não ocorreram inadimplementos no período. Garantias: (I) Como fiadores: FS Indústria "
    "e a FS Ltda. (II) Cessão Fiduciária: (i) a propriedade fiduciária sobre todos e quaisquer direitos e créditos de "
    "titularidade da Fiduciante oriundas do contrato de \"Compra e Venda de Madeira em Pé\". Emissora: [OUTRA "
    "SECURITIZADORA] S.A., inscrita no CNPJ sob o nº 02.332.886/0011-78 (“Emissora”) Ativo: CDCA, com lastro em CDCA. "
    "Garantias: (i) Aval de [OUTRAS EMPRESAS]; (ii) Cessão Fiduciária dos Créditos advindos do Contrato de "
    "Fornecimento.",
])

GABARITO_ECO_243 = {
    "partes": {
        ("securitizadora", "10.753.164/0001-43"): "ECO SECURITIZADORA DE DIREITOS CREDITÓRIOS DO AGRONEGÓCIO S.A.",
        ("agente_fiduciario", "36.113.876/0004-34"): "OLIVEIRA TRUST DISTRIBUIDORA DE TÍTULOS E VALORES MOBILIÁRIOS S.A.",
        ("devedor", "20.003.699/0001-50"): "FS Indústria de Biocombustíveis Ltda.",
        ("avalista", "46.710.597/0001-69"): "FS I INDÚSTRIA DE ETANOL S.A.",
    },
    "garantias": {"sem_garantia": "titulo", "aval": "lastro"},
    "lastro": {"CPR-F"},
}
