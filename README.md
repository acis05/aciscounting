# aciscounting.id v0.1 — MVP Akuntansi & Persediaan

Aplikasi web Python FastAPI + SQLAlchemy + PostgreSQL (Railway), dengan tampilan responsif dan tema Ocean, Emerald, Dark, Sand.

## Deploy GitHub → Railway
1. Buat repository GitHub baru. Upload **isi folder** `akuntansi_cloud` ke root repository (bukan file ZIP).
2. Railway → New Project → Deploy from GitHub Repo → pilih repository.
3. Railway → Add Database → PostgreSQL.
4. Di service aplikasi, set `DATABASE_URL` ke referensi `DATABASE_URL` milik PostgreSQL (contoh `${{Postgres.DATABASE_URL}}`, sesuaikan nama service PostgreSQL).
5. Set `SECRET_KEY` dengan nilai acak panjang (minimal 32 karakter), `COOKIE_SECURE=true` untuk HTTPS.
6. Railway otomatis menggunakan `railway.json` untuk start command dan healthcheck `/health`.
7. Buka domain HTTPS yang dibuat Railway. Klik Daftar, buat akun dan nama perusahaan.
8. Akun perusahaan baru otomatis mendapat COA dasar dan Gudang Utama.

## Lokal
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export SECRET_KEY="random-long-development-secret"
uvicorn app.main:app --reload
```
Buka `http://127.0.0.1:8000`. Tanpa `DATABASE_URL`, gunakan SQLite lokal.

## Modul tersedia
- Login, registrasi, isolasi data berdasarkan perusahaan (1 perusahaan per akun).
- CRUD master COA, pelanggan, pemasok, barang/jasa, gudang, aset tetap.
- Draft / edit / hapus / posting untuk kas masuk/keluar, bank masuk/keluar, faktur dan retur penjualan/pembelian, penerimaan/pembayaran, transfer gudang, penyesuaian, jurnal umum.
- Posting otomatis double entry; jurnal posting terkunci.
- Moving average **global per barang**, stok kuantitas per gudang; transaksi stok tidak boleh backdate.
- Aset tetap: tombol posting penyusutan bulanan garis lurus.
- Laporan dasar, ekspor Excel (.xlsx) dan PDF; grafik penjualan dashboard.
- Empat tema.

## Petunjuk input dokumen
Form transaksi pada v0.1 memakai **payload JSON** (antarmuka sementara untuk MVP). Gunakan ID master yang ditampilkan pada halaman transaksi.

| Jenis | Contoh JSON payload |
|---|---|
| Kas/bank masuk/keluar | `{"amount":100000,"account":"6000"}` (kode akun lawan disesuaikan) |
| Faktur penjualan | `{"amount":150000,"qty":2,"item_id":7}` |
| Faktur pembelian | `{"amount":100000,"qty":2,"item_id":7}` |
| Penerimaan / pembayaran | `{"amount":150000,"bank":"1010"}` |
| Retur penjualan | `{"amount":75000,"qty":1,"item_id":7,"cost":50000}` (cost = HPP asli) |
| Retur pembelian | `{"amount":50000,"qty":1,"item_id":7}` |
| Transfer gudang | `{"qty":1,"item_id":7,"to_warehouse":9}` |
| Penyesuaian stok masuk | `{"qty":1,"item_id":7,"amount":50000}` |
| Penyesuaian stok keluar | `{"qty":-1,"item_id":7}` |
| Jurnal manual | `{"entries":[{"account":"1000","debit":100000,"credit":0},{"account":"3000","debit":0,"credit":100000}]}` |

**Urutan contoh pengujian:** Daftar → master barang → faktur pembelian → posting → faktur penjualan → posting → laporan stok, jurnal, laba rugi.

## Batasan v0.1 — wajib diketahui sebelum pemakaian riil
- Belum ada pengujian akuntansi komprehensif atau audit keamanan. **Jangan gunakan untuk pembukuan resmi atau data keuangan sensitif tanpa review dan pengujian tambahan.**
- UI transaksi masih memakai payload JSON, belum form baris item yang nyaman. Satu faktur hanya memproses satu jenis barang.
- Penerimaan dan pembayaran belum dialokasikan ke faktur spesifik; laporan piutang/hutang masih berupa mutasi akun, belum aging atau subledger per pelanggan/pemasok.
- Arus kas masih menampilkan saldo bersih kas-bank, **bukan laporan arus kas PSAK lengkap**.
- Neraca belum menutup laba berjalan ke ekuitas; laporan laba rugi belum membedakan beban secara detail. Jangan gunakan hasil sebagai laporan final.
- Retur penjualan memerlukan input HPP asli manual. Retur pembelian dengan perbedaan nilai menggunakan akun selisih persediaan; review kebijakan akuntansi sebelum produksi.
- Belum ada PPN, multi-currency, rekonsiliasi bank, multi-user/roles, audit trail lengkap, pembatalan/reversal posted, tutup buku lengkap, dan migrasi Alembic.
- Perhitungan stok moving average menggunakan nilai pembulatan 2 digit per transaksi. Untuk transaksi bersamaan berintensitas tinggi, perlu locking serializable/row-level dan penanganan saldo pembulatan.
- Aset tetap memakai input JSON pada master: `{"cost":12000000,"residual":0,"months":48,"start":"2026-11"}`. Harga perolehan aset belum otomatis dijurnal saat membuat master.
- PDF berupa tabel teks sederhana; laporan lebar mungkin terpotong.
- Tidak ada payment gateway atau paket Free/Pro pada versi ini; satu akun mewakili satu perusahaan.
- Tambahkan CSRF protection, rate limiting login, backup, migrasi skema, validasi ketat transaksi, log audit, dan tes sebelum rilis publik.

## Struktur
- `app/main.py`: model, engine transaksi, route, laporan.
- `app/templates/app.html`: UI.
- `app/static/style.css`: tema dan layout.
- `railway.json`: deploy Railway.


## Branding dan mobile UI

Logo resmi transparan tersedia di `app/static/aciscounting-logo.png`, ikon di `app/static/aciscounting-icon.png`. UI memakai palet hijau Acis, oranye, dan font sans-serif sistem, dengan navigasi mobile off-canvas, overlay untuk menutup menu, input touch-friendly, kartu dashboard dua kolom, dan tabel yang bisa digeser horizontal. Tema Ocean bawaan sekarang menggunakan warna Acis; tiga tema lain tetap tersedia.

Catatan: ini tetap MVP v0.1; input transaksi JSON dan batasan laporan yang dijelaskan di README tetap berlaku.
