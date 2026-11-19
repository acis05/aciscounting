import os, json, io, csv, secrets
from datetime import datetime, date
from decimal import Decimal, ROUND_HALF_UP
from contextlib import contextmanager
from fastapi import FastAPI, Request, Depends, Form, HTTPException
from fastapi.responses import RedirectResponse, StreamingResponse, Response, HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from sqlalchemy import create_engine, Column, Integer, String, ForeignKey, DateTime, Numeric, Text, Boolean, UniqueConstraint, func
from sqlalchemy.orm import declarative_base, sessionmaker
from argon2 import PasswordHasher
from openpyxl import Workbook
from reportlab.pdfgen.canvas import Canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import simpleSplit
from html import escape
from app.financial_reports import report_model, export_xlsx, export_pdf

D=Decimal
ZERO=D('0.00')
def dec(v):
    try: return D(str(v or 0)).quantize(D('.01'),rounding=ROUND_HALF_UP)
    except: raise HTTPException(400,'Angka tidak valid')
def cash(v): return 'Rp '+f'{dec(v):,.2f}'.replace(',','_').replace('.',',').replace('_','.')
DB=os.getenv('DATABASE_URL','sqlite:///./accounting.db').replace('postgres://','postgresql://',1)
engine=create_engine(DB,pool_pre_ping=True,connect_args={'check_same_thread':False} if DB.startswith('sqlite') else {})
Session=sessionmaker(bind=engine,expire_on_commit=False)
Base=declarative_base(); ph=PasswordHasher()
class User(Base):
 __tablename__='users';id=Column(Integer,primary_key=True);email=Column(String(200),unique=True,nullable=False);name=Column(String(120));password=Column(String(300));company_id=Column(Integer,ForeignKey('companies.id'))
class Company(Base):
 __tablename__='companies';id=Column(Integer,primary_key=True);name=Column(String(150),nullable=False);theme=Column(String(30),default='ocean');locked_through=Column(String(10),default='')
class Master(Base):
 __tablename__='masters';id=Column(Integer,primary_key=True);company_id=Column(Integer,index=True,nullable=False);kind=Column(String(25),nullable=False);code=Column(String(60),nullable=False);name=Column(String(180),nullable=False);extra=Column(Text,default='{}');active=Column(Boolean,default=True);__table_args__=(UniqueConstraint('company_id','kind','code'),)
class Document(Base):
 __tablename__='documents';id=Column(Integer,primary_key=True);company_id=Column(Integer,index=True,nullable=False);kind=Column(String(40),nullable=False);number=Column(String(60),nullable=False);date=Column(String(10),nullable=False);party_id=Column(Integer);warehouse_id=Column(Integer);status=Column(String(15),default='draft');memo=Column(Text,default='');payload=Column(Text,default='{}');created_at=Column(DateTime,default=datetime.utcnow);__table_args__=(UniqueConstraint('company_id','number'),)
class Journal(Base):
 __tablename__='journals';id=Column(Integer,primary_key=True);company_id=Column(Integer,index=True);doc_id=Column(Integer,ForeignKey('documents.id'),index=True);date=Column(String(10));account_id=Column(Integer);debit=Column(Numeric(18,2),default=0);credit=Column(Numeric(18,2),default=0);memo=Column(Text,default='')
class Stock(Base):
 __tablename__='stocks';id=Column(Integer,primary_key=True);company_id=Column(Integer,index=True);doc_id=Column(Integer,ForeignKey('documents.id'),index=True);date=Column(String(10));item_id=Column(Integer);warehouse_id=Column(Integer);qty=Column(Numeric(18,4),default=0);value=Column(Numeric(18,2),default=0);unit_cost=Column(Numeric(18,4),default=0)
Base.metadata.create_all(engine)
app=FastAPI(title='aciscounting.id',version='0.7.0')
app.add_middleware(SessionMiddleware,secret_key=os.getenv('SECRET_KEY','DEV_ONLY_CHANGE_THIS_SECRET'),https_only=os.getenv('COOKIE_SECURE','false').lower()=='true',same_site='lax')
ROOT=os.path.dirname(__file__);tplfilter=lambda v: json.loads(v or '{}');app.mount('/static',StaticFiles(directory=ROOT+'/static'),name='static');tpl=Jinja2Templates(directory=ROOT+'/templates');tpl.env.filters['from_json']=tplfilter
@app.exception_handler(HTTPException)
async def friendly_error(req:Request,exc:HTTPException):
 if req.url.path.startswith('/health') or 'application/json' in req.headers.get('accept',''):
  return Response(content=json.dumps({'detail':str(exc.detail)}),status_code=exc.status_code,media_type='application/json')
 message=escape(str(exc.detail))
 back=escape(req.headers.get('referer','/'),quote=True)
 return HTMLResponse(f'''<!doctype html><html lang="id"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Informasi Transaksi</title><style>body{{font-family:system-ui;background:#f2f8f4;color:#18392d;padding:30px}}.box{{background:white;border-radius:16px;padding:28px;max-width:540px;margin:9vh auto;box-shadow:0 12px 35px #1232}}a{{display:inline-block;padding:12px 18px;background:#0c8052;color:white;border-radius:9px;text-decoration:none}}</style><div class="box"><h2>Transaksi belum dapat diproses</h2><p>{message}</p><p>Periksa data atau pengaturan COA, lalu coba kembali.</p><a href="{back}">Kembali ke aplikasi</a></div></html>''',status_code=exc.status_code)

@app.get('/health')
def health():return {'status':'ok'}
def db():
 with Session() as s:yield s
def user(req,s):
 uid=req.session.get('uid');u=s.get(User,uid) if uid else None
 if not u:raise HTTPException(401,'Silakan login terlebih dahulu')
 return u
def owned(s,cls,id,cid):
 x=s.get(cls,id)
 if not x or x.company_id!=cid:raise HTTPException(404,'Data tidak ditemukan')
 return x
def go(path):return RedirectResponse(path,status_code=303)
def page(req,s,title,**ctx):
 try:u=user(req,s)
 except HTTPException:u=None
 c=s.get(Company,u.company_id) if u else None
 return tpl.TemplateResponse('app.html',{'request':req,'title':title,'user':u,'company':c,'cash':cash,'today':date.today().isoformat(),**ctx})
ACCOUNTS=[('1000','Kas','asset'),('1010','Bank','asset'),('1100','Piutang Usaha','asset'),('1200','Persediaan','asset'),('1500','Aset Tetap','asset'),('1590','Akumulasi Penyusutan','contra_asset'),('2000','Hutang Usaha','liability'),('3000','Modal','equity'),('4000','Penjualan','income'),('4010','Retur Penjualan','contra_income'),('5000','HPP','expense'),('6000','Beban Operasional','expense'),('6100','Beban Penyusutan','expense'),('1201','Selisih Persediaan','expense'),('1150','PPN Masukan','asset'),('2100','PPN Keluaran','liability')]
def seed(s,cid):
 for code,name,typ in ACCOUNTS:s.add(Master(company_id=cid,kind='coa',code=code,name=name,extra=json.dumps({'type':typ,'system_code':code})))
 s.add(Master(company_id=cid,kind='warehouse',code='GD-01',name='Gudang Utama'))
def master(s,cid,kind,mid):
 x=owned(s,Master,mid,cid)
 if x.kind!=kind:raise HTTPException(400,'Jenis master tidak sesuai')
 return x
SYSTEM_CODES={c:(n,t) for c,n,t in ACCOUNTS}
def system_code(x):
 e=json.loads(x.extra or '{}')
 return e.get('system_code') or x.code

def ensure_system_coas(s,cid):
 # Safe idempotent migration for older companies; do not replace renamed system accounts.
 existing=s.query(Master).filter_by(company_id=cid,kind='coa').all()
 aliases={system_code(x) for x in existing}
 for code,(name,typ) in SYSTEM_CODES.items():
  if code not in aliases:
   if any(x.code==code for x in existing):
    raise HTTPException(400,f'Kode akun {code} sudah dipakai akun lain; periksa COA')
   x=Master(company_id=cid,kind='coa',code=code,name=name,extra=json.dumps({'type':typ,'system_code':code}))
   s.add(x);existing.append(x)
 s.flush()

def coa(s,cid,code):
 ensure_system_coas(s,cid)
 for x in s.query(Master).filter_by(company_id=cid,kind='coa').all():
  if x.code==code or system_code(x)==code:return x.id
 raise HTTPException(400,f'Akun {code} belum tersedia')
def lines(s,doc,entries):
 debit=sum((dec(x[1]) for x in entries),ZERO);credit=sum((dec(x[2]) for x in entries),ZERO)
 if debit!=credit:raise HTTPException(400,f'Jurnal tidak seimbang: {debit} / {credit}')
 for code,dr,cr in entries:
  if dec(dr)<0 or dec(cr)<0:raise HTTPException(400,'Jurnal negatif tidak diperbolehkan')
  if dec(dr) or dec(cr):s.add(Journal(company_id=doc.company_id,doc_id=doc.id,date=doc.date,account_id=coa(s,doc.company_id,code),debit=dec(dr),credit=dec(cr),memo=doc.memo))
def balances(s,cid,item,warehouse=None):
 q=s.query(Stock).filter_by(company_id=cid,item_id=item)
 if warehouse:q=q.filter_by(warehouse_id=warehouse)
 rows=q.order_by(Stock.date,Stock.id).all()
 return sum((D(x.qty) for x in rows),D(0)),sum((D(x.value) for x in rows),D(0))
def move(s,doc,item,warehouse,qty,value):
 master(s,doc.company_id,'item',item);master(s,doc.company_id,'warehouse',warehouse)
 s.add(Stock(company_id=doc.company_id,doc_id=doc.id,date=doc.date,item_id=item,warehouse_id=warehouse,qty=qty,value=dec(value),unit_cost=(dec(value)/D(qty) if qty else 0)))
def stockout(s,doc,item,warehouse,qty):
 if qty<=0:raise HTTPException(400,'Jumlah harus positif')
 whq,_=balances(s,doc.company_id,item,warehouse)
 if whq<qty:raise HTTPException(400,'Stok gudang tidak cukup')
 totalq,totalv=balances(s,doc.company_id,item)
 cost=(totalv/totalq) if totalq>0 else D(0)
 value=dec(cost*qty);move(s,doc,item,warehouse,-qty,-value);return value

def post(s,doc):
 if doc.status!='draft':raise HTTPException(400,'Hanya draft yang dapat diposting')
 ensure_system_coas(s,doc.company_id)
 c=owned(s,Company,doc.company_id,doc.company_id) if False else s.get(Company,doc.company_id)
 if c.locked_through and doc.date<=c.locked_through:raise HTTPException(400,'Periode sudah dikunci')
 # Block backdated stock transactions to keep moving-average costs stable.
 if doc.kind in ('sale','purchase','sale_return','purchase_return','transfer','adjust'):
  latest=s.query(func.max(Stock.date)).filter_by(company_id=doc.company_id).scalar()
  if latest and doc.date<latest:raise HTTPException(400,'Transaksi stok tidak boleh mundur tanggal; gunakan tanggal terkini')
 p=json.loads(doc.payload);amount=dec(p.get('amount',0));qty=D(str(p.get('qty',0)));item=int(p.get('item_id') or 0);wh=int(doc.warehouse_id or 0);k=doc.kind;E=[]
 if k=='cash_in':E=[('1000',amount,0),(p.get('account','4000'),0,amount)]
 elif k=='cash_out':E=[(p.get('account','6000'),amount,0),('1000',0,amount)]
 elif k=='bank_in':E=[('1010',amount,0),(p.get('account','4000'),0,amount)]
 elif k=='bank_out':E=[(p.get('account','6000'),amount,0),('1010',0,amount)]
 elif k in ('sale','purchase','sale_return','purchase_return'):
  items=p.get('items',[])
  if not isinstance(items,list) or not items:raise HTTPException(400,'Tambahkan minimal satu baris barang atau jasa')
  subtotal=ZERO;tax=ZERO;cost_total=ZERO
  if len({str(z.get('item_id')) for z in items})!=len(items):raise HTTPException(400,'Barang yang sama cukup satu baris')
  original=None
  if k in ('sale_return','purchase_return'):
   source_id=int(p.get('source_id') or 0)
   original=owned(s,Document,source_id,doc.company_id)
   if original.kind!=('sale' if k=='sale_return' else 'purchase') or original.status!='posted':raise HTTPException(400,'Pilih faktur asal yang sudah diposting')
   if doc.party_id!=original.party_id:raise HTTPException(400,'Pelanggan/pemasok harus sama dengan faktur asal')
   if doc.date<original.date:raise HTTPException(400,'Tanggal retur tidak boleh sebelum faktur')
   source_lines={str(z.get('item_id')):z for z in json.loads(original.payload).get('items',[])}
  for line in items:
   iid=int(line.get('item_id') or 0);x=master(s,doc.company_id,'item',iid)
   quantity=D(str(line.get('qty') or 0));price=dec(line.get('price'));rate=dec(line.get('tax_rate',0))
   if quantity<=0 or price<0 or rate not in (ZERO,D('11.00'),D('12.00')):raise HTTPException(400,'Qty, harga, atau tarif PPN tidak valid')
   # Use 0%, 11%, 12% as configurable nominal rate; tax regulations can require different effective bases.
   base=dec(quantity*price);vat=dec(base*rate/D(100));subtotal+=base;tax+=vat
   item_type=json.loads(x.extra or '{}').get('type','goods')
   if item_type not in ('goods','service'):raise HTTPException(400,'Tipe barang/jasa tidak valid')
   if original:
    sl=source_lines.get(str(iid))
    if not sl:raise HTTPException(400,'Barang retur tidak ditemukan pada faktur asal')
    returned=ZERO
    other=s.query(Document).filter_by(company_id=doc.company_id,kind=k,status='posted').all()
    for r in other:
     rp=json.loads(r.payload)
     if int(rp.get('source_id') or 0)==original.id:
      returned+=sum((D(str(z.get('qty') or 0)) for z in rp.get('items',[]) if int(z.get('item_id') or 0)==iid),D(0))
    if quantity+returned>D(str(sl.get('qty') or 0)):raise HTTPException(400,'Jumlah retur melebihi faktur asal')
    if price!=dec(sl.get('price')) or rate!=dec(sl.get('tax_rate',0)):raise HTTPException(400,'Harga dan PPN retur harus sama dengan faktur asal')
   if item_type=='service' and k in ('purchase','purchase_return'):raise HTTPException(400,'Pembelian jasa belum didukung dalam modul persediaan; gunakan jurnal biaya')
   if item_type=='goods':
    if not wh:raise HTTPException(400,'Pilih gudang untuk barang persediaan')
    if k=='purchase':move(s,doc,iid,wh,quantity,base)
    elif k=='sale':
     value=stockout(s,doc,iid,wh,quantity);cost_total+=value
     line['posted_cost']=str(value)
    elif k=='sale_return':
     original_cost=dec(sl.get('posted_cost',0));original_qty=D(str(sl.get('qty')))
     value=dec(original_cost*quantity/original_qty)
     move(s,doc,iid,wh,quantity,value);cost_total+=value
    elif k=='purchase_return':cost_total+=stockout(s,doc,iid,wh,quantity)
  amount=subtotal+tax
  p['amount']=str(amount);p['subtotal']=str(subtotal);p['tax']=str(tax);doc.payload=json.dumps(p)
  if k=='purchase':
   E=[('1200',subtotal,0),('1150',tax,0),('2000',0,amount)]
  elif k=='sale':
   E=[('1100',amount,0),('4000',0,subtotal),('2100',0,tax),('5000',cost_total,0),('1200',0,cost_total)]
  elif k=='sale_return':
   E=[('4010',subtotal,0),('2100',tax,0),('1100',0,amount),('1200',cost_total,0),('5000',0,cost_total)]
  else:
   E=[('2000',amount,0),('1200',0,cost_total),('1150',0,tax)]
   difference=subtotal-cost_total
   if difference>0:E.append(('1201',0,difference))
   elif difference<0:E.append(('1201',-difference,0))
 elif k=='sale_receipt':E=[(p.get('bank','1010'),amount,0),('1100',0,amount)]
 elif k=='purchase_payment':E=[('2000',amount,0),(p.get('bank','1010'),0,amount)]
 elif k=='transfer':
  dst=int(p.get('to_warehouse') or 0)
  if dst==wh:raise HTTPException(400,'Gudang asal dan tujuan harus berbeda')
  cost=stockout(s,doc,item,wh,qty);move(s,doc,item,dst,qty,cost);E=[]
 elif k=='adjust':
  if qty==0:raise HTTPException(400,'Qty penyesuaian tidak boleh nol')
  if qty>0:
   cost=amount;move(s,doc,item,wh,qty,cost);E=[('1200',cost,0),('1201',0,cost)]
  else:
   cost=stockout(s,doc,item,wh,-qty);E=[('1201',cost,0),('1200',0,cost)]
 elif k=='journal':
  E=[(x['account'],dec(x.get('debit',0)),dec(x.get('credit',0))) for x in p.get('entries',[])]
 elif k=='depreciation':
  E=[('6100',amount,0),('1590',0,amount)]
 else:raise HTTPException(400,'Tipe dokumen tidak dikenali')
 if k not in ('transfer','journal') and amount<=0 and k!='adjust':raise HTTPException(400,'Nominal harus positif')
 if k=='journal' and not E:raise HTTPException(400,'Jurnal kosong')
 lines(s,doc,E);doc.status='posted'

KINDS={'cash_in':'Kas Masuk','cash_out':'Kas Keluar','bank_in':'Bank Masuk','bank_out':'Bank Keluar','sale':'Faktur Penjualan','sale_receipt':'Penerimaan Penjualan','sale_return':'Retur Penjualan','purchase':'Faktur Pembelian','purchase_payment':'Pembayaran Pembelian','purchase_return':'Retur Pembelian','transfer':'Transfer Gudang','adjust':'Penyesuaian Persediaan','journal':'Jurnal Umum','depreciation':'Penyusutan'}
MASTER_KINDS={'coa':'COA','customer':'Pelanggan','supplier':'Pemasok','item':'Barang / Jasa','warehouse':'Gudang','asset':'Aset Tetap'}
@app.get('/')
def home(req:Request,s=Depends(db)):
 try:u=user(req,s)
 except HTTPException:return go('/login')
 cid=u.company_id;docs=s.query(Document).filter_by(company_id=cid,status='posted').all();j=s.query(Journal).filter_by(company_id=cid).all();am={x.id:system_code(x) for x in s.query(Master).filter_by(company_id=cid,kind='coa')}
 def sumcode(code,side):return sum((D(getattr(x,side) or 0) for x in j if am.get(x.account_id)==code),ZERO)
 sales=sumcode('4000','credit')-sumcode('4010','debit');expenses=sum((D(x.debit or 0)-D(x.credit or 0) for x in j if am.get(x.account_id) in ('5000','6000','6100','1201')),ZERO)
 return page(req,s,'Dashboard',sales=sales,profit=sales-expenses,receivables=sumcode('1100','debit')-sumcode('1100','credit'),payables=sumcode('2000','credit')-sumcode('2000','debit'),docs=docs[-8:],doc_kinds=KINDS,months=[{'label':f'{m:02d}','sales':float(sum((D(x.credit or 0) for x in j if am.get(x.account_id)=='4000' and x.date[5:7]==f'{m:02d}'),ZERO))} for m in range(1,13)])
@app.get('/register')
def regpage(req:Request,s=Depends(db)):return page(req,s,'Daftar')
@app.post('/register')
def register(req:Request,name:str=Form(...),email:str=Form(...),password:str=Form(...),company:str=Form(...),s=Depends(db)):
 email=email.lower().strip()
 if len(password)<10:raise HTTPException(400,'Password minimal 10 karakter')
 if s.query(User).filter_by(email=email).first():raise HTTPException(400,'Email sudah terdaftar')
 c=Company(name=company[:150]);s.add(c);s.flush();u=User(name=name[:120],email=email,password=ph.hash(password),company_id=c.id);s.add(u);seed(s,c.id);s.commit();req.session.clear();req.session['uid']=u.id;return go('/')
@app.get('/login')
def loginpage(req:Request,s=Depends(db)):return page(req,s,'Login')
@app.post('/login')
def login(req:Request,email:str=Form(...),password:str=Form(...),s=Depends(db)):
 u=s.query(User).filter_by(email=email.lower().strip()).first()
 if not u or not ph.verify(u.password,password):raise HTTPException(401,'Email atau password salah')
 req.session.clear();req.session['uid']=u.id;return go('/')
@app.post('/logout')
def logout(req:Request):req.session.clear();return go('/login')
@app.get('/masters/{kind}')
def masters(req:Request,kind:str,s=Depends(db)):
 u=user(req,s)
 if kind not in MASTER_KINDS:raise HTTPException(404)
 items=s.query(Master).filter_by(company_id=u.company_id,kind=kind).order_by(Master.code).all()
 return page(req,s,MASTER_KINDS[kind],items=items,kind=kind,kind_label=MASTER_KINDS[kind])
async def master_extra(req,kind):
 f=await req.form()
 if kind=='coa':return {'type':f.get('account_type') or 'asset'}
 if kind=='item':return {'type':f.get('item_type') or 'goods'}
 if kind=='asset':
  cost=dec(f.get('asset_cost'));residual=dec(f.get('asset_residual'))
  months=int(f.get('asset_months') or 0)
  if months<1 or cost<residual:raise HTTPException(400,'Data aset tidak valid')
  return {'cost':str(cost),'residual':str(residual),'months':months,'start':f.get('asset_start') or date.today().strftime('%Y-%m')}
 return {}

@app.post('/masters/{kind}')
async def master_add(req:Request,kind:str,code:str=Form(...),name:str=Form(...),extra:str=Form('{}'),s=Depends(db)):
 u=user(req,s)
 if kind not in MASTER_KINDS:raise HTTPException(404)
 data=await master_extra(req,kind)
 if s.query(Master).filter_by(company_id=u.company_id,kind=kind,code=code.strip()).first():raise HTTPException(400,'Kode sudah dipakai')
 s.add(Master(company_id=u.company_id,kind=kind,code=code.strip()[:60],name=name.strip()[:180],extra=json.dumps(data)));s.commit();return go('/masters/'+kind)
@app.post('/masters/{kind}/{mid}/edit')
async def master_edit(req:Request,kind:str,mid:int,code:str=Form(...),name:str=Form(...),extra:str=Form('{}'),s=Depends(db)):
 u=user(req,s);x=master(s,u.company_id,kind,mid)
 data=await master_extra(req,kind)
 if s.query(Master).filter(Master.company_id==u.company_id,Master.kind==kind,Master.code==code.strip(),Master.id!=mid).first():
  raise HTTPException(400,'Kode sudah digunakan master lain')
 if kind=='coa':
  old=json.loads(x.extra or '{}')
  system=old.get('system_code') or (x.code if x.code in SYSTEM_CODES else None)
  if system:
   data['system_code']=system
   # Account classification drives financial reports: do not silently change system account class.
   data['type']=SYSTEM_CODES[system][1]
 x.code=code.strip()[:60];x.name=name.strip()[:180];x.extra=json.dumps(data);s.commit();return go('/masters/'+kind)
@app.post('/masters/{kind}/{mid}/delete')
def master_delete(req:Request,kind:str,mid:int,s=Depends(db)):
 u=user(req,s);x=master(s,u.company_id,kind,mid)
 if kind=='coa' and (system_code(x) in SYSTEM_CODES or s.query(Journal).filter_by(company_id=u.company_id,account_id=mid).first()):raise HTTPException(400,'Akun sistem atau akun terpakai tidak bisa dihapus')
 if kind=='warehouse' and s.query(Stock).filter_by(company_id=u.company_id,warehouse_id=mid).first():raise HTTPException(400,'Gudang sudah memiliki mutasi')
 if kind=='item' and s.query(Stock).filter_by(company_id=u.company_id,item_id=mid).first():raise HTTPException(400,'Barang sudah memiliki mutasi')
 if s.query(Document).filter_by(company_id=u.company_id,party_id=mid).first():raise HTTPException(400,'Master digunakan dokumen')
 s.delete(x);s.commit();return go('/masters/'+kind)
@app.get('/transactions')
def transactions_overview(req:Request,s=Depends(db)):
 u=user(req,s)
 docs=s.query(Document).filter_by(company_id=u.company_id).order_by(Document.date.desc(),Document.id.desc()).limit(500).all()
 return page(req,s,'Semua Transaksi',transaction_overview=docs,transaction_names={k:v for k,v in KINDS.items() if k!='depreciation'})

@app.get('/documents/{kind}')
def documents(req:Request,kind:str,view:str='',s=Depends(db)):
 u=user(req,s)
 if kind not in KINDS:raise HTTPException(404)
 items=s.query(Document).filter_by(company_id=u.company_id,kind=kind).order_by(Document.id.desc()).all()
 lists={k:s.query(Master).filter_by(company_id=u.company_id,kind=k).all() for k in ('customer','supplier','item','warehouse','coa','asset')}
 return page(req,s,KINDS[kind],kind=kind,items=items,lists=lists,kind_label=KINDS[kind],list_only=(view=='list'),invoice_sources=s.query(Document).filter_by(company_id=u.company_id,kind=('sale' if kind=='sale_return' else 'purchase'),status='posted').all() if kind in ('sale_return','purchase_return') else [],doc_details={d.id:json.loads(d.payload) for d in items})
LINE_KINDS=('sale','purchase','sale_return','purchase_return')
async def form_payload(req,s,cid,kind):
 form=await req.form()
 if kind in LINE_KINDS:
  ids=form.getlist('item_id[]');qtys=form.getlist('qty[]');prices=form.getlist('price[]');rates=form.getlist('tax_rate[]')
  if not (len(ids)==len(qtys)==len(prices)==len(rates)):raise HTTPException(400,'Tabel barang tidak lengkap')
  rows=[]
  for iid,qty,price,rate in zip(ids,qtys,prices,rates):
   if not iid:continue
   master(s,cid,'item',int(iid))
   rows.append({'item_id':int(iid),'qty':str(qty),'price':str(price),'tax_rate':str(rate)})
  if not rows:raise HTTPException(400,'Tambahkan minimal satu barang/jasa')
  p={'items':rows}
  if kind.endswith('return'):p['source_id']=int(form.get('source_id') or 0)
  return p
 if kind=='journal':
  entries=[]
  for code,dr,cr in zip(form.getlist('account[]'),form.getlist('debit[]'),form.getlist('credit[]')):
   if code and (dec(dr) or dec(cr)):entries.append({'account':code,'debit':str(dr or 0),'credit':str(cr or 0)})
  return {'entries':entries}
 if kind in ('transfer','adjust'):
  return {'item_id':int(form.get('single_item_id') or 0),'qty':str(form.get('single_qty') or 0),'amount':str(form.get('single_amount') or 0),'to_warehouse':int(form.get('to_warehouse') or 0)}
 return {'amount':str(form.get('amount') or 0),'account':form.get('account') or '6000','bank':form.get('bank') or '1010'}

@app.post('/documents/{kind}')
async def document_add(req:Request,kind:str,number:str=Form(...),date_value:str=Form(...,alias='date'),party_id:int=Form(0),warehouse_id:int=Form(0),memo:str=Form(''),payload:str=Form('{}'),s=Depends(db)):
 u=user(req,s)
 if kind not in KINDS:raise HTTPException(404)
 try:date.fromisoformat(date_value)
 except:raise HTTPException(400,'Tanggal tidak valid')
 p=await form_payload(req,s,u.company_id,kind)
 if party_id:master(s,u.company_id,'customer' if kind in ('sale','sale_receipt','sale_return') else 'supplier' if kind in ('purchase','purchase_payment','purchase_return') else 'customer',party_id)
 if warehouse_id:master(s,u.company_id,'warehouse',warehouse_id)
 doc=Document(company_id=u.company_id,kind=kind,number=number.strip()[:60],date=date_value,party_id=party_id or None,warehouse_id=warehouse_id or None,memo=memo[:1000],payload=json.dumps(p));s.add(doc);s.commit();return go('/documents/'+kind)
@app.post('/documents/{kind}/{did}/edit')
async def document_edit(req:Request,kind:str,did:int,number:str=Form(...),date_value:str=Form(...,alias='date'),party_id:int=Form(0),warehouse_id:int=Form(0),memo:str=Form(''),payload:str=Form('{}'),s=Depends(db)):
 u=user(req,s);x=owned(s,Document,did,u.company_id)
 if x.kind!=kind or x.status!='draft':raise HTTPException(400,'Hanya draft yang bisa diedit')
 try:date.fromisoformat(date_value)
 except:raise HTTPException(400,'Tanggal tidak valid')
 p=await form_payload(req,s,u.company_id,kind)
 if party_id:master(s,u.company_id,'customer' if kind in ('sale','sale_receipt','sale_return') else 'supplier' if kind in ('purchase','purchase_payment','purchase_return') else 'customer',party_id)
 if warehouse_id:master(s,u.company_id,'warehouse',warehouse_id)
 x.number=number.strip()[:60];x.date=date_value;x.party_id=party_id or None;x.warehouse_id=warehouse_id or None;x.memo=memo[:1000];x.payload=json.dumps(p);s.commit();return go('/documents/'+kind)
@app.post('/documents/{kind}/{did}/delete')
def document_delete(req:Request,kind:str,did:int,s=Depends(db)):
 u=user(req,s);x=owned(s,Document,did,u.company_id)
 if x.kind!=kind or x.status!='draft':raise HTTPException(400,'Hanya draft dapat dihapus')
 s.delete(x);s.commit();return go('/documents/'+kind)
@app.post('/documents/{kind}/{did}/post')
def document_post(req:Request,kind:str,did:int,s=Depends(db)):
 u=user(req,s);x=owned(s,Document,did,u.company_id)
 if x.kind!=kind:raise HTTPException(404)
 try:post(s,x);s.commit()
 except:s.rollback();raise
 return go('/documents/'+kind)
@app.get('/documents/sale/{did}/print/{print_type}')
def print_sale(req:Request,did:int,print_type:str,s=Depends(db)):
 u=user(req,s)
 if print_type not in ('invoice','delivery'):raise HTTPException(404,'Jenis cetakan tidak ditemukan')
 doc=owned(s,Document,did,u.company_id)
 if doc.kind!='sale' or doc.status!='posted':raise HTTPException(400,'Cetak hanya tersedia untuk faktur penjualan yang sudah diposting')
 company=s.get(Company,u.company_id)
 party=master(s,u.company_id,'customer',doc.party_id) if doc.party_id else None
 payload=json.loads(doc.payload or '{}')
 output=io.BytesIO();pdf=Canvas(output,pagesize=A4)
 W,H=A4; margin=42;y=H-48
 def txt(x,y,value,size=10,bold=False):
  pdf.setFont('Helvetica-Bold' if bold else 'Helvetica',size)
  pdf.drawString(x,y,str(value).encode('latin-1','replace').decode('latin-1'))
 def header():
  nonlocal y
  y=H-48
  txt(margin,y,company.name,16,True);y-=28
  txt(margin,y,'FAKTUR PENJUALAN' if print_type=='invoice' else 'SURAT JALAN',14,True);y-=24
  txt(margin,y,'Nomor: '+doc.number+'    Tanggal: '+doc.date);y-=18
  txt(margin,y,'Pelanggan: '+(party.name if party else '-'));y-=24
  pdf.line(margin,y,W-margin,y);y-=22
  txt(margin,y,'No.',9,True);txt(margin+32,y,'Barang / Jasa',9,True);txt(margin+290,y,'Qty',9,True)
  if print_type=='invoice':txt(margin+350,y,'Harga',9,True);txt(margin+440,y,'Jumlah',9,True)
  y-=18
 header()
 subtotal=Decimal('0');tax=Decimal('0')
 for idx,line in enumerate(payload.get('items',[]),1):
  if y<110:pdf.showPage();header()
  item=master(s,u.company_id,'item',int(line['item_id']))
  q=Decimal(str(line['qty']));price=dec(line['price']);base=dec(q*price);vat=dec(base*dec(line.get('tax_rate',0))/100)
  subtotal+=base;tax+=vat
  name=item.name[:42]
  txt(margin,y,str(idx),9);txt(margin+32,y,name,9);txt(margin+290,y,str(q.normalize()),9)
  if print_type=='invoice':txt(margin+350,y,f'{price:,.0f}',9);txt(margin+440,y,f'{base:,.0f}',9)
  y-=22
 if print_type=='invoice':
  if y<115:pdf.showPage();header()
  pdf.line(margin,y,W-margin,y);y-=22
  txt(margin+290,y,'Subtotal',10,True);txt(margin+440,y,f'{subtotal:,.0f}',10);y-=19
  txt(margin+290,y,'PPN',10,True);txt(margin+440,y,f'{tax:,.0f}',10);y-=19
  txt(margin+290,y,'Total',11,True);txt(margin+440,y,f'{subtotal+tax:,.0f}',11,True)
 else:
  if y<125:pdf.showPage();header()
  y-=45;txt(margin,y,'Diterima oleh,');txt(margin+310,y,'Diserahkan oleh,');y-=65
  txt(margin,y,'(____________________)');txt(margin+310,y,'(____________________)')
 pdf.save();output.seek(0)
 filename=('faktur-' if print_type=='invoice' else 'surat-jalan-')+str(doc.id)+'.pdf'
 return StreamingResponse(output,media_type='application/pdf',headers={'Content-Disposition':f'inline; filename="{filename}"'})

@app.get('/reports/{name}')
def report(req:Request,name:str,format:str='html',start:str='',end:str='',account_id:int=0,s=Depends(db)):
 u=user(req,s);cid=u.company_id
 if name in ('profit','balance','ledger','cashflow'):
  today=date.today().isoformat();end=end or today;start=start or (today[:4]+'-01-01')
  try:date.fromisoformat(start);date.fromisoformat(end)
  except ValueError:raise HTTPException(400,'Format tanggal tidak valid')
  accounts=s.query(Master).filter_by(company_id=cid,kind='coa').all()
  journals=s.query(Journal).filter_by(company_id=cid).order_by(Journal.date,Journal.id).all()
  documents=s.query(Document).filter_by(company_id=cid).all()
  if account_id and not any(a.id==account_id for a in accounts):raise HTTPException(404,'Akun tidak ditemukan')
  rows,notes=report_model(name,accounts,journals,documents,start,end,account_id or None)
  titles={'profit':'Laporan Laba Rugi','balance':'Laporan Posisi Keuangan (Neraca)','ledger':'Buku Besar','cashflow':'Laporan Arus Kas'}
  title=titles[name];period=('Per '+end if name=='balance' else 'Periode '+start+' s.d. '+end)
  company=s.get(Company,cid).name
  if format=='xlsx':return export_xlsx(title,company,period,rows,notes,name)
  if format=='pdf':return export_pdf(title,company,period,rows,notes,name)
  if format!='html':raise HTTPException(400,'Format ekspor tidak dikenal')
  return page(req,s,title,report_name=name,financial_rows=rows,financial_notes=notes,report_start=start,report_end=end,report_account_id=account_id,report_accounts=sorted(accounts,key=lambda x:x.code),report_period=period)
 coa_rows=s.query(Master).filter_by(company_id=cid,kind='coa').all();am={x.id:x for x in coa_rows};js=s.query(Journal).filter_by(company_id=cid).order_by(Journal.date,Journal.id).all();ss=s.query(Stock).filter_by(company_id=cid).order_by(Stock.date,Stock.id).all();docs={x.id:x for x in s.query(Document).filter_by(company_id=cid)}
 data=[];heads=[]
 if name in ('journals','ledger','trial','profit','balance','cashflow','bank'):
  if name=='journals':heads=['Tanggal','Dokumen','Akun','Debit','Kredit'];data=[[x.date,docs[x.doc_id].number,am[x.account_id].code+' '+am[x.account_id].name,float(x.debit),float(x.credit)] for x in js]
  elif name=='ledger':heads=['Tanggal','Dokumen','Akun','Debit','Kredit'];data=[[x.date,docs[x.doc_id].number,am[x.account_id].code+' '+am[x.account_id].name,float(x.debit),float(x.credit)] for x in sorted(js,key=lambda z:(am[z.account_id].code,z.date,z.id))]
  elif name=='bank':heads=['Tanggal','Dokumen','Akun','Masuk','Keluar'];data=[[x.date,docs[x.doc_id].number,am[x.account_id].name,float(x.debit),float(x.credit)] for x in js if system_code(am[x.account_id]) in ('1000','1010')]
  else:
   totals={x.id:[ZERO,ZERO] for x in coa_rows}
   for j in js:totals[j.account_id][0]+=D(j.debit);totals[j.account_id][1]+=D(j.credit)
   if name=='trial':heads=['Kode','Akun','Debit','Kredit'];data=[[x.code,x.name,float(max(0,totals[x.id][0]-totals[x.id][1])),float(max(0,totals[x.id][1]-totals[x.id][0]))] for x in coa_rows]
   elif name=='profit':heads=['Kode','Akun','Saldo (Kredit - Debit)'];data=[[x.code,x.name,float(totals[x.id][1]-totals[x.id][0])] for x in coa_rows if json.loads(x.extra or '{}').get('type') in ('income','contra_income','expense')]
   elif name=='balance':heads=['Kode','Akun','Saldo (Debit - Kredit)'];data=[[x.code,x.name,float(totals[x.id][0]-totals[x.id][1])] for x in coa_rows if json.loads(x.extra or '{}').get('type') in ('asset','contra_asset','liability','equity')]
   else:heads=['Aktivitas','Jumlah'];data=[['Kas dan Bank - Saldo Bersih',float(sum((D(x.debit)-D(x.credit) for x in js if system_code(am[x.account_id]) in ('1000','1010')),ZERO))]]
 elif name in ('stock','valuation'):
  heads=['Barang','Gudang','Qty','Nilai'];pairs=sorted({(x.item_id,x.warehouse_id) for x in ss});data=[]
  for iid,wid in pairs:
   q=sum((D(x.qty) for x in ss if x.item_id==iid and x.warehouse_id==wid),D(0));v=sum((D(x.value) for x in ss if x.item_id==iid and x.warehouse_id==wid),D(0))
   data.append([s.get(Master,iid).name,s.get(Master,wid).name,float(q),float(v)])
 elif name in ('receivables','payables'):
  code='1100' if name=='receivables' else '2000';heads=['Dokumen','Tanggal','Debit','Kredit'];data=[[docs[x.doc_id].number,x.date,float(x.debit),float(x.credit)] for x in js if system_code(am[x.account_id])==code]
 elif name=='assets':
  heads=['Kode','Aset','Harga Perolehan','Residu','Umur (bulan)','Penyusutan/Bulan'];data=[]
  for a in s.query(Master).filter_by(company_id=cid,kind='asset'):
   e=json.loads(a.extra or '{}');cost=dec(e.get('cost',0));res=dec(e.get('residual',0));life=int(e.get('months',1) or 1);data.append([a.code,a.name,float(cost),float(res),life,float(max(ZERO,(cost-res)/life))])
 else:raise HTTPException(404,'Laporan tidak ditemukan')
 if format=='xlsx':
  wb=Workbook();ws=wb.active;ws.title='Laporan';ws.append(heads)
  for r in data:ws.append(r)
  out=io.BytesIO();wb.save(out);out.seek(0);return StreamingResponse(out,media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',headers={'Content-Disposition':f'attachment; filename="{name}.xlsx"'})
 if format=='pdf':
  out=io.BytesIO();p=Canvas(out,pagesize=A4);y=800;p.setFont('Helvetica-Bold',15);p.drawString(35,y,'Laporan '+name);y-=30;p.setFont('Helvetica',8)
  for r in [heads]+data:
   if y<45:p.showPage();y=800;p.setFont('Helvetica',8)
   p.drawString(35,y,' | '.join(str(v)[:30] for v in r)[:115]);y-=15
  p.save();out.seek(0);return StreamingResponse(out,media_type='application/pdf',headers={'Content-Disposition':f'attachment; filename="{name}.pdf"'})
 return page(req,s,'Laporan '+name,report_name=name,heads=heads,rows=data)
@app.post('/settings')
def settings(req:Request,theme:str=Form(...),locked_through:str=Form(''),s=Depends(db)):
 u=user(req,s);c=s.get(Company,u.company_id)
 if theme not in ('ocean','emerald','dark','sand'):raise HTTPException(400,'Tema tidak dikenal')
 if locked_through:date.fromisoformat(locked_through)
 c.theme=theme;c.locked_through=locked_through;s.commit();return go('/')
@app.post('/assets/{asset_id}/depreciate')
def depreciate(req:Request,asset_id:int,period:str=Form(...),s=Depends(db)):
 u=user(req,s);a=master(s,u.company_id,'asset',asset_id)
 try:period_date=date.fromisoformat(period+'-01')
 except:raise HTTPException(400,'Periode harus YYYY-MM')
 e=json.loads(a.extra or '{}');cost=dec(e.get('cost',0));res=dec(e.get('residual',0));life=int(e.get('months',0) or 0)
 if life<=0 or cost<res:raise HTTPException(400,'Isi extra aset: cost, residual, months yang valid')
 start=e.get('start',date.today().strftime('%Y-%m'))
 if period<start:raise HTTPException(400,'Periode sebelum tanggal mulai penyusutan')
 months=(int(period[:4])-int(start[:4]))*12+int(period[5:7])-int(start[5:7])+1
 if months<1 or months>life:raise HTTPException(400,'Periode di luar umur manfaat')
 number=f'DEP-{asset_id}-{period}'
 if s.query(Document).filter_by(company_id=u.company_id,number=number).first():raise HTTPException(400,'Penyusutan periode ini sudah dibuat')
 amount=dec((cost-res)/life)
 if months==life:amount=(cost-res)-amount*(life-1)
 doc=Document(company_id=u.company_id,kind='depreciation',number=number,date=period_date.isoformat(),memo=f'Penyusutan {a.name} {period}',payload=json.dumps({'amount':str(amount),'asset_id':asset_id}));s.add(doc);s.flush();post(s,doc);s.commit();return go('/reports/assets')
