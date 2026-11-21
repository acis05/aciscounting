import os, json, io, csv, secrets, base64
from datetime import datetime, date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from contextlib import contextmanager
from fastapi import FastAPI, Request, Depends, Form, HTTPException, UploadFile, File
from fastapi.responses import RedirectResponse, StreamingResponse, Response, HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from sqlalchemy import create_engine, Column, Integer, String, ForeignKey, DateTime, Numeric, Text, Boolean, UniqueConstraint, func
from sqlalchemy.orm import declarative_base, sessionmaker
from argon2 import PasswordHasher
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill, Alignment
from reportlab.pdfgen.canvas import Canvas
from reportlab.lib.pagesizes import A4, A5, letter
from reportlab.lib.utils import simpleSplit, ImageReader
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
 __tablename__='companies';id=Column(Integer,primary_key=True);name=Column(String(150),nullable=False);theme=Column(String(30),default='ocean');locked_through=Column(String(10),default='');cutoff_date=Column(String(10),default='')
class Master(Base):
 __tablename__='masters';id=Column(Integer,primary_key=True);company_id=Column(Integer,index=True,nullable=False);kind=Column(String(25),nullable=False);code=Column(String(60),nullable=False);name=Column(String(180),nullable=False);extra=Column(Text,default='{}');active=Column(Boolean,default=True);__table_args__=(UniqueConstraint('company_id','kind','code'),)
class Document(Base):
 __tablename__='documents';id=Column(Integer,primary_key=True);company_id=Column(Integer,index=True,nullable=False);kind=Column(String(40),nullable=False);number=Column(String(60),nullable=False);date=Column(String(10),nullable=False);party_id=Column(Integer);warehouse_id=Column(Integer);status=Column(String(15),default='draft');memo=Column(Text,default='');payload=Column(Text,default='{}');created_at=Column(DateTime,default=datetime.utcnow);__table_args__=(UniqueConstraint('company_id','number'),)
class Journal(Base):
 __tablename__='journals';id=Column(Integer,primary_key=True);company_id=Column(Integer,index=True);doc_id=Column(Integer,ForeignKey('documents.id'),index=True);date=Column(String(10));account_id=Column(Integer);debit=Column(Numeric(18,2),default=0);credit=Column(Numeric(18,2),default=0);memo=Column(Text,default='')
class Stock(Base):
 __tablename__='stocks';id=Column(Integer,primary_key=True);company_id=Column(Integer,index=True);doc_id=Column(Integer,ForeignKey('documents.id'),index=True);date=Column(String(10));item_id=Column(Integer);warehouse_id=Column(Integer);qty=Column(Numeric(18,4),default=0);value=Column(Numeric(18,2),default=0);unit_cost=Column(Numeric(18,4),default=0)
class JournalParty(Base):
 __tablename__='journal_parties';id=Column(Integer,primary_key=True);journal_id=Column(Integer,ForeignKey('journals.id'),unique=True);company_id=Column(Integer,index=True);party_id=Column(Integer,index=True)
class Activity(Base):
 __tablename__='activities';id=Column(Integer,primary_key=True);company_id=Column(Integer,index=True);user_id=Column(Integer);action=Column(String(40));entity=Column(String(40));entity_id=Column(Integer);detail=Column(Text);created_at=Column(DateTime,default=datetime.utcnow)
class MemberRole(Base):
 __tablename__='member_roles';id=Column(Integer,primary_key=True);company_id=Column(Integer,index=True);user_id=Column(Integer,unique=True);role=Column(String(30),default='viewer')
class RoleRule(Base):
 __tablename__='role_rules';id=Column(Integer,primary_key=True);company_id=Column(Integer,index=True);role=Column(String(30));module=Column(String(40));action=Column(String(20));allowed=Column(Boolean,default=False);__table_args__=(UniqueConstraint('company_id','role','module','action'),)
class PrintTemplate(Base):
 __tablename__='print_templates';id=Column(Integer,primary_key=True);company_id=Column(Integer,index=True);kind=Column(String(20));paper=Column(String(15),default='A4');title=Column(String(100));footer=Column(String(300));logo=Column(Text,default='');settings=Column(Text,default='{}');__table_args__=(UniqueConstraint('company_id','kind'),)
Base.metadata.create_all(engine)
# Additive schema migration for PostgreSQL and SQLite; no existing columns removed.
from sqlalchemy import inspect, text as sqltext
with engine.begin() as connection:
 if 'companies' in inspect(connection).get_table_names() and 'cutoff_date' not in {c['name'] for c in inspect(connection).get_columns('companies')}:
  connection.execute(sqltext("ALTER TABLE companies ADD COLUMN cutoff_date VARCHAR(10) DEFAULT ''"))
 if 'print_templates' in inspect(connection).get_table_names() and 'settings' not in {c['name'] for c in inspect(connection).get_columns('print_templates')}:
  connection.execute(sqltext("ALTER TABLE print_templates ADD COLUMN settings TEXT DEFAULT '{}'"))
app=FastAPI(title='aciscounting.id',version='1.5.0')
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
def role_of(s,u):
 r=s.query(MemberRole).filter_by(user_id=u.id,company_id=u.company_id).first()
 return r.role if r else 'owner'
MODULES={'masters':'Master Data','documents':'Transaksi','reports':'Laporan','print':'Desain Cetakan','audit':'Audit Trail','access':'Hak Akses','settings':'Pengaturan'}
ACTIONS={'read':'Lihat','write':'Tambah / Edit / Hapus Draft','post':'Posting','manage':'Kelola'}
def authorize(s,u,action,module=None):
 role=role_of(s,u)
 rules={'owner':{'read','write','post','manage'},'admin':{'read','write','post'},'accounting':{'read','write','post'},'sales':{'read','write'},'purchasing':{'read','write'},'viewer':{'read'}}
 if role=='owner':return
 if module:
  override=s.query(RoleRule).filter_by(company_id=u.company_id,role=role,module=module,action=action).first()
  if override is not None:
   if not override.allowed:raise HTTPException(403,'Akses modul ini tidak diizinkan')
   return
 if action not in rules.get(role,{'read'}):raise HTTPException(403,'Hak akses tidak cukup untuk tindakan ini')
def audit(s,u,action,entity,entity_id,detail=''):
 s.add(Activity(company_id=u.company_id,user_id=u.id,action=action,entity=entity,entity_id=entity_id,detail=str(detail)[:3000]))
def go(path):return RedirectResponse(path,status_code=303)
def page(req,s,title,**ctx):
 try:u=user(req,s)
 except HTTPException:u=None
 c=s.get(Company,u.company_id) if u else None
 return tpl.TemplateResponse('app.html',{'request':req,'title':title,'user':u,'company':c,'cash':cash,'today':date.today().isoformat(),**ctx})
ACCOUNTS=[('1000','Kas','cash'),('1010','Bank','bank'),('1100','Piutang Usaha','receivable'),('1200','Persediaan','asset'),('1500','Aset Tetap','asset'),('1590','Akumulasi Penyusutan','contra_asset'),('2000','Hutang Usaha','payable'),('3000','Modal','equity'),('3090','Opening Balance Equity','equity'),('4000','Penjualan','income'),('4010','Retur Penjualan','contra_income'),('5000','HPP','cogs'),('6000','Beban Operasional','expense'),('6100','Beban Penyusutan','expense'),('1201','Selisih Persediaan','expense'),('1150','PPN Masukan','asset'),('2100','PPN Keluaran','liability')]
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
 for x in existing:
  code=system_code(x)
  if code in ('1000','1010','1100','2000','5000'):
   data=json.loads(x.extra or '{}');data['type']=SYSTEM_CODES[code][1];data['system_code']=code;x.extra=json.dumps(data)
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
def account_type(x):
 return json.loads(x.extra or '{}').get('type','asset')
def account_for(s,cid,code,allowed=None):
 aid=coa(s,cid,code);x=s.get(Master,aid)
 if allowed and account_type(x) not in allowed:raise HTTPException(400,'Tipe akun tidak sesuai: '+x.name)
 return x
def item_accounts(s,cid,item):
 e=json.loads(item.extra or '{}');kind=e.get('type','goods')
 fields=('inventory_account','cogs_account','income_account') if kind=='goods' else ('expense_account','cogs_account','income_account')
 defaults={'inventory_account':'1200','cogs_account':'5000','income_account':'4000','expense_account':'6000'}
 return kind,{f:account_for(s,cid,e.get(f) or defaults[f]).code for f in fields}
def lines(s,doc,entries):
 debit=sum((dec(x[1]) for x in entries),ZERO);credit=sum((dec(x[2]) for x in entries),ZERO)
 if debit!=credit:raise HTTPException(400,f'Jurnal tidak seimbang: {debit} / {credit}')
 for code,dr,cr in entries:
  if dec(dr)<0 or dec(cr)<0:raise HTTPException(400,'Jurnal negatif tidak diperbolehkan')
  if dec(dr) or dec(cr):
   j=Journal(company_id=doc.company_id,doc_id=doc.id,date=doc.date,account_id=coa(s,doc.company_id,code),debit=dec(dr),credit=dec(cr),memo=doc.memo);s.add(j);s.flush()
   typ=account_type(s.get(Master,j.account_id))
   if typ in ('receivable','payable'):
    party=doc.party_id
    if doc.kind=='journal':
     for ent in json.loads(doc.payload or '{}').get('entries',[]):
      if ent.get('account')==code and dec(ent.get('debit',0))==dec(dr) and dec(ent.get('credit',0))==dec(cr):party=int(ent.get('party_id') or 0);break
    if party:s.add(JournalParty(journal_id=j.id,company_id=doc.company_id,party_id=party))
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
 if c.cutoff_date and doc.date<c.cutoff_date:raise HTTPException(400,'Tanggal transaksi sebelum tanggal mulai pakai aplikasi')
 if c.locked_through and doc.date<=c.locked_through:raise HTTPException(400,'Periode sudah dikunci')
 # Block backdated stock transactions to keep moving-average costs stable.
 if doc.kind in ('sale','purchase','sale_return','purchase_return','transfer','adjust'):
  latest=s.query(func.max(Stock.date)).filter_by(company_id=doc.company_id).scalar()
  if latest and doc.date<latest:raise HTTPException(400,'Transaksi stok tidak boleh mundur tanggal; gunakan tanggal terkini')
 p=json.loads(doc.payload);amount=dec(p.get('amount',0));qty=D(str(p.get('qty',0)));item=int(p.get('item_id') or 0);wh=int(doc.warehouse_id or 0);k=doc.kind;E=[]
 if k=='cash_in':E=[(account_for(s,doc.company_id,p.get('cash_bank_account','1000'),('cash',)).code,amount,0),(p.get('account','4000'),0,amount)]
 elif k=='cash_out':E=[(p.get('account','6000'),amount,0),(account_for(s,doc.company_id,p.get('cash_bank_account','1000'),('cash',)).code,0,amount)]
 elif k=='bank_in':E=[(account_for(s,doc.company_id,p.get('cash_bank_account','1010'),('bank',)).code,amount,0),(p.get('account','4000'),0,amount)]
 elif k=='bank_out':E=[(p.get('account','6000'),amount,0),(account_for(s,doc.company_id,p.get('cash_bank_account','1010'),('bank',)).code,0,amount)]
 elif k in ('sale','purchase','sale_return','purchase_return'):
  items=p.get('items',[])
  if not isinstance(items,list) or not items:raise HTTPException(400,'Tambahkan minimal satu baris barang atau jasa')
  subtotal=ZERO;tax=ZERO;cost_total=ZERO;inventory_lines={};cogs_lines={};income_lines={};expense_lines={}
  if len({str(z.get('item_id')) for z in items})!=len(items):raise HTTPException(400,'Barang yang sama cukup satu baris')
  original=None
  if k in ('sale_return','purchase_return'):
   source_id=int(p.get('source_id') or 0)
   original=owned(s,Document,source_id,doc.company_id)
   if original.kind!=('sale' if k=='sale_return' else 'purchase') or original.status!='posted':raise HTTPException(400,'Pilih faktur asal yang sudah diposting')
   if doc.party_id!=original.party_id:raise HTTPException(400,'Pelanggan/pemasok harus sama dengan faktur asal')
   if doc.date<original.date:raise HTTPException(400,'Tanggal retur tidak boleh sebelum faktur')
   source_lines={str(z.get('item_id')):z for z in json.loads(original.payload).get('items',[])}
  invoice_discount=dec(p.get('invoice_discount',0)) if k in ('sale','purchase') else ZERO
  eligible=sum((dec(D(str(z.get('qty') or 0))*dec(z.get('price',0)))-dec(z.get('discount',0)) for z in items),ZERO)
  if invoice_discount<0 or invoice_discount>eligible:raise HTTPException(400,'Diskon faktur melebihi nilai bersih barang/jasa')
  remaining_discount=invoice_discount
  for line_index,line in enumerate(items):
   iid=int(line.get('item_id') or 0);x=master(s,doc.company_id,'item',iid)
   quantity=D(str(line.get('qty') or 0));price=dec(line.get('price'));rate=dec(line.get('tax_rate',0))
   if quantity<=0 or price<0 or rate not in (ZERO,D('11.00'),D('12.00')):raise HTTPException(400,'Qty, harga, atau tarif PPN tidak valid')
   # Use 0%, 11%, 12% as configurable nominal rate; tax regulations can require different effective bases.
   gross=dec(quantity*price);discount=dec(line.get('discount',0));base=gross-discount
   if discount<0 or discount>gross:raise HTTPException(400,'Diskon tidak boleh negatif atau melebihi subtotal')
   if invoice_discount and eligible:
    allocated=remaining_discount if line_index==len(items)-1 else min(remaining_discount,dec(invoice_discount*base/eligible))
    if allocated>base:raise HTTPException(400,'Diskon faktur tidak valid')
    base-=allocated;remaining_discount-=allocated
    line['posted_invoice_discount']=str(allocated)
   item_type,accounts=item_accounts(s,doc.company_id,x)
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
    expected_discount=dec(dec(sl.get('discount',0))*quantity/D(str(sl.get('qty'))))
    if price!=dec(sl.get('price')) or rate!=dec(sl.get('tax_rate',0)) or discount!=expected_discount:raise HTTPException(400,'Harga dan PPN retur harus sama dengan faktur asal')
    return_invoice_discount=dec(dec(sl.get('posted_invoice_discount',0))*quantity/D(str(sl.get('qty'))))
    base-=return_invoice_discount
    line['posted_invoice_discount']=str(return_invoice_discount)
   vat=dec(base*rate/D(100));subtotal+=base;tax+=vat
   if k in ('sale','sale_return'):
    code=accounts['income_account'];income_lines[code]=income_lines.get(code,ZERO)+base
   elif item_type=='service':
    code=accounts['expense_account'];expense_lines[code]=expense_lines.get(code,ZERO)+base
   if item_type=='goods':
    if not wh:raise HTTPException(400,'Pilih gudang untuk barang persediaan')
    if k=='purchase':
     move(s,doc,iid,wh,quantity,base)
     code=accounts['inventory_account'];inventory_lines[code]=inventory_lines.get(code,ZERO)+base
    elif k=='sale':
     value=stockout(s,doc,iid,wh,quantity);cost_total+=value
     for bucket,code in ((cogs_lines,accounts['cogs_account']),(inventory_lines,accounts['inventory_account'])):bucket[code]=bucket.get(code,ZERO)+value
     line['posted_cost']=str(value)
    elif k=='sale_return':
     original_cost=dec(sl.get('posted_cost',0));original_qty=D(str(sl.get('qty')))
     value=dec(original_cost*quantity/original_qty)
     move(s,doc,iid,wh,quantity,value);cost_total+=value
     for bucket,code in ((cogs_lines,accounts['cogs_account']),(inventory_lines,accounts['inventory_account'])):bucket[code]=bucket.get(code,ZERO)+value
    elif k=='purchase_return':
     value=stockout(s,doc,iid,wh,quantity);cost_total+=value
     code=accounts['inventory_account'];inventory_lines[code]=inventory_lines.get(code,ZERO)+value
  amount=subtotal+tax
  cash_payment=bool(p.get('pay_cash')) and k in ('sale','purchase')
  control=account_for(s,doc.company_id,p.get('cash_bank_account') or '1000',('cash','bank')).code if cash_payment else account_for(s,doc.company_id,p.get('control_account') or ('1100' if k.startswith('sale') else '2000'),('receivable',) if k.startswith('sale') else ('payable',)).code
  p['amount']=str(amount);p['subtotal']=str(subtotal);p['tax']=str(tax);doc.payload=json.dumps(p)
  if k=='purchase':
   E=[(code,val,0) for code,val in inventory_lines.items()]+[(code,val,0) for code,val in expense_lines.items()]+[('1150',tax,0),(control,0,amount)]
  elif k=='sale':
   E=[(control,amount,0)]+[(code,0,val) for code,val in income_lines.items()]+[('2100',0,tax)]+[(code,val,0) for code,val in cogs_lines.items()]+[(code,0,val) for code,val in inventory_lines.items()]
  elif k=='sale_return':
   E=[('4010',subtotal,0),('2100',tax,0),(control,0,amount)]+[(code,val,0) for code,val in inventory_lines.items()]+[(code,0,val) for code,val in cogs_lines.items()]
  else:
   E=[(control,amount,0),('1150',0,tax)]+[(code,0,val) for code,val in expense_lines.items()]
   for code,val in inventory_lines.items():E.append((code,0,val))
   difference=subtotal-cost_total-sum(expense_lines.values(),ZERO)
   if difference>0:E.append(('1201',0,difference))
   elif difference<0:E.append(('1201',-difference,0))
 elif k=='sale_receipt':E=[(account_for(s,doc.company_id,p.get('bank','1010'),('cash','bank')).code,amount,0),(account_for(s,doc.company_id,p.get('control_account','1100'),('receivable',)).code,0,amount)]
 elif k=='purchase_payment':E=[(account_for(s,doc.company_id,p.get('control_account','2000'),('payable',)).code,amount,0),(account_for(s,doc.company_id,p.get('bank','1010'),('cash','bank')).code,0,amount)]
 elif k=='transfer':
  dst=int(p.get('to_warehouse') or 0)
  if dst==wh:raise HTTPException(400,'Gudang asal dan tujuan harus berbeda')
  cost=stockout(s,doc,item,wh,qty);move(s,doc,item,dst,qty,cost);E=[]
 elif k=='adjust':
  selected_item=master(s,doc.company_id,'item',item)
  if json.loads(selected_item.extra or '{}').get('type','goods')!='goods':raise HTTPException(400,'Penyesuaian hanya untuk tipe Barang')
  adjustment=account_for(s,doc.company_id,p.get('adjustment_account') or '1201')
  if account_type(adjustment) in ('cash','bank','receivable','payable'):raise HTTPException(400,'Akun penyesuaian tidak boleh Kas, Bank, Piutang atau Hutang')
  inventory=item_accounts(s,doc.company_id,selected_item)[1]['inventory_account']
  if adjustment.id==coa(s,doc.company_id,inventory):raise HTTPException(400,'Akun penyesuaian harus berbeda dari akun persediaan')
  if qty==0:raise HTTPException(400,'Qty penyesuaian tidak boleh nol')
  if qty>0:
   cost=amount;move(s,doc,item,wh,qty,cost);E=[(inventory,cost,0),(adjustment.code,0,cost)]
  else:
   cost=stockout(s,doc,item,wh,-qty);E=[(adjustment.code,cost,0),(inventory,0,cost)]
 elif k=='journal':
  E=[(x['account'],dec(x.get('debit',0)),dec(x.get('credit',0))) for x in p.get('entries',[])]
 elif k=='depreciation':
  E=[('6100',amount,0),('1590',0,amount)]
 else:raise HTTPException(400,'Tipe dokumen tidak dikenali')
 if k not in ('transfer','journal') and amount<=0 and k!='adjust':raise HTTPException(400,'Nominal harus positif')
 if k=='journal' and not E:raise HTTPException(400,'Jurnal kosong')
 if k=='journal':
  for ent in p.get('entries',[]):
   acc=account_for(s,doc.company_id,ent['account'])
   if account_type(acc) in ('receivable','payable'):
    party=int(ent.get('party_id') or 0)
    if not party:raise HTTPException(400,'Jurnal piutang/hutang wajib memilih pelanggan/pemasok')
    master(s,doc.company_id,'customer' if account_type(acc)=='receivable' else 'supplier',party)
 lines(s,doc,E);doc.status='posted'

KINDS={'cash_in':'Kas Masuk','cash_out':'Kas Keluar','bank_in':'Bank Masuk','bank_out':'Bank Keluar','sale':'Faktur Penjualan','sale_receipt':'Penerimaan Penjualan','sale_return':'Retur Penjualan','purchase':'Faktur Pembelian','purchase_payment':'Pembayaran Pembelian','purchase_return':'Retur Pembelian','transfer':'Transfer Gudang','adjust':'Penyesuaian Persediaan','journal':'Jurnal Umum','depreciation':'Penyusutan'}
MASTER_KINDS={'coa':'COA','customer':'Pelanggan','supplier':'Pemasok','item':'Barang / Jasa','warehouse':'Gudang','asset':'Aset Tetap','unit':'Satuan','salesman':'Salesman'}
@app.get('/')
def home(req:Request,s=Depends(db)):
 try:u=user(req,s)
 except HTTPException:return go('/login')
 authorize(s,u,'read','reports')
 cid=u.company_id;today=date.today();month=today.strftime('%Y-%m')
 docs=s.query(Document).filter_by(company_id=cid,status='posted').order_by(Document.date.desc(),Document.id.desc()).all()
 accounts={x.id:x for x in s.query(Master).filter_by(company_id=cid,kind='coa')}
 journals=s.query(Journal).filter_by(company_id=cid).all()
 def typ(j):return account_type(accounts[j.account_id]) if j.account_id in accounts else ''
 def net(j):return D(j.credit or 0)-D(j.debit or 0)
 sales=sum((net(j) for j in journals if typ(j) in ('income','contra_income')),ZERO)
 expenses=sum((-net(j) for j in journals if typ(j) in ('expense','cogs')),ZERO)
 receivables=sum((-net(j) for j in journals if typ(j)=='receivable'),ZERO)
 payables=sum((net(j) for j in journals if typ(j)=='payable'),ZERO)
 current=[j for j in journals if j.date and j.date.startswith(month)]
 current_sales=sum((net(j) for j in current if typ(j) in ('income','contra_income')),ZERO)
 current_expenses=sum((-net(j) for j in current if typ(j) in ('expense','cogs')),ZERO)
 expense_totals={}
 for j in current:
  if typ(j)=='expense':expense_totals[j.account_id]=expense_totals.get(j.account_id,ZERO)-net(j)
 top_expenses=sorted([{'name':accounts[k].name,'amount':v} for k,v in expense_totals.items() if v>0],key=lambda x:x['amount'],reverse=True)[:5]
 total_top=sum((x['amount'] for x in top_expenses),ZERO)
 for x in top_expenses:x['percent']=round(float(x['amount']/total_top*100),2) if total_top else 0
 # Aging estimate: allocate payments/credits to oldest invoices by party and control account.
 # Do not imply exact invoice settlement without an explicit payment-to-invoice link.
 parties={x.id:x.name for x in s.query(Master).filter_by(company_id=cid).filter(Master.kind.in_(['customer','supplier']))}
 due={'sale':[],'purchase':[]}
 for kind,control_type in (('sale','receivable'),('purchase','payable')):
  invoices=[d for d in docs if d.kind==kind and d.party_id]
  credits={}
  for j in journals:
   if typ(j)!=control_type:continue
   doc=s.get(Document,j.doc_id)
   if not doc or not doc.party_id or doc.kind==kind:continue
   key=(doc.party_id,j.account_id)
   change=net(j) if control_type=='receivable' else -net(j)
   credits[key]=credits.get(key,ZERO)+change
  for d in sorted(invoices,key=lambda d:(d.date,d.id)):
   payload=json.loads(d.payload or '{}');
   if payload.get('pay_cash'):continue
   control=payload.get('control_account') or ('1100' if kind=='sale' else '2000')
   try:account_id=coa(s,cid,control)
   except HTTPException:continue
   key=(d.party_id,account_id);gross=dec(payload.get('amount',0));available=max(ZERO,credits.get(key,ZERO));used=min(gross,available)
   credits[key]=available-used;remaining=gross-used
   try:due_date=date.fromisoformat(payload.get('due_date') or '')
   except ValueError:due_date=date.fromisoformat(d.date)+timedelta(days=30)
   if due_date<=today and remaining>0:
    due[kind].append({'name':parties.get(d.party_id,'—'),'number':d.number,'date':due_date.isoformat(),'amount':remaining})
  due[kind]=sorted(due[kind],key=lambda x:x['amount'],reverse=True)[:10]
 # Seven completed calendar days including today, only posted cash/bank movements.
 start=today-timedelta(days=6)
 cash_flow_days=[]
 for n in range(7):
  day=(start+timedelta(days=n)).isoformat()
  cash_flow_days.append({'date':day,'label':day[5:],'incoming':float(sum((dec(json.loads(d.payload or '{}').get('amount',0)) for d in docs if d.date==day and d.kind in ('cash_in','bank_in')),ZERO)),'outgoing':float(sum((dec(json.loads(d.payload or '{}').get('amount',0)) for d in docs if d.date==day and d.kind in ('cash_out','bank_out')),ZERO))})
 health,slow_stock=dashboard_insights(s,cid,today,docs,journals,accounts)
 months=[{'label':f'{m:02d}','sales':float(sum((net(j) for j in journals if typ(j) in ('income','contra_income') and j.date and j.date[:7]==f'{today.year}-{m:02d}'),ZERO))} for m in range(1,13)]
 return page(req,s,'Dashboard',sales=sales,profit=sales-expenses,receivables=receivables,payables=payables,docs=docs[:8],doc_kinds=KINDS,months=months,cash_flow_days=cash_flow_days,top_expenses=top_expenses,profit_month={'income':current_sales,'expenses':current_expenses,'profit':current_sales-current_expenses},overdue_receivables=due['sale'],overdue_payables=due['purchase'],health=health,slow_stock=slow_stock)
def dashboard_insights(s,cid,today,docs,journals,accounts):
 # Read-only checks: never alter ledger or inventory.
 draft_count=s.query(Document).filter_by(company_id=cid,status='draft').count()
 balances={}
 for j in journals:
  balances[j.doc_id]=balances.get(j.doc_id,ZERO)+D(j.debit or 0)-D(j.credit or 0)
 unbalanced=sum(1 for amount in balances.values() if abs(amount)>D('0.01'))
 cash_balances={}
 for j in journals:
  a=accounts.get(j.account_id)
  if a and account_type(a) in ('cash','bank'):
   cash_balances[j.account_id]=cash_balances.get(j.account_id,ZERO)+D(j.debit or 0)-D(j.credit or 0)
 negative_cash=[accounts[i].name for i,v in cash_balances.items() if v<0]
 stocks=s.query(Stock).filter_by(company_id=cid).order_by(Stock.id).all()
 qty={};last_out={};last_move={}
 for st in stocks:
  key=(st.item_id,st.warehouse_id)
  qty[key]=qty.get(key,ZERO)+D(st.qty or 0)
  if st.qty<0:last_out[st.item_id]=max(last_out.get(st.item_id,''),st.date or '')
  last_move[st.item_id]=max(last_move.get(st.item_id,''),st.date or '')
 negatives=sum(1 for q in qty.values() if q<0)
 items={i.id:i for i in s.query(Master).filter_by(company_id=cid,kind='item').all()}
 total_by_item={}
 for (iid,wid),q in qty.items():total_by_item[iid]=total_by_item.get(iid,ZERO)+q
 cutoff=(today-timedelta(days=90)).isoformat()
 slow=[]
 for iid,q in total_by_item.items():
  if q<=0 or iid not in items:continue
  if json.loads(items[iid].extra or '{}').get('type','goods')=='service':continue
  last=last_out.get(iid)
  if not last or last<cutoff:
   slow.append({'code':items[iid].code,'name':items[iid].name,'qty':q,'last_sale':last or 'Belum pernah keluar'})
 slow=sorted(slow,key=lambda x:(-x['qty'],x['name']))[:10]
 health=[{'label':'Transaksi belum diposting','count':draft_count,'url':'/transactions'},
         {'label':'Jurnal tidak seimbang','count':unbalanced,'url':'/reports/journals'},
         {'label':'Saldo kas/bank negatif','count':len(negative_cash),'url':'/reports/cashbank'},
         {'label':'Stok gudang negatif','count':negatives,'url':'/reports/stock'},
         {'label':'Barang tidak terjual 90 hari','count':len(slow),'url':'/#slow-stock'}]
 return health,slow

IMPORT_KINDS={'coa':'COA','customer':'Pelanggan','supplier':'Pemasok','item':'Barang & Jasa'}
IMPORT_HEADERS={'coa':['kode','nama','tipe_akun'], 'customer':['kode','nama','telepon'], 'supplier':['kode','nama','telepon'], 'item':['kode','nama','jenis','akun_persediaan','akun_beban','akun_hpp','akun_pendapatan','harga_jual','satuan']}
COA_TYPES={'cash','bank','receivable','payable','asset','contra_asset','liability','equity','income','contra_income','cogs','expense'}

def import_template_bytes(kind):
 wb=Workbook();ws=wb.active;ws.title='Data '+kind
 ws.append(IMPORT_HEADERS[kind]);examples={'coa':['1020','Bank BCA','bank'],'customer':['C-001','Pelanggan Contoh','08123456789'],'supplier':['S-001','Pemasok Contoh','08123456789'],'item':['B-001','Produk Contoh','goods','1200','','5000','4000','150000','PCS']}
 ws.append(examples[kind]);ws.freeze_panes='A2';ws.auto_filter.ref=f'A1:{chr(64+len(IMPORT_HEADERS[kind]))}2'
 for cell in ws[1]:cell.font=Font(bold=True,color='FFFFFF');cell.fill=PatternFill('solid',fgColor='176A47');cell.alignment=Alignment(wrap_text=True)
 for col in ws.columns:ws.column_dimensions[col[0].column_letter].width=max(18,min(32,max(len(str(c.value or '')) for c in col)+4))
 info=wb.create_sheet('Petunjuk');info.append(['Petunjuk impor master']);info.append(['Hapus baris contoh sebelum impor data nyata.']);info.append(['Kode wajib unik per perusahaan dan jenis master.']);info.append(['Baris kosong diabaikan; jika ada kesalahan, tidak ada data yang disimpan.']);info.append(['Jenis barang: goods atau service. Tipe akun mengikuti pilihan COA.']);info.append(['Kolom akun barang/jasa opsional, gunakan kode COA yang sudah terdaftar.']);info.column_dimensions['A'].width=105
 out=io.BytesIO();wb.save(out);return out.getvalue()

@app.get('/masters/{kind}/template.xlsx')
def master_import_template(req:Request,kind:str,s=Depends(db)):
 u=user(req,s);authorize(s,u,'read','masters')
 if kind not in IMPORT_KINDS:raise HTTPException(404)
 return Response(import_template_bytes(kind),media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',headers={'Content-Disposition':f'attachment; filename="template_{kind}.xlsx"'})

@app.post('/masters/{kind}/import')
async def master_import(req:Request,kind:str,file:UploadFile=File(...),s=Depends(db)):
 u=user(req,s);authorize(s,u,'write','masters')
 if kind not in IMPORT_KINDS:raise HTTPException(404)
 raw=await file.read(2_000_001)
 if len(raw)>2_000_000:raise HTTPException(400,'Ukuran Excel maksimal 2 MB')
 try:wb=load_workbook(io.BytesIO(raw),read_only=True,data_only=True)
 except Exception:raise HTTPException(400,'File harus berupa Excel .xlsx yang valid')
 ws=wb.worksheets[0];headers=[str(c.value or '').strip().lower() for c in next(ws.iter_rows(max_row=1))]
 if headers!=IMPORT_HEADERS[kind]:raise HTTPException(400,'Header Excel tidak cocok dengan template '+kind)
 existing={x.code for x in s.query(Master).filter_by(company_id=u.company_id,kind=kind)}
 coa_lookup={x.code:x for x in s.query(Master).filter_by(company_id=u.company_id,kind='coa')}
 prepared=[];seen=set();errors=[]
 for index,row in enumerate(ws.iter_rows(min_row=2,values_only=True),start=2):
  if not any(v is not None and str(v).strip() for v in row):continue
  if index>1001:errors.append('Maksimal 1000 baris data');break
  vals=[str(v).strip() if v is not None else '' for v in row[:len(headers)]]
  vals+=['']*(len(headers)-len(vals));code,name=vals[:2]
  if not code or not name or len(code)>60 or len(name)>180:errors.append(f'Baris {index}: kode/nama kosong atau terlalu panjang');continue
  if code in existing or code in seen:errors.append(f'Baris {index}: kode {code} sudah ada/duplikat');continue
  seen.add(code);extra={}
  if kind in ('customer','supplier'):extra={'phone':vals[2][:50]}
  if kind=='coa':
   typ=vals[2].lower()
   if typ not in COA_TYPES:errors.append(f'Baris {index}: tipe akun tidak valid');continue
   extra={'type':typ}
  elif kind=='item':
   typ=(vals[2] or 'goods').lower()
   if typ not in ('goods','service'):errors.append(f'Baris {index}: jenis harus goods/service');continue
   extra={'type':typ}
   try:
    extra['sale_price']=str(dec(vals[7])) if vals[7] else '0'
    if dec(extra['sale_price'])<0:raise ValueError()
   except Exception:errors.append(f'Baris {index}: harga jual tidak valid');continue
   extra['unit']=vals[8] if len(vals)>8 else ''
   if extra['unit'] and not s.query(Master).filter_by(company_id=u.company_id,kind='unit',code=extra['unit']).first():errors.append(f'Baris {index}: satuan {extra["unit"]} belum terdaftar');continue
   for key,val,allowed in zip(['inventory_account','expense_account','cogs_account','income_account'],vals[3:7],[('asset',),('expense',),('cogs',),('income',)]):
    if not val:continue
    account=coa_lookup.get(val)
    if not account or account_type(account) not in allowed:errors.append(f'Baris {index}: akun {key} ({val}) tidak sesuai COA');continue
    extra[key]=val
  prepared.append(Master(company_id=u.company_id,kind=kind,code=code,name=name,extra=json.dumps(extra)))
 wb.close()
 if errors:raise HTTPException(400,'Impor dibatalkan, tidak ada data tersimpan. '+ '; '.join(errors[:12]))
 if not prepared:raise HTTPException(400,'Tidak ada baris data untuk diimpor')
 s.add_all(prepared);audit(s,u,'import',kind,0,f'{len(prepared)} master dari Excel');s.commit()
 return go('/masters/'+kind+'?imported='+str(len(prepared)))

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
 u=user(req,s);authorize(s,u,'read','masters')
 if kind not in MASTER_KINDS:raise HTTPException(404)
 if kind in ('coa','item'):ensure_system_coas(s,u.company_id);s.commit()
 items=s.query(Master).filter_by(company_id=u.company_id,kind=kind).order_by(Master.code).all()
 return page(req,s,MASTER_KINDS[kind],items=items,kind=kind,kind_label=MASTER_KINDS[kind],accounts=s.query(Master).filter_by(company_id=u.company_id,kind='coa').order_by(Master.code).all(),opening_warehouses=s.query(Master).filter_by(company_id=u.company_id,kind='warehouse').all(),units=s.query(Master).filter_by(company_id=u.company_id,kind='unit').order_by(Master.name).all(),master_summary=master_summaries(s,u.company_id,kind,items))

def master_summaries(s,cid,kind,items):
 result={x.id:{'balance':ZERO,'qty':ZERO} for x in items}
 if kind=='item':
  for item_id,qty in s.query(Stock.item_id,func.sum(Stock.qty)).filter_by(company_id=cid).group_by(Stock.item_id):
   if item_id in result:result[item_id]['qty']=qty or ZERO
 elif kind in ('customer','supplier'):
  account_ids={x.id:account_type(x) for x in s.query(Master).filter_by(company_id=cid,kind='coa').all()}
  wanted='receivable' if kind=='customer' else 'payable'
  for j,jp in s.query(Journal,JournalParty).join(JournalParty,JournalParty.journal_id==Journal.id).filter(Journal.company_id==cid,JournalParty.company_id==cid):
   if jp.party_id in result and account_ids.get(j.account_id)==wanted:
    result[jp.party_id]['balance']+=dec(j.debit)-dec(j.credit) if kind=='customer' else dec(j.credit)-dec(j.debit)
 return result

@app.get('/masters/{kind}/{mid}')
def master_detail(req:Request,kind:str,mid:int,s=Depends(db)):
 u=user(req,s);authorize(s,u,'read','masters')
 if kind not in MASTER_KINDS:raise HTTPException(404)
 x=master(s,u.company_id,kind,mid)
 return page(req,s,'Detail '+MASTER_KINDS[kind],kind=kind,kind_label=MASTER_KINDS[kind],detail_master=x,accounts=s.query(Master).filter_by(company_id=u.company_id,kind='coa').order_by(Master.code).all(),opening_warehouses=s.query(Master).filter_by(company_id=u.company_id,kind='warehouse').all(),opening_values=opening_values(s,u.company_id,x),units=s.query(Master).filter_by(company_id=u.company_id,kind='unit').order_by(Master.name).all())

def opening_values(s,cid,x):
 d=s.query(Document).filter_by(company_id=cid,number=f'OPEN-{x.kind.upper()}-{x.id}').first()
 if not d:return {'amount':'0','qty':'0','unit_cost':'0','warehouse_id':0}
 p=json.loads(d.payload or '{}');return {'amount':p.get('amount','0'),'qty':p.get('qty','0'),'unit_cost':p.get('unit_cost','0'),'warehouse_id':d.warehouse_id or 0}

def opening_balance(s,u,x,amount,qty=ZERO,unit_cost=ZERO,warehouse_id=0):
 """One auditable opening document per master; replacement is atomic and blocks later stock moves."""
 c=s.get(Company,u.company_id)
 if not c.cutoff_date:raise HTTPException(400,'Atur Tanggal Mulai Pakai di Pengaturan terlebih dahulu')
 if c.locked_through and c.cutoff_date<=c.locked_through:raise HTTPException(400,'Saldo awal berada dalam periode terkunci')
 if x.kind=='coa' and account_type(x) in ('receivable','payable'):
  if amount:raise HTTPException(400,'Saldo awal Piutang/Hutang harus melalui master pelanggan/pemasok')
  return
 if x.kind=='coa' and account_type(x) in ('income','contra_income','cogs','expense') and amount:
  raise HTTPException(400,'Saldo awal pendapatan dan beban tidak diizinkan; gunakan akun neraca')
 if x.kind=='item' and json.loads(x.extra or '{}').get('type','goods')!='goods':
  if amount or qty:raise HTTPException(400,'Saldo awal stok hanya untuk barang, bukan jasa')
  return
 if amount<0:raise HTTPException(400,'Saldo awal tidak boleh negatif')
 if x.kind=='item' and (qty<0 or unit_cost<0):raise HTTPException(400,'Stok awal dan harga pokok tidak boleh negatif')
 if x.kind in ('customer','supplier') and amount<0:raise HTTPException(400,'Saldo awal pelanggan/pemasok tidak boleh negatif')
 if x.kind=='item':amount=dec(qty*unit_cost)
 number=f'OPEN-{x.kind.upper()}-{x.id}'
 old=s.query(Document).filter_by(company_id=u.company_id,number=number).first()
 if old:
  if x.kind=='item':
   later=s.query(Stock).filter(Stock.company_id==u.company_id,Stock.item_id==x.id,Stock.doc_id!=old.id).first()
   if later:raise HTTPException(400,'Stok barang sudah bergerak; saldo awal tidak dapat diubah')
  s.query(JournalParty).filter(JournalParty.journal_id.in_(s.query(Journal.id).filter_by(doc_id=old.id))).delete(synchronize_session=False)
  s.query(Journal).filter_by(doc_id=old.id).delete()
  s.query(Stock).filter_by(doc_id=old.id).delete()
  s.delete(old);s.flush()
 if not amount and not qty:return
 if x.kind=='item' and not warehouse_id:raise HTTPException(400,'Pilih gudang untuk saldo awal barang')
 doc=Document(company_id=u.company_id,kind='opening',number=number,date=c.cutoff_date,party_id=x.id if x.kind in ('customer','supplier') else None,warehouse_id=warehouse_id if x.kind=='item' else None,status='posted',memo=f'Saldo awal {x.kind}: {x.name}',payload=json.dumps({'master_id':x.id,'amount':str(amount),'qty':str(qty),'unit_cost':str(unit_cost)}))
 s.add(doc);s.flush()
 if x.kind=='coa':
  if account_type(x)=='equity' and (x.code=='3090' or system_code(x)=='3090'):raise HTTPException(400,'Opening Balance Equity tidak dapat diisi saldo awal langsung')
  account=x
 elif x.kind=='customer':account=account_for(s,u.company_id,'1100',('receivable',))
 elif x.kind=='supplier':account=account_for(s,u.company_id,'2000',('payable',))
 else:
  master(s,u.company_id,'warehouse',warehouse_id)
  _,accts=item_accounts(s,u.company_id,x);account=account_for(s,u.company_id,accts['inventory_account'],('asset',))
  move(s,doc,x.id,warehouse_id,qty,amount)
 opening=account_for(s,u.company_id,'3090',('equity',))
 typ=account_type(account)
 credit_normal=typ in ('equity','liability','payable','contra_asset','contra_income')
 primary_debit=ZERO if credit_normal else amount
 primary_credit=amount if credit_normal else ZERO
 for acc,dr,cr in ((account,primary_debit,primary_credit),(opening,primary_credit,primary_debit)):
  if not dr and not cr:continue
  j=Journal(company_id=u.company_id,doc_id=doc.id,date=doc.date,account_id=acc.id,debit=dr,credit=cr,memo=doc.memo);s.add(j);s.flush()
  if acc.id==account.id and x.kind in ('customer','supplier'):
   s.add(JournalParty(journal_id=j.id,company_id=u.company_id,party_id=x.id))
 audit(s,u,'opening_balance',x.kind,x.id,str(amount))

async def master_extra(req,kind):
 f=await req.form()
 if kind=='coa':
  typ=f.get('account_type') or 'asset'
  if typ not in ('cash','bank','receivable','payable','asset','contra_asset','liability','equity','income','contra_income','cogs','expense'):raise HTTPException(400,'Tipe akun tidak valid')
  return {'type':typ}
 if kind in ('customer','supplier'):
  return {'phone':(f.get('phone') or '').strip()[:50], 'address':(f.get('address') or '').strip()[:500], 'contact_name':(f.get('contact_name') or '').strip()[:180], 'email':(f.get('email') or '').strip()[:180]}
 if kind=='item':
  typ=f.get('item_type') or 'goods'
  if typ not in ('goods','service'):raise HTTPException(400,'Jenis barang tidak valid')
  data={'type':typ}
  allowed={'inventory_account':('asset',),'cogs_account':('cogs',),'income_account':('income',),'expense_account':('expense',)}
  for key,types in allowed.items():
   code=(f.get(key) or '').strip()
   if code:account_for(req.state.db,req.state.company_id,code,types);data[key]=code
  try:price=dec(f.get('sale_price') or 0)
  except Exception:raise HTTPException(400,'Harga jual tidak valid')
  if price<0:raise HTTPException(400,'Harga jual tidak boleh negatif')
  data['sale_price']=str(price)
  unit=(f.get('unit') or '').strip()
  if unit and not req.state.db.query(Master).filter_by(company_id=req.state.company_id,kind='unit',code=unit).first():raise HTTPException(400,'Satuan belum terdaftar')
  data['unit']=unit
  return data
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
 authorize(s,u,'write','masters')
 req.state.db=s;req.state.company_id=u.company_id
 data=await master_extra(req,kind)
 if s.query(Master).filter_by(company_id=u.company_id,kind=kind,code=code.strip()).first():raise HTTPException(400,'Kode sudah dipakai')
 x=Master(company_id=u.company_id,kind=kind,code=code.strip()[:60],name=name.strip()[:180],extra=json.dumps(data));s.add(x);s.flush()
 f=await req.form()
 if kind in ('coa','customer','supplier','item') and (dec(f.get('opening_balance') or 0) or dec(f.get('opening_qty') or 0)):
  opening_balance(s,u,x,dec(f.get('opening_balance') or 0),dec(f.get('opening_qty') or 0),dec(f.get('opening_unit_cost') or 0),int(f.get('opening_warehouse') or 0))
 audit(s,u,'create',kind,x.id,x.code);s.commit();return go('/masters/'+kind)
@app.post('/masters/{kind}/{mid}/edit')
async def master_edit(req:Request,kind:str,mid:int,code:str=Form(...),name:str=Form(...),extra:str=Form('{}'),s=Depends(db)):
 u=user(req,s);authorize(s,u,'write','masters');x=master(s,u.company_id,kind,mid)
 req.state.db=s;req.state.company_id=u.company_id
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
 x.code=code.strip()[:60];x.name=name.strip()[:180];x.extra=json.dumps(data)
 f=await req.form()
 if kind in ('coa','customer','supplier','item') and 'opening_balance' in f:
  opening_balance(s,u,x,dec(f.get('opening_balance') or 0),dec(f.get('opening_qty') or 0),dec(f.get('opening_unit_cost') or 0),int(f.get('opening_warehouse') or 0))
 audit(s,u,'edit',kind,x.id,x.code);s.commit();return go('/masters/'+kind)
@app.post('/masters/{kind}/{mid}/delete')
def master_delete(req:Request,kind:str,mid:int,s=Depends(db)):
 u=user(req,s);authorize(s,u,'write','masters');x=master(s,u.company_id,kind,mid)
 if kind=='coa' and (system_code(x) in SYSTEM_CODES or s.query(Journal).filter_by(company_id=u.company_id,account_id=mid).first()):raise HTTPException(400,'Akun sistem atau akun terpakai tidak bisa dihapus')
 if kind=='warehouse' and s.query(Stock).filter_by(company_id=u.company_id,warehouse_id=mid).first():raise HTTPException(400,'Gudang sudah memiliki mutasi')
 if kind=='item' and s.query(Stock).filter_by(company_id=u.company_id,item_id=mid).first():raise HTTPException(400,'Barang sudah memiliki mutasi')
 if s.query(Document).filter_by(company_id=u.company_id,party_id=mid).first():raise HTTPException(400,'Master digunakan dokumen')
 audit(s,u,'delete',kind,x.id,x.code);s.delete(x);s.commit();return go('/masters/'+kind)
@app.get('/subledger')
def subledger(req:Request,account_id:int=0,party_id:int=0,s=Depends(db)):
 u=user(req,s)
 accounts=[a for a in s.query(Master).filter_by(company_id=u.company_id,kind='coa').all() if account_type(a) in ('receivable','payable')]
 parties=s.query(Master).filter(Master.company_id==u.company_id,Master.kind.in_(['customer','supplier'])).order_by(Master.name).all()
 rows=[];balance=ZERO
 if account_id:
  a=master(s,u.company_id,'coa',account_id)
  if account_type(a) not in ('receivable','payable'):raise HTTPException(400,'Pilih akun piutang/hutang')
  q=s.query(Journal,JournalParty).join(JournalParty,JournalParty.journal_id==Journal.id).filter(Journal.company_id==u.company_id,Journal.account_id==account_id)
  if party_id:master(s,u.company_id,'customer' if account_type(a)=='receivable' else 'supplier',party_id);q=q.filter(JournalParty.party_id==party_id)
  for j,jp in q.order_by(Journal.date,Journal.id).all():
   balance+=dec(j.debit)-dec(j.credit)
   rows.append({'date':j.date,'debit':j.debit,'credit':j.credit,'balance':balance,'party_id':jp.party_id,'doc_id':j.doc_id})
 docs={x.id:x.number for x in s.query(Document).filter_by(company_id=u.company_id).all()}
 names={x.id:x.name for x in parties}
 return page(req,s,'Buku Besar Pembantu',subledger_accounts=accounts,subledger_parties=parties,subledger_rows=rows,subledger_names=names,subledger_docs=docs,selected_account=account_id,selected_party=party_id)
@app.get('/settings/cutoff')
def cutoff_settings(req:Request,s=Depends(db)):
 u=user(req,s);authorize(s,u,'manage','settings')
 return page(req,s,'Tanggal Mulai Pakai',cutoff_settings=True)
@app.post('/settings/cutoff')
async def save_cutoff(req:Request,s=Depends(db)):
 u=user(req,s);authorize(s,u,'manage','settings');f=await req.form()
 value=str(f.get('cutoff_date') or '')
 try:date.fromisoformat(value)
 except ValueError:raise HTTPException(400,'Tanggal mulai pakai tidak valid')
 c=s.get(Company,u.company_id)
 if c.cutoff_date and c.cutoff_date!=value:
  if s.query(Document).filter_by(company_id=u.company_id,status='posted').first():raise HTTPException(400,'Tanggal mulai pakai tidak dapat diganti setelah ada transaksi posting atau saldo awal')
 if not c.cutoff_date and s.query(Document).filter(Document.company_id==u.company_id,Document.status=='posted',Document.date<value).first():raise HTTPException(400,'Ada transaksi posting sebelum tanggal tersebut; tanggal mulai pakai harus sebelum atau sama dengan tanggal transaksi tertua')
 c.cutoff_date=value;audit(s,u,'update','cutoff',c.id,value);s.commit();return go('/settings/cutoff')

@app.get('/print-design')
def print_design(req:Request,s=Depends(db)):
 u=user(req,s);authorize(s,u,'manage','print')
 templates={x.kind:x for x in s.query(PrintTemplate).filter_by(company_id=u.company_id).all()}
 return page(req,s,'Desain Cetakan',print_templates=templates)
@app.post('/print-design')
async def save_print_design(req:Request,s=Depends(db)):
 u=user(req,s);authorize(s,u,'manage','print');f=await req.form()
 kind=str(f.get('kind') or 'invoice');paper=str(f.get('paper') or 'A4')
 if kind not in ('invoice','delivery') or paper not in ('A4','A5','Letter'):raise HTTPException(400,'Format tidak valid')
 x=s.query(PrintTemplate).filter_by(company_id=u.company_id,kind=kind).first()
 if not x:x=PrintTemplate(company_id=u.company_id,kind=kind);s.add(x)
 x.paper=paper;x.title=str(f.get('title') or '')[:100];x.footer=str(f.get('footer') or '')[:300]
 fields=('show_logo','show_company','show_title','show_number','show_date','show_customer','show_address','show_sku','show_unit','show_qty','show_price','show_discount','show_tax','show_total','show_signature','show_footer')
 x.settings=json.dumps({key:key in f for key in fields}|{'accent':str(f.get('accent') or '#16845b')[:7],'extra_header':str(f.get('extra_header') or '')[:180],'extra_footer':str(f.get('extra_footer') or '')[:180]})
 logo=f.get('logo')
 if logo and getattr(logo,'filename',''):
  raw=await logo.read()
  if len(raw)>250000:raise HTTPException(400,'Logo maksimal 250 KB')
  if not (raw.startswith(b'\x89PNG\r\n\x1a\n') or raw.startswith(b'\xff\xd8\xff')):raise HTTPException(400,'Logo harus PNG/JPEG')
  x.logo=base64.b64encode(raw).decode()
 audit(s,u,'edit','print_template',0,kind);s.commit();return go('/print-design')
@app.get('/print-design/preview/{kind}')
def print_preview(req:Request,kind:str,s=Depends(db)):
 u=user(req,s);authorize(s,u,'manage','print')
 if kind not in ('invoice','delivery'):raise HTTPException(404)
 t=s.query(PrintTemplate).filter_by(company_id=u.company_id,kind=kind).first()
 cfg=json.loads(t.settings or '{}') if t else {}
 def show(key):return cfg.get(key,True)
 company=s.get(Company,u.company_id).name
 parts=['<html lang="id"><meta charset="utf-8"><title>Pratinjau Cetakan</title><style>body{font:14px Arial;max-width:760px;margin:35px auto;padding:35px;border:1px solid #ddd;color:#223}h1{color:'+escape(cfg.get('accent','#16845b'))+'}table{width:100%;border-collapse:collapse}th,td{border-bottom:1px solid #ddd;padding:10px;text-align:left}</style>']
 if show('show_company'):parts.append('<h2>'+escape(company)+'</h2>')
 if show('show_title'):parts.append('<h1>'+escape(t.title if t and t.title else ('FAKTUR PENJUALAN' if kind=='invoice' else 'SURAT JALAN'))+'</h1>')
 if cfg.get('extra_header'):parts.append('<p>'+escape(cfg['extra_header'])+'</p>')
 if show('show_number'):parts.append('<p>Nomor: CONTOH-001</p>')
 if show('show_date'):parts.append('<p>Tanggal: '+date.today().isoformat()+'</p>')
 if show('show_customer'):parts.append('<p>Pelanggan: Contoh Pelanggan</p>')
 cols=['Barang'];cols+=['Kode'] if show('show_sku') else [];cols+=['Qty'] if show('show_qty') else [];cols+=['Satuan'] if show('show_unit') else []
 if kind=='invoice':cols+=['Harga'] if show('show_price') else [];cols+=['Diskon'] if show('show_discount') else []
 parts.append('<table><tr>'+''.join('<th>'+x+'</th>' for x in cols)+'</tr><tr>'+''.join('<td>'+x+'</td>' for x in ['Contoh Produk']+(['BRG-001'] if show('show_sku') else [])+(['2'] if show('show_qty') else [])+(['pcs'] if show('show_unit') else [])+(['100.000'] if kind=='invoice' and show('show_price') else [])+(['0'] if kind=='invoice' and show('show_discount') else []))+'</tr></table>')
 if kind=='invoice' and show('show_total'):parts.append('<p style="text-align:right">Total: Rp200.000</p>')
 if show('show_signature'):parts.append('<p style="margin-top:55px">Penerima: ______________ &nbsp;&nbsp; Petugas: ______________</p>')
 if show('show_footer') and t and t.footer:parts.append('<p>'+escape(t.footer)+'</p>')
 if cfg.get('extra_footer'):parts.append('<p>'+escape(cfg['extra_footer'])+'</p>')
 parts.append('<p style="color:#888;font-size:11px">Pratinjau data contoh, bukan dokumen transaksi asli.</p></html>')
 return HTMLResponse(''.join(parts))
@app.get('/audit-trail')
def audit_trail(req:Request,s=Depends(db)):
 u=user(req,s);authorize(s,u,'manage','audit')
 records=s.query(Activity).filter_by(company_id=u.company_id).order_by(Activity.id.desc()).limit(500).all()
 people={x.id:x.name for x in s.query(User).filter_by(company_id=u.company_id).all()}
 return page(req,s,'Audit Trail',audit_records=records,audit_people=people)
@app.get('/access')
def access_page(req:Request,s=Depends(db)):
 u=user(req,s);authorize(s,u,'manage','access')
 members=s.query(User).filter_by(company_id=u.company_id).all()
 roles={r.user_id:r.role for r in s.query(MemberRole).filter_by(company_id=u.company_id).all()}
 return page(req,s,'Hak Akses',members=members,member_roles=roles,role_modules=MODULES,role_actions=ACTIONS,role_rules={(r.role,r.module,r.action):r.allowed for r in s.query(RoleRule).filter_by(company_id=u.company_id).all()})
@app.post('/access/add')
def access_add(req:Request,name:str=Form(...),email:str=Form(...),password:str=Form(...),role:str=Form('viewer'),s=Depends(db)):
 u=user(req,s);authorize(s,u,'manage','access')
 if role not in ('admin','accounting','sales','purchasing','viewer'):raise HTTPException(400,'Peran tidak valid')
 if len(password)<10:raise HTTPException(400,'Password minimal 10 karakter')
 if s.query(User).filter_by(email=email.strip().lower()).first():raise HTTPException(400,'Email sudah terdaftar')
 x=User(company_id=u.company_id,name=name[:120],email=email.strip().lower(),password=ph.hash(password));s.add(x);s.flush()
 s.add(MemberRole(company_id=u.company_id,user_id=x.id,role=role));audit(s,u,'create','user',x.id,email);s.commit();return go('/access')
@app.post('/access/rules')
async def access_rules(req:Request,s=Depends(db)):
 u=user(req,s);authorize(s,u,'manage','access');f=await req.form()
 role=str(f.get('role') or '')
 if role not in ('admin','accounting','sales','purchasing','viewer'):raise HTTPException(400,'Role tidak valid')
 for module in MODULES:
  for action in ACTIONS:
   allowed=f'{module}_{action}' in f
   rule=s.query(RoleRule).filter_by(company_id=u.company_id,role=role,module=module,action=action).first()
   if not rule:rule=RoleRule(company_id=u.company_id,role=role,module=module,action=action);s.add(rule)
   rule.allowed=allowed
 audit(s,u,'edit','role_rules',0,role);s.commit();return go('/access')
@app.post('/access/{uid}/role')
def access_role(req:Request,uid:int,role:str=Form(...),s=Depends(db)):
 u=user(req,s);authorize(s,u,'manage','access')
 if uid==u.id:raise HTTPException(400,'Tidak dapat mengubah peran sendiri')
 if role not in ('admin','accounting','sales','purchasing','viewer'):raise HTTPException(400,'Peran tidak valid')
 member=owned(s,User,uid,u.company_id);r=s.query(MemberRole).filter_by(user_id=uid,company_id=u.company_id).first()
 if not r:raise HTTPException(400,'Pemilik akun tidak dapat diturunkan dari sini')
 r.role=role;audit(s,u,'role_change','user',uid,role);s.commit();return go('/access')
@app.get('/transactions')
def transactions_overview(req:Request,s=Depends(db)):
 u=user(req,s)
 docs=s.query(Document).filter_by(company_id=u.company_id).order_by(Document.date.desc(),Document.id.desc()).limit(500).all()
 return page(req,s,'Semua Transaksi',transaction_overview=docs,transaction_names={k:v for k,v in KINDS.items() if k!='depreciation'})

@app.get('/documents/{kind}')
def documents(req:Request,kind:str,view:str='',s=Depends(db)):
 u=user(req,s);authorize(s,u,'read','documents')
 if kind not in KINDS:raise HTTPException(404)
 ensure_system_coas(s,u.company_id);s.commit()
 items=s.query(Document).filter_by(company_id=u.company_id,kind=kind).order_by(Document.id.desc()).all()
 lists={k:s.query(Master).filter_by(company_id=u.company_id,kind=k).all() for k in ('customer','supplier','item','warehouse','coa','asset','salesman')}
 return page(req,s,KINDS[kind],kind=kind,items=items,lists=lists,kind_label=KINDS[kind],list_only=(view=='list'),invoice_sources=s.query(Document).filter_by(company_id=u.company_id,kind=('sale' if kind=='sale_return' else 'purchase'),status='posted').all() if kind in ('sale_return','purchase_return') else [],doc_details={d.id:json.loads(d.payload) for d in items})
LINE_KINDS=('sale','purchase','sale_return','purchase_return')
async def form_payload(req,s,cid,kind):
 form=await req.form()
 if kind in LINE_KINDS:
  ids=form.getlist('item_id[]');qtys=form.getlist('qty[]');prices=form.getlist('price[]');rates=form.getlist('tax_rate[]');discounts=form.getlist('discount[]') or ['0']*len(ids)
  if not (len(ids)==len(qtys)==len(prices)==len(rates)==len(discounts)):raise HTTPException(400,'Tabel barang tidak lengkap')
  rows=[]
  for iid,qty,price,rate,discount in zip(ids,qtys,prices,rates,discounts):
   if not iid:continue
   master(s,cid,'item',int(iid))
   rows.append({'item_id':int(iid),'qty':str(qty),'price':str(price),'tax_rate':str(rate),'discount':str(discount)})
  if not rows:raise HTTPException(400,'Tambahkan minimal satu barang/jasa')
  p={'items':rows,'control_account':(form.get('control_account') or ('1100' if kind.startswith('sale') else '2000')),'invoice_discount':str(form.get('invoice_discount') or '0'),'due_date':str(form.get('due_date') or ''),'salesman_id':int(form.get('salesman_id') or 0) if kind=='sale' else 0,'pay_cash':bool(form.get('pay_cash')),'cash_bank_account':str(form.get('cash_bank_account') or '')}
  if kind in ('sale','purchase') and p['pay_cash']:account_for(s,cid,p['cash_bank_account'],('cash','bank'))
  if kind=='sale' and p['salesman_id']:master(s,cid,'salesman',p['salesman_id'])
  if kind.endswith('return'):p['source_id']=int(form.get('source_id') or 0)
  return p
 if kind=='journal':
  entries=[]
  parties=form.getlist('line_party_id[]')
  for i,(code,dr,cr) in enumerate(zip(form.getlist('account[]'),form.getlist('debit[]'),form.getlist('credit[]'))):
   if code and (dec(dr) or dec(cr)):
    entry={'account':code,'debit':str(dr or 0),'credit':str(cr or 0),'party_id':int(parties[i] or 0) if i<len(parties) else 0}
    a=account_for(s,cid,code)
    if account_type(a) in ('receivable','payable'):
     if not entry['party_id']:raise HTTPException(400,'Akun Piutang/Hutang harus memilih pelanggan/pemasok')
     master(s,cid,'customer' if account_type(a)=='receivable' else 'supplier',entry['party_id'])
    entries.append(entry)
  return {'entries':entries}
 if kind in ('transfer','adjust'):
  return {'item_id':int(form.get('single_item_id') or 0),'qty':str(form.get('single_qty') or 0),'amount':str(form.get('single_amount') or 0),'to_warehouse':int(form.get('to_warehouse') or 0),'adjustment_account':str(form.get('adjustment_account') or '1201')}
 return {'amount':str(form.get('amount') or 0),'account':form.get('account') or '6000','bank':form.get('bank') or '1010','cash_bank_account':form.get('cash_bank_account') or ('1000' if kind.startswith('cash_') else '1010'),'control_account':form.get('control_account') or ('1100' if kind=='sale_receipt' else '2000')}

@app.post('/documents/{kind}')
async def document_add(req:Request,kind:str,number:str=Form(...),date_value:str=Form(...,alias='date'),party_id:int=Form(0),warehouse_id:int=Form(0),memo:str=Form(''),payload:str=Form('{}'),s=Depends(db)):
 u=user(req,s)
 if kind not in KINDS:raise HTTPException(404)
 authorize(s,u,'write','documents')
 try:date.fromisoformat(date_value)
 except:raise HTTPException(400,'Tanggal tidak valid')
 p=await form_payload(req,s,u.company_id,kind)
 if party_id:master(s,u.company_id,'customer' if kind in ('sale','sale_receipt','sale_return') else 'supplier' if kind in ('purchase','purchase_payment','purchase_return') else 'customer',party_id)
 if warehouse_id:master(s,u.company_id,'warehouse',warehouse_id)
 doc=Document(company_id=u.company_id,kind=kind,number=number.strip()[:60],date=date_value,party_id=party_id or None,warehouse_id=warehouse_id or None,memo=memo[:1000],payload=json.dumps(p));s.add(doc);s.flush();audit(s,u,'create','document',doc.id,doc.number);s.commit();return go('/documents/'+kind)
def unlock_posted_document(s,u,x):
 """Safely remove a posted document's effects before editing/deleting it.

 Stock documents can only be reopened when they are the latest stock movement,
 because the inventory costing engine uses moving-average valuation.
 """
 if x.status!='posted':return
 c=s.get(Company,u.company_id)
 if c.locked_through and x.date<=c.locked_through:
  raise HTTPException(400,'Periode sudah dikunci; transaksi tidak dapat diubah')
 for r in s.query(Document).filter_by(company_id=u.company_id,status='posted').all():
  if r.id!=x.id and r.kind in ('sale_return','purchase_return'):
   if int(json.loads(r.payload or '{}').get('source_id') or 0)==x.id:
    raise HTTPException(400,'Transaksi sudah memiliki retur; batalkan retur terlebih dahulu')
 own_stocks=s.query(Stock).filter_by(company_id=u.company_id,doc_id=x.id).all()
 if own_stocks:
  latest_id=s.query(func.max(Stock.id)).filter_by(company_id=u.company_id).scalar()
  if latest_id and latest_id>max(row.id for row in own_stocks):
   raise HTTPException(400,'Ada mutasi stok setelah transaksi ini; ubah/hapus transaksi stok terbaru terlebih dahulu')
  # Do not let stock reversals leave any warehouse with negative quantities.
  keys={(row.item_id,row.warehouse_id) for row in own_stocks}
  for item_id,warehouse_id in keys:
   current,_=balances(s,u.company_id,item_id,warehouse_id)
   reversing=sum((D(row.qty) for row in own_stocks if row.item_id==item_id and row.warehouse_id==warehouse_id),D(0))
   if current-reversing<0:
    raise HTTPException(400,'Tidak bisa membatalkan posting: stok gudang menjadi negatif')
 journal_ids=[row.id for row in s.query(Journal.id).filter_by(company_id=u.company_id,doc_id=x.id).all()]
 if journal_ids:s.query(JournalParty).filter(JournalParty.company_id==u.company_id,JournalParty.journal_id.in_(journal_ids)).delete(synchronize_session=False)
 s.query(Journal).filter_by(company_id=u.company_id,doc_id=x.id).delete(synchronize_session=False)
 s.query(Stock).filter_by(company_id=u.company_id,doc_id=x.id).delete(synchronize_session=False)
 x.status='draft'

@app.post('/documents/{kind}/{did}/reopen')
def document_reopen(req:Request,kind:str,did:int,s=Depends(db)):
 u=user(req,s);authorize(s,u,'write','documents');x=owned(s,Document,did,u.company_id)
 if x.kind!=kind:raise HTTPException(404)
 if x.status=='posted':
  try:
   unlock_posted_document(s,u,x)
   audit(s,u,'reopen','document',x.id,x.number)
   s.commit()
  except:s.rollback();raise
 return go('/documents/'+kind+'?view=list#transaction-list')

@app.post('/documents/{kind}/{did}/edit')
async def document_edit(req:Request,kind:str,did:int,number:str=Form(...),date_value:str=Form(...,alias='date'),party_id:int=Form(0),warehouse_id:int=Form(0),memo:str=Form(''),payload:str=Form('{}'),s=Depends(db)):
 u=user(req,s);authorize(s,u,'write','documents');x=owned(s,Document,did,u.company_id)
 if x.kind!=kind or x.status!='draft':raise HTTPException(400,'Klik Edit pada transaksi terposting untuk membuka kembali sebagai Draft terlebih dahulu')
 try:date.fromisoformat(date_value)
 except:raise HTTPException(400,'Tanggal tidak valid')
 p=await form_payload(req,s,u.company_id,kind)
 if party_id:master(s,u.company_id,'customer' if kind in ('sale','sale_receipt','sale_return') else 'supplier' if kind in ('purchase','purchase_payment','purchase_return') else 'customer',party_id)
 if warehouse_id:master(s,u.company_id,'warehouse',warehouse_id)
 x.number=number.strip()[:60];x.date=date_value;x.party_id=party_id or None;x.warehouse_id=warehouse_id or None;x.memo=memo[:1000];x.payload=json.dumps(p);audit(s,u,'edit','document',x.id,x.number);s.commit();return go('/documents/'+kind)
@app.post('/documents/{kind}/{did}/delete')
def document_delete(req:Request,kind:str,did:int,s=Depends(db)):
 u=user(req,s);authorize(s,u,'write','documents');x=owned(s,Document,did,u.company_id)
 if x.kind!=kind:raise HTTPException(404)
 try:
  if x.status=='posted':unlock_posted_document(s,u,x)
  audit(s,u,'delete','document',x.id,x.number)
  s.delete(x);s.commit()
 except:s.rollback();raise
 return go('/transactions')
@app.post('/documents/{kind}/{did}/post')
def document_post(req:Request,kind:str,did:int,s=Depends(db)):
 u=user(req,s);authorize(s,u,'post','documents');x=owned(s,Document,did,u.company_id)
 if x.kind!=kind:raise HTTPException(404)
 try:post(s,x);audit(s,u,'post','document',x.id,x.number);s.commit()
 except:s.rollback();raise
 return go('/documents/'+kind)
@app.get('/documents/sale/{did}/print/{print_type}')
def print_sale(req:Request,did:int,print_type:str,s=Depends(db)):
 u=user(req,s);authorize(s,u,'read','documents')
 if print_type not in ('invoice','delivery'):raise HTTPException(404,'Jenis cetakan tidak ditemukan')
 doc=owned(s,Document,did,u.company_id)
 if doc.kind!='sale' or doc.status!='posted':raise HTTPException(400,'Cetak hanya tersedia untuk faktur penjualan yang sudah diposting')
 company=s.get(Company,u.company_id)
 party=master(s,u.company_id,'customer',doc.party_id) if doc.party_id else None
 payload=json.loads(doc.payload or '{}')
 template=s.query(PrintTemplate).filter_by(company_id=u.company_id,kind=print_type).first()
 paper={'A4':A4,'A5':A5,'Letter':letter}.get(template.paper if template else 'A4',A4)
 cfg=json.loads(template.settings or '{}') if template else {}
 def show(key):return cfg.get(key,True)
 output=io.BytesIO();pdf=Canvas(output,pagesize=paper)
 W,H=paper; margin=42;y=H-48
 def txt(x,y,value,size=10,bold=False):
  pdf.setFont('Helvetica-Bold' if bold else 'Helvetica',size)
  pdf.drawString(x,y,str(value).encode('latin-1','replace').decode('latin-1'))
 def header():
  nonlocal y
  y=H-48
  if show('show_logo') and template and template.logo:
   try:pdf.drawImage(ImageReader(io.BytesIO(base64.b64decode(template.logo))),W-130,y-8,width=85,height=36,preserveAspectRatio=True,mask='auto')
   except Exception:pass
  if show('show_company'):txt(margin,y,company.name,16,True);y-=28
  if show('show_title'):txt(margin,y,(template.title if template and template.title else ('FAKTUR PENJUALAN' if print_type=='invoice' else 'SURAT JALAN')),14,True);y-=24
  if cfg.get('extra_header'):txt(margin,y,cfg['extra_header'][:90],9);y-=18
  if show('show_number'):txt(margin,y,'Nomor: '+doc.number);y-=18
  if show('show_date'):txt(margin,y,'Tanggal: '+doc.date);y-=18
  if show('show_customer'):txt(margin,y,'Pelanggan: '+(party.name if party else '-'));y-=24
  pdf.line(margin,y,W-margin,y);y-=22
  txt(margin,y,'No.',9,True);txt(margin+32,y,'Barang / Jasa',9,True)
  if show('show_qty'):txt(margin+290,y,'Qty',9,True)
  if print_type=='invoice' and show('show_price'):txt(margin+350,y,'Harga',9,True)
  if print_type=='invoice' and show('show_total'):txt(margin+440,y,'Jumlah',9,True)
  y-=18
 header()
 subtotal=Decimal('0');tax=Decimal('0')
 for idx,line in enumerate(payload.get('items',[]),1):
  if y<110:pdf.showPage();header()
  item=master(s,u.company_id,'item',int(line['item_id']))
  q=Decimal(str(line['qty']));price=dec(line['price']);base=dec(q*price)-dec(line.get('discount',0))-dec(line.get('posted_invoice_discount',0));vat=dec(base*dec(line.get('tax_rate',0))/100)
  subtotal+=base;tax+=vat
  name=item.name[:42]
  txt(margin,y,str(idx),9);txt(margin+32,y,name,9)
  if show('show_qty'):txt(margin+290,y,str(q.normalize()),9)
  if print_type=='invoice' and show('show_price'):txt(margin+350,y,f'{price:,.0f}',9)
  if print_type=='invoice' and show('show_total'):txt(margin+440,y,f'{base:,.0f}',9)
  y-=22
 if print_type=='invoice':
  if y<115:pdf.showPage();header()
  pdf.line(margin,y,W-margin,y);y-=22
  txt(margin+290,y,'Subtotal',10,True);txt(margin+440,y,f'{subtotal:,.0f}',10);y-=19
  if show('show_tax'):txt(margin+290,y,'PPN',10,True);txt(margin+440,y,f'{tax:,.0f}',10);y-=19
  if show('show_total'):txt(margin+290,y,'Total',11,True);txt(margin+440,y,f'{subtotal+tax:,.0f}',11,True)
 else:
  if y<125:pdf.showPage();header()
  if show('show_signature'):
   y-=45;txt(margin,y,'Diterima oleh,');txt(margin+310,y,'Diserahkan oleh,');y-=65
   txt(margin,y,'(____________________)');txt(margin+310,y,'(____________________)')
 if show('show_footer') and template and template.footer:
  txt(margin,38,template.footer[:90],8)
 if cfg.get('extra_footer'):txt(margin,24,cfg['extra_footer'][:90],8)
 pdf.save();output.seek(0)
 filename=('faktur-' if print_type=='invoice' else 'surat-jalan-')+str(doc.id)+'.pdf'
 return StreamingResponse(output,media_type='application/pdf',headers={'Content-Disposition':f'inline; filename="{filename}"'})

@app.get('/reports/{name}')
def report(req:Request,name:str,format:str='html',start:str='',end:str='',account_id:int=0,s=Depends(db)):
 u=user(req,s);authorize(s,u,'read','reports');cid=u.company_id
 if name=='bank':
  accounts=s.query(Master).filter_by(company_id=cid,kind='coa').order_by(Master.code).all()
  bank_accounts=[a for a in accounts if account_type(a) in ('cash','bank')]
  if account_id and account_id not in [a.id for a in bank_accounts]:raise HTTPException(400,'Pilih akun Kas atau Bank')
  selected=[a for a in bank_accounts if not account_id or a.id==account_id]
  today=date.today().isoformat();end=end or today;start=start or today[:4]+'-01-01'
  try:date.fromisoformat(start);date.fromisoformat(end)
  except ValueError:raise HTTPException(400,'Tanggal tidak valid')
  if start>end:raise HTTPException(400,'Periode tidak valid')
  rows=[];docs={d.id:d for d in s.query(Document).filter_by(company_id=cid).all()}
  for a in selected:
   js=s.query(Journal).filter_by(company_id=cid,account_id=a.id).order_by(Journal.date,Journal.id).all()
   opening=sum((dec(j.debit)-dec(j.credit) for j in js if j.date<start),ZERO)
   balance=opening
   rows.append(dict(kind='section',label=a.code+' — '+a.name,amount=None))
   rows.append(dict(kind='opening',label='Saldo awal',balance=opening))
   for j in js:
    if not start<=j.date<=end:continue
    balance+=dec(j.debit)-dec(j.credit)
    rows.append(dict(kind='detail',date=j.date,doc=docs[j.doc_id].number if j.doc_id in docs else '-',label=j.memo or (docs[j.doc_id].number if j.doc_id in docs else 'Jurnal'),debit=dec(j.debit),credit=dec(j.credit),balance=balance))
   rows.append(dict(kind='total',label='Saldo akhir '+a.name,balance=balance))
  title='Buku Kas dan Bank';period='Periode '+start+' s.d. '+end;company=s.get(Company,cid).name
  if format=='xlsx':return export_xlsx(title,company,period,rows,[], 'ledger')
  if format=='pdf':return export_pdf(title,company,period,rows,[], 'ledger')
  return page(req,s,title,report_name='bank',financial_rows=rows,financial_notes=[],report_start=start,report_end=end,report_account_id=account_id,report_accounts=bank_accounts,report_period=period)
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
  heads=['Barang','Gudang','Qty','Nilai'] if name=='stock' else ['Kode Barang','Nama Barang','Total Qty','Nilai Persediaan']
  data=[]
  if name=='stock':
   for iid,wid in sorted({(x.item_id,x.warehouse_id) for x in ss}):
    q=sum((D(x.qty) for x in ss if x.item_id==iid and x.warehouse_id==wid),D(0));v=sum((D(x.value) for x in ss if x.item_id==iid and x.warehouse_id==wid),D(0))
    data.append([s.get(Master,iid).name,s.get(Master,wid).name,float(q),float(v)])
  else:
   for iid in sorted({x.item_id for x in ss}):
    item=s.get(Master,iid);q=sum((D(x.qty) for x in ss if x.item_id==iid),D(0));v=sum((D(x.value) for x in ss if x.item_id==iid),D(0))
    data.append([item.code,item.name,float(q),float(v)])
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
@app.get('/settings-page')
def settings_page(req:Request,s=Depends(db)):
 u=user(req,s);authorize(s,u,'read','settings');return page(req,s,'Pengaturan Tema',theme_settings=True)
@app.post('/settings')
def settings(req:Request,theme:str=Form(...),s=Depends(db)):
 u=user(req,s);authorize(s,u,'manage','settings');c=s.get(Company,u.company_id)
 if theme not in ('ocean','emerald','dark','sand'):raise HTTPException(400,'Tema tidak dikenal')
 c.theme=theme;audit(s,u,'update','settings',c.id,'Ubah tema');s.commit();return go('/settings-page')
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
