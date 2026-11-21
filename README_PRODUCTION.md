# aciscounting.id v1.6 — FREE/PRO & Platform Admin (Beta)

## Railway
- Provision PostgreSQL and connect `DATABASE_URL` (Railway PostgreSQL reference).
- Set `SECRET_KEY` to a random 32+ byte secret and `COOKIE_SECURE=true` for HTTPS.
- Set `ADMIN_EMAIL` to your private administrator email.
- Generate `ADMIN_PASSWORD_HASH` using Argon2, for example: `python -c "from argon2 import PasswordHasher; import getpass; print(PasswordHasher().hash(getpass.getpass()))"`. Copy only the resulting hash into Railway Variables, never the plain password.
- `railway.json` runs uvicorn on `$PORT`. Keep a single web replica for this SQLite-free PostgreSQL deployment until session/locking is reviewed.
- Open `/platform-admin/login` to manage companies and users.
- Registration `/register` defaults to FREE. Login `/login` uses email/password.
- Admin PRO activation is manual (payment gateway is NOT integrated); price Rp299.000/year. Renewals extend from the current expiry if active.
- Admin password reset displays a temporary password once; it must be changed on next login. Share temporary passwords through a secure private channel.
- No self-service email recovery or email verification is implemented. Add before public production.

## FREE limits
- Items 20 total; customers 30; suppliers 30.
- Sales and purchase invoices 20 combined/month.
- Cash in/out and bank in/out 60 combined/month.
- Manual journals 30/month.
- Cashflow report PRO only.
- Existing data is retained after downgrade; new records are blocked once quota is reached.
- Asset menus and routes disabled. Historical asset records are not deleted.

## SECURITY / production caveats
- Beta. Verify tenant isolation, CSRF protection for all forms, login rate limiting, email verification, payment verification, database migration, backups and accounting reconciliation before opening paid subscriptions.
- Admin password hash and session secret must never be committed to GitHub.
- Reset sessions remain valid until a user next requests a page; enforce full session invalidation in a production hardening pass.

## Perubahan v1.7 — paket FREE/PRO

- FREE: impor master Excel (termasuk template) diblokir server; PRO tetap dapat mengimpor.
- FREE: hanya satu gudang bawaan; form tambah gudang disembunyikan dan endpoint tambah gudang dibatasi di server.
- FREE: transfer gudang, penyesuaian barang, retur penjualan dan retur pembelian ditandai (PRO), diarahkan ke halaman Upgrade dan diblokir di endpoint akses dokumen.
- FREE: seluruh ekspor laporan Excel/PDF diblokir di server dan tombol ekspor disembunyikan; tampilan HTML tetap tersedia kecuali Arus Kas.
- Barang: nilai saldo awal otomatis dari Qty Awal × Harga Pokok Awal per unit, tanpa input Saldo Awal (Rp) tersendiri. Nilai jurnal pembukaan dihitung backend.
- Pengaturan → Upgrade ke PRO berisi manfaat PRO, Rp299.000/tahun dan tautan WhatsApp 0878-8453-8950.
- Upgrade PRO masih manual melalui panel admin; tidak ada pembayaran otomatis atau konfirmasi pembayaran di aplikasi.

Lakukan backup database dan uji pada Railway staging sebelum deploy publik.
