const pptxgen = require('pptxgenjs');
const React = require('react');
const RDS = require('react-dom/server');
const sharp = require('sharp');
const fa = require('react-icons/fa');

const C = {
  dark: '14532D', mid: '2E7D4F', tint: 'E7F3EA', tint2: 'D3EADB',
  amber: 'E8A317', amberLt: 'FCEFC7', text: '1F2937', muted: '5B6B63', white: 'FFFFFF'
};
async function icon(Comp, color) {
  const svg = RDS.renderToStaticMarkup(React.createElement(Comp, { color: '#' + color, size: 256 }));
  const buf = await sharp(Buffer.from(svg)).resize(256, 256).png().toBuffer();
  return 'image/png;base64,' + buf.toString('base64');
}

(async () => {
  const pres = new pptxgen();
  pres.layout = 'LAYOUT_WIDE'; // 13.333 x 7.5
  pres.title = 'JelantahKu - SDG 12 Challenge';
  const s = pres.addSlide();
  s.background = { color: 'FFFFFF' };
  const F = 'Arial';
  const T = (txt, o) => s.addText(txt, Object.assign({ isTextBox: true, fontFace: F, color: C.text, margin: 0 }, o));

  // ---------- Header ----------
  s.addShape(pres.shapes.RECTANGLE, { x: 0, y: 0.3, w: 0.18, h: 0.9, fill: { color: C.dark }, line: { color: C.dark } });
  T('SDG CHALLENGE · BPC SERIES', { x: 0.4, y: 0.25, w: 8, h: 0.3, fontSize: 13, bold: true, italic: true, color: C.mid });
  T('JelantahKu: mengubah minyak jelantah rumah tangga yang terbuang menjadi biosolar untuk energi yang lebih berkelanjutan', {
    x: 0.4, y: 0.55, w: 9.3, h: 0.75, fontSize: 19, bold: true, valign: 'top' });

  // logo card (top right)
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 9.95, y: 0.25, w: 3.0, h: 0.95, rectRadius: 0.12,
    fill: { color: C.white }, line: { color: 'E5E7EB' }, shadow: { type: 'outer', color: '000000', opacity: 0.15, blur: 6, offset: 2, angle: 90 } });
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 10.1, y: 0.37, w: 0.72, h: 0.72, rectRadius: 0.06, fill: { color: 'BF8B2E' }, line: { color: 'BF8B2E' } });
  T([{ text: '12', options: { fontSize: 18, bold: true, breakLine: true } }, { text: 'SDG', options: { fontSize: 9, bold: true } }],
    { x: 10.1, y: 0.37, w: 0.72, h: 0.72, color: C.white, align: 'center', valign: 'middle' });
  T([{ text: 'Jelantah', options: { color: C.dark } }, { text: 'Ku', options: { color: C.amber } }],
    { x: 10.95, y: 0.38, w: 1.95, h: 0.4, fontSize: 20, bold: true });
  T('Responsible Consumption & Production', { x: 10.95, y: 0.76, w: 1.95, h: 0.35, fontSize: 8, color: C.muted });

  s.addShape(pres.shapes.LINE, { x: 0.4, y: 1.4, w: 12.53, h: 0, line: { color: C.dark, width: 1 } });

  // ---------- Column headers ----------
  const cols = [
    { n: '1', t: 'Problem', x: 0.4, w: 2.9 },
    { n: '2', t: 'Root Cause (5 Whys)', x: 3.44, w: 3.35 },
    { n: '3', t: 'Customer', x: 6.93, w: 2.95 },
    { n: '4', t: 'Evidence', x: 10.02, w: 2.91 },
  ];
  const hy = 1.52;
  cols.forEach(c => {
    s.addShape(pres.shapes.OVAL, { x: c.x, y: hy, w: 0.36, h: 0.36, fill: { color: C.amber }, line: { color: C.amber } });
    T(c.n, { x: c.x, y: hy, w: 0.36, h: 0.36, fontSize: 13, bold: true, color: C.white, align: 'center', valign: 'middle' });
    T(c.t, { x: c.x + 0.45, y: hy, w: c.w - 0.45, h: 0.36, fontSize: 17, bold: true, color: C.dark, valign: 'middle' });
  });
  const top = 2.0, bottom = 5.3, H = bottom - top;

  // ---------- 1. Problem ----------
  {
    const c = cols[0];
    s.addShape(pres.shapes.RECTANGLE, { x: c.x, y: top, w: c.w, h: 2.05, fill: { color: C.dark }, line: { color: C.dark } });
    T('Jelantah rumah tangga dibuang ke saluran air atau dipakai berulang, padahal bisa jadi biodiesel. Kebutuhan biodiesel nasional (B40) masih hampir seluruhnya dipenuhi dari CPO baru.',
      { x: c.x + 0.18, y: top + 0.12, w: c.w - 0.36, h: 1.81, fontSize: 12.5, color: C.white, valign: 'middle', lineSpacingMultiple: 1.05 });
    T('Dampaknya', { x: c.x, y: top + 2.17, w: c.w, h: 0.28, fontSize: 11, bold: true, color: C.mid });
    const imp = [['Air & tanah tercemar'], ['Kesehatan keluarga terancam'], ['Energi terus menyedot CPO baru']];
    imp.forEach((it, i) => {
      const y = top + 2.5 + i * 0.28;
      s.addShape(pres.shapes.OVAL, { x: c.x + 0.02, y: y + 0.08, w: 0.11, h: 0.11, fill: { color: C.amber }, line: { color: C.amber } });
      T(it[0], { x: c.x + 0.22, y, w: c.w - 0.22, h: 0.27, fontSize: 10.5, valign: 'middle' });
    });
  }

  // ---------- 2. Root Cause ----------
  {
    const c = cols[1];
    const whys = [
      'Jelantah rumah tangga tidak masuk industri biodiesel karena tidak terkumpul.',
      'Pengepul hanya mengambil dari restoran, hotel & industri bervolume besar.',
      'Volume per rumah kecil (±1–2 L/bulan) & tersebar sehingga logistik mahal.',
      'Belum ada sistem kluster RT/RW & standar kualitas jelantah.',
      'Tidak ada insentif & edukasi; jelantah dianggap sampah, bukan energi.',
    ];
    const bh = 0.46, gap = 0.06;
    whys.forEach((w, i) => {
      const y = top + i * (bh + gap);
      s.addShape(pres.shapes.RECTANGLE, { x: c.x, y, w: c.w, h: bh, fill: { color: C.tint }, line: { color: C.tint } });
      T('Why ' + (i + 1), { x: c.x + 0.08, y, w: 0.55, h: bh, fontSize: 9, bold: true, color: C.mid, valign: 'middle' });
      T(w, { x: c.x + 0.65, y, w: c.w - 0.73, h: bh, fontSize: 9.5, valign: 'middle' });
    });
    const ry = top + 5 * (bh + gap);
    s.addShape(pres.shapes.RECTANGLE, { x: c.x, y: ry, w: c.w, h: bottom - ry, fill: { color: C.mid }, line: { color: C.mid } });
    T([{ text: 'Akar masalah: ', options: { bold: true, color: 'FDE68A' } },
       { text: 'belum ada rantai pasok jelantah rumah tangga yang terkumpul, terstandar & berinsentif.' }],
      { x: c.x + 0.12, y: ry, w: c.w - 0.24, h: bottom - ry, fontSize: 10, color: C.white, valign: 'middle' });
  }

  // ---------- 3. Customer ----------
  {
    const c = cols[2];
    const icHome = await icon(fa.FaHome, C.white), icTruck = await icon(fa.FaTractor, C.white);
    const personas = [
      { ic: icHome, role: 'PEMASOK', name: 'Ibu Rina, 38 · IRT, Bekasi',
        pain: 'Buang ±1,5 L jelantah/bulan ke wastafel; saluran mampet, bingung harus ke mana.',
        gain: 'Setor praktis & dapat uang/poin.' },
      { ic: icTruck, role: 'PEMBELI BIOSOLAR', name: 'Pak Darto, 45 · UMKM penggilingan padi',
        pain: 'Ratusan liter solar/bulan; solar nonsubsidi mahal, kuota subsidi terbatas.',
        gain: 'BBM lebih murah & pasokan stabil.' },
    ];
    const ph = (H - 0.15) / 2;
    personas.forEach((p, i) => {
      const y = top + i * (ph + 0.15);
      s.addShape(pres.shapes.RECTANGLE, { x: c.x, y, w: c.w, h: ph, fill: { color: C.tint }, line: { color: C.tint } });
      s.addShape(pres.shapes.OVAL, { x: c.x + 0.12, y: y + 0.12, w: 0.5, h: 0.5, fill: { color: C.dark }, line: { color: C.dark } });
      s.addImage({ data: p.ic, x: c.x + 0.24, y: y + 0.24, w: 0.26, h: 0.26 });
      T(p.role, { x: c.x + 0.72, y: y + 0.1, w: c.w - 0.8, h: 0.22, fontSize: 8.5, bold: true, color: C.amber, charSpacing: 1 });
      T(p.name, { x: c.x + 0.72, y: y + 0.31, w: c.w - 0.8, h: 0.36, fontSize: 10, bold: true, color: C.dark, valign: 'top' });
      T([{ text: 'Pain: ', options: { bold: true } }, { text: p.pain, options: { breakLine: true } },
         { text: 'Gain: ', options: { bold: true } }, { text: p.gain }],
        { x: c.x + 0.12, y: y + 0.72, w: c.w - 0.24, h: ph - 0.8, fontSize: 9.5, valign: 'top', paraSpaceAfter: 3 });
    });
  }

  // ---------- 4. Evidence ----------
  {
    const c = cols[3];
    const ev = [
      ['±3 jt kL', 'potensi jelantah nasional per tahun; baru sebagian kecil terkumpul', 'Traction Energy Asia'],
      ['B40', 'mandatori biodiesel sejak 2025; kebutuhan FAME belasan juta kL/tahun', 'Kementerian ESDM'],
      ['80–90%', 'rendemen jelantah menjadi biodiesel lewat transesterifikasi', 'riset kampus & pilot daerah'],
      ['1 : 1.000', '1 L jelantah dapat mencemari hingga ±1.000 L air', 'DLH / organisasi lingkungan'],
    ];
    const eh = (H - 3 * 0.1) / 4;
    ev.forEach((e, i) => {
      const y = top + i * (eh + 0.1);
      s.addShape(pres.shapes.RECTANGLE, { x: c.x, y, w: c.w, h: eh, fill: { color: i % 2 ? C.tint : C.tint2 }, line: { color: C.tint } });
      T(e[0], { x: c.x + 0.1, y, w: 1.05, h: eh, fontSize: 15, bold: true, color: C.dark, valign: 'middle', fit: 'shrink' });
      T([{ text: e[1], options: { breakLine: true } }, { text: e[2], options: { italic: true, color: C.muted, fontSize: 7.5 } }],
        { x: c.x + 1.2, y: y + 0.03, w: c.w - 1.28, h: eh - 0.06, fontSize: 8.5, valign: 'middle' });
    });
  }

  // ---------- 5. Opportunity band ----------
  const oy = 5.48, oh = 1.5;
  s.addShape(pres.shapes.RECTANGLE, { x: 0.4, y: oy, w: 12.53, h: oh, fill: { color: C.white }, line: { color: C.dark, width: 1.25 } });
  s.addShape(pres.shapes.RECTANGLE, { x: 0.4, y: oy, w: 12.53, h: 0.38, fill: { color: C.dark }, line: { color: C.dark } });
  s.addShape(pres.shapes.OVAL, { x: 5.3, y: oy + 0.04, w: 0.3, h: 0.3, fill: { color: C.amber }, line: { color: C.amber } });
  T('5', { x: 5.3, y: oy + 0.04, w: 0.3, h: 0.3, fontSize: 11, bold: true, color: C.white, align: 'center', valign: 'middle' });
  T('Opportunity', { x: 5.68, y: oy, w: 3, h: 0.38, fontSize: 15, bold: true, color: C.white, valign: 'middle' });
  T('"JelantahKu membangun rantai pasok jelantah rumah tangga lewat drop-off tingkat RT dan pick-up terjadwal berbayar, lalu mengolahnya menjadi biosolar (biodiesel) yang dijual ke UMKM, nelayan, dan armada diesel sebagai bahan bakar yang lebih murah dan ramah lingkungan."',
    { x: 0.6, y: oy + 0.44, w: 12.13, h: 0.5, fontSize: 11.5, italic: true, bold: true, color: C.dark, align: 'center', valign: 'middle' });
  const chips = ['Rumah tangga setor jelantah (±Rp3–5rb/L)', 'Drop-off RT / pick-up terjadwal', 'Olah jadi biosolar (SNI 7182)', 'Jual B2B: UMKM, nelayan, armada'];
  const cw = 2.75, cg = 0.35, cx0 = 0.4 + (12.53 - (4 * cw + 3 * cg)) / 2, cy = oy + 1.0;
  chips.forEach((ch, i) => {
    const x = cx0 + i * (cw + cg);
    s.addShape(pres.shapes.RECTANGLE, { x, y: cy, w: cw, h: 0.38, fill: { color: C.amberLt }, line: { color: C.amberLt } });
    T(ch, { x: x + 0.05, y: cy, w: cw - 0.1, h: 0.38, fontSize: 9.5, bold: true, align: 'center', valign: 'middle' });
    if (i < 3) s.addShape(pres.shapes.LINE, { x: x + cw + 0.05, y: cy + 0.19, w: cg - 0.1, h: 0, line: { color: C.dark, width: 1.5, endArrowType: 'triangle' } });
  });

  // ---------- Footer ----------
  T('Sumber: Traction Energy Asia (potensi jelantah Indonesia); Kementerian ESDM (mandatori B40, HIP BBN); SNI 7182 Biodiesel. Angka perlu diverifikasi ke sumber asli.',
    { x: 0.4, y: 7.08, w: 12.53, h: 0.25, fontSize: 7.5, italic: true, color: C.muted });

  s.addNotes('Pitch 60 detik: Indonesia butuh jutaan kiloliter biodiesel tiap tahun, hampir semuanya dari sawit baru. Di sisi lain, jutaan liter jelantah rumah tangga dibuang ke selokan. Tidak ada yang mau mengumpulkan jelantah rumah tangga karena volumenya kecil dan tersebar. JelantahKu mengumpulkannya lewat drop-off di tiap RT dan pick-up terjadwal, dan warga dibayar per liter. Jelantah itu kami olah jadi biosolar dan kami jual ke UMKM dan nelayan dengan harga lebih murah dari solar nonsubsidi. Limbah dapur jadi energi, dan itulah SDG 12.');

  await pres.writeFile({ fileName: __dirname + '/JelantahKu_SDG12.pptx' });
})();
