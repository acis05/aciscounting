# aciscounting.id v2.0 Beta — Laporan Persediaan & Admin

- Fix pemeriksaan Origin POST panel admin saat HTTPS diterminasi reverse proxy Railway; tetap memblokir origin berbeda.
- Format Neraca Saldo menggunakan pemisah ribuan Indonesia dan dua desimal.
- Daftar COA menampilkan saldo akun dari akumulasi jurnal.
- Laporan Mutasi Stok Barang: qty awal, masuk, keluar, akhir per barang/gudang dan periode.
- Laporan Valuasi Persediaan (PRO): qty/nilai awal, masuk, keluar, akhir per barang.
- Nilai keluar berasal dari mutasi stok yang diposting (moving average engine).

## Instalasi
Backup PostgreSQL, unggah seluruh isi ZIP ke GitHub dan deploy Railway. Pertahankan DATABASE_URL, SECRET_KEY, COOKIE_SECURE=true, ADMIN_EMAIL, ADMIN_PASSWORD. Tidak perlu reset database.

## Catatan
Lakukan uji aktivasi PRO pada domain Railway sebenarnya dan rekonsiliasi valuasi terhadap buku besar persediaan sebelum produksi. Kode status beta.
