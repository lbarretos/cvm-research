-- Habilita RLS em todas as tabelas e cria política de leitura pública.
-- service_role key bypassa RLS por design (necessário para o CI escrever).
-- anon key e authenticated key respeitam as policies abaixo (somente SELECT).

ALTER TABLE companies ENABLE ROW LEVEL SECURITY;
CREATE POLICY "read_public" ON companies FOR SELECT USING (true);

ALTER TABLE ipe_docs ENABLE ROW LEVEL SECURITY;
CREATE POLICY "read_public" ON ipe_docs FOR SELECT USING (true);

ALTER TABLE vlmo_posicao ENABLE ROW LEVEL SECURITY;
CREATE POLICY "read_public" ON vlmo_posicao FOR SELECT USING (true);

ALTER TABLE vlmo_movimentacoes ENABLE ROW LEVEL SECURITY;
CREATE POLICY "read_public" ON vlmo_movimentacoes FOR SELECT USING (true);

ALTER TABLE recompra_programas ENABLE ROW LEVEL SECURITY;
CREATE POLICY "read_public" ON recompra_programas FOR SELECT USING (true);

ALTER TABLE fre_capital_social ENABLE ROW LEVEL SECURITY;
CREATE POLICY "read_public" ON fre_capital_social FOR SELECT USING (true);

ALTER TABLE fre_posicao_acionaria ENABLE ROW LEVEL SECURITY;
CREATE POLICY "read_public" ON fre_posicao_acionaria FOR SELECT USING (true);

ALTER TABLE fre_remuneracao_orgao ENABLE ROW LEVEL SECURITY;
CREATE POLICY "read_public" ON fre_remuneracao_orgao FOR SELECT USING (true);
