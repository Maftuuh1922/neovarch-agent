# Remote dari mana saja — relay & Bluetooth

*Bahasa Indonesia di bawah · English further down.*

> **v1.4.7: Tailscale adalah jalur utama.** Relay bawaan NeovarchLabs (`wss://relay.neovarchlabs.web.id`) tidak
> pernah di‑deploy, jadi sejak v1.4.7 **tidak ada relay bawaan**: HP mencoba alamat Tailscale PC (100.x / MagicDNS)
> dulu, lalu LAN, lalu Bluetooth bila aktif, dan relay **hanya** bila Anda mengisi URL relay sendiri di
> Pengaturan ▸ Remote ▸ Relay URL. QR/HP lama yang masih membawa URL relay bawaan itu mengabaikannya (tanpa pesan
> error). Kode relay di `relay/` dan pengaturannya tetap ada untuk yang ingin menjalankan relay sendiri — panduan di
> bawah masih berlaku untuk itu. Cara memasang Tailscale: README ▸ *Remote dari mana saja*.
>
> **v1.4.7: Tailscale is the primary path.** The built-in NeovarchLabs relay was never deployed, so there is **no
> default relay** any more: the phone tries the PC's Tailscale address first, then the LAN, then Bluetooth, and a
> relay **only** when you set your own relay URL. The self-hosting guide below still applies.

---

## Bahasa Indonesia

### Singkatnya

Pindai QR dari PC **sekali**. Setelah itu aplikasi Neovarch di HP menemukan PC Anda sendiri, di mana pun:

1. **Langsung (LAN)** — Wi‑Fi yang sama, atau hotspot HP/PC (tidak butuh internet sama sekali).
2. **Lewat Bluetooth** — bila diaktifkan di PC dan HP, dan PC berada dalam jangkauan (tanpa internet).
3. **Lewat relay** — dari mana saja lewat internet: data seluler, Wi‑Fi kantor, luar kota.

Tanpa aplikasi tambahan, tanpa VPN, tanpa akun, gratis. Status di HP menunjukkan jalurnya: **Langsung (LAN)**,
**Lewat Bluetooth**, atau **Lewat relay**. Bila jaringan berganti, HP pindah jalur sendiri dan kembali ke LAN begitu
LAN terjangkau lagi; tidak perlu memasangkan ulang.

### Cara kerjanya

```
 HP ──(keluar)──▶ relay ◀──(keluar)── PC
       wss://relay…/v1/phone/<pcId>      wss://relay…/v1/pc/<pcId>?k=<kunci room>
```

* PC dan HP sama‑sama membuka koneksi **keluar** ke relay. Tidak ada port yang perlu dibuka di router,
  tidak ada IP publik.
* Relay hanya meneruskan pesan di dalam "room" milik satu PC. Ia **tidak menyimpan apa pun** selain soket yang sedang
  hidup, dan **tidak bisa membaca isinya**.
* Room diidentifikasi `pcId = base64url(sha256(kunci_room))[:22]`. Hanya pemegang kunci room (PC Anda) yang bisa
  menempati sisi PC; HP hanya tahu `pcId`.

### Privasi & keamanan (enkripsi ujung‑ke‑ujung)

* Saat memindai QR, HP menyimpan **kunci publik PC** (X25519) dan membuat **kunci perangkat** sendiri (disimpan di
  penyimpanan aman HP: Android Keystore lewat flutter_secure_storage).
* Setiap koneksi lewat relay/Bluetooth dimulai dengan jabat tangan: `X25519(perangkat, PC)` + `X25519(efemeral,
  efemeral)` → HKDF‑SHA256 → dua kunci ChaCha20‑Poly1305 (satu per arah). Kunci efemeral baru tiap koneksi
  (*forward secrecy*). Nonce = penghitung per arah; pesan yang diulang, dihapus, atau ditukar urutannya ditolak dan
  koneksi ditutup (*replay protection*).
* Relay hanya melihat: kapan sebuah HP terhubung ke room tertentu, ukuran dan waktu pesan. Isi (obrolan, file,
  token) tidak pernah terlihat.
* **Pemasangan:** QR membawa kode pemasangan sekali pakai yang berlaku 30 menit. HP yang sudah pernah tersambung
  lewat LAN mendaftarkan kuncinya otomatis (tidak perlu QR baru).
* **Mencabut HP:** PC ▸ Pengaturan ▸ Remote ▸ *Perangkat terpasang* ▸ **Cabut**. Koneksi HP itu lewat relay/Bluetooth
  langsung diputus dan kuncinya ditolak. (Akses LAN memakai token gateway; untuk mencabut semuanya sekaligus,
  pakai **Buat token baru**.)

### Server relay bawaan

Neovarch memakai relay publik NeovarchLabs secara bawaan (URL‑nya sudah terisi di PC dan ikut di QR, jadi pengguna
tidak perlu mengetik apa pun). Anda bebas menjalankan relay sendiri — gratis.

### Menjalankan relay sendiri

**Cloudflare (gratis, ±3 perintah).** Butuh akun Cloudflare gratis dan Node.js.

```bash
cd relay
npx wrangler login
npx wrangler deploy
```

Wrangler mencetak `https://neovarch-relay.<akun>.workers.dev`. Masukkan sebagai `wss://neovarch-relay.<akun>.workers.dev`
di PC ▸ Pengaturan ▸ Remote ▸ **Relay URL**, lalu pindai ulang QR di HP (atau biarkan: HP mengambil URL baru
otomatis saat berikutnya tersambung lewat LAN).

Memakai Durable Object berbasis SQLite (tersedia di paket gratis) dan WebSocket Hibernation, jadi room yang diam
tidak memakan kuota. Kuota gratis Cloudflare (saat penulisan: 100.000 request Worker/hari; pesan WebSocket masuk
dihitung 20:1) cukup untuk pemakaian pribadi; cek halaman harga Cloudflare untuk angka terbaru.

**Docker / VPS / server rumah.**

```bash
docker build -t neovarch-relay relay/
docker run -d --restart unless-stopped -p 8787:8787 neovarch-relay
```

Atau tanpa Docker: `node relay/src/node-server.js` (Node ≥ 20, tanpa dependensi npm). Pasang di belakang reverse
proxy TLS (Caddy, nginx, Cloudflare Tunnel) supaya HP memakai `wss://`. Contoh Caddy:

```
relay.contoh.id {
  reverse_proxy 127.0.0.1:8787
}
```

**Batas (keduanya sama, bisa diatur lewat env/`[vars]`):** pesan maks 256 KiB (`MAX_MESSAGE_BYTES`), maks 5 HP per
room (`MAX_PHONES_PER_ROOM`), koneksi diam 120 detik ditutup (`IDLE_SECONDS`; aplikasi mengirim ping tiap 25–30
detik), batas laju per koneksi (100 pesan/detik, 1 MiB/detik, dengan burst). Node: `MAX_ROOMS` (bawaan 10.000).

### Mengarahkan aplikasi ke relay Anda

PC ▸ Pengaturan ▸ Remote ▸ **Relay URL** → `wss://relay.anda`. Kosongkan untuk kembali ke relay bawaan. HP membaca
URL relay dari QR, dan memperbaruinya sendiri setiap kali tersambung lewat LAN.

Untuk build sendiri: relay bawaan adalah satu konstanta di `desktop/apps/desktop/electron/relay-defaults.ts`
(bisa juga di‑override saat build dengan `NEOVARCH_DEFAULT_RELAY_URL`); core menyimpan nilai yang sama di
`core/neovarch/remote_link/__init__.py` untuk `neovarch serve` tanpa aplikasi desktop.

### Bluetooth

> **Belum tersedia di rilis ini.** Pengaturan dan jabat tangannya sudah disiapkan, tetapi transport Bluetooth
> (server RFCOMM di PC dan klien di HP) belum disertakan. Untuk sekarang jalurnya: LAN, lalu relay.

* Mati secara bawaan. Aktifkan di PC (Pengaturan ▸ Remote ▸ Bluetooth) **dan** di HP (Pengaturan ▸ PC ▸ Bluetooth).
* PC: Linux dengan BlueZ (lihat bagian Bluetooth di bawah untuk detail teknis dan alasannya memakai RFCOMM).
* Memakai jabat tangan dan enkripsi yang sama dengan relay; pasangan Bluetooth sistem (bonding) tidak wajib karena
  keamanan berasal dari kunci yang dipasangkan lewat QR.

### Jalankan di latar belakang

PC ▸ Pengaturan ▸ Remote ▸ **Jalankan di latar belakang**: gateway dan klien relay tetap berjalan walaupun jendela
ditutup. Jendela pindah ke ikon tray (menu tray: *Buka*, *Keluar (gateway tetap berjalan)*, *Hentikan semua &
keluar*). Gateway dijalankan sebagai proses terpisah dengan log di `neovarch-remote-gateway.log` (folder data
aplikasi), jadi tidak ikut mati saat aplikasi keluar; saat aplikasi dibuka lagi, gateway yang masih berjalan
dipakai lagi, bukan dimulai ulang.

**Mulai saat login** membuka Neovarch tersembunyi di tray setiap kali masuk ke komputer (Linux: berkas
`~/.config/autostart/neovarch-agent.desktop`; Windows/macOS: item login sistem).

Dari HP (layar **PC ▸ Layanan latar**): status layanan, sakelar *Jalan di latar* dan *Mulai saat login*, serta tombol
*Hentikan agen*, *Mulai ulang agen*, *Mulai ulang gateway*, *Hentikan gateway*. REST (token gateway wajib):

```
GET  /api/remote/background                   status + pengaturan
POST /api/remote/background                   {run_in_background?, start_at_login?}
POST /api/remote/background/{aksi}            stop-agent | restart-agent | restart-gateway | stop-gateway
```

Catatan: gateway yang dihentikan dari HP hanya bisa dinyalakan lagi dari PC. Mematikan *Jalan di latar* dari HP saat
aplikasi PC tertutup langsung menghentikan gateway. Perubahan *Mulai saat login* dari HP diterapkan saat aplikasi PC
berjalan (paling lambat ±15 detik).

### Tanpa internet sama sekali

Mode LAN sudah bekerja lewat **hotspot** HP atau PC tanpa internet: nyalakan hotspot di HP, sambungkan PC ke hotspot
itu (atau sebaliknya), dan aplikasi tersambung langsung.

---

## English

### In short

> **Bluetooth is not shipped yet:** the settings and handshake are in place, but the Bluetooth transport itself is
> not included in this release. Today the paths are LAN, then the relay.

Scan the PC's QR code **once**. From then on the Neovarch phone app finds your PC by itself, wherever you are, trying
in order: **direct LAN** (same Wi‑Fi or a phone/PC hotspot — no internet needed), **Bluetooth** (when enabled on both
and in range), then the **relay** over the internet. No extra app, no VPN, no account, free. The phone shows which
path is live ("Langsung (LAN)", "Lewat Bluetooth", "Lewat relay"), switches by itself when the network changes, and
returns to the LAN as soon as it is reachable.

### How it works

Both the PC and the phone open **outbound** WebSockets to the relay (`/v1/pc/<pcId>?k=<roomKey>` and
`/v1/phone/<pcId>`); no router ports, no public IP. The relay forwards frames inside one PC's room, stores nothing
but live sockets, and cannot read anything. `pcId = base64url(sha256(roomKey))[:22]`, so only the holder of the room
key (your PC) can take the PC side.

### Privacy (end‑to‑end encryption)

Pairing pins the PC's X25519 public key on the phone; the phone creates its own device key (secure storage).
Each relay/Bluetooth connection runs `X25519(device, pc) ‖ X25519(eph, eph)` → HKDF‑SHA256 → one
ChaCha20‑Poly1305 key per direction, fresh per connection (forward secrecy). Nonces are per‑direction counters
that are never sent: a replayed, dropped or reordered frame fails authentication and closes the link. The relay sees
only that a phone joined a room, and message sizes/times. New devices enroll with a 30‑minute pairing code from
the QR, or automatically on their next LAN connection. Revoke a phone in PC ▸ Settings ▸ Remote ▸ Paired devices.

Full wire format: [remote-protocol.md](remote-protocol.md#7-remote-dari-mana-saja-relay--bluetooth).

### Self‑hosting

* **Cloudflare (free):** `cd relay && npx wrangler login && npx wrangler deploy`, then set
  `wss://neovarch-relay.<account>.workers.dev` as the Relay URL on the PC. Uses SQLite‑backed Durable Objects (free
  plan) with WebSocket hibernation.
* **Docker:** `docker build -t neovarch-relay relay/ && docker run -d -p 8787:8787 neovarch-relay`, or
  `node relay/src/node-server.js` (Node ≥ 20, zero npm dependencies). Put it behind TLS (Caddy/nginx/Cloudflare
  Tunnel) so phones use `wss://`.
* Limits (both): 256 KiB per message, 5 phones per room, 120 s idle timeout, per‑connection rate limit; configurable
  via env / `[vars]`.

### Pointing the app at your relay

PC ▸ Settings ▸ Remote ▸ Relay URL (empty = built‑in default). The phone reads the relay URL from the QR and keeps
it fresh on every LAN connection. For your own builds the default is a single constant in
`desktop/apps/desktop/electron/relay-defaults.ts` (or `NEOVARCH_DEFAULT_RELAY_URL` at build time).

### No internet at all

LAN mode already works over a phone or PC **hotspot** with no internet connection.
