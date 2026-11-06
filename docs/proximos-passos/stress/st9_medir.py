"""Etapa 9: qualidade do texto e lacunas de extração em ipe_docs, por camada (só leitura, ~9 min no banco vivo).

Uso: .venv/bin/python docs/proximos-passos/stress/st9_medir.py "$PWD/cvm_research.db"
"""
import sys
import sqlite3,re,collections,time
t0=time.time()
con=sqlite3.connect(f"file:{sys.argv[1]}?mode=ro",uri=True)
QUENTE_CAT=('Fato Relevante','Comunicado ao Mercado','Aviso aos Acionistas','Reunião da Administração')
st=collections.defaultdict(lambda: collections.Counter())
for cat,tipo,esp,dref,txt,falhou,nch in con.execute("SELECT categoria,tipo,especie,data_referencia,texto_extraido,extracao_falhou,chars_extraidos FROM ipe_docs"):
    quente = cat in QUENTE_CAT or (cat=='Assembleia' and esp in ('Ata','Proposta da Administração','Sumário das Decisões','Edital de Convocação')) or (cat=='Dados Econômico-Financeiros' and tipo=='Press-release')
    if quente: g='QUENTE'
    elif cat=='Dados Econômico-Financeiros' and (tipo or '').startswith('Demonstrações Financeiras'): g='DF:'+tipo.replace('Demonstrações Financeiras','DF')
    else: g='FRIA:'+cat
    c=st[g]; c['n']+=1
    if txt is None:
        c['falhou' if falhou else 'pendente']+=1; continue
    L=len(txt); c['chars']+=L
    cid=txt.count('(cid:')
    if cid*7/ max(L,1) > 0.01: c['cid>1%']+=1
    s=txt[:200000]; toks=re.findall(r'\S+',s)
    if toks:
        um=sum(1 for x in toks if len(x)==1 and x.isalpha())
        if um/len(toks)>0.25: c['letras_soltas']+=1
    if L<500: c['curto<500']+=1
print('%.0fs'%(time.time()-t0))
keys=['n','pendente','falhou','cid>1%','letras_soltas','curto<500','chars']
rows=sorted(st.items(),key=lambda kv:-kv[1]['n'])
print('grupo|'+'|'.join(keys))
for g,c in rows:
    if c['n']>=200 or g.startswith('DF') or g=='QUENTE': print(g+'|'+'|'.join(str(c[k]) if k!='chars' else f"{c[k]/1e9:.2f}G" for k in keys))
