/**
 * Data.gs — Generator dataset sintetis untuk survei PULIH.
 *
 * File ini murni JavaScript (tanpa API Apps Script) supaya bisa dijalankan
 * juga di Node untuk audit angka sebelum dikirim ke Google Form.
 *
 * Prinsip: marginal setiap pertanyaan dipasang lewat KUOTA (bukan sampling
 * acak), jadi persentase hasil akhir persis seperti target — bukan "kira-kira
 * mendekati". Korelasi antar-jawaban dibangun lewat satu skor laten per
 * responden, supaya cross-tab "kecocokan untuk PULIH" ikut jatuh di angka
 * yang diminta.
 */

var N_RESPONDEN = 42;
var SEED = 20260915;

/* ------------------------------------------------------------------ *
 * Target distribusi (sesuai profil hasil survei)
 * ------------------------------------------------------------------ */

var TARGET = {
  // Peran responden — pilihan tunggal.
  peran: {
    tipe: 'pilihan',
    opsi: [
      { key: 'anak',        pct: 0.33 },
      { key: 'pasangan',    pct: 0.19 },
      { key: 'saudara',     pct: 0.14 },
      { key: 'pasienSendiri', pct: 0.07 },
      { key: 'tidakPernah', pct: 0.12 }
    ],
    sisa: 'lainnya' // 15% sisanya masuk opsi lain (teman/orang tua/lainnya)
  },

  // Yang perlu dilakukan setelah pulang — centang (boleh lebih dari satu).
  tahuHarusApa: {
    tipe: 'centang',
    opsi: [
      { key: 'obat',        pct: 0.93 },
      { key: 'latihan',     pct: 0.86 },
      { key: 'kontrol',     pct: 0.74 },
      { key: 'pantau',      pct: 0.69 },
      { key: 'catat',       pct: 0.24 }
    ]
  },

  // "Sulit tahu harus melakukan apa" — skala 1..5, rata-rata 3,67; 4-5 = 60%.
  sulitTahu: {
    tipe: 'skala',
    jumlah: { 1: 0, 2: 5, 3: 12, 4: 17, 5: 8 } // mean 154/42 = 3,67
  },

  // Sumber informasi — centang.
  sumberInfo: {
    tipe: 'centang',
    opsi: [
      { key: 'dokter',    pct: 0.93 },
      { key: 'resep',     pct: 0.50 },
      { key: 'keluarga',  pct: 0.48 },
      { key: 'internet',  pct: 0.48 },
      { key: 'discharge', pct: 0.48 }
    ]
  },

  // Informasi tersebar di banyak tempat — frekuensi, pilihan tunggal.
  infoTersebar: {
    tipe: 'pilihan',
    urut: true, // opsi diurutkan dari paling "berat" ke paling ringan
    opsi: [
      { key: 'sangatSering', pct: 0.14 },
      { key: 'sering',       pct: 0.31 }, // sering + sangat sering = 45%
      { key: 'kadang',       pct: 0.43 },
      { key: 'jarang',       pct: 0.10 },
      { key: 'tidakPernah',  pct: 0.02 }
    ]
  },

  // Kesulitan terbesar — centang.
  kesulitan: {
    tipe: 'centang',
    opsi: [
      { key: 'pahamLatihan', pct: 0.52 },
      { key: 'tahuAktivitas', pct: 0.33 },
      { key: 'tahuPerkembangan', pct: 0.29 }
    ]
  },

  // Lupa pertanyaan saat kontrol — frekuensi, pilihan tunggal.
  lupaPertanyaan: {
    tipe: 'pilihan',
    urut: true,
    opsi: [
      { key: 'sangatSering', pct: 0.05 },
      { key: 'sering',       pct: 0.29 },
      { key: 'kadang',       pct: 0.45 },
      { key: 'jarang',       pct: 0.17 },
      { key: 'tidakPernah',  pct: 0.04 }
    ]
  },

  // Fitur paling dibutuhkan — centang.
  palingDibutuhkan: {
    tipe: 'centang',
    opsi: [
      { key: 'pengingatObat',  pct: 0.57 },
      { key: 'panduanAktivitas', pct: 0.43 },
      { key: 'jadwalKontrol',  pct: 0.38 }
    ]
  },

  // Peran caregiver penting — skala 1..5, rata-rata 4,38; 4-5 = 83%.
  peranCaregiver: {
    tipe: 'skala',
    jumlah: { 1: 0, 2: 2, 3: 5, 4: 10, 5: 25 } // mean 184/42 = 4,38
  },

  // Tantangan caregiver — centang.
  tantanganCaregiver: {
    tipe: 'centang',
    opsi: [
      { key: 'ingatJadwal',   pct: 0.43 },
      { key: 'bantuFisik',    pct: 0.43 },
      { key: 'tahuAktivitas', pct: 0.31 }
    ]
  },

  // Fitur paling membantu caregiver — centang.
  fiturMembantu: {
    tipe: 'centang',
    opsi: [
      { key: 'panduanLatihan',  pct: 0.67 },
      { key: 'jadwalObat',      pct: 0.60 },
      { key: 'recoveryPlan',    pct: 0.45 },
      { key: 'recoverySummary', pct: 0.33 }
    ]
  },

  // Empat pertanyaan minat aplikasi — skala 1..5.
  appGabungan: {
    tipe: 'skala',
    jumlah: { 1: 0, 2: 4, 3: 5, 4: 13, 5: 20 } // mean 175/42 = 4,17; 4-5 = 79%
  },
  satuTampilan: {
    tipe: 'skala',
    jumlah: { 1: 0, 2: 3, 3: 6, 4: 14, 5: 19 } // 4-5 = 79%
  },
  catatKendala: {
    tipe: 'skala',
    jumlah: { 1: 1, 2: 4, 3: 13, 4: 13, 5: 11 } // 4-5 = 57%
  },
  rangkumanKontrol: {
    tipe: 'skala',
    jumlah: { 1: 0, 2: 3, 3: 7, 4: 14, 5: 18 } // 4-5 = 76%
  },

  // Siapa yang mengoperasikan aplikasi — pilihan tunggal.
  siapaOperasikan: {
    tipe: 'pilihan',
    opsi: [
      { key: 'bersama',         pct: 0.36 },
      { key: 'caregiver',       pct: 0.33 },
      { key: 'tergantungKondisi', pct: 0.26 },
      { key: 'pasien',          pct: 0.05 }
    ]
  },

  // Pasien kesulitan pakai smartphone — pilihan tunggal.
  kesulitanSmartphone: {
    tipe: 'pilihan',
    urut: true,
    opsi: [
      { key: 'ya',     pct: 0.62 },
      { key: 'mungkin', pct: 0.24 },
      { key: 'tidak',  pct: 0.14 }
    ]
  },

  // Cara pakai kalau pasien punya keterbatasan — pilihan tunggal.
  caraPakai: {
    tipe: 'pilihan',
    urut: true,
    opsi: [
      { key: 'caregiverPenuh',   pct: 0.26 }, // caregiver pegang sebagian besar
      { key: 'caregiverBantu',   pct: 0.31 }, // caregiver bantu sebagian
      { key: 'bergantian',       pct: 0.24 },
      { key: 'pasienMandiri',    pct: 0.19 }
    ]
  },

  // Fitur aksesibilitas — centang.
  aksesibilitas: {
    tipe: 'centang',
    opsi: [
      { key: 'tampilanSederhana', pct: 0.79 },
      { key: 'tombolBesar',       pct: 0.62 },
      { key: 'langkahSedikit',    pct: 0.55 }
    ]
  }
};

/** Target cross-tab "kecocokan untuk PULIH" (hasil simulasi, bukan pertanyaan form). */
var TARGET_KECOCOKAN = {
  cocok: 0.79,
  sangatCocok: 0.64,
  perPeran: { pasangan: 0.88, anak: 0.64 }
};

/** Seberapa kuat tiap pertanyaan mengikuti skor laten (0 = acak, 1 = kaku). */
var KORELASI = {
  tahuHarusApa: 0.35, sulitTahu: 0.70, sumberInfo: 0.25, infoTersebar: 0.60,
  kesulitan: 0.65, lupaPertanyaan: 0.55, palingDibutuhkan: 0.45,
  peranCaregiver: 0.50, tantanganCaregiver: 0.50, fiturMembantu: 0.55,
  appGabungan: 0.80, satuTampilan: 0.70, catatKendala: 0.60,
  rangkumanKontrol: 0.65, siapaOperasikan: 0.20, kesulitanSmartphone: 0.30,
  caraPakai: 0.30, aksesibilitas: 0.40
};

/** Kecenderungan tiap peran terhadap skor laten (pasangan paling tinggi). */
var BIAS_PERAN = {
  pasangan: 1.15, saudara: 0.55, lainnya: 0.45, pasienSendiri: 0.15,
  tidakPernah: -0.15, anak: -0.65
};

/* ------------------------------------------------------------------ *
 * Utilitas
 * ------------------------------------------------------------------ */

/** PRNG deterministik (mulberry32) — hasil selalu sama untuk seed yang sama. */
function buatRng(seed) {
  var a = seed >>> 0;
  return function () {
    a = (a + 0x6D2B79F5) >>> 0;
    var t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** Normal(0,1) lewat Box-Muller. */
function gauss(rng) {
  var u = 1 - rng(), v = rng();
  return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
}

/**
 * Pembagian kuota metode sisa terbesar (Hamilton): total selalu persis n,
 * dan tiap bagian sedekat mungkin dengan persentase targetnya.
 */
function kuota(persen, n) {
  var mentah = persen.map(function (p) { return p * n; });
  var hasil = mentah.map(Math.floor);
  var terpakai = hasil.reduce(function (a, b) { return a + b; }, 0);
  var sisa = mentah
    .map(function (v, i) { return { i: i, r: v - Math.floor(v) }; })
    .sort(function (a, b) { return b.r - a.r || a.i - b.i; });
  for (var k = 0; terpakai < n; k++, terpakai++) hasil[sisa[k % sisa.length].i]++;
  return hasil;
}

/** Urutan indeks 0..n-1 diurut menaik berdasarkan skor. */
function urutkanIndeks(skor) {
  return skor
    .map(function (s, i) { return { i: i, s: s }; })
    .sort(function (a, b) { return a.s - b.s || a.i - b.i; })
    .map(function (o) { return o.i; });
}

/* ------------------------------------------------------------------ *
 * Generator
 * ------------------------------------------------------------------ */

/**
 * Bangun dataset sintetis.
 * @param {number} n jumlah baris
 * @param {number} seed benih PRNG
 * @param {{centangWajib: Array<string>}=} opsi key pertanyaan kotak centang yang
 *        wajib diisi di form; baris yang tidak mencentang apa pun akan ditambal
 *        tanpa mengubah jumlah per opsi.
 * @return {Array<Object>} satu objek per responden, key = key pertanyaan
 */
function bangunDataset(n, seed, opsi) {
  n = n || N_RESPONDEN;
  var centangWajib = (opsi && opsi.centangWajib) || [];
  var rng = buatRng(seed || SEED);
  var i;

  var baris = [];
  for (i = 0; i < n; i++) baris.push({ _id: i + 1 });

  // 1. Peran responden.
  var specPeran = TARGET.peran;
  var keyPeran = specPeran.opsi.map(function (o) { return o.key; });
  var pctPeran = specPeran.opsi.map(function (o) { return o.pct; });
  if (specPeran.sisa) {
    var totalPct = pctPeran.reduce(function (a, b) { return a + b; }, 0);
    keyPeran = keyPeran.concat([specPeran.sisa]);
    pctPeran = pctPeran.concat([Math.max(0, 1 - totalPct)]);
  }
  var nPeran = kuota(pctPeran, n);
  var kolamPeran = [];
  keyPeran.forEach(function (k, idx) {
    for (var j = 0; j < nPeran[idx]; j++) kolamPeran.push(k);
  });
  // acak penempatan peran ke baris
  urutkanIndeks(baris.map(function () { return rng(); })).forEach(function (rowIdx, pos) {
    baris[rowIdx].peran = kolamPeran[pos];
  });

  // 2. Skor laten: kebutuhan/keterlibatan responden.
  var z = baris.map(function (r) { return (BIAS_PERAN[r.peran] || 0) + gauss(rng); });

  // 3. Pertanyaan skala & pilihan & centang — semua lewat kuota + peringkat laten.
  Object.keys(TARGET).forEach(function (key) {
    if (key === 'peran') return;
    var spec = TARGET[key];
    var w = KORELASI[key] == null ? 0.4 : KORELASI[key];
    var skor = z.map(function (zi) { return w * zi + (1 - w) * gauss(rng); });

    if (spec.tipe === 'skala') {
      var nilai = [];
      [1, 2, 3, 4, 5].forEach(function (v) {
        var c = spec.jumlah[v] || 0;
        for (var j = 0; j < c; j++) nilai.push(v);
      });
      // nilai sudah menaik; peringkat laten terendah dapat nilai terendah
      urutkanIndeks(skor).forEach(function (rowIdx, pos) {
        baris[rowIdx][key] = nilai[pos];
      });

    } else if (spec.tipe === 'pilihan') {
      var pct = spec.opsi.map(function (o) { return o.pct; });
      var cnt = kuota(pct, n);
      var kolam = [];
      if (spec.urut) {
        // opsi[0] = paling "berat" → diberikan ke skor laten tertinggi
        for (var oi = spec.opsi.length - 1; oi >= 0; oi--) {
          for (var j2 = 0; j2 < cnt[oi]; j2++) kolam.push(spec.opsi[oi].key);
        }
        urutkanIndeks(skor).forEach(function (rowIdx, pos) {
          baris[rowIdx][key] = kolam[pos];
        });
      } else {
        spec.opsi.forEach(function (o, oi) {
          for (var j3 = 0; j3 < cnt[oi]; j3++) kolam.push(o.key);
        });
        urutkanIndeks(baris.map(function () { return rng(); })).forEach(function (rowIdx, pos) {
          baris[rowIdx][key] = kolam[pos];
        });
      }

    } else if (spec.tipe === 'centang') {
      baris.forEach(function (r) { r[key] = []; });
      spec.opsi.forEach(function (o) {
        var c = Math.round(o.pct * n);
        var skorOpsi = skor.map(function (s) { return s + 0.45 * gauss(rng); });
        var urut = urutkanIndeks(skorOpsi); // menaik
        for (var j4 = n - c; j4 < n; j4++) baris[urut[j4]][key].push(o.key);
      });
      // jaga urutan opsi tetap sama dengan urutan di form
      var urutOpsi = spec.opsi.map(function (o) { return o.key; });
      baris.forEach(function (r) {
        r[key].sort(function (a, b) { return urutOpsi.indexOf(a) - urutOpsi.indexOf(b); });
      });
    }
  });

  // 4. Pertanyaan centang yang wajib di form tidak boleh kosong.
  centangWajib.forEach(function (key) {
    if (!TARGET[key] || TARGET[key].tipe !== 'centang') return;
    pastikanMinimalSatu(baris, key, TARGET[key].opsi.map(function (o) { return o.key; }));
  });

  // 5. Pasang cross-tab kecocokan: siapa yang memberi nilai >= 4 pada
  //    "aplikasi gabungan bermanfaat" ditentukan per kelompok peran.
  pasangKecocokan(baris, z, n, rng);

  return baris;
}

/**
 * Pastikan tiap baris mencentang minimal satu opsi, dengan memindahkan centang
 * dari baris yang punya banyak. Jumlah centang tiap opsi tidak berubah, jadi
 * persentase per opsi tetap persis seperti target.
 *
 * Bisa gagal kalau total centang lebih sedikit daripada jumlah baris — dalam
 * kasus itu sebagian baris tetap kosong dan Code.gs yang menambalnya.
 */
function pastikanMinimalSatu(baris, key, urutOpsi) {
  for (var i = 0; i < baris.length; i++) {
    if (baris[i][key].length > 0) continue;

    // Donor: baris dengan centang terbanyak, supaya kehilangan satu tidak
    // membuatnya ikut kosong.
    var donor = -1, opsiPindah = null;
    for (var j = 0; j < baris.length; j++) {
      if (j === i || baris[j][key].length < 2) continue;
      if (donor === -1 || baris[j][key].length > baris[donor][key].length) donor = j;
    }
    if (donor === -1) continue; // tidak ada donor: biarkan, akan dilaporkan

    // Ambil opsi paling langka yang dimiliki donor, supaya baris "kebutuhan
    // rendah" ini tidak selalu kebagian opsi yang paling populer.
    var paling = null;
    baris[donor][key].forEach(function (o) {
      if (paling === null || urutOpsi.indexOf(o) > urutOpsi.indexOf(paling)) paling = o;
    });
    opsiPindah = paling;

    baris[donor][key].splice(baris[donor][key].indexOf(opsiPindah), 1);
    baris[i][key].push(opsiPindah);
    baris[i][key].sort(function (a, b) { return urutOpsi.indexOf(a) - urutOpsi.indexOf(b); });
  }
}

/**
 * Susun ulang nilai `appGabungan` supaya proporsi nilai >= 4 per kelompok peran
 * sesuai target (total 79%, pasangan 88%, anak 64%), lalu rapikan indikator
 * masalah/minat supaya angka "cocok" dan "sangat cocok" jatuh tepat.
 */
function pasangKecocokan(baris, z, n, rng) {
  var spec = TARGET.appGabungan.jumlah;
  var nTinggi = (spec[4] || 0) + (spec[5] || 0);

  // Berapa baris "tinggi" (>=4) untuk tiap kelompok peran.
  var kelompok = {};
  baris.forEach(function (r, i) {
    (kelompok[r.peran] = kelompok[r.peran] || []).push(i);
  });

  var jatah = {};
  var terpakai = 0;
  Object.keys(TARGET_KECOCOKAN.perPeran).forEach(function (p) {
    if (!kelompok[p]) return;
    jatah[p] = Math.round(TARGET_KECOCOKAN.perPeran[p] * kelompok[p].length);
    terpakai += jatah[p];
  });
  var sisaBaris = [];
  Object.keys(kelompok).forEach(function (p) {
    if (jatah[p] == null) sisaBaris = sisaBaris.concat(kelompok[p]);
  });
  var sisaTinggi = nTinggi - terpakai;

  // Bagi sisa jatah ke kelompok lain secara proporsional, dengan batas: tidak
  // ada peran bernama yang rate-nya melewati kelompok tertinggi (pasangan).
  // Luapan yang tidak muat ditampung bucket sisa ("lainnya"), yang memang
  // gabungan beberapa opsi kecil dan bukan kelompok pembanding.
  var bucketSisa = TARGET.peran.sisa;
  var batasRate = Math.max.apply(null, Object.keys(TARGET_KECOCOKAN.perPeran)
    .map(function (p) { return TARGET_KECOCOKAN.perPeran[p]; }));
  var kelompokLain = Object.keys(kelompok).filter(function (p) { return jatah[p] == null; });
  var ukuran = kelompokLain.map(function (p) { return kelompok[p].length; });
  var totalUkuran = ukuran.reduce(function (a, b) { return a + b; }, 0) || 1;
  var bagi = kuota(ukuran.map(function (u) { return u / totalUkuran; }), Math.max(0, sisaTinggi));

  var luapan = 0;
  kelompokLain.forEach(function (p, idx) {
    var maks = p === bucketSisa
      ? kelompok[p].length
      : Math.min(kelompok[p].length, Math.floor(batasRate * kelompok[p].length));
    jatah[p] = Math.min(bagi[idx], maks);
    luapan += bagi[idx] - jatah[p];
  });
  // Tampung luapan: bucket sisa dulu, baru kelompok terbesar kalau masih ada.
  var penampung = kelompokLain.slice().sort(function (a, b) {
    if (a === bucketSisa) return -1;
    if (b === bucketSisa) return 1;
    return kelompok[b].length - kelompok[a].length;
  });
  penampung.forEach(function (p) {
    if (luapan <= 0) return;
    var ruang = kelompok[p].length - jatah[p];
    var ambil = Math.min(ruang, luapan);
    jatah[p] += ambil;
    luapan -= ambil;
  });

  // Pilih baris "tinggi" di tiap kelompok: skor laten tertinggi menang.
  var tinggi = [];
  Object.keys(kelompok).forEach(function (p) {
    var anggota = kelompok[p].slice().sort(function (a, b) { return z[b] - z[a]; });
    tinggi = tinggi.concat(anggota.slice(0, jatah[p]));
  });
  var setTinggi = {};
  tinggi.forEach(function (i) { setTinggi[i] = true; });

  // Bagikan nilai: baris tinggi dapat 5/4, sisanya 3/2/1 — jumlah tiap nilai tetap.
  var nilaiTinggi = [];
  for (var a = 0; a < (spec[5] || 0); a++) nilaiTinggi.push(5);
  for (var b = 0; b < (spec[4] || 0); b++) nilaiTinggi.push(4);
  var nilaiRendah = [];
  [3, 2, 1].forEach(function (v) {
    for (var c = 0; c < (spec[v] || 0); c++) nilaiRendah.push(v);
  });

  tinggi.sort(function (x, y) { return z[y] - z[x]; }).forEach(function (rowIdx, pos) {
    baris[rowIdx].appGabungan = nilaiTinggi[pos];
  });
  var rendah = [];
  for (var i = 0; i < n; i++) if (!setTinggi[i]) rendah.push(i);
  rendah.sort(function (x, y) { return z[y] - z[x]; }).forEach(function (rowIdx, pos) {
    baris[rowIdx].appGabungan = nilaiRendah[pos];
  });

  // Semua yang menilai app >= 4 harus punya minimal 1 masalah.
  baris.forEach(function (r, idx) {
    if (r.appGabungan >= 4 && hitungMasalah(r) === 0) {
      tukarCentang(baris, 'kesulitan', 'pahamLatihan', idx);
    }
  });

  // Setel jumlah "sangat cocok" ke target lewat tukar-menukar yang
  // mempertahankan jumlah per opsi (marginal tidak berubah).
  var targetSangat = Math.round(TARGET_KECOCOKAN.sangatCocok * n);
  setelSangatCocok(baris, targetSangat, rng);
}

function hitungMasalah(r) {
  var c = 0;
  if (r.sulitTahu >= 4) c++;
  if (r.infoTersebar === 'sering' || r.infoTersebar === 'sangatSering') c++;
  if (r.lupaPertanyaan === 'sering' || r.lupaPertanyaan === 'sangatSering' ||
      r.lupaPertanyaan === 'kadang') c++;
  if (r.kesulitan && r.kesulitan.length > 0) c++;
  return c;
}

function hitungMinat(r) {
  var c = 0;
  if (r.appGabungan >= 4) c++;
  if (r.satuTampilan >= 4) c++;
  if (r.catatKendala >= 4) c++;
  if (r.rangkumanKontrol >= 4) c++;
  return c;
}

function isCocok(r) { return r.appGabungan >= 4 && hitungMasalah(r) >= 1; }
function isSangatCocok(r) { return hitungMinat(r) >= 3 && hitungMasalah(r) >= 2; }

/** Pindahkan satu centang `opsi` dari baris yang punya ke baris `tujuan`. */
function tukarCentang(baris, key, opsi, tujuan) {
  if (baris[tujuan][key].indexOf(opsi) !== -1) return false;
  for (var i = 0; i < baris.length; i++) {
    if (i === tujuan) continue;
    var r = baris[i];
    var pos = r[key].indexOf(opsi);
    if (pos !== -1 && r[key].length > 1) { // jangan bikin baris lain kosong
      r[key].splice(pos, 1);
      baris[tujuan][key].push(opsi);
      return true;
    }
  }
  return false;
}

/** Tukar nilai skala antara dua baris — jumlah tiap nilai tetap. */
function tukarSkala(baris, key, a, b) {
  var t = baris[a][key];
  baris[a][key] = baris[b][key];
  baris[b][key] = t;
}

/**
 * Setel jumlah "sangat cocok" ke `target` dengan menukar nilai `catatKendala`
 * (pertanyaan minat paling longgar) antar-baris, sehingga marginalnya utuh.
 */
function setelSangatCocok(baris, target, rng) {
  for (var putaran = 0; putaran < 400; putaran++) {
    var kini = baris.filter(isSangatCocok).length;
    if (kini === target) return;
    var naik = kini < target;
    var ditemukan = false;

    for (var a = 0; a < baris.length && !ditemukan; a++) {
      for (var b = 0; b < baris.length; b++) {
        if (a === b || baris[a].catatKendala === baris[b].catatKendala) continue;
        var sebelum = isSangatCocok(baris[a]) + isSangatCocok(baris[b]);
        tukarSkala(baris, 'catatKendala', a, b);
        var sesudah = isSangatCocok(baris[a]) + isSangatCocok(baris[b]);
        if ((naik && sesudah > sebelum) || (!naik && sesudah < sebelum)) {
          ditemukan = true;
          break;
        }
        tukarSkala(baris, 'catatKendala', a, b); // batalkan
      }
    }
    if (!ditemukan) return; // sudah mentok
  }
}

/* ------------------------------------------------------------------ *
 * Isian tambahan
 * ------------------------------------------------------------------ */

/** Rentang umur yang masuk akal untuk tiap peran responden. */
var RENTANG_UMUR = {
  anak:          [24, 43],
  pasangan:      [46, 68],
  saudara:       [31, 56],
  pasienSendiri: [42, 70],
  tidakPernah:   [22, 46],
  lainnya:       [26, 52]
};

/**
 * Umur responden, menyesuaikan perannya — anak pasien jauh lebih muda daripada
 * pasangan pasien, jadi umur acak tanpa memandang peran akan terlihat janggal.
 *
 * Deterministik: baris yang sama selalu menghasilkan umur yang sama.
 *
 * @param {Object} baris satu baris dataset
 * @return {number} umur dalam tahun
 */
function umurResponden(baris) {
  var r = RENTANG_UMUR[baris.peran] || [25, 55];
  var rng = buatRng(SEED + baris._id * 7919);
  // rata-rata dua angka acak: hasilnya menumpuk di tengah rentang, bukan rata.
  var posisi = (rng() + rng()) / 2;
  return r[0] + Math.round(posisi * (r[1] - r[0]));
}

if (typeof module !== 'undefined') {
  module.exports = {
    RENTANG_UMUR: RENTANG_UMUR, umurResponden: umurResponden,
    N_RESPONDEN: N_RESPONDEN, SEED: SEED, TARGET: TARGET,
    TARGET_KECOCOKAN: TARGET_KECOCOKAN, bangunDataset: bangunDataset,
    hitungMasalah: hitungMasalah, hitungMinat: hitungMinat,
    isCocok: isCocok, isSangatCocok: isSangatCocok
  };
}
