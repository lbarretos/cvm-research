"""
Base de teste do módulo de renda fixa: schema completo + dados FICTÍCIOS para os quatro códigos de exemplo
(RUMOB6, ERDVB4, CRA024004SB, CRA02300796). Nomes levam "[TESTE]", CNPJs são inventados e `fonte = 'teste'`:
nada aqui descreve os títulos reais. Serve para exercitar ingestão derivada (extração por regra, grupo) e o MCP
sem rede.

Estrutura montada:
- ALFA LOGÍSTICA (emissora do RUMOB6) é controlada pela HOLDING ALFA, que é controlada pela FAMÍLIA ALFA (CPF),
  com a cadeia descrita no FRE da própria ALFA (id_acionista_relacionado) e também no FRE da HOLDING.
- BETA RODOVIAS (ERDVB4) é controlada pela HOLDING ALFA → mesmo grupo do RUMOB6.
- CRA024004SB: securitizadora fictícia, devedora AGRO DELTA (sem FRE), fiadora ALFA LOGÍSTICA (só no PDF) →
  entra no grupo pelo fiador. Lastro CPR-F, cessão fiduciária e fundo de reserva no termo.
- CRA02300796: sem PDF ingerido (get_bond tem de avisar), devedor fora da base.

Uso:
  python tests/fixtures/rf/make_test_db.py /caminho/rf_teste.db
  CVM_DB_PATH=/caminho/rf_teste.db .venv/bin/python scripts/mcp/cvm_mcp.py   # MCP sobre a base de teste
"""
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(RAIZ / "scripts" / "ingest"))

ALFA = "11.111.111/0001-11"
HOLDING = "44.444.444/0001-44"
BETA = "55.555.555/0001-55"
SECURIT = "66.666.666/0001-66"
DELTA = "77.777.777/0001-77"
OMEGA = "88.888.888/0001-88"
AGENTE = "22.222.222/0001-22"
CPF_FAMILIA = "123.456.789-00"

ESCRITURA_RUMOB6 = f"""
INSTRUMENTO PARTICULAR DE ESCRITURA DA 6ª EMISSÃO DE DEBÊNTURES SIMPLES, NÃO CONVERSÍVEIS EM AÇÕES, DA ESPÉCIE
QUIROGRAFÁRIA, COM GARANTIA ADICIONAL FIDEJUSSÓRIA [TESTE]
Pelo presente instrumento particular, de um lado,
(i) ALFA LOGÍSTICA S.A. [TESTE], sociedade por ações com registro de companhia aberta, com sede na cidade de
São Paulo, inscrita no CNPJ sob o nº {ALFA} (“Emissora”);
(ii) AGENTE TESTE DTVM LTDA., instituição financeira, inscrita no CNPJ/ME sob o nº {AGENTE}, neste ato
representada na forma de seu contrato social (“Agente Fiduciário”); e
(iii) HOLDING ALFA PARTICIPAÇÕES S.A. [TESTE], sociedade anônima, inscrita no CNPJ sob o nº {HOLDING}
(doravante denominada “Fiadora”).
CLÁUSULA 4 – As Debêntures serão da espécie quirografária, com garantia adicional fidejussória na forma de fiança
prestada pela Fiadora. As Debêntures não contarão com alienação fiduciária de ações.
"""

TERMO_CRA = f"""
TERMO DE SECURITIZAÇÃO DE DIREITOS CREDITÓRIOS DO AGRONEGÓCIO DA 1ª SÉRIE DA 240ª EMISSÃO DE CERTIFICADOS DE
RECEBÍVEIS DO AGRONEGÓCIO [TESTE]
SECURITIZADORA TESTE S.A., sociedade por ações, inscrita no CNPJ sob o nº {SECURIT} (“Emissora” ou
“Securitizadora”), e AGENTE TESTE DTVM LTDA., instituição financeira, inscrita no CNPJ sob o nº {AGENTE}
(“Agente Fiduciário”), e, ainda, AGRO DELTA S.A. [TESTE], sociedade anônima, inscrita no CNPJ sob o nº {DELTA}
(“Devedora”), e ALFA LOGÍSTICA S.A. [TESTE], sociedade por ações, inscrita no CNPJ sob o nº {ALFA} (“Fiadora”).
Os CRA têm como lastro os Direitos Creditórios do Agronegócio representados pela Cédula de Produto Rural
Financeira (“CPR-F”) emitida pela Devedora. Em garantia, será constituída cessão fiduciária de recebíveis e
um fundo de reserva equivalente a duas parcelas de juros.
"""


def _dias(n: int) -> list[str]:
    out, d = [], date.today()
    while len(out) < n:
        d -= timedelta(days=1)
        if d.weekday() < 5:
            out.append(d.isoformat())
    return out


def montar(path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.executescript((RAIZ / "schema.sql").read_text())
    conn.executemany("INSERT INTO companies (cnpj, ticker, nome_cvm, setor) VALUES (?,?,?,?)", [
        (ALFA, "TSTA3", "ALFA LOGISTICA S.A. [TESTE]", "Transporte"),
        (HOLDING, "TSTH3", "HOLDING ALFA PARTICIPACOES S.A. [TESTE]", "Holding"),
        (BETA, "TSTB3", "BETA RODOVIAS S.A. [TESTE]", "Transporte"),
    ])
    fre = [
        # FRE da ALFA: HOLDING controla (direto) e, na cadeia, a FAMÍLIA controla a HOLDING
        (ALFA, "2026-01-01", 1, 10, None, "HOLDING ALFA PARTICIPACOES S.A.", "PJ", HOLDING, 30.0, "S"),
        (ALFA, "2026-01-01", 1, 11, None, "Outros", None, None, 70.0, "N"),
        (ALFA, "2026-01-01", 1, 12, 10, "FAMILIA ALFA", "PF", CPF_FAMILIA, 60.0, "S"),
        # FRE da HOLDING (companhia da base): a mesma família
        (HOLDING, "2026-01-01", 2, 20, None, "FAMILIA ALFA", "PF", CPF_FAMILIA, 60.0, "S"),
        # FRE da BETA: controlada pela HOLDING
        (BETA, "2026-01-01", 1, 30, None, "HOLDING ALFA PARTICIPACOES S.A.", "PJ", HOLDING, 51.0, "S"),
    ]
    conn.executemany(
        "INSERT INTO fre_posicao_acionaria (cnpj_companhia, data_referencia, versao, id_acionista, "
        "id_acionista_relacionado, acionista, tipo_pessoa_acionista, cpf_cnpj_acionista, "
        "percentual_total_acoes_circulacao, acionista_controlador) VALUES (?,?,?,?,?,?,?,?,?,?)", fre)
    ativos = [
        ("RUMOB6", "DEB", ALFA, "ALFA LOGISTICA S.A. [TESTE]", None, None, "6", "1", "2022-06-15", "2032-06-15",
         1.5e9, "IPCA", "IPCA + 6,0000%", "Quirografária com garantia adicional fidejussória", 1, "AGENTE TESTE DTVM"),
        ("ERDVB4", "DEB", BETA, "BETA RODOVIAS S.A. [TESTE]", None, None, "4", "2", "2023-03-01", "2030-03-01",
         8e8, "DI", "DI + 1,8000%", "Quirografária", 0, "AGENTE TESTE DTVM"),
        ("CRA024004SB", "CRA", SECURIT, "SECURITIZADORA TESTE S.A.", DELTA, "AGRO DELTA S.A. [TESTE]", "240", "1",
         "2024-04-10", "2031-04-15", 6e8, "IPCA", "IPCA + 7,1000%", None, 1, None),
        ("CRA02300796", "CRA", SECURIT, "SECURITIZADORA TESTE S.A.", OMEGA, "OMEGA AGRO LTDA. [TESTE]", "23", "796",
         "2023-07-20", "2028-07-20", 2e8, "DI", "DI + 2,5000%", None, 1, None),
    ]
    conn.executemany(
        "INSERT INTO rf_ativos (codigo, tipo, emissor_cnpj, emissor_nome, devedor_cnpj, devedor_nome, emissao, serie, "
        "data_emissao, data_vencimento, valor_emissao, indexador, remuneracao, especie_garantia, incentivada_12431, "
        "agente_fiduciario, fonte, atualizado_em) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'teste',date('now'))", ativos)
    conn.execute(
        "INSERT INTO rf_ofertas (chave, fonte, numero_registro, codigo, tipo_ativo, emissor_cnpj, emissor_nome, "
        "emissao, serie, data_registro, valor_total, remuneracao, rito, lider_nome) "
        "VALUES ('teste|1', 'cvm_160', 'TESTE/2024/001', 'CRA024004SB', 'CRA', ?, 'SECURITIZADORA TESTE S.A.', "
        "'240', '1', '2024-04-01', 6e8, 'IPCA + 7,1000%', 'Automático', 'BANCO TESTE')", (SECURIT,))
    taxas = []
    for i, d in enumerate(_dias(22)):
        taxas.append(("RUMOB6", d, "DEB", "IPCA", 6.4 + i * 0.01, 1012.5 - i, 101.2, 1650))
        taxas.append(("ERDVB4", d, "DEB", "DI", 1.55, 1003.0, 100.4, 980))
        taxas.append(("CRA024004SB", d, "CRA", "IPCA", 7.3, 998.0, 99.1, 1400))
    conn.executemany("INSERT INTO rf_taxas (codigo, data, tipo, indice, taxa_indicativa, pu, pct_pu_par, duration_du) "
                     "VALUES (?,?,?,?,?,?,?,?)", taxas)
    for doc_id, cod, tipo, assunto, txt in [
            ("TESTE-ESC-RUMOB6", "RUMOB6", "Escritura de Emissão de Debêntures", "6ª Emissão de Debêntures", ESCRITURA_RUMOB6),
            ("TESTE-TERMO-CRA", "CRA024004SB", "Termo de Securitização", "1ª Série da 240ª Emissão de CRA", TERMO_CRA)]:
        conn.execute("INSERT INTO rf_docs (doc_id, origem, tipo, assunto, data_entrega, link_download, texto_extraido, "
                     "chars_extraidos) VALUES (?, 'url', ?, ?, '2024-04-01', 'https://exemplo.invalido/teste.pdf', ?, ?)",
                     (doc_id, tipo, assunto, txt, len(txt)))
        conn.execute("INSERT INTO rf_doc_ativo VALUES (?, ?)", (doc_id, cod))
    conn.execute("INSERT INTO rf_docs_fts(rf_docs_fts) VALUES ('rebuild')")
    conn.commit()

    import extrai_rf
    import ingest_rf_cadastro
    import rf_grupo
    from utils import upsert
    upsert(conn, "rf_partes", ingest_rf_cadastro.partes_de_cadastro(conn, incluir_teste=True), conflict="chave")
    extrai_rf.processar(conn)
    rf_grupo.reconstruir(conn)
    return conn


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    destino = Path(sys.argv[1])
    if destino.exists():
        sys.exit(f"{destino} já existe; escolha outro caminho")
    montar(destino).close()
    print(f"base de teste em {destino}")
