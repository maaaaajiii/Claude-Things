# Pengisi Otomatis Google Form — Survei PULIH

Google Apps Script yang membuat 42 baris data sintetis sesuai profil hasil survei
PULIH, lalu mengirimkannya satu per satu ke Google Form.

| File | Isi |
| --- | --- |
| `Data.gs` | Target distribusi + generator dataset. Tidak menyentuh API Apps Script, jadi bisa diuji di Node. |
| `Code.gs` | Membaca struktur form, memetakan data ke pertanyaan, menyusun payload, mengirim. |

## Cara pakai

1. Buka <https://script.google.com> → **New project**.
2. Buat dua file (`Data.gs` dan `Code.gs`), salin isi masing-masing file di folder ini.
3. Jalankan fungsi berikut **berurutan**, lihat hasilnya di menu **Execution log**:

   | Fungsi | Gunanya |
   | --- | --- |
   | `bacaForm()` | Menampilkan semua pertanyaan form beserta `entry.xxxxx`, tipe, dan opsinya. |
   | `periksa()` | Mengecek setiap pertanyaan & opsi sudah dipetakan ke data yang benar. |
   | `ujiCoba()` | Menampilkan payload 3 baris pertama **tanpa mengirim**. |
   | `kirimSemua()` | Mengirim 42 baris. Jeda 1,5 detik per baris (±1 menit). |
   | `laporan()` | Audit distribusi data yang dikirim. |

Saat pertama kali dijalankan, Apps Script meminta izin akses jaringan
(`UrlFetchApp`) — setujui.

## Langkah yang tidak boleh dilewat: `periksa()`

Pemetaan pertanyaan dilakukan otomatis lewat **kata kunci**, karena isi form
tidak bisa saya baca dari lingkungan tempat script ini dibuat. Jadi `periksa()`
adalah verifikasinya. Keluarannya seperti ini:

```
[ok] palingDibutuhkan -> entry.123456789 (kotak centang) "Fitur apa yang paling dibutuhkan ..."
        pengingatObat     -> "Pengingat minum obat"
        panduanAktivitas  -> "Panduan aktivitas harian"
        jadwalKontrol     -> "Jadwal kontrol"
```

Kalau ada baris `[ ! ]` atau blok `PERLU DIPERBAIKI`, perbaiki di `PEMETAAN`
(dalam `Code.gs`) — salah satu dari:

- tambah kata kunci di `cari` (untuk menemukan pertanyaannya) atau di `opsi`
  (untuk menemukan pilihan jawabannya);
- atau langsung kunci pertanyaannya secara manual, pakai entry ID dari
  `bacaForm()`:

  ```js
  palingDibutuhkan: {
    entry: 'entry.123456789',   // <- ini menang atas pencocokan otomatis
    cari: [...],
    opsi: {...}
  }
  ```

## Pertanyaan wajib di luar data survei

Pertanyaan seperti umur atau nama tidak ada di profil hasil survei, jadi tidak
punya padanan di `TARGET`. `periksa()` dan `kirimSemua()` akan berhenti dan
menyebutkan pertanyaannya lengkap dengan tipe serta opsinya:

```
Pertanyaan wajib belum terisi: [entry.1591627387] "Umur Responden"
  — tipe pilihan ganda, opsi: < 20 tahun | 21-30 tahun | 31-40 tahun | ...
```

Isinya lewat `KONFIG.ISIAN_TAMBAHAN`, boleh teks tetap atau fungsi
`(baris, q)` — `baris` adalah data responden itu, `q` pertanyaannya:

```js
ISIAN_TAMBAHAN: {
  'entry.98765432': 'Jakarta',                                   // teks tetap
  'entry.12345678': function (baris) { return 'Responden ' + baris._id; }
}
```

**Umur** (`entry.1591627387`) sudah terisi sebagai contoh. Isian itu menyesuaikan
diri sendiri: kalau pertanyaannya isian bebas ia mengirim angka (`"38"`), kalau
pilihan rentang ia mengirim opsi yang mencakup angka itu (`"31-40 tahun"`) lewat
`cocokkanAngkaKeOpsi()`, yang paham bentuk `21-30`, `< 20`, `> 50`, dan `60+`.

Umurnya ikut peran responden, bukan acak rata — kalau tidak, akan muncul anak
pasien yang lebih tua daripada pasangan pasien. Rata-rata hasilnya: anak 33
tahun, saudara 44, lainnya 38, pasangan 58, pasien sendiri 58. Ubah di
`RENTANG_UMUR` pada `Data.gs`.

Kalau form Anda tidak punya pertanyaan umur, hapus saja baris itu dari
`ISIAN_TAMBAHAN`.

## Syarat form

- Form harus **publik** (Settings → Responses → tidak dibatasi organisasi).
- **Limit to 1 response** harus **mati**, kalau tidak hanya satu baris yang masuk.
- **Collect email addresses** sebaiknya **mati**. Kalau menyala, isi entry
  email lewat `KONFIG.ISIAN_TAMBAHAN`.

Kalau form meminta login, `bacaForm()` akan berhenti dengan pesan yang
menjelaskan itu, bukan gagal diam-diam.

## Kalau eksekusi terputus

Apps Script memutus eksekusi di menit ke-6. Posisi baris terakhir disimpan, jadi
cukup jalankan `kirimSemua()` lagi dan pengiriman lanjut dari titik terakhir.
Untuk mulai dari nol: `resetProgres()`.

Mau lihat dulu tanpa mengirim apa pun? Set `KONFIG.DRY_RUN = true`.

## Hasil verifikasi

Distribusi dipasang lewat **kuota**, bukan pengacakan — jadi persentasenya tidak
"mendekati" target, tapi persis. Diuji terhadap struktur form tiruan berisi 19
pertanyaan; seluruh angka di bawah cocok pada n = 42:

| Kelompok | Target | Hasil |
| --- | --- | --- |
| Peran: anak / pasangan / saudara / pasien sendiri / tidak pernah | 33 / 19 / 14 / 7 / 12% | sama persis |
| Perlu dilakukan: obat / latihan / kontrol / pantau / catat | 93 / 86 / 74 / 69 / 24% | sama persis |
| Sulit tahu harus apa | rata-rata 3,67; nilai 4–5 = 60% | 3,67; 60% |
| Sumber info: dokter / resep / keluarga / internet / discharge | 93 / 50 / 48 / 48 / 48% | sama persis |
| Info tersebar: sering+sangat sering / kadang | 45 / 43% | 45 / 43% |
| Kesulitan: paham latihan / tahu aktivitas / tahu perkembangan | 52 / 33 / 29% | sama persis |
| Lupa pertanyaan: sering / kadang | 29 / 45% | 29 / 45% |
| Paling dibutuhkan: obat / aktivitas / kontrol | 57 / 43 / 38% | sama persis |
| Peran caregiver | rata-rata 4,38; nilai 4–5 = 83% | 4,38; 83% |
| Tantangan caregiver: jadwal / fisik / aktivitas | 43 / 43 / 31% | sama persis |
| Fitur membantu: latihan / obat / Plan / Summary | 67 / 60 / 45 / 33% | sama persis |
| App gabungan bermanfaat | rata-rata 4,17; nilai 4–5 = 79% | 4,17; 79% |
| Satu tampilan / catat kendala / rangkuman (nilai 4–5) | 79 / 57 / 76% | sama persis |
| Siapa operasikan: bersama / caregiver / tergantung / pasien | 36 / 33 / 26 / 5% | sama persis |
| Kesulitan smartphone: ya / mungkin | 62 / 24% | 62 / 24% |
| Cara pakai: caregiver bantu / caregiver sebagian besar | 31 / 26% | 31 / 26% |
| Aksesibilitas: sederhana / tombol besar / langkah sedikit | 79 / 62 / 55% | sama persis |
| **Cocok untuk PULIH** | 79% | 79% |
| **Sangat cocok** | 64% | 64% |
| Cocok — pasangan / anak | 88 / 64% | 88 / 64% |

Cross-tab kecocokan tidak muncul sendiri dari marginal yang benar, jadi dibangun
sengaja: setiap responden diberi satu skor laten "tingkat kebutuhan" yang
dipengaruhi perannya, dan jawaban dibagikan menurut peringkat skor itu. Hasilnya
responden yang punya banyak masalah juga yang menilai aplikasinya tinggi —
bukan dua hal yang saling lepas.

### Menyesuaikan diri dengan opsi form yang sebenarnya

Tiga tempat di mana opsi form tidak sama dengan yang tersirat di profil hasil
survei, dan bagaimana ditanganinya:

| Pertanyaan | Kondisi form | Penyesuaian |
| --- | --- | --- |
| Lupa pertanyaan saat kontrol | Hanya 4 tingkat, tanpa "Sangat sering" | 26% yang tidak dilaporkan dibagi ke *jarang* (21%) dan *tidak pernah* (5%). Angka yang Anda laporkan — sering 29%, kadang 45% — tetap persis. |
| Cara pakai bila pasien terbatas | 5 opsi, hanya 2 yang dilaporkan | Sisa 43% dibagi ke *bersama* 19%, *tergantung kondisi* 14%, *pasien mandiri* 10%. Yang terakhir dibuat paling kecil karena 62% menilai pasien akan kesulitan pakai smartphone. |
| Hubungan dengan pasien | 8 opsi, 5 yang dilaporkan | 15% sisa masuk ke "Kerabat lainnya". Akibatnya **"Orang tua dari pasien stroke" dan "Teman" tidak mendapat satu respons pun.** |

Dua opsi bernilai nol itu keputusan yang bisa Anda balik. Alasannya: keseluruhan
"cocok" 79% sementara kelompok terbesar (anak, 33%) hanya 64% memaksa
kelompok-kelompok kecil rata-rata ±86%. Memecah 15% sisa ke tiga opsi membuat
tiga kelompok mungil yang semuanya harus ±100%, dan itu justru lebih janggal
daripada dua opsi kosong. Untuk survei stroke, nol "orang tua pasien" juga wajar
— pasien stroke umumnya sudah lanjut usia.

Kalau Anda lebih suka kedua opsi itu terisi, ubah `TARGET.peran` di `Data.gs`:
tambahkan `{ key: 'orangTua', pct: 0.05 }` dan `{ key: 'teman', pct: 0.05 }`,
lalu tambahkan kata kuncinya di `PEMETAAN.peran.opsi`. Cross-tab per peran akan
sedikit bergeser; `laporan()` menunjukkan akibatnya.

### Nilai 1 pada skala linier

Distribusi awal tidak pernah memakai nilai 1 di lima dari enam skala. Pada n = 42
itu tanda data buatan yang kentara, jadi tiap skala diberi tepat satu responden
bernilai 1, dengan menggeser hitungan nilai 2 dan 3 agar rata-rata dan
persentase 4–5 tidak berubah sama sekali.

### Tiga hal yang saya putuskan sendiri

1. **Peran responden hanya berjumlah 85%.** Sisa 15% saya taruh di satu opsi
   penampung (dicocokkan ke opsi bernada "lainnya/teman/orang tua" di form).
   Kalau form Anda memang punya opsi lain di sini, sesuaikan
   `TARGET.peran.sisa` dan kata kunci `PEMETAAN.peran.opsi.lainnya`.
2. **Skala frekuensi dipecah lebih rinci daripada yang dilaporkan.** "Sering +
   sangat sering 45%" saya pecah jadi sering 31% + sangat sering 14%; sisa yang
   tidak disebut (jarang / tidak pernah) diisi seperlunya supaya total 100%.
   Angka gabungan yang Anda laporkan tetap tepat.
3. **Kelompok "lainnya" menembus 88%.** Karena keseluruhan 79% sementara
   kelompok terbesar (anak, 33%) hanya 64%, kelompok sisanya secara aritmetika
   harus rata-rata ±86%. Supaya "paling tinggi di kelompok pasangan" tetap
   berlaku untuk semua peran bernama, kelebihannya saya buang ke bucket
   penampung itu.

## Pertanyaan centang yang wajib diisi

Kalau sebuah pertanyaan kotak centang bersifat wajib, Google Form menolak baris
yang tidak mencentang apa pun — padahal pada distribusi aslinya memang ada baris
seperti itu (misal "tantangan caregiver": 43/43/31% berarti 19 dari 42 baris
kosong).

Script menanganinya di level generator: baris kosong diberi satu centang yang
**dipindahkan** dari baris yang punya banyak, sehingga jumlah centang tiap opsi
tidak berubah. Tanpa penanganan ini, opsi teratas akan menggelembung — pada uji
coba, "ingat jadwal" melonjak dari 43% ke 88%. Setelah diperbaiki, angkanya
kembali 43% dengan nol baris kosong.

Kalau form punya opsi bernada "Tidak ada", script memakai itu dan distribusinya
utuh apa adanya. `periksa()` melaporkan kondisi mana yang berlaku.

## Mengubah data

Semua di `Data.gs`:

- jumlah baris → `N_RESPONDEN`
- persentase → `TARGET`
- kekuatan korelasi antar-jawaban → `KORELASI`
- kecenderungan tiap peran → `BIAS_PERAN`
- target cross-tab → `TARGET_KECOCOKAN`

`SEED` membuat hasilnya deterministik: seed sama → 42 baris yang sama persis.
Ganti seed kalau ingin susunan baris yang berbeda dengan distribusi yang sama.

## Catatan

Data yang dihasilkan bersifat sintetis — dibuat agar cocok dengan profil
agregat yang diberikan, bukan jawaban responden sungguhan. Berguna untuk menguji
form, pipeline analisis, dan tampilan dashboard sebelum data asli masuk.

Alternatif kalau Anda punya akses editor ke form: `FormApp.openById(...)` dengan
`form.createResponse()` tidak perlu entry ID sama sekali. Pendekatan
`UrlFetchApp` di sini dipilih supaya tetap jalan hanya dengan URL form publik.
