# Discord Bot Management & Community System

Bot Discord modular, production-ready, dibangun dengan Python 3.11+ dan discord.py 2.x.
Mendukung slash command lengkap: welcome system, invite management, announcement,
role system (dropdown/reaction/autorole), ticket system,
activity logging, image management, dan konfigurasi per-guild.

---

## Daftar Isi

1. [Requirements](#1-requirements)
2. [Discord Developer Portal Setup](#2-discord-developer-portal-setup)
3. [Environment Variables](#3-environment-variables)
4. [Instalasi (Local/Development)](#4-instalasi-localdevelopment)
5. [Database Setup & Migrasi](#5-database-setup--migrasi)
6. [Menjalankan Bot](#6-menjalankan-bot)
7. [Command Synchronization](#7-command-synchronization)
8. [Deployment VPS (Ubuntu 22.04/24.04)](#8-deployment-vps-ubuntu-2204-2404)
9. [Update Bot](#9-update-bot)
10. [Backup Database](#10-backup-database)
11. [Daftar Command Lengkap](#11-daftar-command-lengkap)
12. [Troubleshooting](#12-troubleshooting)

---

## 1. Requirements

- Python 3.11 atau lebih baru
- pip & venv
- Git
- Akun Discord Developer (gratis) untuk membuat Bot Application
- VPS Ubuntu 22.04 / 24.04 untuk production (opsional untuk development lokal)
- (Opsional) Akses S3-compatible storage — jika ingin image management memakai S3

---

## 2. Discord Developer Portal Setup

### 2.1 Membuat Application & Bot

1. Buka https://discord.com/developers/applications
2. Klik **New Application**, beri nama (misalnya `Community Manager`)
3. Masuk ke tab **Bot** → klik **Add Bot**
4. Klik **Reset Token** untuk mendapatkan token bot pertama kali, lalu **copy** token tersebut.
   Token ini akan dimasukkan ke `.env` sebagai `DISCORD_TOKEN`.

   ⚠️ **Jangan pernah membagikan token ini ke siapa pun atau meng-commit-nya ke repository publik.**

### 2.2 Privileged Gateway Intents

Masih di tab **Bot**, scroll ke bagian **Privileged Gateway Intents** dan aktifkan:

- ✅ **Server Members Intent** — dibutuhkan untuk: welcome system, autorole, member log, invite tracker
- ✅ **Message Content Intent** — dibutuhkan untuk: message log (menampilkan isi pesan yang diedit/dihapus)

Tanpa kedua intent ini bot akan gagal login (`PrivilegedIntentsRequired`).

### 2.3 OAuth2 — Invite Bot ke Server

1. Masuk ke tab **OAuth2 → URL Generator**
2. Di **Scopes**, centang:
   - `bot`
   - `applications.commands` (wajib untuk slash command)
3. Di **Bot Permissions**, centang minimal:
   - Manage Roles
   - Manage Channels
   - Manage Guild (untuk invite management)
   - View Audit Log (wajib untuk anti-nuke)
   - Kick Members (wajib jika hukuman anti-nuke memakai kick)
   - Ban Members (wajib jika hukuman anti-nuke memakai ban)
   - Manage Expressions (untuk rollback emoji yang dihapus)
   - Create Instant Invite
   - View Channels
   - Send Messages
   - Embed Links
   - Attach Files
   - Read Message History
   - Add Reactions
   - Use External Emojis
   - Manage Messages (untuk fitur logging & moderasi ticket)
   - Mention Everyone (jika ingin fitur announcement mention @everyone)
4. Copy URL yang dihasilkan di bagian bawah, buka di browser, pilih server, klik **Authorize**.

### 2.4 Role Hierarchy

Setelah bot masuk server, buka **Server Settings → Roles**, dan **pindahkan role bot ke posisi
lebih tinggi** dari role-role yang akan dikelola bot (autorole, dropdown role, reaction role,
dan anti-nuke).
Bot tidak bisa memberikan/mencabut role yang posisinya lebih tinggi dari role bot sendiri
(ini adalah aturan Discord API, bukan bug).

---

## 3. Environment Variables

Salin `.env.example` menjadi `.env`:

```bash
cp .env.example .env
```

Lalu isi minimal:

```env
DISCORD_TOKEN=isi_dengan_token_bot_anda
BOT_OWNER_ID=id_discord_anda
```

Semua variabel lain dijelaskan langsung sebagai komentar di dalam `.env.example`,
termasuk konfigurasi database dan S3 storage.

Activity bot juga dapat diputar otomatis dengan mengisi `CUSTOM_ACTIVITIES`.
Pisahkan setiap teks dengan `|`, lalu atur jedanya melalui
`ACTIVITY_ROTATION_INTERVAL` (dalam detik). Placeholder `{servers}` tersedia
untuk menampilkan jumlah server yang sedang terhubung. Jika `CUSTOM_ACTIVITIES`
dikosongkan, bot tetap memakai status per-guild yang diatur melalui `/set-status`.

### Migrasi Database (SQLite → PostgreSQL/MySQL)

Default `DATABASE_URL` memakai SQLite (tidak perlu setup tambahan). Untuk pindah ke
PostgreSQL atau MySQL di production, cukup:

```bash
# PostgreSQL
pip install asyncpg
# .env: DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/discordbot

# MySQL
pip install aiomysql
# .env: DATABASE_URL=mysql+aiomysql://user:password@localhost:3306/discordbot
```

Tidak ada perubahan kode yang diperlukan — seluruh model database ditulis dengan
SQLAlchemy 2.0 yang portable antar dialect.

---

## 4. Instalasi (Local/Development)

```bash
git clone https://github.com/USERNAME/REPOSITORY.git
cd REPOSITORY

python3 -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate

pip install --upgrade pip
pip install -r requirements.txt

cp .env.example .env
nano .env   # isi DISCORD_TOKEN dan BOT_OWNER_ID
```

---

## 5. Database Setup & Migrasi

Tabel database dibuat **otomatis** saat bot pertama kali dijalankan (lihat `database/engine.py`
fungsi `init_db()`, dipanggil di `setup_hook()` pada `bot.py`). Tidak perlu menjalankan
migration script secara manual untuk instalasi baru.

Jika memakai SQLite, file database akan dibuat di `data/bot.db`.

---

## 6. Menjalankan Bot

```bash
source venv/bin/activate
python bot.py
```

Jika berhasil, akan muncul log:

```
[INFO] [__main__] Bot login sebagai NamaBot#0000 (ID: ...)
[INFO] [__main__] Terhubung ke 1 server.
```

Test dengan mengetik `/ping` di server Discord Anda.

---

## 7. Command Synchronization

- **Development**: isi `DEV_GUILD_ID` di `.env` dengan ID server testing Anda.
  Command akan langsung ter-sync ke guild tersebut (perubahan langsung terlihat,
  tidak perlu menunggu cache Discord).
- **Production**: kosongkan `DEV_GUILD_ID`. Bot akan melakukan **global command sync**,
  yang bisa memakan waktu hingga ±1 jam untuk muncul di semua server (perilaku normal
  dari Discord API, bukan bug pada bot).

Sinkronisasi dilakukan otomatis setiap kali bot start, lewat method `_sync_commands()`
di `bot.py`.

---

## 8. Deployment VPS (Ubuntu 22.04 / 24.04)

### 8.1 Login SSH

```bash
ssh root@IP_VPS
```

### 8.2 Update System

```bash
apt update && apt upgrade -y
```

### 8.3 Install Dependency

```bash
apt install -y python3 python3-pip python3-venv git
python3 --version
git --version
```

### 8.4 Buat User Khusus (Jangan Jalankan Bot Sebagai Root)

```bash
adduser discordbot
su - discordbot
```

### 8.5 Clone Project

```bash
mkdir -p /home/discordbot/discord-bot
cd /home/discordbot/discord-bot
git clone https://github.com/USERNAME/REPOSITORY.git .
```

### 8.6 Virtual Environment & Dependencies

```bash
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### 8.7 Konfigurasi `.env`

```bash
nano .env
```

Isi seperti pada [bagian 3](#3-environment-variables). Simpan dengan `Ctrl+O`, `Enter`, `Ctrl+X`.

### 8.8 Test Jalankan Manual

```bash
source venv/bin/activate
python bot.py
```

Pastikan bot online dan `/ping` berhasil dipanggil. Setelah yakin berjalan normal,
tekan `Ctrl+C` untuk berhenti, lalu lanjut ke setup systemd.

### 8.9 Setup Systemd Service

Keluar dari user `discordbot`:

```bash
exit
```

Copy file service yang sudah disediakan di `deploy/discordbot.service`:

```bash
cp /home/discordbot/discord-bot/deploy/discordbot.service /etc/systemd/system/discordbot.service
```

Isi file tersebut (sudah disiapkan, sesuaikan path jika berbeda):

```ini
[Unit]
Description=Discord Bot Management & Community System
After=network.target

[Service]
Type=simple
User=discordbot
Group=discordbot
WorkingDirectory=/home/discordbot/discord-bot
ExecStart=/home/discordbot/discord-bot/venv/bin/python bot.py
Restart=always
RestartSec=5
EnvironmentFile=/home/discordbot/discord-bot/.env

NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

### 8.10 Enable & Start Service

```bash
systemctl daemon-reload
systemctl enable discordbot
systemctl start discordbot
systemctl status discordbot
```

### 8.11 Melihat Live Logs

```bash
journalctl -u discordbot -f
```

Atau lihat file log aplikasi:

```bash
tail -f /home/discordbot/discord-bot/logs/bot.log
```

### 8.12 Restart / Stop

```bash
systemctl restart discordbot
systemctl stop discordbot
```

---

## 9. Update Bot

```bash
su - discordbot
cd /home/discordbot/discord-bot
git pull
source venv/bin/activate
pip install -r requirements.txt
exit
systemctl restart discordbot
```

---

## 10. Backup Database

Jika memakai SQLite:

```bash
su - discordbot
cd /home/discordbot/discord-bot
cp data/bot.db "data/bot_backup_$(date +%Y-%m-%d_%H-%M-%S).db"
```

Disarankan menjadwalkan backup otomatis via **cron**:

```bash
crontab -e
```

Tambahkan baris (backup setiap hari jam 03:00):

```
0 3 * * * cp /home/discordbot/discord-bot/data/bot.db /home/discordbot/discord-bot/data/bot_backup_$(date +\%Y-\%m-\%d).db
```

---

## 11. Daftar Command Lengkap

| Kategori | Command | Keterangan |
|---|---|---|
| General | `/ping` | Cek latency bot |
| General | `/help` | Daftar command via container + select menu (khusus administrator) |
| Payment | `/show payment` | Tampilkan detail payment dan QR payment server |
| Payment | `/payment set` | Member menyimpan beberapa payment miliknya sendiri |
| Payment | `/payment list` | Member melihat semua payment miliknya sendiri |
| Payment | `/payment edit` | Member mengubah payment miliknya sendiri |
| Payment | `/payment delete` | Member menghapus payment miliknya sendiri |
| Payment | `/payment clear` | Admin menghapus konfigurasi payment server |
| Settings | `/settings`, `/config` | Dashboard konfigurasi server |
| Settings | `/set-status` | Ubah teks status bot (Watching ...) |
| Welcome | `/welcome enable` \| `disable` \| `set-type` \| `set-text` \| `set-embed` \| `set-mention` \| `set-timestamp` \| `preview` | Kelola welcome message |
| Leave | `/leave enable` \| `disable` \| `set-type` \| `set-text` \| `set-embed` \| `set-mention` \| `set-timestamp` \| `preview` | Pesan saat member keluar, sama seperti welcome |
| Invite | `/invite create` \| `list` \| `delete` \| `info` \| `leaderboard` \| `user` \| `stats` | Kelola invite & tracker; invite permanen menampilkan kartu `PERMANENT LINK @everyone` |
| Role | `/role dropdown` | Buat panel dropdown role; pilih role dari menu |
| Role | `/role reaction` | Buat panel reaction role, contoh `🎮 @Gamer 🎨 @Artist` |
| Role | `/role autorole` | Role otomatis untuk member baru; kosongkan untuk mematikan |
| Announcement | `/announcement create` | Buat & preview announcement sebelum dikirim |
| Ticket | `/ticket setup` | Atur kategori & role support |
| Ticket | `/ticket config` | Dashboard konfigurasi ticket interaktif (administrator) |
| Ticket | `/ticket panel` | Wizard Ticket Panel / Application Panel dengan Components V2 |
| Logging | `/log set-channel` | Atur channel message/voice/member log dengan username dan Discord ID |
| Image | `/image upload` \| `show` \| `list` \| `delete` | Image management |
| Custom Message | `/custom create` \| `list` \| `editor` \| `quick-edit` \| `set-mode` \| `set-json` \| `preview` \| `send` \| `delete` | Builder pesan seperti Discohook (administrator) |
| Anti-Nuke | `/antinuke setup` | Aktifkan proteksi, channel log, hukuman, dan batas pelanggaran |
| Anti-Nuke | `/antinuke toggle` | Aktifkan atau nonaktifkan seluruh sistem |
| Anti-Nuke | `/antinuke feature` | Aktifkan atau nonaktifkan satu jenis proteksi |
| Anti-Nuke | `/antinuke whitelist-add` \| `whitelist-remove` | Kelola member tepercaya |
| Anti-Nuke | `/antinuke status` | Tampilkan konfigurasi dan status 18 proteksi |
| Worker Status | `/worker-status` | Input list worker maksimal 10 orang, publish panel Components V2 ke channel pilihan, dan kelola status worker |

### Sistem Anti-Nuke

Konfigurasi `/antinuke` hanya dapat digunakan oleh **owner server** atau user yang
ID-nya tersimpan sebagai `BOT_OWNER_ID`. Administrator biasa tidak dapat mematikan
proteksi. Owner server, owner bot, bot itu sendiri, dan member whitelist selalu
dianggap tepercaya.

Jalankan setup awal:

```text
/antinuke setup log_channel:#security-log punishment:Cabut semua role violation_limit:1 window_seconds:10 mention_limit:5
```

Semua proteksi aktif secara default setelah setup:

- anti ban, kick, bot add, dan prune;
- anti role create, delete, rename, permission berbahaya, dan pemberian role berbahaya;
- anti channel create, delete, dan rename;
- anti server rename dan icon change;
- anti emoji delete, mass mention, invite link, dan ghost ping.

Pilihan hukuman tersedia: `strip_roles`, `kick`, `ban`, atau `none` (hanya log).
`violation_limit` menentukan berapa pelanggaran dalam `window_seconds` sebelum hukuman
dijalankan. Tindakan berbahaya tetap dicoba untuk di-rollback pada pelanggaran pertama.

Anti-nuke membutuhkan **View Audit Log** agar dapat menemukan pelaku. Pastikan juga
bot memiliki **Manage Roles**, **Manage Channels**, **Manage Guild**, **Manage Messages**,
**Manage Expressions**, **Kick Members**, dan **Ban Members** sesuai fitur/hukuman yang
digunakan. Role bot wajib berada di atas role pelaku dan role yang akan dipulihkan.

Rollback tidak dapat menjamin pemulihan penuh. Member yang dikick/prune tidak dapat
dimasukkan kembali otomatis. Pesan/history channel yang dihapus, assignment member
pada role yang dihapus, invite channel, serta aset emoji yang sudah tidak tersedia di
CDN Discord juga mungkin tidak dapat dipulihkan. Jika pelaku tidak ditemukan di audit
log, kejadian dicatat tetapi rollback dan hukuman dilewati untuk mencegah tindakan sah
ikut dibatalkan.

### Role System

```text
/role dropdown  channel, judul, deskripsi -> pilih role dari menu -> panel dikirim
/role reaction  channel, judul, roles: 🎮 @Gamer 🎨 @Artist -> panel + reaction dikirim
/role autorole  roles: @Member -> role otomatis member baru (kosongkan untuk mematikan)
```

Dropdown memuat maksimal 25 role dan reaction role maksimal 20 role per panel, sesuai
batas Discord. Untuk mengganti panel, hapus pesan panel lama lalu buat yang baru.
Panel yang dibuat dengan command role versi lama tetap berfungsi. Semua panel memakai
Discord Components V2 berupa container polos tanpa sidebar warna.

Menu `/help`, konfigurasi payment, `/show payment`, `/image show`, informasi awal
ticket, serta konfigurasi dan pesan welcome juga menggunakan Discord Components V2.
Seluruh tampilan tersebut memakai container polos tanpa sidebar warna embed.
Kategori `/help` menggunakan application emoji dari PNG dalam `assets/help_icons`.
Bot membuat emoji tersebut otomatis saat `/help` pertama kali dibuka dan memakai
emoji bawaan sebagai fallback jika API Discord sedang tidak tersedia. File
`imge role.png` dipetakan ke kategori Image, sedangkan `role.png` ke kategori Role.
Selain ikon dropdown, `/help` menampilkan banner Components V2 dari
`assets/help_banners`. `help.png` menjadi header halaman utama dan banner kategori
diganti otomatis sesuai pilihan dropdown. Kategori Image memakai `help.png` sebagai
fallback karena tidak ada banner `image.png` pada aset kategori yang diberikan.

Gunakan `/image delete name:<nama>` untuk menghapus image yang pernah di-upload.
Command ini khusus pengelola server dan menghapus file dari storage lokal atau
object S3 terlebih dahulu, kemudian menghapus catatannya dari database. Jika
penghapusan storage gagal, data database dipertahankan agar tidak kehilangan jejak.

Tombol `Claim Ticket`, `Lock`, `Unlock`, dan `Rename` hanya dapat digunakan oleh
administrator atau member yang memiliki role support dari `/ticket setup support_role`.
Pada mode Text Channel, `Lock` hanya mencabut izin mengirim pesan dari pembuat ticket;
akses melihat channel dan membaca riwayat tetap aktif. Pada Forum Thread, Discord tidak
menyediakan overwrite per-user, sehingga `Lock` mengarsipkan dan mengunci thread sampai
staff menekan `Unlock`.
Dropdown kategori ticket otomatis di-reset setelah dipilih, sehingga kategori yang
sama dapat langsung dipilih kembali tanpa harus memilih kategori lain terlebih dahulu.

### Dashboard Ticket

Gunakan `/ticket config` untuk membuka dashboard privat khusus administrator.
Dashboard menyediakan kategori ticket dinamis beserta pertanyaan pembuka, beberapa
role support dan admin, channel log/transcript/rating, kategori tempat ticket dibuat,
format nama channel, batas ticket, cooldown, auto-close, mode hapus atau arsip,
fitur call staff/self-close/rating/transcript, pause panel, reset, serta style panel.
Setelah konfigurasi selesai, jalankan `/ticket panel` untuk membuka wizard panel.
Pilih **Ticket Panel** untuk membuat ticket sebagai Text Channel atau Forum Thread,
atau **Application Panel** untuk mengumpulkan jawaban modal ke forum review. Staff
dengan akses ticket dapat menerima atau menolak application dan applicant menerima
hasilnya melalui DM. Semua panel publik menggunakan Discord Components V2. Wizard
juga menyediakan channel tujuan panel dan custom message saat ticket dibuka. Perubahan
kategori dan style dari `/ticket config` tetap memperbarui panel yang sudah tersimpan.
Forum Thread mengikuti permission Forum Channel induknya; gunakan Text Channel bila
setiap ticket harus memiliki permission privat khusus per member.

### Konfigurasi Payment

Setiap member dapat menambahkan banyak opsi payment miliknya sendiri langsung dari
Discord menggunakan `/payment set`, misalnya QRIS, DANA, GoPay, OVO, BCA, atau
metode lainnya. Payment antar-user disimpan terpisah, sehingga dua user dapat
memakai nama opsi yang sama tanpa saling menimpa.
Parameter `name` opsional dengan nilai default `Payment`, sehingga command versi
lama yang hanya memiliki `text` dan `qr_image` tetap dapat dipakai saat Discord
belum selesai memperbarui cache slash command.
Field `text` digunakan untuk detail rekening atau e-wallet, sedangkan `qr_image`
digunakan untuk meng-upload gambar QR. Keduanya opsional, tetapi minimal salah
satu harus diisi. Jika nama belum ada, `/payment set` membuat opsi baru. Jika nama
sudah ada untuk user tersebut, command yang sama memperbarui opsi miliknya; bagian
yang tidak diisi tetap dipertahankan. `/payment list`, `/payment edit`, dan
`/payment delete` hanya membaca atau mengubah payment milik user yang menjalankan
command. `/show payment` menampilkan seluruh payment server beserta nama pemiliknya.
Data versi lama tetap tampil sebagai `Payment server`. Administrator dapat memakai
`/payment clear` untuk menghapus seluruh opsi payment dari semua pemilik.
Saat bot pertama kali dijalankan setelah update, opsi dari tabel payment lama
dipindahkan otomatis ke tabel multi-pemilik tanpa menghapus file QR. Jangan hanya
mengganti `cogs/payments.py`; file model, repository, dan engine database dari
rilis yang sama juga wajib diunggah sebelum bot direstart.
Tampilan `/show payment` merapikan input berformat
`Metode : nomor | nama penerima` menjadi blok metode, nomor, nama penerima,
pemilik Discord, dan peringatan pembayaran yang terpisah.

### Custom Message Builder

Fitur `/custom` menyediakan builder pesan bergaya Discohook dan hanya dapat
digunakan oleh administrator. Tersedia tiga mode:

- `Legacy Embed`: pesan webhook dengan embed Discord versi lama.
- `Components V2`: container baru dengan text display, separator, media gallery,
  section/thumbnail, dan link button.
- `Both`: mengirim legacy embed lalu Components V2 secara berurutan. Discord tidak
  mengizinkan embed lama dan Components V2 berada dalam satu pesan, sehingga mode
  ini memang menghasilkan dua pesan dengan identitas webhook yang sama.

Alur penggunaan melalui web editor:

```text
/custom create name:Promo mode:Both
/custom editor draft_id:1
Buka link editor -> edit -> Save -> pilih channel -> Send
```

Aktifkan web editor melalui `.env` jika hosting menyediakan port HTTP publik atau
reverse proxy/domain:

```env
CUSTOM_WEB_ENABLED=true
CUSTOM_WEB_HOST=0.0.0.0
CUSTOM_WEB_PORT=8080
CUSTOM_WEB_PUBLIC_URL=https://builder.domainkamu.com
```

Pada Pterodactyl, tambahkan allocation port untuk `CUSTOM_WEB_PORT`, lalu arahkan
domain/reverse proxy ke port tersebut. Gunakan HTTPS pada domain publik. Jika
hosting tidak menyediakan akses port web, semua fungsi tetap dapat digunakan dari
Discord dengan alur berikut:

```text
/custom create
/custom quick-edit
/custom editor              (download template/export JSON)
/custom set-json             (upload kembali JSON yang sudah diedit)
/custom preview
/custom send
```

`/custom set-mode` mengganti mode draft, `/custom list` menampilkan ID draft, dan
`/custom delete` menghapus draft. Bot membutuhkan izin **Manage Webhooks** dan
**Send Messages** pada channel tujuan. Link web editor berisi token rahasia yang
memberikan akses menyimpan dan mengirim draft; jangan membagikan link tersebut.

### Web Dashboard & Hosting Panel

Dashboard web memakai gaya brutalist dari referensi dan berjalan dalam proses Python
yang sama dengan bot serta custom message editor. Tidak perlu menjalankan Node.js di
hosting. Dashboard menyediakan:

- login OAuth2 Discord dengan scope `identify` dan `guilds`;
- daftar server yang dimiliki atau dapat dikelola user;
- server info: owner, boost, boost tier, role, channel text/voice, member, dan ID;
- status Welcome, Payment, Invite, Role, Ticket, Logging, Image,
  Custom Message, Anti-Nuke, serta Announcement;
- toggle Welcome dan Ticket untuk administrator, serta Anti-Nuke khusus owner;
- daftar slash command aktif;
- pembuatan, pembukaan, dan penghapusan draft melalui Custom Message Editor.

Custom Message Editor menggabungkan editor webhook klasik dan Components V2 dalam
satu workspace. Editor mendukung content, identitas webhook, hingga 10 Legacy Embed,
field, author, image, footer, container V2, text, section, media gallery, file attachment,
separator,
dan row link button. Pesan dapat dikirim melalui channel bot atau URL webhook resmi
Discord. URL webhook eksternal hanya digunakan ketika tombol **Send** ditekan dan
tidak disimpan ke draft maupun database.

Tambahkan Redirect URL di **Discord Developer Portal → OAuth2 → Redirects**:

```text
https://panel.domainkamu.com/auth/discord/callback
```

Kemudian isi `.env`:

```env
CUSTOM_WEB_ENABLED=true
DASHBOARD_ENABLED=true
CUSTOM_WEB_HOST=0.0.0.0
CUSTOM_WEB_PORT=8080
CUSTOM_WEB_PUBLIC_URL=https://panel.domainkamu.com
DISCORD_CLIENT_ID=application_id_bot
DISCORD_CLIENT_SECRET=oauth_client_secret
DASHBOARD_REDIRECT_URI=https://panel.domainkamu.com/auth/discord/callback
DASHBOARD_SESSION_HOURS=12
```

Pada hosting panel, alokasikan satu port HTTP yang sama dengan `CUSTOM_WEB_PORT`, lalu
arahkan domain/reverse proxy ke port tersebut. URL dashboard adalah `/dashboard`,
custom editor tetap `/custom/<token>`, dan health check tersedia di `/health`.
Saat `DASHBOARD_ENABLED=true`, editor custom juga otomatis tersedia untuk draft yang
dibuat dari dashboard. `CUSTOM_WEB_ENABLED=true` tetap dapat dipakai untuk menjalankan
editor tanpa mengaktifkan dashboard OAuth.
Jangan mengisi `DISCORD_CLIENT_SECRET` di source code atau membagikannya kepada siapa pun.

---

## 12. Troubleshooting

**Bot tidak online / error saat start**
- Cek `DISCORD_TOKEN` di `.env` sudah benar dan belum di-reset di Developer Portal.
- Pastikan **Server Members Intent** dan **Message Content Intent** sudah diaktifkan
  di Developer Portal (lihat [bagian 2.2](#22-privileged-gateway-intents)).

**Slash command tidak muncul di Discord**
- Jika `DEV_GUILD_ID` diisi: command harus langsung muncul di guild tersebut.
  Jika tidak, pastikan bot punya scope `applications.commands` saat di-invite.
- Jika sync global (production): tunggu hingga 1 jam, atau coba leave & rejoin
  channel di Discord client untuk memaksa refresh cache.
- Jika muncul `CommandSignatureMismatch`, bot otomatis menjalankan recovery sync
  langsung ke guild tersebut. Tunggu sekitar 10 detik, hapus command lama dari
  kolom chat, lalu pilih kembali command terbaru dari autocomplete Discord.

**Web editor custom message tidak dapat dibuka**
- Pastikan `CUSTOM_WEB_ENABLED=true` atau `DASHBOARD_ENABLED=true`, nilai
  `CUSTOM_WEB_PUBLIC_URL` dapat diakses publik, dan port `CUSTOM_WEB_PORT` sudah
  dialokasikan/dibuka oleh hosting.
- Jika tidak tersedia port HTTP atau reverse proxy, gunakan fallback JSON melalui
  `/custom editor` dan `/custom set-json`; bot tidak bergantung pada web editor.

**Dashboard meminta login ulang setelah bot restart**
- Sesi OAuth disimpan sementara di memori agar token akses Discord tidak ditulis ke
  database. Restart bot akan menghapus sesi dan pengguna perlu login kembali.

**Login Discord kembali ke `/?code=...` dan tetap menampilkan halaman login**
- `DASHBOARD_REDIRECT_URI` atau Redirect OAuth Discord masih mengarah ke root domain.
  Versi terbaru dapat memproses callback root sebagai fallback, tetapi konfigurasi
  yang disarankan tetap `https://domain/auth/discord/callback` pada kedua tempat.

**Log menyebut gateway reconnect saat memperbarui activity**
- Bot menunda perubahan activity sampai koneksi Discord kembali READY. Pesan ini
  bersifat informasional dan activity yang gagal tidak akan dilewati dari rotasi.

**Bot tidak bisa memberi role (autorole/dropdown/reaction role)**
- Pastikan role bot **lebih tinggi** dari role yang ingin diberikan
  (Server Settings → Roles → drag posisi role bot ke atas).

**Anti-nuke mencatat kejadian tetapi tidak melakukan rollback/hukuman**
- Pastikan bot memiliki izin **View Audit Log** dan izin pengelolaan yang sesuai.
- Pastikan role bot berada di atas role pelaku. Tanpa atribusi audit log yang valid,
  sistem sengaja hanya mencatat kejadian agar tidak membatalkan tindakan sah.

**Ticket tidak bisa dibuat**
- Jalankan `/ticket setup` terlebih dahulu untuk mengatur kategori channel.
- Pastikan bot punya izin **Manage Channels** di server.

**Service systemd gagal start**
- Cek log detail: `journalctl -u discordbot -n 100 --no-pager`
- Pastikan path `WorkingDirectory` dan `ExecStart` di `discordbot.service`
  sesuai dengan lokasi instalasi project Anda.

**Ingin reset seluruh data**
- Hentikan bot (`systemctl stop discordbot`), backup dulu (lihat bagian 10),
  lalu hapus `data/bot.db` — tabel akan dibuat ulang otomatis saat bot start berikutnya.

---

## Struktur Project

```
discord-bot/
├── bot.py                     # Entry point utama
├── config.py                  # Loader environment variables
├── requirements.txt
├── .env.example
├── database/
│   ├── models.py               # Definisi tabel (SQLAlchemy)
│   ├── engine.py                # Engine & session factory
│   └── repositories.py         # Fungsi CRUD per domain
├── cogs/                       # Slash command per fitur (modular)
│   ├── general.py
│   ├── settings.py
│   ├── welcome.py
│   ├── invites.py
│   ├── roles.py
│   ├── announcements.py
│   ├── tickets.py
│   ├── logging_cog.py
│   ├── images.py
│   ├── custom_messages.py
│   └── anti_nuke.py
├── ui/                          # Button, Select Menu, Modal
│   ├── role_views.py
│   ├── ticket_views.py
│   ├── ticket_dashboard.py
│   ├── modals.py
│   └── help_view.py
├── services/                    # Logika bisnis non-Discord
│   ├── storage.py                # Abstraksi local/url/S3
│   ├── custom_messages.py          # Renderer legacy embed dan Components V2
│   ├── custom_web.py               # Web server editor opsional
│   ├── transcript.py
│   └── invite_cache.py
├── web/
│   └── custom_editor.html          # UI builder web responsif
├── utils/
│   ├── logger.py
│   ├── permissions.py
│   ├── error_handler.py
│   ├── embeds.py
│   └── placeholders.py
├── data/                        # Database & file upload (jangan commit)
├── logs/                        # Log rotating (jangan commit)
└── deploy/
    └── discordbot.service       # Template systemd unit
```
