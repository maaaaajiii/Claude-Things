/**
 * Code.gs — Pengisi otomatis Google Form survei PULIH.
 *
 * Script ini membaca sendiri struktur form yang dituju (entry ID, tipe
 * pertanyaan, dan daftar opsi), mencocokkannya dengan spesifikasi data di
 * Data.gs lewat kata kunci, lalu mengirim jawaban satu per satu ke endpoint
 * /formResponse.
 *
 * Urutan pemakaian:
 *   1. bacaForm()   -> cek struktur form terbaca dengan benar
 *   2. periksa()    -> cek semua pertanyaan & opsi berhasil dipetakan
 *   3. ujiCoba()    -> lihat payload 3 baris pertama TANPA mengirim
 *   4. kirimSemua() -> kirim seluruh baris
 *   5. laporan()    -> audit distribusi data yang dikirim
 */

var KONFIG = {
  // ID panjang dari URL form (bagian setelah /forms/d/e/).
  FORM_ID: '1FAIpQLSeW8AGONKBVyFAOJWWBoInh_s8rYgyykaiQt9_h5xzcblZuFQ',

  // Jeda antar-pengiriman (ms). Jangan terlalu kecil supaya tidak kena limit.
  JEDA_MS: 1500,

  // Kalau true, kirimSemua() hanya mencetak log tanpa benar-benar mengirim.
  DRY_RUN: false,

  // Isian untuk pertanyaan wajib yang tidak ada di spesifikasi data (misal umur
  // atau nama). Key = entry ID; value = teks tetap, atau fungsi(baris, q) yang
  // menerima baris dataset dan objek pertanyaannya.
  ISIAN_TAMBAHAN: {

    // "Umur Responden". Jalan untuk dua bentuk pertanyaan sekaligus:
    // isian bebas -> mengirim angkanya ("38"); pilihan rentang -> mengirim opsi
    // yang mencakup angka itu ("31-40 tahun"). Umurnya mengikuti peran
    // responden, jadi anak pasien tidak muncul lebih tua daripada pasangannya.
    'entry.1591627387': function (baris, q) {
      var umur = umurResponden(baris);
      return (q && q.opsi.length) ? cocokkanAngkaKeOpsi(umur, q.opsi) : String(umur);
    }
  }
};

function urlForm(jenis) {
  return 'https://docs.google.com/forms/d/e/' + KONFIG.FORM_ID + '/' + jenis;
}

/* ------------------------------------------------------------------ *
 * 1. Membaca struktur form
 * ------------------------------------------------------------------ */

var TIPE = {
  0: 'isian singkat', 1: 'paragraf', 2: 'pilihan ganda', 3: 'dropdown',
  4: 'kotak centang', 5: 'skala linier', 7: 'grid', 8: 'pemisah halaman',
  9: 'tanggal', 10: 'waktu'
};

/**
 * Ambil dan urai FB_PUBLIC_LOAD_DATA_ dari halaman form publik.
 * @return {{pertanyaan: Array, jumlahHalaman: number, fbzx: string}}
 */
function ambilStrukturForm() {
  var res = UrlFetchApp.fetch(urlForm('viewform'), {
    muteHttpExceptions: true,
    followRedirects: true
  });
  var kode = res.getResponseCode();
  var html = res.getContentText();

  if (kode !== 200) {
    throw new Error('Gagal membuka form (HTTP ' + kode + '). Pastikan form publik.');
  }
  if (html.indexOf('FB_PUBLIC_LOAD_DATA_') === -1) {
    throw new Error(
      'Halaman form tidak berisi data pertanyaan. Kemungkinan form meminta login ' +
      'atau hanya bisa diisi anggota organisasi tertentu.');
  }

  var cocok = html.match(/FB_PUBLIC_LOAD_DATA_ *= *([\s\S]*?);\s*<\/script>/);
  if (!cocok) throw new Error('Struktur halaman form tidak dikenali.');

  var data = JSON.parse(cocok[1]);
  var mentah = (data[1] && data[1][1]) || [];

  var pertanyaan = [];
  var halaman = 1;

  mentah.forEach(function (item) {
    var tipe = item[3];
    if (tipe === 8) { halaman++; return; } // pemisah halaman
    if (!item[4]) return;                  // judul/gambar/teks, bukan pertanyaan

    item[4].forEach(function (bidang) {
      pertanyaan.push({
        entryId: bidang[0],
        judul: String(item[1] || '').trim(),
        deskripsi: String(item[2] || '').trim(),
        tipe: tipe,
        namaTipe: TIPE[tipe] || ('tipe-' + tipe),
        wajib: bidang[2] === 1 || bidang[2] === true,
        opsi: (bidang[1] || []).map(function (o) { return String(o[0]); })
      });
    });
  });

  var fbzx = (html.match(/name="fbzx"\s+value="(-?\d+)"/) || [])[1] ||
             (html.match(/"fbzx"\s*:\s*"(-?\d+)"/) || [])[1] || '';

  return { pertanyaan: pertanyaan, jumlahHalaman: halaman, fbzx: fbzx };
}

/** Cetak struktur form ke Logger — jalankan ini paling awal. */
function bacaForm() {
  var s = ambilStrukturForm();
  var baris = ['Form: ' + urlForm('viewform'),
               'Halaman: ' + s.jumlahHalaman,
               'Jumlah pertanyaan: ' + s.pertanyaan.length, ''];
  s.pertanyaan.forEach(function (q, i) {
    baris.push((i + 1) + '. [entry.' + q.entryId + '] (' + q.namaTipe +
               (q.wajib ? ', wajib' : '') + ')');
    baris.push('   ' + q.judul);
    if (q.opsi.length) baris.push('   opsi: ' + q.opsi.join(' | '));
  });
  var teks = baris.join('\n');
  Logger.log(teks);
  return teks;
}

/* ------------------------------------------------------------------ *
 * 2. Pemetaan spesifikasi data -> pertanyaan form
 * ------------------------------------------------------------------ *
 * `cari`  : kata kunci untuk menemukan pertanyaannya di form.
 * `opsi`  : kata kunci untuk menemukan tiap opsi jawabannya.
 * `entry` : opsional — isi manual 'entry.123456' kalau pencocokan otomatis
 *           meleset (lihat hasil bacaForm()).
 */

var PEMETAAN = {
  peran: {
    cari: ['peran', 'hubungan', 'anda', 'pasien', 'mendampingi'],
    opsi: {
      anak: ['anak'],
      pasangan: ['pasangan', 'suami', 'istri'],
      saudara: ['saudara', 'kakak', 'adik'],
      // "mengalami stroke" sengaja dipakai, bukan "pernah" — kata "pernah" juga
      // muncul di opsi "Tidak pernah mendampingi ...".
      pasienSendiri: ['mengalami stroke', 'saya sedang', 'saya sendiri',
                      'pasien sendiri', 'saya adalah pasien'],
      tidakPernah: ['tidak pernah'],
      lainnya: ['kerabat', 'lain', 'teman', 'orang tua']
    }
  },
  tahuHarusApa: {
    cari: ['perlu dilakukan', 'setelah pulang', 'harus dilakukan', 'sepulang'],
    opsi: {
      obat: ['obat'],
      latihan: ['latihan', 'fisioterapi'],
      kontrol: ['kontrol', 'jadwal kontrol'],
      pantau: ['pantau', 'memantau', 'kondisi'],
      catat: ['catat', 'mencatat', 'perkembangan']
    },
    kosong: ['tidak ada', 'tidak satu pun', 'tidak satupun', 'none', 'semua sudah jelas']
  },
  sulitTahu: {
    cari: ['sulit', 'bingung', 'tahu', 'apa yang harus'],
    opsi: {}
  },
  sumberInfo: {
    cari: ['sumber', 'informasi', 'dapat', 'dari mana'],
    opsi: {
      dokter: ['dokter', 'tenaga kesehatan', 'perawat'],
      resep: ['resep'],
      keluarga: ['keluarga', 'kerabat', 'teman'],
      internet: ['internet', 'google', 'online'],
      discharge: ['discharge', 'lembar', 'surat pulang', 'ringkasan']
    },
    kosong: ['tidak ada', 'tidak satu pun', 'tidak satupun', 'none', 'semua sudah jelas']
  },
  infoTersebar: {
    cari: ['tersebar', 'terpisah', 'banyak tempat', 'berbeda'],
    opsi: {
      sangatSering: ['sangat sering', 'selalu'],
      sering: ['sering'],
      kadang: ['kadang'],
      jarang: ['jarang'],
      tidakPernah: ['tidak pernah']
    }
  },
  kesulitan: {
    cari: ['kesulitan terbesar', 'paling sulit', 'paling menyulitkan'],
    opsi: {
      pahamLatihan: ['instruksi latihan', 'memahami latihan', 'paham latihan', 'latihan'],
      tahuAktivitas: ['aktivitas', 'boleh dilakukan'],
      tahuPerkembangan: ['perkembangan', 'kemajuan', 'progres']
    },
    kosong: ['tidak ada', 'tidak satu pun', 'tidak satupun', 'none', 'semua sudah jelas']
  },
  lupaPertanyaan: {
    cari: ['lupa', 'pertanyaan', 'kontrol'],
    opsi: {
      sering: ['sering'],
      kadang: ['kadang'],
      jarang: ['jarang'],
      tidakPernah: ['tidak pernah']
    }
  },
  palingDibutuhkan: {
    cari: ['paling dibutuhkan', 'paling diperlukan', 'butuhkan'],
    opsi: {
      pengingatObat: ['pengingat obat', 'reminder obat', 'obat'],
      panduanAktivitas: ['panduan aktivitas', 'aktivitas harian', 'aktivitas'],
      jadwalKontrol: ['jadwal kontrol', 'kontrol']
    },
    kosong: ['tidak ada', 'tidak satu pun', 'tidak satupun', 'none', 'semua sudah jelas']
  },
  peranCaregiver: {
    cari: ['caregiver', 'pendamping', 'penting', 'peran'],
    opsi: {}
  },
  tantanganCaregiver: {
    cari: ['tantangan', 'caregiver', 'pendamping'],
    opsi: {
      ingatJadwal: ['ingat jadwal', 'mengingat jadwal', 'jadwal'],
      bantuFisik: ['aktivitas fisik', 'membantu fisik', 'fisik'],
      tahuAktivitas: ['aktivitas yang benar', 'aktivitas yang tepat', 'aktivitas']
    },
    kosong: ['tidak ada', 'tidak satu pun', 'tidak satupun', 'none', 'semua sudah jelas']
  },
  fiturMembantu: {
    cari: ['fitur', 'membantu', 'caregiver'],
    opsi: {
      panduanLatihan: ['panduan latihan', 'latihan'],
      jadwalObat: ['jadwal obat', 'obat'],
      recoveryPlan: ['recovery plan'],
      recoverySummary: ['recovery summary']
    },
    kosong: ['tidak ada', 'tidak satu pun', 'tidak satupun', 'none', 'semua sudah jelas']
  },
  appGabungan: {
    cari: ['aplikasi', 'gabung', 'bermanfaat', 'satu aplikasi'],
    opsi: {}
  },
  satuTampilan: {
    cari: ['satu tampilan', 'tampilan harian', 'satu layar', 'harian'],
    opsi: {}
  },
  catatKendala: {
    cari: ['catat kendala', 'mencatat kendala', 'keluhan', 'kendala'],
    opsi: {}
  },
  rangkumanKontrol: {
    cari: ['rangkuman', 'ringkasan', 'sebelum kontrol'],
    opsi: {}
  },
  siapaOperasikan: {
    cari: ['mengoperasikan', 'siapa yang', 'menggunakan aplikasi'],
    opsi: {
      bersama: ['bersama', 'berdua'],
      caregiver: ['caregiver', 'pendamping', 'keluarga'],
      tergantungKondisi: ['tergantung'],
      pasien: ['pasien sendiri', 'pasien']
    }
  },
  kesulitanSmartphone: {
    cari: ['smartphone', 'ponsel', 'hp', 'kesulitan'],
    opsi: {
      ya: ['ya'],
      mungkin: ['mungkin'],
      tidak: ['tidak']
    }
  },
  caraPakai: {
    cari: ['keterbatasan', 'cara', 'digunakan', 'bagaimana'],
    opsi: {
      caregiverPenuh: ['sebagian besar', 'sepenuhnya', 'caregiver yang'],
      caregiverBantu: ['membantu mengoperasikan', 'dibantu', 'bantu'],
      bersama: ['bersama', 'berdua', 'bergantian'],
      tergantungKondisi: ['tergantung'],
      pasienMandiri: ['mandiri', 'sendiri']
    }
  },
  aksesibilitas: {
    cari: ['aksesibilitas', 'fitur', 'lansia', 'mudah'],
    opsi: {
      tampilanSederhana: ['sederhana', 'simpel'],
      tombolBesar: ['tombol besar', 'huruf besar', 'besar'],
      langkahSedikit: ['langkah', 'sedikit', 'singkat']
    },
    kosong: ['tidak ada', 'tidak satu pun', 'tidak satupun', 'none', 'semua sudah jelas']
  }
};

function normalkan(t) {
  return String(t).toLowerCase().replace(/[^a-z0-9\s]/g, ' ').replace(/\s+/g, ' ').trim();
}

/** Skor kecocokan: berapa banyak kata kunci yang muncul di teks. */
function skorCocok(teks, kunci) {
  var n = normalkan(teks);
  var skor = 0;
  kunci.forEach(function (k) {
    if (n.indexOf(normalkan(k)) !== -1) skor++;
  });
  return skor;
}

/**
 * Bobot kecocokan tipe data terhadap tipe pertanyaan form.
 * Tipe yang tidak terdaftar dianggap tidak kompatibel dan langsung dibuang —
 * ini yang mencegah spesifikasi skala merebut pertanyaan kotak centang, dsb.
 */
var TIPE_COCOK = {
  skala:   { 5: 3, 2: 1, 3: 1 }, // idealnya skala linier; radio/dropdown 1-5 juga bisa
  centang: { 4: 3 },             // kotak centang tidak punya pengganti
  pilihan: { 2: 3, 3: 3, 5: 1 }
};

/**
 * Petakan tiap key data ke pertanyaan form.
 *
 * Pencocokan dilakukan global: semua pasangan (spesifikasi x pertanyaan) diberi
 * skor lebih dulu, lalu diambil dari skor tertinggi ke terendah. Cara ini
 * menghindari masalah pencocokan berurutan, di mana spesifikasi yang diproses
 * duluan bisa menyerobot pertanyaan yang sebetulnya milik spesifikasi lain.
 *
 * @return {{peta: Object, masalah: Array<string>}}
 */
function petakan(struktur) {
  var pertanyaan = struktur.pertanyaan;
  var peta = {};
  var masalah = [];
  var qTerpakai = {};

  // a) entry manual menang atas pencocokan otomatis.
  var keyOtomatis = [];
  Object.keys(PEMETAAN).forEach(function (key) {
    var spec = PEMETAAN[key];
    if (!spec.entry) { keyOtomatis.push(key); return; }
    var id = String(spec.entry).replace(/^entry\./, '');
    var manual = pertanyaan.filter(function (q) { return String(q.entryId) === id; })[0];
    if (!manual) { masalah.push(key + ': entry ' + spec.entry + ' tidak ada di form'); return; }
    peta[key] = { q: manual, opsi: petakanOpsi(key, spec, manual, masalah) };
    qTerpakai[manual.entryId] = true;
  });

  // b) skor seluruh pasangan yang tipenya kompatibel.
  var pasangan = [];
  keyOtomatis.forEach(function (key) {
    var spec = PEMETAAN[key];
    var bobot = TIPE_COCOK[(TARGET[key] || {}).tipe] || {};
    pertanyaan.forEach(function (q) {
      if (qTerpakai[q.entryId]) return;
      var bonusTipe = bobot[q.tipe];
      if (!bonusTipe) return;
      var skor = skorCocok(q.judul + ' ' + q.deskripsi, spec.cari);
      if (!skor) return;
      pasangan.push({ key: key, q: q, skor: skor * 10 + bonusTipe });
    });
  });

  // c) ambil dari skor tertinggi; urutan tie-break dibuat pasti supaya
  //    hasilnya sama setiap kali dijalankan.
  pasangan.sort(function (a, b) {
    return b.skor - a.skor || (a.key < b.key ? -1 : a.key > b.key ? 1 : 0) ||
           a.q.entryId - b.q.entryId;
  });

  var keyTerpakai = {};
  pasangan.forEach(function (p) {
    if (keyTerpakai[p.key] || qTerpakai[p.q.entryId]) return;
    keyTerpakai[p.key] = p;
    qTerpakai[p.q.entryId] = true;
    peta[p.key] = { q: p.q, opsi: petakanOpsi(p.key, PEMETAAN[p.key], p.q, masalah) };
  });

  // d) laporkan yang gagal dipetakan dan yang benar-benar ambigu.
  keyOtomatis.forEach(function (key) {
    if (keyTerpakai[key]) return;
    var adaKandidat = pasangan.some(function (p) { return p.key === key; });
    masalah.push(key + ': ' + (adaKandidat
      ? 'semua pertanyaan yang cocok sudah diambil spesifikasi lain'
      : 'tidak ada pertanyaan yang cocok') +
      '. Isi PEMETAAN.' + key + '.entry secara manual (lihat hasil bacaForm()).');
  });
  keyOtomatis.forEach(function (key) {
    var dipakai = keyTerpakai[key];
    if (!dipakai) return;
    // Ambigu hanya kalau ada pertanyaan berskor sama yang sampai akhir tidak
    // diambil spesifikasi mana pun — kalau sudah terpakai, seri tadi sudah
    // terurai dengan sendirinya.
    var bebas = pasangan.filter(function (p) {
      return p.key === key && p.skor === dipakai.skor && p.q.entryId !== dipakai.q.entryId &&
        !Object.keys(keyTerpakai).some(function (k) {
          return keyTerpakai[k].q.entryId === p.q.entryId;
        });
    });
    if (bebas.length) {
      masalah.push(key + ': skornya seri antara "' + dipakai.q.judul + '" dan "' +
                   bebas[0].q.judul + '". Pastikan pilihannya benar, atau isi PEMETAAN.' +
                   key + '.entry secara manual.');
    }
  });

  // e) pertanyaan wajib yang tidak tersentuh sama sekali.
  pertanyaan.forEach(function (q) {
    if (!q.wajib || qTerpakai[q.entryId]) return;
    if (KONFIG.ISIAN_TAMBAHAN['entry.' + q.entryId] != null) return;
    masalah.push('Pertanyaan wajib belum terisi: [entry.' + q.entryId + '] "' + q.judul +
                 '" — tipe ' + q.namaTipe +
                 (q.opsi.length ? ', opsi: ' + q.opsi.join(' | ') : ', isian bebas') +
                 '. Tambahkan ke KONFIG.ISIAN_TAMBAHAN.');
  });

  return { peta: peta, masalah: masalah };
}

/** Petakan key opsi data -> teks opsi asli di form. */
function petakanOpsi(key, spec, q, masalah) {
  if (!q.opsi.length) return {};
  var hasil = {};
  var terpakai = {};

  Object.keys(spec.opsi || {}).forEach(function (okey) {
    var kandidat = q.opsi
      .map(function (teks, i) {
        return { teks: teks, i: i, skor: terpakai[i] ? -1 : skorCocok(teks, spec.opsi[okey]) };
      })
      .filter(function (c) { return c.skor > 0; })
      .sort(function (a, b) { return b.skor - a.skor; });

    if (!kandidat.length) {
      masalah.push(key + '/' + okey + ': opsi tidak ditemukan. Opsi tersedia: ' +
                   q.opsi.join(' | '));
      return;
    }
    hasil[okey] = kandidat[0].teks;
    terpakai[kandidat[0].i] = true;
  });

  // Opsi "tidak ada / tidak satu pun", kalau form menyediakannya. Dipakai untuk
  // baris yang tidak mencentang apa pun pada pertanyaan kotak centang wajib.
  (spec.kosong || []).some(function (kata) {
    for (var i = 0; i < q.opsi.length; i++) {
      if (!terpakai[i] && skorCocok(q.opsi[i], [kata]) > 0) {
        hasil.__kosong = q.opsi[i];
        terpakai[i] = true;
        return true;
      }
    }
    return false;
  });

  return hasil;
}

/**
 * Hitung berapa baris yang tidak mencentang apa pun pada pertanyaan kotak
 * centang wajib. Form akan menolak kiriman seperti itu, jadi perlu ditambal.
 * @return {Object} key pertanyaan -> {jumlah, adaOpsiKosong, judul}
 */
function centangKosong(peta, data) {
  var hasil = {};
  Object.keys(peta).forEach(function (key) {
    var m = peta[key];
    if (!m.q.wajib || m.q.tipe !== 4) return;
    var jumlah = 0;
    data.forEach(function (r) {
      if (Object.prototype.toString.call(r[key]) === '[object Array]' && !r[key].length) jumlah++;
    });
    if (jumlah) {
      hasil[key] = { jumlah: jumlah, adaOpsiKosong: !!m.opsi.__kosong, judul: m.q.judul };
    }
  });
  return hasil;
}

/** Cek pemetaan tanpa mengirim apa pun. */
function periksa() {
  var struktur = ambilStrukturForm();
  var hasil = petakan(struktur);
  var baris = [];

  Object.keys(PEMETAAN).forEach(function (key) {
    var m = hasil.peta[key];
    if (!m) { baris.push('[ ! ] ' + key + ' -> TIDAK TERPETAKAN'); return; }
    baris.push('[ok] ' + key + ' -> entry.' + m.q.entryId + ' (' + m.q.namaTipe + ') "' +
               m.q.judul + '"');
    Object.keys(m.opsi).forEach(function (o) {
      baris.push('        ' + o + ' -> "' + m.opsi[o] + '"');
    });
  });

  var kosong = centangKosong(hasil.peta, datasetUntuk(hasil.peta));
  var keyKosong = Object.keys(kosong);
  if (keyKosong.length) {
    baris.push('', '--- KOTAK CENTANG WAJIB TANPA PILIHAN ---');
    keyKosong.forEach(function (k) {
      baris.push('  ' + k + ': ' + kosong[k].jumlah + ' baris tidak mencentang apa pun. ' +
        (kosong[k].adaOpsiKosong
          ? 'Akan diisi opsi "tidak ada" — distribusi opsi lain tetap utuh.'
          : 'Form tidak punya opsi "tidak ada", jadi baris itu akan diisi opsi ' +
            'pertama dan persentasenya bergeser. Solusi lebih rapi: jadikan ' +
            'pertanyaan ini tidak wajib, atau tambahkan opsi "Tidak ada".'));
    });
  }

  if (hasil.masalah.length) {
    baris.push('', '--- PERLU DIPERBAIKI (' + hasil.masalah.length + ') ---');
    hasil.masalah.forEach(function (m) { baris.push('  * ' + m); });
  } else {
    baris.push('', 'Semua pertanyaan dan opsi berhasil dipetakan.');
  }

  var teks = baris.join('\n');
  Logger.log(teks);
  return teks;
}

/** Key pertanyaan centang yang wajib diisi dan tidak punya opsi "tidak ada". */
function keyCentangWajib(peta) {
  return Object.keys(peta).filter(function (k) {
    return peta[k].q.wajib && peta[k].q.tipe === 4 && !peta[k].opsi.__kosong;
  });
}

/** Dataset yang sudah disesuaikan dengan pertanyaan wajib di form. */
function datasetUntuk(peta) {
  return bangunDataset(N_RESPONDEN, SEED, { centangWajib: keyCentangWajib(peta) });
}

/* ------------------------------------------------------------------ *
 * 3. Menyusun payload
 * ------------------------------------------------------------------ */

/**
 * Cocokkan sebuah angka ke opsi berbentuk rentang, misalnya "31-40 tahun",
 * "< 30", "> 60 tahun", atau "60+". Dipakai untuk isian seperti umur, yang di
 * satu form bisa berupa isian bebas dan di form lain berupa pilihan rentang.
 *
 * @param {number} angka nilai yang dicari
 * @param {Array<string>} opsi daftar opsi apa adanya dari form
 * @return {string} teks opsi yang cocok; kalau tidak ada yang cocok, opsi
 *         dengan angka terdekat
 */
function cocokkanAngkaKeOpsi(angka, opsi) {
  var terdekat = null, jarakTerdekat = Infinity;

  for (var i = 0; i < opsi.length; i++) {
    var teks = String(opsi[i]);
    var angkaOpsi = (teks.match(/\d+/g) || []).map(Number);
    if (!angkaOpsi.length) continue;

    var n = normalkan(teks);
    var keBawah = /(^|\s)(kurang|bawah|maks|maksimal)(\s|$)/.test(n) || teks.indexOf('<') !== -1;
    var keAtas = /(^|\s)(lebih|atas|min|minimal)(\s|$)/.test(n) || teks.indexOf('>') !== -1 ||
                 /\d\s*\+/.test(teks);

    if (angkaOpsi.length >= 2) {
      var a = Math.min(angkaOpsi[0], angkaOpsi[1]);
      var b = Math.max(angkaOpsi[0], angkaOpsi[1]);
      if (angka >= a && angka <= b) return teks;
      var jarak = angka < a ? a - angka : angka - b;
      if (jarak < jarakTerdekat) { jarakTerdekat = jarak; terdekat = teks; }
    } else {
      var v = angkaOpsi[0];
      if (keBawah && angka <= v) return teks;
      if (keAtas && angka >= v) return teks;
      if (!keBawah && !keAtas && angka === v) return teks;
      var j2 = Math.abs(angka - v);
      if (j2 < jarakTerdekat) { jarakTerdekat = j2; terdekat = teks; }
    }
  }

  return terdekat || opsi[0];
}

/** Ubah nilai skala 1..5 menjadi salah satu opsi skala milik form. */
function nilaiSkala(nilai, q) {
  if (!q.opsi.length) return String(nilai);
  if (q.opsi.length === 5) return q.opsi[nilai - 1];
  // skala form bukan 1..5: petakan proporsional
  var idx = Math.round((nilai - 1) / 4 * (q.opsi.length - 1));
  return q.opsi[Math.max(0, Math.min(q.opsi.length - 1, idx))];
}

/** Bangun body x-www-form-urlencoded untuk satu baris data. */
function bangunPayload(baris, peta, struktur) {
  var bagian = [];

  function tambah(entryId, nilai) {
    bagian.push('entry.' + entryId + '=' + encodeURIComponent(nilai));
  }

  Object.keys(PEMETAAN).forEach(function (key) {
    var m = peta[key];
    if (!m) return;
    var nilai = baris[key];
    if (nilai == null) return;

    if (typeof nilai === 'number') {
      tambah(m.q.entryId, nilaiSkala(nilai, m.q));
    } else if (Object.prototype.toString.call(nilai) === '[object Array]') {
      if (!nilai.length && m.q.wajib) {
        // Kotak centang wajib tidak boleh kosong. Pakai opsi "tidak ada" kalau
        // form punya; kalau tidak, pakai opsi pertama (distribusi opsi itu akan
        // sedikit bergeser — periksa() melaporkan berapa baris yang terdampak).
        var tambal = m.opsi.__kosong;
        if (!tambal) {
          var urut = Object.keys(PEMETAAN[key].opsi || {});
          for (var u = 0; u < urut.length && !tambal; u++) tambal = m.opsi[urut[u]];
        }
        if (tambal) tambah(m.q.entryId, tambal);
        return;
      }
      nilai.forEach(function (o) {
        if (m.opsi[o]) tambah(m.q.entryId, m.opsi[o]);
      });
    } else if (m.opsi[nilai]) {
      tambah(m.q.entryId, m.opsi[nilai]);
    }
  });

  Object.keys(KONFIG.ISIAN_TAMBAHAN).forEach(function (entryKey) {
    var v = KONFIG.ISIAN_TAMBAHAN[entryKey];
    var id = String(entryKey).replace(/^entry\./, '');
    // Pertanyaannya ikut dikirim ke fungsi, supaya isian bisa menyesuaikan diri
    // dengan tipe dan daftar opsinya (lihat contoh umur di KONFIG).
    var q = null;
    for (var i = 0; i < struktur.pertanyaan.length; i++) {
      if (String(struktur.pertanyaan[i].entryId) === id) { q = struktur.pertanyaan[i]; break; }
    }
    var nilai = typeof v === 'function' ? v(baris, q) : v;
    if (nilai != null && nilai !== '') tambah(id, nilai);
  });

  var halaman = [];
  for (var i = 0; i < struktur.jumlahHalaman; i++) halaman.push(i);
  bagian.push('fvv=1');
  bagian.push('pageHistory=' + halaman.join(','));
  if (struktur.fbzx) bagian.push('fbzx=' + encodeURIComponent(struktur.fbzx));
  bagian.push('submit=Submit');

  return bagian.join('&');
}

/* ------------------------------------------------------------------ *
 * 4. Pengiriman
 * ------------------------------------------------------------------ */

var KUNCI_PROGRES = 'PULIH_INDEKS_TERAKHIR';

/** Lihat payload 3 baris pertama tanpa mengirim. */
function ujiCoba() {
  var struktur = ambilStrukturForm();
  var hasil = petakan(struktur);
  if (hasil.masalah.length) {
    Logger.log('Pemetaan belum bersih — jalankan periksa() dulu:\n  ' +
               hasil.masalah.join('\n  '));
  }
  var data = datasetUntuk(hasil.peta);
  var keluar = [];
  data.slice(0, 3).forEach(function (baris, i) {
    keluar.push('--- baris ' + (i + 1) + ' ---');
    keluar.push(JSON.stringify(baris));
    keluar.push(bangunPayload(baris, hasil.peta, struktur));
    keluar.push('');
  });
  var teks = keluar.join('\n');
  Logger.log(teks);
  return teks;
}

/**
 * Kirim seluruh baris ke form.
 * Aman diulang: posisi terakhir disimpan, jadi kalau kena batas waktu eksekusi
 * Apps Script (6 menit), cukup jalankan lagi dan pengiriman lanjut dari sana.
 * Panggil resetProgres() untuk memulai dari nol.
 */
function kirimSemua() {
  var struktur = ambilStrukturForm();
  var hasil = petakan(struktur);

  var fatal = hasil.masalah.filter(function (m) { return m.indexOf('wajib') !== -1; });
  if (fatal.length) {
    throw new Error('Ada pertanyaan wajib yang belum terpetakan:\n  ' + fatal.join('\n  '));
  }
  if (hasil.masalah.length) {
    Logger.log('Peringatan pemetaan:\n  ' + hasil.masalah.join('\n  '));
  }

  var props = PropertiesService.getScriptProperties();
  var mulai = Number(props.getProperty(KUNCI_PROGRES) || 0);
  var data = datasetUntuk(hasil.peta);
  var url = urlForm('formResponse');
  var berhasil = 0, gagal = 0;

  for (var i = mulai; i < data.length; i++) {
    var payload = bangunPayload(data[i], hasil.peta, struktur);

    if (KONFIG.DRY_RUN) {
      Logger.log('[DRY RUN] baris ' + (i + 1) + ': ' + payload);
      berhasil++;
    } else {
      var res = UrlFetchApp.fetch(url, {
        method: 'post',
        contentType: 'application/x-www-form-urlencoded',
        payload: payload,
        followRedirects: true,
        muteHttpExceptions: true
      });
      var kode = res.getResponseCode();
      var isi = res.getContentText();
      var ok = kode === 200 &&
        (isi.indexOf('freebirdFormviewerViewResponseConfirmationMessage') !== -1 ||
         /Your response has been recorded|Responsmu telah direkam|Jawaban Anda telah direkam|telah direkam/i.test(isi));

      if (ok) {
        berhasil++;
      } else {
        gagal++;
        Logger.log('Baris ' + (i + 1) + ' gagal (HTTP ' + kode + '). ' +
                   'Cuplikan: ' + isi.substring(0, 200).replace(/\s+/g, ' '));
      }
      Utilities.sleep(KONFIG.JEDA_MS);
    }

    props.setProperty(KUNCI_PROGRES, String(i + 1));
  }

  var ringkas = 'Selesai. Berhasil: ' + berhasil + ', gagal: ' + gagal +
                ', total baris: ' + data.length + '.';
  Logger.log(ringkas);
  return ringkas;
}

/** Mulai ulang pengiriman dari baris pertama. */
function resetProgres() {
  PropertiesService.getScriptProperties().deleteProperty(KUNCI_PROGRES);
  Logger.log('Progres direset. kirimSemua() akan mulai dari baris 1.');
}

/* ------------------------------------------------------------------ *
 * 5. Audit distribusi
 * ------------------------------------------------------------------ */

/** Cetak distribusi dataset yang dihasilkan, untuk dibandingkan dengan target. */
function laporan() {
  // Audit memakai dataset yang sama persis dengan yang dikirim, termasuk
  // penyesuaian untuk pertanyaan centang wajib.
  var data, catatan = '', struktur = null;
  try {
    struktur = ambilStrukturForm();
    var hasil = petakan(struktur);
    data = datasetUntuk(hasil.peta);
  } catch (e) {
    data = bangunDataset(N_RESPONDEN, SEED);
    catatan = '(form tidak terbaca: ' + e.message + ' — audit memakai dataset dasar)';
  }
  var n = data.length;
  var baris = ['N = ' + n, catatan, ''];

  function persen(c) { return c + ' (' + Math.round(100 * c / n) + '%)'; }

  Object.keys(TARGET).forEach(function (key) {
    var spec = TARGET[key];
    if (spec.tipe === 'skala') {
      var dist = { 1: 0, 2: 0, 3: 0, 4: 0, 5: 0 }, total = 0;
      data.forEach(function (r) { dist[r[key]]++; total += r[key]; });
      baris.push(key + ': rata-rata ' + (total / n).toFixed(2) +
                 ', nilai 4-5 = ' + Math.round(100 * (dist[4] + dist[5]) / n) + '%' +
                 ' [1:' + dist[1] + ' 2:' + dist[2] + ' 3:' + dist[3] +
                 ' 4:' + dist[4] + ' 5:' + dist[5] + ']');
    } else if (spec.tipe === 'centang') {
      var c = {};
      data.forEach(function (r) {
        r[key].forEach(function (o) { c[o] = (c[o] || 0) + 1; });
      });
      baris.push(key + ': ' + Object.keys(c).map(function (k) {
        return k + ' ' + persen(c[k]);
      }).join(', '));
    } else {
      var p = {};
      data.forEach(function (r) { p[r[key]] = (p[r[key]] || 0) + 1; });
      baris.push(key + ': ' + Object.keys(p).map(function (k) {
        return k + ' ' + persen(p[k]);
      }).join(', '));
    }
  });

  // Isian tambahan (umur, dsb.) tidak ada di TARGET, jadi kalau tidak dicetak
  // di sini ia lolos dari audit sama sekali.
  if (struktur) {
    Object.keys(KONFIG.ISIAN_TAMBAHAN).forEach(function (entryKey) {
      var id = String(entryKey).replace(/^entry\./, '');
      var q = null;
      for (var i = 0; i < struktur.pertanyaan.length; i++) {
        if (String(struktur.pertanyaan[i].entryId) === id) { q = struktur.pertanyaan[i]; break; }
      }
      var v = KONFIG.ISIAN_TAMBAHAN[entryKey];
      var hitung = {};
      data.forEach(function (r) {
        var nilai = typeof v === 'function' ? v(r, q) : v;
        hitung[nilai] = (hitung[nilai] || 0) + 1;
      });
      // Opsi diurutkan seperti di form supaya yang bernilai nol ikut terlihat.
      var urut = (q && q.opsi.length) ? q.opsi : Object.keys(hitung).sort();
      baris.push((q ? q.judul : entryKey) + ': ' + urut.map(function (o) {
        return o + ' ' + persen(hitung[o] || 0);
      }).join(', '));
    });
  }

  var cocok = data.filter(isCocok).length;
  var sangat = data.filter(isSangatCocok).length;
  baris.push('', '--- kecocokan untuk PULIH ---');
  baris.push('cocok: ' + persen(cocok) + '  (target ' +
             Math.round(100 * TARGET_KECOCOKAN.cocok) + '%)');
  baris.push('sangat cocok: ' + persen(sangat) + '  (target ' +
             Math.round(100 * TARGET_KECOCOKAN.sangatCocok) + '%)');

  var perPeran = {};
  data.forEach(function (r) {
    perPeran[r.peran] = perPeran[r.peran] || { n: 0, c: 0 };
    perPeran[r.peran].n++;
    if (isCocok(r)) perPeran[r.peran].c++;
  });
  Object.keys(perPeran).forEach(function (p) {
    baris.push('  ' + p + ': ' + perPeran[p].c + '/' + perPeran[p].n + ' = ' +
               Math.round(100 * perPeran[p].c / perPeran[p].n) + '%');
  });

  var teks = baris.join('\n');
  Logger.log(teks);
  return teks;
}
