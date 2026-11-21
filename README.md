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


## v0.6 — navigasi v0.4 dipertahankan
- Sidebar accordion dan submenu tetap seperti v0.4 (bukan panel pop-up v0.5).
- Semua Transaksi menampilkan daftar lintas modul.
- Tiap menu transaksi memiliki tab Input dan Daftar, termasuk edit/hapus draft.
- Faktur penjualan yang telah diposting: tombol Cetak Faktur dan Cetak Surat Jalan (tanpa harga).
- Transaksi posting terkunci; tidak bisa edit/hapus langsung agar jurnal dan stok tidak rusak.
- Lakukan backup database sebelum deploy.

## v0.7 — Penyajian laporan dan master data
- Menu/sidebar v0.4/v0.6 tidak diubah.
- Laba Rugi, Neraca, Buku Besar, dan Arus Kas: filter tanggal, subtotal, saldo berjalan, catatan, ekspor Excel dan PDF dengan tabel terformat.
- Semua laporan lainnya tetap mempunyai opsi ekspor Excel/PDF dari v0.6.
- Daftar master dibuat lebih padat (baris, font, dan input lebih kecil).
- Format laporan bersifat **PSAK-inspired**, bukan sertifikasi kepatuhan PSAK. Arus kas belum dapat memisahkan investasi/pendanaan otomatis dari jurnal manual; cek catatan laporan.
- Tidak ada migrasi skema database dalam v0.7. Backup PostgreSQL sebelum deploy.

## Update v0.8 — Fondasi akun, dokumen, audit dan pengguna

- COA kini mendukung jenis **Kas, Bank, Piutang, Hutang**. Akun sistem lama dimigrasikan otomatis saat membuka halaman COA/dokumen. Kode akun sistem boleh diubah, sementara identitas internal tetap dipertahankan.
- Kas/Bank masuk dan keluar dapat memilih akun Kas/Bank dari COA, termasuk beberapa akun berbeda.
- Barang dan jasa dapat memiliki pemetaan akun persediaan/beban, HPP, dan pendapatan. Pembelian jasa langsung dicatat ke akun beban, tanpa mutasi stok. Pembelian barang memakai akun persediaan per item, dan penjualan memakai akun pendapatan, HPP, dan persediaan per item.
- Faktur pembelian memilih akun bertipe Hutang, faktur penjualan memilih akun bertipe Piutang. Diskon **nominal per baris** mengurangi nilai sebelum PPN.
- Jurnal manual dapat menautkan pelanggan/pemasok pada akun Piutang/Hutang; menu **Buku Besar Pembantu** menampilkan saldo per akun dan pihak. Satu pihak boleh menggunakan beberapa akun.
- **Desain Cetakan** menyimpan judul, ukuran kertas A4/A5/Letter, logo PNG/JPEG (maks. 250 KB), dan catatan kaki per jenis dokumen. Ini pengaturan tata letak dasar, **belum editor drag-and-drop**.
- **Audit Trail** merekam tambah/edit/hapus master, tambah/edit/hapus/posting draft, pengelolaan pengguna dan template. Log belum merekam seluruh perubahan lama sebelum v0.8 dan belum memiliki diff before/after rinci.
- **Hak Akses** menambah pengguna dalam perusahaan dengan role owner, admin, accounting, sales, purchasing, viewer. Peran dasar sudah memeriksa aksi tulis/posting di backend, tetapi **pembatasan per modul untuk sales/purchasing dan perlindungan seluruh endpoint belum lengkap**. Jangan anggap ini sistem otorisasi produksi yang sudah diaudit.
- Sidebar lama v0.4/v0.6 dipertahankan; menu baru ditambahkan sebagai tautan sederhana.

### Perhatian sebelum deploy

1. **Backup database PostgreSQL** sebelum update.
2. Deploy seluruh isi ZIP ke GitHub/Railway dengan DATABASE_URL dan SECRET_KEY lama. Tidak perlu menghapus database.
3. Tabel baru (`activities`, `member_roles`, `print_templates`, `journal_parties`) dibuat otomatis oleh SQLAlchemy. Perubahan tipe akun lama dilakukan saat mengakses master/dokumen.
4. Uji jurnal barang, jasa, diskon, retur, buku besar pembantu, dan hak akses dengan data percobaan **sebelum** digunakan untuk pencatatan nyata.
5. Fitur masih **beta**; belum diaudit kepatuhan PSAK, keamanan, kontrol akses, maupun kesesuaian pajak.

## Pembaruan v0.9 (beta)

- Penyesuaian persediaan: pilihan **Akun Penyesuaian** untuk jurnal lawan, hanya item tipe Barang; akun persediaan mengikuti master barang. Akun kas/bank/piutang/hutang tidak dapat dipilih sebagai akun penyesuaian.
- Buku Kas Bank: filter per akun Kas/Bank, saldo awal, mutasi debit/kredit (masuk/keluar), saldo berjalan, saldo akhir, ekspor Excel/PDF.
- Valuasi Persediaan: total per barang dari seluruh gudang (tanpa kolom gudang), tampilan angka lokal 2 desimal.
- Desain Cetakan: checkbox komponen, header/footer tambahan, warna aksen, serta halaman pratinjau dengan data contoh. Pilihan yang sudah diterapkan pada PDF mencakup logo, perusahaan, judul, nomor, tanggal, pelanggan, kuantitas, harga, PPN, total, tanda tangan dan footer. Beberapa pilihan tambahan (alamat, SKU, satuan, diskon, warna aksen) masih untuk pengembangan berikutnya dan belum mengubah PDF akhir.
- Hak Akses: tabel `role_rules` dan editor centang izin role per modul/aksi. Pemeriksaan server-side telah diterapkan untuk master data, transaksi, laporan, pengaturan cetakan, audit, dan manajemen akses; audit lebih lanjut atas semua endpoint masih diperlukan.

**Migrasi:** kolom `print_templates.settings` ditambahkan secara aditif pada startup. Lakukan backup PostgreSQL sebelum deploy. Tidak ada reset database. Untuk penggunaan produksi, audit keamanan, pengujian transaksi dan backup/restore tetap diperlukan.


## v1.0 — Edit dan Hapus pada Semua Transaksi
- Tombol Edit dan Hapus pada daftar gabungan, baik Draft maupun Sudah Posting.
- Edit transaksi Posted membuka kembali transaksi menjadi Draft, menghapus jurnal dan mutasi stok lama, lalu pengguna menyimpan perubahan dan melakukan Posting ulang.
- Hapus transaksi Posted menghapus jurnal dan mutasi stok yang terkait sebelum menghapus dokumen.
- Demi keamanan moving-average, transaksi yang memengaruhi stok hanya dapat dibuka/dihapus jika tidak ada mutasi stok sesudahnya; transaksi yang sudah memiliki retur tidak dapat dibuka/dihapus.
- Transaksi dalam periode terkunci tidak dapat dibuka/dihapus. Aktivitas reopen/delete dicatat pada Audit Trail.
- Sebelum menggunakan pada database produksi, lakukan backup dan uji skenario transaksi berantai di staging.

## v1.1 Beta — Dashboard dan Diskon Faktur
- Dashboard: grafik 5 akun beban terbesar bulan berjalan, grafik ringkas pendapatan/beban/laba bulan berjalan, 10 estimasi piutang dan hutang jatuh tempo terbesar.
- Jatuh tempo diinput di faktur penjualan/pembelian; dokumen lama tanpa tanggal jatuh tempo diasumsikan 30 hari dari tanggal faktur. Karena pelunasan belum ditautkan langsung ke nomor faktur, daftar jatuh tempo merupakan **estimasi** dengan alokasi pembayaran ke faktur tertua per pelanggan/pemasok dan akun pengendali. Jangan menganggap daftar ini sebagai aging piutang/hutang yang sudah direkonsiliasi.
- Diskon faktur nominal pada bagian bawah faktur penjualan/pembelian. Dialokasikan proporsional ke nilai bersih tiap baris sebelum PPN sehingga mengurangi pendapatan/biaya perolehan persediaan; jurnal retur menyesuaikan diskon faktur asal secara proporsional.
- Pengaturan tema dipindahkan dari dashboard ke submenu Pengaturan. Fitur penguncian periode tidak dihapus dari mesin jurnal maupun database; hanya kontrolnya tidak ditampilkan pada dashboard.
- Buku Besar Pembantu dipindah ke submenu Laporan. Master COA, pelanggan, pemasok, barang/jasa lebih ringkas pada HP.
- Tetap **BETA**. Uji dahulu pada database staging, backup PostgreSQL sebelum deploy. Dashboard jatuh tempo bukan rekonsiliasi pembayaran faktur; pembukuan multi-tenant dan seluruh role tetap memerlukan audit keamanan.
