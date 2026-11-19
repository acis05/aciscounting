"""Period-based accounting reports; display is PSAK-inspired, not an audit/compliance certification."""
import io
from datetime import date
from decimal import Decimal
from collections import defaultdict
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer, KeepTogether
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4, landscape
from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from html import escape

Z=Decimal('0')
def money(n):return f'{Decimal(str(n)):,.2f}'.replace(',','_').replace('.',',').replace('_','.')
def account_type(a):
 import json
 return json.loads(a.extra or '{}').get('type','')
def report_model(name,accounts,journals,documents,start,end,account_id=None):
 if start>end:raise HTTPException(400,'Tanggal mulai tidak boleh melewati tanggal akhir')
 ac={a.id:a for a in accounts};docs={d.id:d for d in documents}
 entries=[j for j in journals if j.account_id in ac and j.date<=end]
 current=[j for j in entries if j.date>=start]
 rows=[];notes=[]
 def add(label,amount=None,level=0,kind='detail',code=''):
  rows.append({'label':label,'amount':amount,'level':level,'kind':kind,'code':code})
 def totals(jset):
  t=defaultdict(lambda:[Z,Z])
  for j in jset:t[j.account_id][0]+=Decimal(j.debit);t[j.account_id][1]+=Decimal(j.credit)
  return t
 t=totals(current);all_t=totals(entries)
 def balance(a,balances,normal='debit'):
  v=balances[a.id];return (v[0]-v[1]) if normal=='debit' else (v[1]-v[0])
 def group(title,types,normal,balances):
  add(title,kind='section');s=Z
  for a in sorted(accounts,key=lambda x:x.code):
   if account_type(a) not in types:continue
   typ=account_type(a)
   v=balance(a,balances,normal)
   if typ=='contra_income':v=-v
   if v: add(a.name,v,1,'detail',a.code)
   s+=v
  add('Jumlah '+title,s,kind='subtotal');return s
 if name=='profit':
  sales=group('Pendapatan Usaha',('income',),'credit',t)
  returns=group('Pengurang Pendapatan',('contra_income',),'credit',t)
  net=sales-returns;add('PENDAPATAN BERSIH',net,kind='total')
  costs=Z;expenses=Z
  add('Beban Pokok Penjualan',kind='section')
  for a in sorted(accounts,key=lambda x:x.code):
   if account_type(a)=='expense' and (a.code.startswith('5') or a.code=='1201'):
    v=balance(a,t);costs+=v
    if v:add(a.name,v,1,'detail',a.code)
  add('Jumlah Beban Pokok Penjualan',costs,kind='subtotal')
  gross=net-costs;add('LABA (RUGI) KOTOR',gross,kind='total')
  add('Beban Operasional dan Lainnya',kind='section')
  for a in sorted(accounts,key=lambda x:x.code):
   if account_type(a)=='expense' and not (a.code.startswith('5') or a.code=='1201'):
    v=balance(a,t);expenses+=v
    if v:add(a.name,v,1,'detail',a.code)
  add('Jumlah Beban Operasional dan Lainnya',expenses,kind='subtotal')
  add('LABA (RUGI) PERIODE BERJALAN',gross-expenses,kind='grand')
  notes.append('Klasifikasi HPP memakai kode akun 5xxx dan 1201; periksa pemetaan COA jika kode akun diubah.')
 elif name=='balance':
  assets=group('ASET',('asset','contra_asset','cash','bank','receivable'),'debit',all_t)
  liabilities=group('LIABILITAS',('liability','payable'),'credit',all_t)
  equity=group('EKUITAS',('equity',),'credit',all_t)
  profit=Z
  for a in accounts:
   typ=account_type(a)
   if typ=='income':profit+=balance(a,all_t,'credit')
   elif typ=='contra_income':profit-=balance(a,all_t,'debit')
   elif typ=='expense':profit-=balance(a,all_t,'debit')
  add('Laba (Rugi) Akumulatif Belum Ditutup',profit,1)
  add('JUMLAH LIABILITAS DAN EKUITAS',liabilities+equity+profit,kind='grand')
  add('SELISIH KESEIMBANGAN',assets-liabilities-equity-profit,kind='check')
  notes.append('Laba akumulatif dihitung dari jurnal pendapatan/beban sejak awal pencatatan; akun penutupan laba dan saldo awal perlu ditinjau.')
 elif name=='ledger':
  selected=sorted((a for a in accounts if account_id is None or a.id==account_id),key=lambda x:x.code)
  if account_id is not None and not selected:raise HTTPException(404,'Akun tidak ditemukan')
  rows=[]
  for a in selected:
   opening=sum((Decimal(j.debit)-Decimal(j.credit) for j in entries if j.account_id==a.id and j.date<start),Z)
   aj=[j for j in current if j.account_id==a.id];running=opening
   if not aj and not opening:continue
   rows.append({'kind':'section','label':f'{a.code} · {a.name}'})
   rows.append({'kind':'ledger','date':'','doc':'','label':'Saldo Awal','debit':None,'credit':None,'balance':opening})
   for j in aj:
    running+=Decimal(j.debit)-Decimal(j.credit)
    rows.append({'kind':'ledger','date':j.date,'doc':docs[j.doc_id].number if j.doc_id in docs else '—','label':j.memo or 'Jurnal','debit':Decimal(j.debit),'credit':Decimal(j.credit),'balance':running})
   rows.append({'kind':'ledger_total','date':'','doc':'','label':'Saldo Akhir','debit':sum((Decimal(j.debit) for j in aj),Z),'credit':sum((Decimal(j.credit) for j in aj),Z),'balance':running})
  notes.append('Saldo debit positif; saldo kredit ditampilkan negatif pada kolom saldo berjalan.')
 elif name=='cashflow':
  # Direct method: cash movement grouped by document origin. Mixed journal transactions are kept in a separate, explicit group.
  cash_ids={a.id for a in accounts if __import__('json').loads(a.extra or '{}').get('type') in ('cash','bank') or a.code in ('1000','1010') or __import__('json').loads(a.extra or '{}').get('system_code') in ('1000','1010')}
  opening=sum((Decimal(j.debit)-Decimal(j.credit) for j in entries if j.account_id in cash_ids and j.date<start),Z)
  movements=defaultdict(lambda:Z)
  kind_map={'cash_in':('Operasi','Penerimaan kas lainnya'),'cash_out':('Operasi','Pengeluaran kas lainnya'),'bank_in':('Operasi','Penerimaan bank lainnya'),'bank_out':('Operasi','Pengeluaran bank lainnya'),'sale_receipt':('Operasi','Penerimaan dari pelanggan'),'purchase_payment':('Operasi','Pembayaran kepada pemasok')}
  for j in current:
   if j.account_id not in cash_ids:continue
   d=docs.get(j.doc_id);kind=d.kind if d else ''
   category,label=kind_map.get(kind,('Belum diklasifikasikan','Jurnal/aktivitas kas lainnya'))
   movements[(category,label)]+=Decimal(j.debit)-Decimal(j.credit)
  add('SALDO KAS DAN SETARA KAS AWAL PERIODE',opening,kind='total')
  sums={}
  for category in ('Operasi','Investasi','Pendanaan','Belum diklasifikasikan'):
   add('ARUS KAS AKTIVITAS '+category.upper(),kind='section')
   val=Z
   for (cat,label),amount in sorted(movements.items()):
    if cat==category and amount:
     add(label,amount,1);val+=amount
   add('Arus Kas Bersih '+category,val,kind='subtotal');sums[category]=val
  change=sum(sums.values(),Z)
  add('KENAIKAN (PENURUNAN) BERSIH KAS',change,kind='total')
  add('SALDO KAS DAN SETARA KAS AKHIR PERIODE',opening+change,kind='grand')
  notes.append('Metode langsung berbasis jenis dokumen. Jurnal manual dan transaksi investasi/pendanaan belum diklasifikasikan otomatis; tinjau kelompok Belum diklasifikasikan sebelum menggunakan laporan resmi.')
 return rows,notes

def export_xlsx(title,company,period,rows,notes,name):
 wb=Workbook();ws=wb.active;ws.title='Laporan';ws.sheet_view.showGridLines=False
 ledger=name=='ledger';columns=6 if ledger else 3
 ws.merge_cells(start_row=1,start_column=1,end_row=1,end_column=columns);ws.cell(1,1,company).font=Font(size=15,bold=True,color='0A6847')
 ws.merge_cells(start_row=2,start_column=1,end_row=2,end_column=columns);ws.cell(2,1,title).font=Font(size=13,bold=True)
 ws.merge_cells(start_row=3,start_column=1,end_row=3,end_column=columns);ws.cell(3,1,period).font=Font(size=10,color='64748B')
 header=['Tanggal','Dokumen','Keterangan','Debit','Kredit','Saldo'] if ledger else ['Kode','Uraian','Jumlah (Rp)']
 ws.append([]);ws.append(header)
 for cell in ws[5]:cell.fill=PatternFill('solid',fgColor='0D6D4B');cell.font=Font(bold=True,color='FFFFFF')
 for r in rows:
  if ledger:
   vals=['','','',None,None,None] if r['kind']=='section' else [r.get('date',''),r.get('doc',''),r['label'],float(r['debit']) if r.get('debit') is not None else None,float(r['credit']) if r.get('credit') is not None else None,float(r['balance']) if r.get('balance') is not None else None]
   if r['kind']=='section':vals[2]=r['label']
  else:vals=[r.get('code',''),('  ' if r.get('level') else '')+r['label'],float(r['amount']) if r.get('amount') is not None else None]
  ws.append(vals);idx=ws.max_row
  if r['kind'] in ('section','subtotal','total','grand','check','ledger_total'):
   color='DFF3E9' if r['kind'] in ('grand','total') else 'F0F5F2'
   for cell in ws[idx]:cell.fill=PatternFill('solid',fgColor=color);cell.font=Font(bold=True,color='174E3B')
  for cell in ws[idx]:
   if cell.column in ((4,5,6) if ledger else (3,)) and isinstance(cell.value,(int,float)):cell.number_format='#,##0.00;[Red](#,##0.00);–'
 ws.append([])
 for note in notes:ws.append(['Catatan:',note]);ws.merge_cells(start_row=ws.max_row,start_column=2,end_row=ws.max_row,end_column=columns)
 for col,width in enumerate(([16,23,54,19,19,20] if ledger else [16,63,25]),1):ws.column_dimensions[get_column_letter(col)].width=width
 ws.freeze_panes='A6';ws.auto_filter.ref=None
 ws.print_options.horizontalCentered=True;ws.sheet_properties.pageSetUpPr.fitToPage=True;ws.page_setup.fitToWidth=1;ws.page_setup.fitToHeight=0
 out=io.BytesIO();wb.save(out);out.seek(0)
 return StreamingResponse(out,media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',headers={'Content-Disposition':f'attachment; filename="{name}.xlsx"'})

def export_pdf(title,company,period,rows,notes,name):
 out=io.BytesIO();ledger=name=='ledger';doc=SimpleDocTemplate(out,pagesize=landscape(A4) if ledger else A4,rightMargin=30,leftMargin=30,topMargin=35,bottomMargin=35)
 styles=getSampleStyleSheet();styles.add(ParagraphStyle(name='CompanyV7',parent=styles['Heading2'],textColor=colors.HexColor('#0D6D4B'),spaceAfter=4));styles.add(ParagraphStyle(name='HeadV7',parent=styles['Normal'],fontSize=9,textColor=colors.white,leading=12));styles.add(ParagraphStyle(name='NoteV7',parent=styles['Normal'],fontSize=8,leading=11,textColor=colors.HexColor('#475569')))
 story=[Paragraph(escape(company),styles['CompanyV7']),Paragraph(escape(title),styles['Heading2']),Paragraph(escape(period),styles['NoteV7']),Spacer(1,12)]
 widths=[68,85,260,85,85,85] if ledger else [65,325,140]
 head=['Tanggal','Dokumen','Keterangan','Debit','Kredit','Saldo'] if ledger else ['Kode','Uraian','Jumlah (Rp)']
 data=[[Paragraph(escape(h),styles['HeadV7']) for h in head]];sections=[]
 for r in rows:
  if ledger:
   if r['kind']=='section':vals=['','',r['label'],'','','']
   else:vals=[r.get('date',''),r.get('doc',''),r['label']]+[money(r[k]) if r.get(k) is not None else '' for k in ('debit','credit','balance')]
  else:vals=[r.get('code',''),('   ' if r.get('level') else '')+r['label'],money(r['amount']) if r.get('amount') is not None else '']
  data.append([Paragraph(escape(str(v)),styles['NoteV7']) for v in vals]);
  if r['kind'] in ('section','subtotal','total','grand','check','ledger_total'):sections.append((len(data)-1,r['kind']))
 table=Table(data,colWidths=widths,repeatRows=1,hAlign='LEFT')
 ts=[('BACKGROUND',(0,0),(-1,0),colors.HexColor('#0D6D4B')),('TEXTCOLOR',(0,0),(-1,0),colors.white),('BOTTOMPADDING',(0,0),(-1,-1),6),('TOPPADDING',(0,0),(-1,-1),6),('VALIGN',(0,0),(-1,-1),'TOP'),('LINEBELOW',(0,0),(-1,0),.5,colors.HexColor('#0D6D4B')),('ALIGN',(-1,1),(-1,-1),'RIGHT')]
 for i,kind in sections:ts.append(('BACKGROUND',(0,i),(-1,i),colors.HexColor('#E3F4EB') if kind in ('grand','total') else colors.HexColor('#F1F5F3')))
 table.setStyle(TableStyle(ts));story.append(table);story.append(Spacer(1,14))
 for note in notes:story.append(Paragraph('Catatan: '+escape(note),styles['NoteV7']))
 doc.build(story);out.seek(0)
 return StreamingResponse(out,media_type='application/pdf',headers={'Content-Disposition':f'attachment; filename="{name}.pdf"'})
