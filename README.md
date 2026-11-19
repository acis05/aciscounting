# aciscounting.id v0.3 — Sistem Akuntansi Simpel

MVP FastAPI + PostgreSQL untuk GitHub dan Railway. Brand/logo Acis dipertahankan.

## Deploy
1. Upload **isi folder ini** ke root repository GitHub.
2. Buat project Railway dari repository tersebut dan tambahkan PostgreSQL.
3. Pada service aplikasi isi `DATABASE_URL` dengan reference ke `Postgres.DATABASE_URL`, `SECRET_KEY` dengan secret acak kuat, dan `COOKIE_SECURE=true`.
4. Railway membaca `railway.json`; buat public domain pada Settings → Networking.
5. Kunjungi `/register` untuk membuat perusahaan dan akun pertama.

## Perubahan v0.3
- Form master dan transaksi tanpa input JSON.
- Tabel item dinamis untuk faktur penjualan, pembelian, dan retur.
- Per baris: item, qty, harga, tarif PPN 0/11/12%, total.
- Posting pembelian menambah stok dan menjurnal persediaan, PPN masukan, hutang.
- Posting penjualan mengurangi stok, menjurnal piutang, penjualan, PPN keluaran, HPP, dan persediaan.
- Retur harus merujuk faktur asal dan harga/PPN sesuai faktur.
- Jurnal manual dengan baris akun/debit/kredit, tanpa JSON.
- Draft bisa diedit/hapus, posting terkunci.
- Logo, tema, dan navigasi mobile dipertahankan.

## Batasan penting
- **Belum siap untuk pembukuan produksi / klaim patuh PSAK.** Laporan neraca dan arus kas masih sederhana, subledger per faktur dan rekonsiliasi pembayaran belum lengkap, dan audit trail/CSRF/migrasi database belum matang.
- Tarif PPN yang tersedia adalah tarif nominal per baris; peraturan perpajakan dapat mensyaratkan DPP nilai lain, pengecualian, atau perlakuan khusus. Verifikasi dengan akuntan/pajak sebelum penggunaan.
- Pembelian jasa belum didukung pada faktur pembelian; untuk sementara gunakan jurnal beban.
- Penjualan jasa didukung tanpa mutasi stok.
- Persediaan moving average dihitung secara global per barang, kuantitas per gudang.
- Transaksi stok tanggal mundur diblokir, tetapi mekanisme koreksi, retur kompleks, dan stok negatif lintas transaksi masih perlu penguatan.
- `Base.metadata.create_all()` menambah tabel yang belum ada, **bukan sistem migrasi skema**. Lakukan backup PostgreSQL sebelum update.
- Semua perubahan perlu diuji dengan dataset dan skenario riil sebelum digunakan secara operasional.

## Pengujian lokal yang dilakukan
Registrasi, halaman master, form transaksi, posting pembelian + PPN, posting penjualan + PPN + HPP, dan retur penjualan berhasil diuji menggunakan SQLite dan TestClient. PostgreSQL Railway dan tampilan di perangkat fisik belum diuji.

## Pembaruan v0.4

- Kode COA sistem boleh diganti. Identitas akun untuk jurnal otomatis disimpan pada `extra.system_code` (tidak perlu migrasi skema database). Tipe akun sistem dipertahankan agar klasifikasi laporan tidak rusak.
- Jika database perusahaan lama belum memiliki akun sistem seperti PPN Masukan 1150, aplikasi membuat akun sistem yang hilang saat posting. Jika terjadi konflik kode dengan akun lain, perbaiki COA dahulu.
- Cetak faktur dan surat jalan PDF tersedia di daftar Faktur Penjualan setelah Posting. Surat jalan hanya berisi nama barang dan jumlah, tanpa harga, subtotal, atau PPN.
- Sidebar menggunakan ikon dan submenu visual yang lebih jelas, termasuk pada layar HP.
- Error validasi dari formulir ditampilkan sebagai halaman penjelasan, bukan JSON mentah (respons API yang meminta JSON tetap JSON).

**Perhatian:** Lakukan backup PostgreSQL sebelum deploy. Uji data historis dan perhitungan pajak dengan akuntan sebelum penggunaan produksi. Dokumen cetak belum termasuk nomor seri pajak, tanda tangan digital, alamat lengkap, atau format faktur pajak resmi.

## v0.5 — Navigasi dan daftar transaksi (19 November 2026)

- Sidebar ringkas: klik kategori membuka panel mengambang berisi grid ikon submenu ke samping, bukan dropdown memanjang.
- Mobile: panel ikon 2 kolom, tablet 3 kolom, desktop 4 kolom. Klik di luar panel atau Escape untuk menutup.
- Menu **Semua Transaksi** di sidebar menampilkan daftar lintas jenis transaksi dan tautan menuju daftar per jenis.
- Setiap halaman input transaksi mempunyai tab **Input** dan **Daftar**, dengan tombol **Edit Draft**, **Hapus**, dan **Posting** untuk dokumen draft. Dokumen posted terkunci sesuai audit trail akuntansi.
- **Faktur Penjualan**: tombol **Cetak Faktur** dan **Cetak Surat Jalan** muncul pada baris faktur yang sudah diposting. Surat jalan tidak menampilkan harga.
- Tidak ada perubahan skema database, environment variables Railway tetap sama. Backup PostgreSQL sebelum update.

Catatan: menu dan tata letak baru diuji secara otomatis melalui HTML/TestClient, belum diuji visual pada perangkat fisik. Perbaikan ini tidak mengubah engine jurnal v0.4.
