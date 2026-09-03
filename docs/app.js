'use strict';

const ALL_PARKS = [['tdl', '東京ディズニーランド'], ['tds', '東京ディズニーシー']];
const PARK_KEYS = ALL_PARKS.map((p) => p[0]);
const STORE_KEY = 'tdr.park';

// 表示対象のパーク。'tdl' | 'tds' | 'both'
let parkMode = 'both';
let currentDate = null;
let data = null;

function PARKS_() {
  return parkMode === 'both' ? ALL_PARKS : ALL_PARKS.filter((p) => p[0] === parkMode);
}
const CAT_JA = {
  attraction: 'アトラクション', show: 'パレード/ショー', greeting: 'キャラクターグリーティング',
  shop: 'ショップ', restaurant: 'レストラン', service: 'サービス施設',
};
const STALE_MIN = 30;

const el = (tag, cls, text) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
};
const q = (name) => new URLSearchParams(location.search).get(name);

function fmtClock(iso) {
  if (!iso) return null;
  const d = new Date(iso);
  return isNaN(d) ? null : `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}
function ageMinutes(iso) {
  if (!iso) return null;
  const d = new Date(iso);
  return isNaN(d) ? null : Math.round((Date.now() - d.getTime()) / 60000);
}
function fmtDate(s) {
  if (!s) return '';
  const [y, m, d] = s.split('-').map(Number);
  const w = '日月火水木金土'[new Date(y, m - 1, d).getDay()];
  return `${y}年${m}月${d}日(${w})`;
}
function shiftDate(s, days) {
  const [y, m, d] = s.split('-').map(Number);
  const dt = new Date(y, m - 1, d + days);
  const p2 = (n) => String(n).padStart(2, '0');
  return `${dt.getFullYear()}-${p2(dt.getMonth() + 1)}-${p2(dt.getDate())}`;
}

function crowdClass(p) { return p == null ? '' : p <= 40 ? 'lo' : p <= 70 ? 'mid' : 'hi'; }
function parkTag(p) { return el('span', 'parkTag ' + p, p === 'tdl' ? 'ランド' : 'シー'); }

// 「取得失敗（前回値 HH:MM）」を出すための共通表示
function freshness(label, iso) {
  const age = ageMinutes(iso);
  const t = fmtClock(iso);
  if (t == null) return { text: `${label}: 取得できていません`, stale: true };
  if (age != null && age >= STALE_MIN) {
    return { text: `${label}: ${t}（${age}分前）`, stale: true };
  }
  return { text: `${label}: ${t}`, stale: false };
}

// ---------- 各セクション ----------

function renderHeader(d, date, official) {
  const box = document.createDocumentFragment();
  const isTarget = date === d.dates.target;
  box.appendChild(el('h1', null, `${fmtDate(date)}${isTarget ? ' の来園計画' : ''}`));

  const today = d.dates.today;
  const sub = el('p', 'muted', `今日: ${fmtDate(today)}　更新: ${fmtClock(d.generated_at) || '不明'}`);
  box.appendChild(sub);

  for (const [pk, name] of PARKS_()) {
    const panel = el('div', 'panel');
    const head = el('div');
    head.appendChild(parkTag(pk));
    head.appendChild(el('b', null, name));
    panel.appendChild(head);

    const entry = ((official || {}).parks || {})[pk] || {};
    const hours = entry.hours || {};
    const ticket = entry.ticket || {};
    const crowdT = ((d.crowd || {})[pk] || {})[date] || {};
    const crowdToday = ((d.crowd || {})[pk] || {})[today] || {};

    const kv = el('div', 'kv');
    kv.appendChild(el('div', null, `開園 ${hours.open && hours.close ? hours.open + ' - ' + hours.close : '—'}`));
    kv.appendChild(el('div', null, `1デー大人 ${ticket.adult_1day ? '￥' + ticket.adult_1day.toLocaleString() : '—'}${ticket.status ? '（' + ticket.status + '）' : ''}`));
    const c1 = el('div');
    c1.append('当日の混雑予想 ');
    c1.appendChild(el('span', 'crowd ' + crowdClass(crowdT.crowd_pct), crowdT.crowd_pct != null ? crowdT.crowd_pct + '%' : '—'));
    kv.appendChild(c1);
    if (date !== today) {
      const c2 = el('div');
      c2.append('今日 ');
      c2.appendChild(el('span', 'crowd ' + crowdClass(crowdToday.crowd_pct), crowdToday.crowd_pct != null ? crowdToday.crowd_pct + '%' : '—'));
      kv.appendChild(c2);
    }
    panel.appendChild(kv);
    if (entry.note === 'not_published') {
      panel.appendChild(el('div', 'warn', 'この日のスケジュールは公式サイトに未掲載です（翌月分は前月8日ごろ掲載）。'));
    }
    if (entry.note === 'fetch_failed') {
      panel.appendChild(el('div', 'err', 'この日の公式データを取得できませんでした。'));
    }
    box.appendChild(panel);
  }

  // 鮮度と連続失敗の警告
  const rows = [
    freshness('公式サイト', (official || {}).fetched_at),
    freshness('待ち時間', d.waits_fetched_at),
    freshness('DPA', (d.dpa_today || {}).last_polled_at),
    freshness('混雑カレンダー', d.crowd_fetched_at),
  ];
  const stale = rows.filter((r) => r.stale);
  const info = el('p', 'muted', rows.map((r) => r.text).join('　/　'));
  box.appendChild(info);
  if (stale.length) {
    box.appendChild(el('div', 'warn', `${stale.length}件のデータが${STALE_MIN}分以上古いか未取得です。表示中の値は最新でない可能性があります。`));
  }
  const failing = Object.entries(d.health || {}).filter(([, v]) => (v.consecutive_failures || 0) >= 2);
  if (failing.length) {
    box.appendChild(el('div', 'err', '連続失敗中のコレクタ: ' + failing.map(([k, v]) => `${k}(${v.consecutive_failures}回)`).join(', ')));
  }
  return box;
}

function renderShows(official, date) {
  const box = document.createDocumentFragment();
  box.appendChild(el('h2', null, `ショースケジュール — ${fmtDate(date)}`));
  if (!official) {
    box.appendChild(el('div', 'warn',
      'この日の公式スケジュールは取得していません。取得するのは今日・明日・来園予定日の3日分です。'
      + '来園日を変えるなら config/settings.json の watch_dates を直すと翌朝から取得します。'));
    return box;
  }
  for (const [pk, name] of PARKS_()) {
    const entry = ((official.parks || {})[pk]) || {};
    const h = el('h3');
    h.appendChild(parkTag(pk));
    h.append(name);
    box.appendChild(h);
    const shows = entry.shows || [];
    if (!shows.length) {
      box.appendChild(el('p', 'muted', entry.note === 'not_published' ? '未掲載' : '公演の掲載がありません。'));
      continue;
    }
    const wrap = el('div', 'panel');
    for (const s of shows) {
      const item = el('div', 'item');
      item.appendChild(el('div', 'name', s.name));
      const badges = el('div');
      if (s.dpa) badges.appendChild(el('span', 'badge dpa', 'DPA対象'));
      if (s.entry) badges.appendChild(el('span', 'badge entry', 'エントリー受付'));
      if (s.reservation_only) badges.appendChild(el('span', 'badge yoyaku', '要事前予約'));
      if (badges.childNodes.length) item.appendChild(badges);
      const times = el('div', 'times' + (s.changed ? ' changed' : ''),
        s.times && s.times.length ? s.times.join('　/　') : '時刻の記載なし');
      item.appendChild(times);
      if (s.changed) item.appendChild(el('div', 'muted', '当日変更あり（公式サイトで赤字表示）'));
      wrap.appendChild(item);
    }
    box.appendChild(wrap);
    const greet = entry.greetings || [];
    if (greet.length) {
      const g = el('details');
      g.appendChild(el('summary', 'muted', `キャラクターグリーティング ${greet.length}件`));
      const gw = el('div', 'panel');
      for (const x of greet) {
        const item = el('div', 'item');
        item.appendChild(el('div', 'name', x.name));
        item.appendChild(el('div', 'times', (x.times || []).join('　/　') || '—'));
        gw.appendChild(item);
      }
      g.appendChild(gw);
      box.appendChild(g);
    }
  }
  return box;
}

// latest.json に無い日を ?date= で開いたとき、個別の official ファイルから
// 当日休止＋期間休止の和集合を組み立てる（build_latest.py の closures_for と同じ規則）。
// 公式の日次を取っていない日は、期間つき休止だけで判定する。
function closuresFromSchedule(schedule, date) {
  const out = {};
  for (const [pk] of PARKS_()) {
    const cats = {};
    for (const it of (schedule || {})[pk] || []) {
      if (it.from && it.from > date) continue;
      if (it.to && it.to < date) continue;
      if (!it.from && !it.undecided) continue;
      (cats[it.category] = cats[it.category] || []).push(
        { name: it.name, from: it.from, to: it.to, undecided: !!it.undecided });
    }
    out[pk] = cats;
  }
  return out;
}

function closuresFromOfficial(official, date) {
  const out = {};
  for (const [pk] of PARKS_()) {
    const cats = {};
    const entry = ((official.parks || {})[pk]) || {};
    for (const [cat, list] of Object.entries(entry.closures_today || {})) {
      for (const name of list) {
        (cats[cat] = cats[cat] || []).push({ name, from: null, to: null, undecided: false });
      }
    }
    for (const it of ((official.closures_schedule || {})[pk]) || []) {
      if (it.from && it.from > date) continue;
      if (it.to && it.to < date) continue;
      if (!it.from && !it.undecided) continue;
      const list = (cats[it.category] = cats[it.category] || []);
      const hit = list.find((x) => x.name === it.name);
      if (hit) Object.assign(hit, { from: it.from, to: it.to, undecided: !!it.undecided });
      else list.push({ name: it.name, from: it.from, to: it.to, undecided: !!it.undecided });
    }
    out[pk] = cats;
  }
  return out;
}

function renderClosures(closures, date, scheduleOnly) {
  const box = document.createDocumentFragment();
  box.appendChild(el('h2', null, `休止情報 — ${fmtDate(date)}`));
  const day = (closures || {})[date];
  if (!day) {
    box.appendChild(el('p', 'muted', 'この日の休止情報がありません。'));
    return box;
  }
  if (scheduleOnly) {
    box.appendChild(el('div', 'warn',
      '公式の日次ページを取得していない日なので、期間が決まっている長期休止だけを出しています。当日限りの休止は含まれません。'));
  }
  for (const [pk, name] of PARKS_()) {
    const cats = day[pk] || {};
    const total = Object.values(cats).reduce((a, v) => a + v.length, 0);
    const h = el('h3');
    h.appendChild(parkTag(pk));
    h.append(`${name}（${total}件）`);
    box.appendChild(h);
    if (!total) { box.appendChild(el('p', 'muted', '休止なし')); continue; }
    const wrap = el('div', 'panel');
    for (const key of Object.keys(CAT_JA)) {
      const items = cats[key] || [];
      if (!items.length) continue;
      const c = el('div', 'cat');
      c.appendChild(el('div', 'catName', `${CAT_JA[key]}（${items.length}）`));
      const ul = el('ul');
      for (const it of items) {
        const li = el('li', null, it.name);
        let period = null;
        if (it.undecided) period = `${it.from || '?'} 〜 終了未定`;
        else if (it.from || it.to) period = `${it.from || '?'} 〜 ${it.to || '?'}`;
        if (period) li.appendChild(el('span', 'period', '　' + period));
        ul.appendChild(li);
      }
      c.appendChild(ul);
      wrap.appendChild(c);
    }
    box.appendChild(wrap);
  }
  return box;
}

function bandOf(p) {
  if (p == null) return null;
  return p <= 30 ? '0-30' : p <= 60 ? '31-60' : p <= 80 ? '61-80' : '81-100';
}

function renderDpa(d, date) {
  const box = document.createDocumentFragment();
  box.appendChild(el('h2', null, 'ディズニー・プレミアアクセス（DPA）'));
  const names = Object.fromEntries((d.attractions || []).map((a) => [a.key, a]));
  const est = (d.dpa_estimates || {}).attractions || {};

  // 来園日の売切目安
  box.appendChild(el('h3', null, `${fmtDate(date)} の売切目安`));
  const rows = [];
  const active = PARKS_().map((x) => x[0]);
  for (const a of d.attractions || []) {
    if (!a.dpa || !active.includes(a.park)) continue;
    const pct = (((d.crowd || {})[a.park] || {})[date] || {}).crowd_pct;
    const band = bandOf(pct);
    const e = band ? (est[a.key] || {})[band] : null;
    rows.push({ a, band, pct, e });
  }
  if (!rows.length) {
    box.appendChild(el('p', 'muted', 'DPA対象施設がありません。'));
  } else {
    const tbl = el('table');
    const thead = el('tr');
    ['施設', '混雑帯', '売切目安', '根拠'].forEach((t) => thead.appendChild(el('th', null, t)));
    tbl.appendChild(thead);
    for (const { a, band, pct, e } of rows) {
      const tr = el('tr');
      const td0 = el('td');
      td0.appendChild(parkTag(a.park));
      td0.append(a.name_ja);
      tr.appendChild(td0);
      tr.appendChild(el('td', null, band ? `${band}%（予想${pct}%）` : '—'));
      const v = e && e.median;
      const td2 = el('td', 'num', v ? `${v}頃` : 'データなし');
      tr.appendChild(td2);
      const td3 = el('td');
      if (e && e.source === 'observed') {
        td3.append(`実績${e.samples}件`);
      } else if (v) {
        td3.appendChild(el('span', 'badge prov', '暫定'));
        if (e.note) td3.appendChild(el('div', 'muted', e.note));
      } else {
        td3.append('—');
      }
      tr.appendChild(td3);
      tbl.appendChild(tr);
    }
    const sc = el('div', 'scroll'); sc.appendChild(tbl);
    box.appendChild(sc);
    box.appendChild(el('p', 'muted', `目安は蓄積した実績の中央値。実績が${(d.dpa_estimates || {}).min_samples || 3}件に満たない帯は初期値（暫定）を出し、初期値が未設定なら「データなし」と表示します。時刻は取得間隔ぶん粗い値です。`));
  }

  // 今日の実績
  box.appendChild(el('h3', null, `今日（${fmtDate(d.dates.today)}）の販売状況`));
  const today = d.dpa_today;
  if (!today || !today.attractions) {
    box.appendChild(el('p', 'muted', 'まだ記録がありません。'));
  } else {
    const tbl = el('table');
    const thead = el('tr');
    ['施設', '価格', '最初の売切', '状態'].forEach((t) => thead.appendChild(el('th', null, t)));
    tbl.appendChild(thead);
    const entries = Object.entries(today.attractions)
      .filter(([k]) => (names[k] || {}).dpa && active.includes((names[k] || {}).park))
      .sort((a, b) => (a[1].first_sold_out_at || 'z').localeCompare(b[1].first_sold_out_at || 'z'));
    for (const [k, rec] of entries) {
      const tr = el('tr');
      const td0 = el('td');
      td0.appendChild(parkTag(rec.park || (names[k] || {}).park));
      td0.append((names[k] || {}).name_ja || k);
      tr.appendChild(td0);
      tr.appendChild(el('td', 'num', rec.price ? '￥' + rec.price.toLocaleString() : '—'));
      const t = fmtClock(rec.first_sold_out_at);
      tr.appendChild(el('td', 'num', t ? t + '頃' : '—'));
      const resale = (rec.events || []).some((e) => e.note === 'resale');
      const st = rec.status_at_close === 'on_sale' ? '販売中' : '売切';
      tr.appendChild(el('td', null, st + (resale ? '（再販あり）' : '')));
      tbl.appendChild(tr);
    }
    const sc = el('div', 'scroll'); sc.appendChild(tbl);
    box.appendChild(sc);
  }

  // 直近7日
  const recent = (d.dpa_recent || []).filter((r) => Object.keys(r.attractions || {}).length);
  if (recent.length) {
    const det = el('details');
    det.appendChild(el('summary', 'muted', `直近の売切実績（${recent.length}日分）`));
    const tbl = el('table');
    const thead = el('tr');
    ['日付', '混雑', '施設', '最初の売切'].forEach((t) => thead.appendChild(el('th', null, t)));
    tbl.appendChild(thead);
    for (const r of recent) {
      for (const [k, v] of Object.entries(r.attractions)) {
        const a = names[k] || {};
        if (!active.includes(a.park)) continue;
        const tr = el('tr');
        tr.appendChild(el('td', null, r.date));
        tr.appendChild(el('td', 'num', (r.crowd_pct || {})[a.park] != null ? r.crowd_pct[a.park] + '%' : '—'));
        tr.appendChild(el('td', null, a.name_ja || k));
        tr.appendChild(el('td', 'num', (fmtClock(v.first_sold_out_at) || '—') + (v.resale ? '（再販）' : '')));
        tbl.appendChild(tr);
      }
    }
    const sc = el('div', 'scroll'); sc.appendChild(tbl);
    det.appendChild(sc);
    box.appendChild(det);
  }
  return box;
}

function renderWaits(d) {
  const box = document.createDocumentFragment();
  box.appendChild(el('h2', null, `待ち時間 — 今日（${fmtDate(d.dates.today)}）`));
  const names = Object.fromEntries((d.attractions || []).map((a) => [a.key, a]));
  const waits = d.waits || {};
  let any = false;
  for (const [pk, name] of PARKS_()) {
    const p = waits[pk];
    if (!p) continue;
    const max = p.daily_max || {};
    const last = (p.last || {}).waits || {};
    const closed = (p.last || {}).closed || [];
    const keys = Object.keys(max).filter((k) => (names[k] || {}).watch);
    if (!keys.length && !closed.length) continue;
    any = true;
    const h = el('h3');
    h.appendChild(parkTag(pk));
    h.append(name);
    box.appendChild(h);
    keys.sort((a, b) => (max[b].minutes || 0) - (max[a].minutes || 0));
    const tbl = el('table');
    const thead = el('tr');
    ['施設', '当日最大', '現在'].forEach((t) => thead.appendChild(el('th', null, t)));
    tbl.appendChild(thead);
    for (const k of keys) {
      const tr = el('tr');
      tr.appendChild(el('td', null, (names[k] || {}).name_ja || k));
      tr.appendChild(el('td', 'num', `${max[k].minutes}分 (${fmtClock(max[k].at) || '—'})`));
      tr.appendChild(el('td', 'num', last[k] != null ? `${last[k]}分` : '—'));
      tbl.appendChild(tr);
    }
    const sc = el('div', 'scroll'); sc.appendChild(tbl);
    box.appendChild(sc);
    if (closed.length) {
      box.appendChild(el('p', 'muted', '運営休止中: ' + closed.map((k) => (names[k] || {}).name_ja || k).join('、')));
    }
  }
  if (!any) box.appendChild(el('p', 'muted', '今日の待ち時間はまだ記録されていません。'));
  return box;
}

// ---------- 起動 ----------

async function loadJson(path) {
  const r = await fetch(path, { cache: 'no-store' });
  if (!r.ok) throw new Error(`${path}: HTTP ${r.status}`);
  return r.json();
}

function renderControls() {
  const box = el('div', 'controls');

  const row1 = el('div', 'ctlRow');
  const prev = el('button', 'ctlBtn', '‹ 前日');
  prev.onclick = () => go(shiftDate(currentDate, -1));
  const input = el('input', 'ctlDate');
  input.type = 'date';
  input.value = currentDate;
  input.onchange = () => { if (input.value) go(input.value); };
  const next = el('button', 'ctlBtn', '翌日 ›');
  next.onclick = () => go(shiftDate(currentDate, 1));
  row1.append(prev, input, next);
  box.appendChild(row1);

  const row2 = el('div', 'ctlRow seg');
  for (const [val, label] of [['tdl', 'ランド'], ['tds', 'シー'], ['both', '両方']]) {
    const b = el('button', 'segBtn' + (parkMode === val ? ' on' : ''), label);
    b.onclick = () => setPark(val);
    row2.appendChild(b);
  }
  const t = el('button', 'ctlBtn', '来園日へ');
  t.onclick = () => go(data.dates.target);
  row2.appendChild(t);
  box.appendChild(row2);
  return box;
}

function go(date) {
  currentDate = date;
  syncUrl();
  render();
}

function setPark(mode) {
  parkMode = mode;
  try { localStorage.setItem(STORE_KEY, mode); } catch (e) { /* プライベートモード等 */ }
  syncUrl();
  render();
}

function syncUrl() {
  const u = new URLSearchParams();
  u.set('date', currentDate);
  if (parkMode !== 'both') u.set('park', parkMode);
  history.replaceState(null, '', '?' + u.toString());
}

async function render() {
  const app = document.getElementById('app');
  const d = data;

  let official = (d.official || {})[currentDate];
  if (official === undefined) {
    // latest.json に無い日は、ファイルが実在するときだけ読む。
    if ((d.official_dates || []).includes(currentDate)) {
      try { official = await loadJson(`data/official/${currentDate}.json`); }
      catch { official = null; }
    } else {
      official = null;
    }
  }

  let closures = (d.closures || {})[currentDate];
  if (!closures) {
    closures = official
      ? closuresFromOfficial(official, currentDate)
      : closuresFromSchedule(d.closures_schedule, currentDate);
  }

  app.textContent = '';
  app.appendChild(renderControls());
  app.appendChild(renderHeader(d, currentDate, official));
  app.appendChild(renderShows(official, currentDate));
  app.appendChild(renderClosures({ [currentDate]: closures }, currentDate, !official));
  app.appendChild(renderDpa(d, currentDate));
  app.appendChild(renderWaits(d));
  window.scrollTo(0, 0);
}

async function main() {
  const app = document.getElementById('app');
  try {
    data = await loadJson('data/latest.json');
  } catch (e) {
    app.textContent = '';
    app.appendChild(el('div', 'err', 'データを読み込めませんでした: ' + e.message));
    return;
  }

  let stored = null;
  try { stored = localStorage.getItem(STORE_KEY); } catch (e) { /* 読めなくても既定で動く */ }
  const fromUrl = q('park');
  parkMode = [...PARK_KEYS, 'both'].includes(fromUrl) ? fromUrl
    : ([...PARK_KEYS, 'both'].includes(stored) ? stored : 'both');

  currentDate = /^\d{4}-\d{2}-\d{2}$/.test(q('date') || '') ? q('date') : data.dates.target;
  syncUrl();
  await render();
}

main();
