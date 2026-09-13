# smc-prompt

`smc-prompt` adalah **CLI Python sekali-jalan (single-run)** yang mengambil data
OHLC dari **Binance public REST API** (tanpa API key), menghitung **fakta
struktural yang objektif dan mekanis** (lapisan `[FAKTA]`), menyuntikkan fakta
tersebut ke dalam template prompt yang tetap, lalu **mencetak prompt akhir ke
terminal** dan **menyalinnya ke clipboard**.

Alat ini adalah **utilitas penyiapan data (data-preparation utility)** untuk LLM
teks di hilir. Ia **tidak melakukan penalaran apa pun** sendiri; seluruh
interpretasi non-trivial (DOL, liquidity sweep, bias, konfirmasi entry)
didelegasikan sepenuhnya kepada LLM yang membaca prompt.

> Dokumentasi desain lengkap dan beku (frozen) tersedia di
> [`docs/DESIGN_SPEC.md`](docs/DESIGN_SPEC.md).

---

## Fitur Utama

- **Dua lapisan payload** yang disuntikkan ke prompt:
  - **Layer A — Computed Summary:** harga saat ini, swing high/low terdeteksi
    (harga + timestamp), klasifikasi struktur mekanis, metrik jarak, dan
    ATR(14) opsional.
  - **Layer B — Raw Candle Table:** tabel OHLC ringkas format CSV (HTF daily dan
    LTF hourly) agar LLM dapat menurunkan sendiri FVG, Order Block, dan
    CHoCH/MSS (butuh 3 candle untuk FVG, beberapa swing untuk CHoCH/MSS).
- **Deteksi swing deterministik:** N-bar Williams Fractal (default `N = 5`)
  dengan post-filter pemisahan ATR. Tanpa random, tanpa rekursi, tanpa
  lookahead.
- **Klasifikasi struktur mekanis:** `Bullish` / `Bearish` / `Ranging/Mixed` —
  murni perbandingan numerik swing terakhir, **bukan** "bias".
- **Retry + backoff** dan **failover host** (connection error, HTTP 451
  geo-block, HTTP 403).
- **Output ganda:** cetak ke `stdout` **dan** salin ke clipboard; jika clipboard
  tidak tersedia (lingkungan headless), prompt ditulis ke berkas fallback.
- **Tanpa API key**, hanya endpoint **read-only public market data**.

## Non-Goals (batas keras)

- **Tidak ada panggilan LLM API apa pun.**
- **Tidak ada penalaran SMC/ICT** — tidak menghitung DOL, tidak menarasikan
  liquidity sweep, tidak menetapkan trading bias.
- **Tidak ada pemrosesan gambar/vision.**
- **Tidak ada eksekusi order / auto-trading.**
- Hanya endpoint **read-only public** Binance market data yang dipanggil.

## Persyaratan (Requirements)

- **Python 3.10 atau lebih baru** (`requires-python = ">=3.10"`).
- Sistem operasi: Windows / macOS / Linux.
- Koneksi internet ke endpoint publik Binance.
- Dependensi Python (lihat [`requirements.txt`](requirements.txt)):
  - [`requests`](https://pypi.org/project/requests/) `>= 2.31.0`
  - [`pandas`](https://pypi.org/project/pandas/) `>= 2.0.0`
  - [`pyperclip`](https://pypi.org/project/pyperclip/) `>= 1.8.2`
  - [`click`](https://pypi.org/project/click/) `>= 8.1.7`
  - [`jinja2`](https://pypi.org/project/jinja2/) `>= 3.1.2`
- Catatan clipboard: di Linux headless, `pyperclip` membutuhkan `xclip`/`xsel`.
  Bila tidak ada, prompt otomatis dialihkan ke berkas fallback.

## Instalasi

```bash
# 1. Clone repositori
git clone <URL_REPO_ANDA> smc-prompt
cd smc-prompt

# 2. Buat dan aktifkan virtualenv
python -m venv .venv

# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

# 3. Pasang dependensi
pip install -r requirements.txt

# 4. Pasang paket dalam mode editable (opsional, untuk console script)
pip install -e .
```

Setelah `pip install -e .`, skrip konsol `smc-prompt` tersedia di `PATH`.
Paket juga dapat dijalankan tanpa instalasi melalui `python -m smc_prompt`.

## Cara Penggunaan (Usage)

Bentuk umum:

```
smc-prompt <SYMBOL> [--htf-candles N] [--ltf-candles N] [--swing-lookback N]
                     [--distance-reference {nearest,most-recent}] [--no-atr]
                     [--base-url URL] [--output-dir PATH] [--debug]
```

Entry point yang tersedia:

- `smc-prompt <SYMBOL> ...` — console script dari `pip install -e .`
  ([`pyproject.toml`](pyproject.toml)).
- `python -m smc_prompt <SYMBOL> ...` — tanpa instalasi
  ([`smc_prompt/__main__.py`](smc_prompt/__main__.py)).

Bantuan dan versi:

```bash
smc-prompt --help      # atau -h
smc-prompt --version
```

### Penjelasan Opsi / Flag CLI

Tabel berikut diturunkan langsung dari [`smc_prompt/cli.py`](smc_prompt/cli.py)
dan [`smc_prompt/config.py`](smc_prompt/config.py).

| Flag / Argumen | Tipe | Default | Keterangan |
|---|---|---|---|
| `SYMBOL` | positional `str` | — | Simbol Binance Spot, mis. `BTCUSDT`. Case-insensitive; dinormalisasi ke huruf besar. Wajib diisi. |
| `--htf-candles` | `int >= 10` | `60` | Jumlah candle **daily tertutup** (closed) pada tabel mentah HTF. |
| `--ltf-candles` | `int >= 10` | `100` | Jumlah candle **hourly tertutup** (closed) pada tabel mentah LTF. |
| `--swing-lookback` | `int` ganjil `>= 3` | `5` | Ukuran window fractal `N` untuk deteksi swing. |
| `--distance-reference` | pilihan: `nearest` \| `most-recent` | `nearest` | Referensi swing untuk perhitungan jarak. `nearest` = swing terdekat berdasarkan jarak harga absolut ke harga saat ini; `most-recent` = swing terbaru berdasarkan timestamp. |
| `--no-atr` | flag | off (ATR aktif) | Menghilangkan baris ATR(14) dari prompt. Perhitungan ATR tetap dilakukan (dipakai filter swing); hanya tampilan yang disembunyikan. |
| `--base-url` | `str` (URL) | `None` | Override host REST Binance. Host ini di-`prepend` ke daftar host default, tetap dengan failover. |
| `--output-dir` | `path` (folder) | `output` | Direktori untuk berkas fallback clipboard. |
| `--debug` | flag | off | Cetak stack trace saat error. |
| `--version` | flag | — | Tampilkan versi program lalu keluar. |
| `-h`, `--help` | flag | — | Tampilkan bantuan lalu keluar. |

### Semantik `--distance-reference`

- `nearest` (default): swing high/low yang dilaporkan adalah swing terdeteksi
  yang **harganya paling dekat secara absolut** dengan harga saat ini.
- `most-recent`: swing high/low yang dilaporkan adalah **swing terdeteksi
  terbaru berdasarkan timestamp**.

Kedua mode terimplementasi penuh; default adalah `nearest`.

### Failover Host

CLI mencoba host secara berurutan dan berpindah (failover) saat connection
error, HTTP 451 (geo-block), dan HTTP 403:

1. `https://api.binance.com`
2. `https://data-api.binance.vision`

Memberikan `--base-url` akan menempatkan host tersebut di urutan pertama,
diikuti host fallback yang tersisa (host yang sama tidak diduplikasi). Daftar
host tersimpan di [`smc_prompt/config.py`](smc_prompt/config.py) sebagai
konstanta `DEFAULT_BASE_URLS`.

### Format Output

- Prompt yang dirender dicetak ke **stdout** dan disalin ke **clipboard**.
- Pada operasi normal, teks prompt adalah **satu-satunya** konten di stdout;
  peringatan dan error dikirim ke stderr.
- Bila clipboard tidak tersedia (lingkungan headless), prompt ditulis ke
  `output/<SYMBOL>_<YYYYMMDDTHHMMSSZ>.md` dan sebuah peringatan dikirim ke
  stderr, mis. `output/BTCUSDT_20260913T080934Z.md`.
- Setiap baris CSV berformat: HTF `YYYY-MM-DD,O,H,L,C` dan LTF
  `YYYY-MM-DD HH:MM,O,H,L,C` (tanpa header, tanpa kolom indeks).

---

### Examples

Bagian ini berisi contoh siap-tempel (copy-paste) untuk skenario umum. Semua
contoh menggunakan CLI yang sudah terpasang (`smc-prompt`). Bila belum
menginstal paket, ganti `smc-prompt` dengan `python -m smc_prompt`.

#### 1. Menjalankan standar (default) pada BTCUSDT

Menghasilkan prompt dengan 60 candle daily HTF, 100 candle hourly LTF,
`--swing-lookback 5`, referensi jarak `nearest`, dan ATR(14) aktif.

```bash
smc-prompt BTCUSDT
```

Keluaran yang diharapkan:

- Prompt lengkap tercetak ke **stdout**.
- Pesan `[smc-prompt] Prompt copied to clipboard.` ke **stderr**.
- Exit code `0`.

#### 2. Menjalankan tanpa instalasi (via `python -m`)

Cocok bila Anda hanya ingin menjalankan dari source tree tanpa
`pip install -e .`.

```bash
python -m smc_prompt BTCUSDT
```

Keluaran yang diharapkan sama dengan contoh 1.

#### 3. Simbol kustom, case-insensitive

Simbol dinormalisasi otomatis ke huruf besar (`ethusdt` menjadi `ETHUSDT`).

```bash
smc-prompt ethusdt
```

Keluaran yang diharapkan: prompt untuk `PAIR = ETHUSDT`, exit code `0`.

#### 4. Mengatur jumlah candle HTF dan LTF kustom

Mengambil 60 candle daily closed untuk HTF dan 100 candle hourly closed untuk
LTF (nilai default, ditulis eksplisit). Minimum yang valid adalah `10`.

```bash
smc-prompt ETHUSDT --htf-candles 60 --ltf-candles 100
```

Keluaran yang diharapkan: ukuran tabel candle pada prompt mengikuti angka yang
diminta (`HTF_CANDLE_COUNT` dan `LTF_CANDLE_COUNT`). Bila histori closed yang
tersedia lebih sedikit, tabel otomatis diperkecil dan sebuah peringatan
dikirim ke stderr dengan exit code tetap `0`.

#### 5. Histori lebih panjang untuk konteks lebih banyak

Meminta 200 candle daily dan 300 candle hourly (fetch internal ditambah
`context_buffer` 50, dibatasi maksimum 1000 candle).

```bash
smc-prompt BTCUSDT --htf-candles 200 --ltf-candles 300
```

Keluaran yang diharapkan: tabel candle lebih panjang pada prompt. Prompt menjadi
lebih besar; perhatikan batas panjang paste pada UI chat tujuan.

#### 6. Mengubah ukuran window fractal swing

Window `N` harus bilangan ganjil `>= 3`. Nilai lebih besar menghasilkan swing
yang lebih sedikit namun lebih signifikan.

```bash
smc-prompt SOLUSDT --swing-lookback 7
```

Keluaran yang diharapkan: swing high/low terdeteksi dapat berbeda dari `N = 5`.
Argumen genap atau `< 3` akan gagal dengan exit code `2`.

#### 7. Memilih referensi swing `most-recent`

Melaporkan swing high/low **terbaru berdasarkan timestamp**, bukan yang terdekat
secara harga.

```bash
smc-prompt SOLUSDT --distance-reference most-recent
```

Keluaran yang diharapkan: baris "Swing high/low terdeteksi" pada prompt memakai
swing paling anyar. Nilai selain `nearest`/`most-recent` akan ditolak oleh
`click.Choice` (exit code `2`).

#### 8. Menghilangkan baris ATR (opsional)

ATR(14) aktif secara default. Gunakan `--no-atr` untuk menyembunyikan baris ATR
dari prompt (perhitungan ATR internal tetap digunakan untuk filter swing).

```bash
smc-prompt BTCUSDT --no-atr
```

Keluaran yang diharapkan: prompt tanpa baris `- ATR(14): ... (opsional)` pada
bagian HTF maupun LTF.

#### 9. Memilih host / data source alternatif

Meng-override host REST Binance. Host ini dicoba lebih dulu, lalu fallback ke
host default bila terblokir.

```bash
smc-prompt BTCUSDT --base-url https://data-api.binance.vision
```

Keluaran yang diharapkan: permintaan dilayani oleh host yang diberikan. Bila
host gagal (connection error / HTTP 451 / HTTP 403), CLI berpindah ke host
fallback berikutnya.

#### 10. Menentukan direktori output untuk berkas fallback

Mengarahkan berkas fallback clipboard ke direktori kustom. Direktori dibuat
otomatis bila belum ada.

```bash
smc-prompt BTCUSDT --output-dir ./hasil
```

Keluaran yang diharapkan:

- Bila clipboard tersedia: prompt tercetak + tersalin, pesan
  `[smc-prompt] Prompt copied to clipboard.` pada stderr.
- Bila clipboard tidak tersedia (headless): prompt ditulis ke
  `./hasil/BTCUSDT_<YYYYMMDDTHHMMSSZ>.md` dan peringatan dikirim ke stderr.

#### 11. Mode debug untuk stack trace

Menampilkan stack trace lengkap saat terjadi error, berguna untuk pelaporan bug.

```bash
smc-prompt BTCUSDT --debug
```

Keluaran yang diharapkan: pada error, stack trace dicetak ke stderr selain pesan
error ringkas.

#### 12. Menggabungkan beberapa opsi

Contoh realistis: ETHUSDT, referensi swing terbaru, tanpa ATR, output ke folder
kustom, dan mode debug.

```bash
smc-prompt ETHUSDT --htf-candles 120 --ltf-candles 200 \
  --swing-lookback 5 --distance-reference most-recent \
  --no-atr --output-dir ./output --debug
```

Keluaran yang diharapkan: satu prompt lengkap sesuai seluruh opsi, exit code
`0`.

#### 13. Menampilkan bantuan dan versi

```bash
smc-prompt --help
smc-prompt -h
smc-prompt --version
```

Keluaran yang diharapkan:

- `--help` / `-h`: ringkasan usage, argumen, dan seluruh opsi beserta default.
- `--version`: menampilkan `smc-prompt, version 0.1.0` (versi dari
  [`smc_prompt/__init__.py`](smc_prompt/__init__.py)).

#### 14. Contoh kegagalan yang umum (beserta exit code)

Simbol tidak terdaftar di Binance Spot (exit code `3`):

```bash
smc-prompt NOTACOIN
```

Keluaran yang diharapkan:
`[smc-prompt] ERROR: Symbol 'NOTACOIN' is not listed on Binance Spot. Check the spelling (e.g. BTCUSDT).`

Argumen tidak valid, mis. `--swing-lookback` genap (exit code `2`):

```bash
smc-prompt BTCUSDT --swing-lookback 4
```

Keluaran yang diharapkan:
`[smc-prompt] ERROR: --swing-lookback must be an odd integer >= 3.`

Jumlah candle di bawah minimum (exit code `2`):

```bash
smc-prompt BTCUSDT --htf-candles 5
```

Keluaran yang diharapkan:
`[smc-prompt] ERROR: --htf-candles must be an integer >= 10.`

#### Catatan: mode offline / data lokal

**Tidak ada** opsi CLI untuk menjalankan secara offline atau membaca data OHLC
lokal. `smc-prompt` selalu mengambil data live dari Binance public REST API.
Bila jaringan tidak tersedia atau host tidak dapat dijangkau setelah retry,
CLI gagal dengan `NetworkError` (exit code `4`).

---

## Konfigurasi

`smc-prompt` **tidak membaca variabel lingkungan (environment variable)** apa
pun. Semua nilai non-CLI adalah konstanta default di
[`smc_prompt/config.py`](smc_prompt/config.py) yang dapat diubah di level kode
(API Python), bukan melalui CLI atau env var.

Konstanta penting (`smc_prompt/config.py`):

| Konstanta | Default | Keterangan |
|---|---|---|
| `HTF_INTERVAL` | `1d` | Interval kline Binance untuk HTF. |
| `LTF_INTERVAL` | `1h` | Interval kline Binance untuk LTF. |
| `DEFAULT_BASE_URLS` | `(https://api.binance.com, https://data-api.binance.vision)` | Daftar host fallback yang dapat di-override. |
| `DEFAULT_HTF_CANDLES` | `60` | Default `--htf-candles`. |
| `DEFAULT_LTF_CANDLES` | `100` | Default `--ltf-candles`. |
| `DEFAULT_SWING_LOOKBACK` | `5` | Default `--swing-lookback`. |
| `DEFAULT_SWING_MERGE_ATR_MULT` | `0.5` | Pemisahan minimum antar swing sejenis (`× ATR(14)`); lebih dekat akan digabung. |
| `DEFAULT_ATR_PERIOD` | `14` | Lookback ATR. |
| `DEFAULT_STRUCTURE_MIN_SWINGS` | `4` | Minimum swing untuk mencoba klasifikasi. |
| `DEFAULT_STRUCTURE_LAST_SWINGS` | `6` | Jumlah swing terakhir untuk klasifikasi. |
| `DEFAULT_CONTEXT_BUFFER` | `50` | Candle ekstra yang di-fetch agar swing di tepi kiri tabel tetap terdeteksi. |
| `FETCH_LIMIT_MAX` | `1000` | Batas keras klines Binance. |
| `DEFAULT_REQUEST_TIMEOUT` | `10.0` | Timeout per request (detik). |
| `DEFAULT_RETRY_MAX` | `3` | Jumlah percobaan ulang. |
| `DEFAULT_OUTPUT_DIR` | `output` | Direktori fallback clipboard. |
| `DEFAULT_DELISTED_ZERO_VOLUME_STREAK` | `3` | Ambang peringatan zero-volume. |
| `MIN_CANDLES` | `10` | Minimum candle yang diminta. |
| `MIN_SWING_LOOKBACK` | `3` | Minimum window fractal. |

Turunan: `htf_fetch_limit = min(htf_candles + context_buffer, fetch_limit_max)`,
sama untuk LTF.

## Struktur Proyek

```
smc_prompt/
├── __init__.py            # konstanta versi paket
├── __main__.py            # memungkinkan `python -m smc_prompt`
├── cli.py                 # entrypoint Click + orkestrasi (satu-satunya penulis stdout/stderr)
├── config.py              # default imutabel, string interval, aturan format
├── models.py              # dataclass / kontrak payload bertipe
├── errors.py              # hierarki exception (memetakan exit code)
├── data_fetcher.py        # klien REST Binance + retry/backoff + failover host
├── structure_analyzer.py  # deteksi swing, klasifikasi, jarak, ATR
├── template_renderer.py   # pembangun placeholder + render Jinja2
├── output.py              # clipboard + fallback berkas
└── templates/
    └── prompt_template.j2 # template prompt (byte-frozen)

docs/
└── DESIGN_SPEC.md         # spesifikasi desain beku

pyproject.toml             # metadata paket, dependensi, entry point
requirements.txt           # daftar dependensi runtime
README.md                  # dokumen ini
```

## Klasifikasi Struktur

`structure_class` adalah perbandingan mekanis murni dari swing terakhir:

- **Bullish** — dua swing high terakhir membentuk Higher High **dan** dua swing
  low terakhir membentuk Higher Low.
- **Bearish** — dua swing high terakhir membentuk Lower High **dan** dua swing
  low terakhir membentuk Lower Low.
- **Ranging/Mixed** — selain di atas, atau kurang dari dua high / dua low.

## Deteksi Swing

N-bar Williams Fractal (default `N = 5`) dengan post-filter deterministik: dua
swing sejenis berurutan yang berjarak kurang dari `0.5 × ATR(14)` digabung,
menyisakan yang lebih ekstrem. Tanpa random, tanpa rekursi, tanpa lookahead
melebihi window.

Candle terakhir yang **belum tertutup (half-open) dikecualikan** dari seluruh
perhitungan swing, ATR, klasifikasi, dan tabel. Candle tersebut hanya dipakai
sebagai fallback harga saat ini bila endpoint ticker tidak tersedia (endpoint
ticker adalah sumber utama).

## Exit Codes

| Kode | Arti |
|---|---|
| 0 | Sukses (peringatan mungkin tetap dikeluarkan). |
| 1 | Error internal tak terduga. |
| 2 | Argumen / konfigurasi tidak valid. |
| 3 | Simbol tidak terdaftar di Binance Spot. |
| 4 | Binance API tidak dapat dijangkau setelah retry. |
| 5 | Histori closed tidak cukup untuk menghitung struktur. |
| 6 | Gagal menyalin ke clipboard atau menulis berkas fallback. |

## Troubleshooting

- **`Clipboard unavailable ... Wrote prompt to <path>`** — lingkungan headless
  atau `xclip`/`xsel` tidak terpasang. Prompt tetap tersedia di berkas fallback
  pada `--output-dir`; tidak ada tindakan tambahan yang diperlukan.
- **`Symbol '<SYM>' is not listed on Binance Spot` (exit 3)** — periksa ejaan
  simbol; gunakan format seperti `BTCUSDT` (base + quote, tanpa pemisah).
- **`Binance API unreachable ...` (exit 4)** — masalah jaringan atau host
  terblokir (mis. HTTP 451 geo-block). Coba
  `--base-url https://data-api.binance.vision`.
- **`Not enough closed <tf> history ...` (exit 5)** — histori closed tidak
  mencukupi. **Tidak ada** mode data lokal/offline; gunakan simbol dengan
  histori cukup.
- **Argumen ditolak (exit 2)** — pastikan `--swing-lookback` ganjil `>= 3` dan
  `--htf-candles`/`--ltf-candles` `>= 10`.
- **Karakter non-ASCII pada Windows** — CLI memaksa stream stdout/stderr ke
  UTF-8 secara otomatis; tidak perlu konfigurasi manual.

## Catatan dan Batasan Diketahui

- **Presisi harga dipilih berdasarkan magnitudo**, bukan tick size simbol:
  `>= 1000` → 2 desimal, `>= 1` → 4 desimal, `< 1` → 8 desimal. Pasangan
  berharga sangat rendah mungkin memerlukan presisi berbasis tick size
  (penyempurnaan yang didokumentasikan).
- **`half = (N-1)/2` bar closed terbaru tidak pernah bisa menjadi swing**,
  sehingga swing yang dilaporkan bisa tertinggal beberapa bar. Ini melekat pada
  metode fractal.
- **Heuristik zero-volume untuk simbol delisted hanyalah peringatan** (exit 0).
  Pasangan bervolume rendah namun tetap tradable dapat memicu peringatan palsu.
- Semua timestamp adalah **UTC**; jam host dipakai untuk memutuskan "apakah
  candle terakhir sudah closed?".
- Prompt tidak disanitasi terhadap prompt-injection, tetapi seluruh konten yang
  disuntikkan adalah data numerik/simbol yang dikendalikan oleh alat ini.

## Lisensi

Dirilis di bawah **MIT License** (lihat metadata `license = { text = "MIT" }`
pada [`pyproject.toml`](pyproject.toml)).
