# aciscounting.id v2.1 — COA Preset, Kas/Bank Terpadu, Import Transaksi

## Fitur
- Master Data → COA: pilihan rekomendasi General, Dagang, Jasa, Kontraktor, Kuliner, Manufaktur, Online Shop, Konsultan/Profesional, Properti/Sewa. Preview daftar akun sebelum menerapkan. Akun yang sudah ada tidak diubah; kode bentrok dilewati. Semua akun tetap dapat diedit.
- Sidebar Kas & Bank: Kas/Bank Masuk dan Kas/Bank Keluar. Pilih akun COA tipe Kas atau Bank. Dokumen bank_in/bank_out lama tetap didukung dan ditampilkan dalam daftar gabungan.
- PRO: import XLSX Kas/Bank Masuk, Kas/Bank Keluar, dan Jurnal Umum, beserta unduhan template pada tiap menu. FREE tidak dapat mengakses endpoint impor/template.
- Hasil impor selalu Draft, harus diperiksa dan diposting satu per satu. Impor jurnal: beberapa baris dengan nomor sama digabung dan harus seimbang. Untuk akun piutang/hutang yang memerlukan identitas pihak, gunakan entri manual.

## Instalasi
Backup PostgreSQL Railway, lalu deploy source ini melalui GitHub. DATABASE_URL, SECRET_KEY, COOKIE_SECURE, ADMIN_EMAIL, ADMIN_PASSWORD tetap seperti versi sebelumnya. Tidak ada migrasi tabel baru.

## Catatan
Template menyertakan data contoh, hapus baris contoh sebelum mengimpor data nyata. Kode akun preset adalah rekomendasi umum, bukan COA final untuk seluruh kebutuhan pajak/industri. Validasi akuntansi dan pengujian migrasi pada database staging diperlukan sebelum produksi.
