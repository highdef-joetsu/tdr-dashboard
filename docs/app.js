'use strict';

const ALL_PARKS = [['tdl', '東京ディズニーランド'], ['tds', '東京ディズニーシー']];
const PARK_KEYS = ALL_PARKS.map((p) => p[0]);
const PARK_SHORT = { tdl: 'ランド', tds: 'シー' };
const STORE_KEY = 'tdr.park';
const STALE_MIN = 30;
const PERMANENT_YEARS = 2;
const CAT_JA = {
  attraction: 'アトラクション', show: 'パレード/ショー', greeting: 'キャラクターグリーティング',
  shop: 'ショップ', restaurant: 'レストラン', service: 'サービス施設',
};
const VERDICT = {
  buy: ['買う価値あり', 'b-good'], skip: ['買わなくてよい', 'b-info'],
  depends: ['滞在計画次第', 'b-warn'], insufficient: ['データ不足', ''],
};
const CHANGE_JA = {
  published: 'スケジュール掲載', hours: '開園時間', ticket: 'チケット価格',
  ticket_status: 'チケット販売状況', show_added: 'ショー追加', show_removed: 'ショー削除',
  show_times: '公演時刻', show_badges: '対象制度', closure_added: '休止に追加',
  closure_removed: '休止から復帰', long_closure_added: '長期休止に追加',
  long_closure_removed: '長期休止から復帰', long_closure_period: '休止期間',
};

let parkMode = 'both';
let currentDate = null;
let data = null;
// Worker が5分ごとに取っている最新値。GitHub 経由の取り込みは遅れるので、
// 「現在」だけはここから直接読む。取れなくても repo のデータで動く。
let live = null;

const PARKS_ = () => (parkMode === 'both' ? ALL_PARKS : ALL_PARKS.filter((p) => p[0] === parkMode));
const activeKeys = () => PARKS_().map((p) => p[0]);

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
  return `${y}年${m}月${d}日（${'日月火水木金土'[new Date(y, m - 1, d).getDay()]}）`;
}
function shiftDate(s, days) {
  const [y, m, d] = s.split('-').map(Number);
  const dt = new Date(y, m - 1, d + days);
  const p = (n) => String(n).padStart(2, '0');
  return `${dt.getFullYear()}-${p(dt.getMonth() + 1)}-${p(dt.getDate())}`;
}
const crowdLevel = (p) => (p == null ? null : p <= 40 ? ['lo', '空いている'] : p <= 70 ? ['mid', 'やや混雑'] : ['hi', '混雑']);
const parkTag = (p) => el('span', 'parkTag ' + p, PARK_SHORT[p]);

function badge(text, kind) {
  const b = el('span', 'badge' + (kind ? ' ' + kind : ''));
  if (kind) b.appendChild(el('span', 'dot'));
  b.append(text);
  return b;
}

// ---------- 最新値（Worker の /live） ----------
async function loadLive(d) {
  if (!d.live_endpoint) return null;
  try {
    const r = await fetch(d.live_endpoint, { cache: 'no-store' });
    if (!r.ok) return null;
    const j = await r.json();
    // Worker は 22:00〜翌8:00 は取得しないので、朝いちばんに前夜の値が返る。
    // 日付が今日でなければ「現在」として使わない（時刻だけ見せると前夜の値を
    // 今の値と読み違える）。
    if (!j || !j.at || (j.date && d.dates && j.date !== d.dates.today)) return null;
    return j;
  } catch (e) {
    return null;   // 取れなくても repo 側のデータで表示できる
  }
}

/** /live の生値を内部キーに対応付ける。対応表は latest.json 側が持っている。 */
function liveWaits(d) {
  if (!live) return null;
  const byId = {};
  for (const a of d.attractions || []) if (a.queue_times_id) byId[a.queue_times_id] = a;
  const waits = {}, closed = {};
  for (const [park, rides] of Object.entries(live.waits || {})) {
    for (const r of rides || []) {
      const a = byId[r.id];
      if (!a || a.park !== park) continue;
      if (r.is_open) waits[a.key] = r.wait_time;
      else (closed[park] = closed[park] || []).push(a.key);
    }
  }
  return { waits, closed };
}

function liveDpa(d) {
  if (!live || !live.dpa) return null;
  const byId = {};
  for (const a of d.attractions || []) if (a.themeparks_id) byId[a.themeparks_id] = a;
  const out = {};
  for (const x of live.dpa) {
    const a = byId[x.id];
    if (!a) continue;
    const paid = (x.queue || {}).PAID_RETURN_TIME;
    out[a.key] = { state: paid ? paid.state : null, status: x.status,
                   price: paid && paid.price ? paid.price.amount : null };
  }
  return out;
}

// ---------- スパークライン（単系列。識別は行の見出しとパークタグが担う） ----------
const SPARK = { w: 300, h: 62, padT: 14, padB: 16, padX: 8, hue: '#3F456F' };

function sparkline(curve) {
  const hours = Object.keys(curve).map(Number).sort((a, b) => a - b);
  if (hours.length < 2) return null;
  const maxV = Math.max(...hours.map((h) => curve[h]));
  const minH = hours[0], maxH = hours[hours.length - 1];
  const { w, h, padT, padB, padX, hue } = SPARK;
  const x = (hr) => padX + (w - padX * 2) * (maxH === minH ? 0.5 : (hr - minH) / (maxH - minH));
  const y = (v) => padT + (h - padT - padB) * (1 - v / (maxV || 1));
  const peakH = hours.reduce((a, b) => (curve[b] > curve[a] ? b : a));
  const late = hours.filter((hr) => hr >= 15);
  const lateH = late.length ? late.reduce((a, b) => (curve[b] < curve[a] ? b : a)) : null;

  const ns = 'http://www.w3.org/2000/svg';
  const mk = (tag, attrs) => {
    const n = document.createElementNS(ns, tag);
    for (const k in attrs) n.setAttribute(k, attrs[k]);
    return n;
  };
  const svg = mk('svg', { viewBox: `0 0 ${w} ${h}`, class: 'spark', role: 'img' });
  svg.setAttribute('aria-label',
    `時間帯別の待ち時間。ピークは${peakH}時台の${curve[peakH]}分` +
    (lateH !== null ? `、${lateH}時台は${curve[lateH]}分。` : '。'));
  svg.appendChild(mk('line', { x1: 0, y1: h - padB, x2: w, y2: h - padB, stroke: '#EDE8E1', 'stroke-width': 1 }));
  const pts = hours.map((hr) => `${x(hr)},${y(curve[hr])}`).join(' ');
  svg.appendChild(mk('polygon', { points: `${x(minH)},${h - padB} ${pts} ${x(maxH)},${h - padB}`, fill: hue, 'fill-opacity': 0.09 }));
  svg.appendChild(mk('polyline', { points: pts, fill: 'none', stroke: hue, 'stroke-width': 2, 'stroke-linejoin': 'round', 'stroke-linecap': 'round' }));
  for (const hr of hours) {
    const c = mk('circle', { cx: x(hr), cy: y(curve[hr]), r: 9, fill: 'transparent' });
    const t = document.createElementNS(ns, 'title');
    t.textContent = `${hr}時台 ${curve[hr]}分`;
    c.appendChild(t);
    svg.appendChild(c);
  }
  const mid = padT + (h - padT - padB) / 2;
  for (const hr of [peakH, lateH]) {
    if (hr === null || hr === undefined) continue;
    const py = y(curve[hr]);
    svg.appendChild(mk('circle', { cx: x(hr), cy: py, r: 4, fill: hue, stroke: '#fff', 'stroke-width': 2 }));
    const above = py > mid;
    const lbl = mk('text', {
      x: Math.min(w - 30, Math.max(26, x(hr))),
      y: above ? Math.max(10, py - 8) : Math.min(h - padB - 4, py + 16),
      'text-anchor': 'middle', class: 'sparkLabel' });
    lbl.textContent = `${hr}時 ${curve[hr]}分`;
    svg.appendChild(lbl);
  }
  if (peakH !== minH && lateH !== minH) {
    const a = mk('text', { x: 0, y: h - 3, class: 'sparkAxis' }); a.textContent = `${minH}時`; svg.appendChild(a);
  }
  if (peakH !== maxH && lateH !== maxH) {
    const a = mk('text', { x: w, y: h - 3, 'text-anchor': 'end', class: 'sparkAxis' }); a.textContent = `${maxH}時`; svg.appendChild(a);
  }
  return svg;
}

// ---------- 休止（恒久終了の判定はサーバ側 is_permanent と同じ規則） ----------
function isPermanent(it, date) {
  if (!it.undecided || !it.from) return false;
  const [y, m, d] = date.split('-');
  return it.from < `${String(Number(y) - PERMANENT_YEARS).padStart(4, '0')}-${m}-${d}`;
}
function covers(it, date) {
  if (it.from && it.from > date) return false;
  if (it.to && it.to < date) return false;
  return !!(it.from || it.undecided);
}
function closuresFromSchedule(schedule, date) {
  const out = {};
  for (const [pk] of PARKS_()) {
    const cats = {};
    for (const it of (schedule || {})[pk] || []) {
      if (!covers(it, date)) continue;
      (cats[it.category] = cats[it.category] || []).push(
        { name: it.name, from: it.from, to: it.to, undecided: !!it.undecided, permanent: isPermanent(it, date) });
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
      for (const name of list) (cats[cat] = cats[cat] || []).push({ name, from: null, to: null, undecided: false });
    }
    for (const it of ((official.closures_schedule || {})[pk]) || []) {
      if (!covers(it, date)) continue;
      const list = (cats[it.category] = cats[it.category] || []);
      const perm = isPermanent(it, date);
      const hit = list.find((x) => x.name === it.name);
      if (hit) Object.assign(hit, { from: it.from, to: it.to, undecided: !!it.undecided, permanent: perm });
      else list.push({ name: it.name, from: it.from, to: it.to, undecided: !!it.undecided, permanent: perm });
    }
    out[pk] = cats;
  }
  return out;
}
const splitPermanent = (cats) => {
  const live = {}, perm = [];
  for (const [k, items] of Object.entries(cats || {})) {
    for (const it of items) {
      if (it.permanent) perm.push({ ...it, category: k });
      else (live[k] = live[k] || []).push(it);
    }
  }
  return [live, perm];
};

// ---------- 操作列 ----------
function renderControls() {
  const box = el('div', 'controls');
  const r1 = el('div', 'ctlRow');
  const prev = el('button', 'ctlBtn', '‹ 前日');
  prev.onclick = () => go(shiftDate(currentDate, -1));
  const input = el('input', 'ctlDate');
  input.type = 'date';
  input.value = currentDate;
  input.setAttribute('aria-label', '表示する日付');
  input.onchange = () => { if (input.value) go(input.value); };
  const next = el('button', 'ctlBtn', '翌日 ›');
  next.onclick = () => go(shiftDate(currentDate, 1));
  r1.append(prev, input, next);

  const r2 = el('div', 'ctlRow');
  const seg = el('div', 'ctlRow seg');
  for (const [val, label] of [['tdl', 'ランド'], ['tds', 'シー'], ['both', '両方']]) {
    const b = el('button', 'segBtn' + (parkMode === val ? ' on' : ''), label);
    b.setAttribute('aria-pressed', String(parkMode === val));
    b.onclick = () => setPark(val);
    seg.appendChild(b);
  }
  const t = el('button', 'ctlBtn', '来園日');
  t.onclick = () => go(data.dates.target);
  r2.append(seg, t);
  box.append(r1, r2);
  return box;
}

// ---------- 要点 ----------
function keyPoints(d, date, official, closures) {
  const out = [];
  const names = Object.fromEntries((d.attractions || []).map((a) => [a.key, a]));
  const act = activeKeys();

  // DPA対象・watch対象の施設が休止していないか
  const watched = (d.attractions || []).filter((a) => act.includes(a.park));
  for (const [pk] of PARKS_()) {
    const [live] = splitPermanent((closures || {})[pk]);
    const closedNames = new Set((live.attraction || []).map((x) => x.name));
    for (const a of watched.filter((x) => x.park === pk)) {
      if (closedNames.has(a.name_ja)) {
        const it = (live.attraction || []).find((x) => x.name === a.name_ja);
        const period = it && it.to ? `${it.from} 〜 ${it.to}` : (it && it.undecided ? '終了未定' : '');
        out.push({ mark: 'bad', html: [`${a.name_ja}は休止`, a.dpa ? '（DPA対象）' : '', period ? ` ${period}` : ''] });
      }
    }
  }
  // 買う価値ありのDPA
  const buys = Object.entries(d.dpa_advice || {})
    .filter(([k, v]) => v.verdict === 'buy' && act.includes((names[k] || {}).park));
  if (buys.length) {
    out.push({ mark: 'good', html: [`DPAは${buys.length}施設で「買う価値あり」`,
      `（${buys.map(([k]) => (names[k] || {}).name_ja).slice(0, 2).join('・')}${buys.length > 2 ? ' ほか' : ''}）`] });
  }
  // 変更
  const ch = ((d.changes || {})[date] || []).filter((r) => act.includes(r.park));
  if (ch.length) out.push({ mark: 'info', html: [`前回の取得から${ch.length}件の変更`] });

  // 未掲載・取得失敗
  for (const [pk, nm] of PARKS_()) {
    const e = ((official || {}).parks || {})[pk] || {};
    if (e.note === 'not_published') out.push({ mark: 'warn', html: [`${nm}のスケジュールは未掲載`] });
    if (e.note === 'fetch_failed') out.push({ mark: 'warn', html: [`${nm}の公式データを取得できていない`] });
  }
  if (!official) out.push({ mark: 'warn', html: ['この日の公式スケジュールは取得対象外（今日・明日・来園日のみ）'] });
  return out;
}

function renderKeyPoints(points) {
  if (!points.length) return null;
  const card = el('div', 'card');
  const body = el('div', 'row');
  const ul = el('ul', 'keyList');
  for (const p of points) {
    const li = el('li');
    li.appendChild(el('span', 'mark ' + p.mark));
    const span = el('span');
    const b = el('b', null, p.html[0]);
    span.appendChild(b);
    for (const rest of p.html.slice(1)) if (rest) span.append(rest);
    li.appendChild(span);
    ul.appendChild(li);
  }
  body.appendChild(ul);
  card.appendChild(body);
  return card;
}

// ---------- パーク概況 ----------
function renderParkStat(d, date, official) {
  const frag = document.createDocumentFragment();
  for (const [pk, name] of PARKS_()) {
    const entry = ((official || {}).parks || {})[pk] || {};
    const hours = entry.hours || {};
    const ticket = entry.ticket || {};
    const crowd = ((d.crowd || {})[pk] || {})[date] || {};
    const card = el('div', 'card');
    const head = el('div', 'cardHead');
    head.appendChild(parkTag(pk));
    head.appendChild(el('h3', null, name));
    card.appendChild(head);

    const body = el('div', 'cardBody');
    const stats = el('div', 'parkStat');
    const mk = (k, v, unit) => {
      const s = el('div', 'stat');
      s.appendChild(el('span', 'k', k));
      const val = el('span', 'v');
      val.append(v);
      if (unit) val.appendChild(el('small', null, unit));
      s.appendChild(val);
      return s;
    };
    stats.appendChild(mk('開園', hours.open && hours.close ? `${hours.open}–${hours.close}` : '—'));
    stats.appendChild(mk('1デー大人', ticket.adult_1day ? `¥${ticket.adult_1day.toLocaleString()}` : '—',
      ticket.status && ticket.status !== '販売中' ? ` ${ticket.status}` : ''));
    body.appendChild(stats);

    const lv = crowdLevel(crowd.crowd_pct);
    const cb = el('div', 'crowdBar');
    const track = el('div', 'track');
    const fill = el('div', 'fill ' + (lv ? lv[0] : ''));
    fill.style.width = (crowd.crowd_pct != null ? crowd.crowd_pct : 0) + '%';
    track.appendChild(fill);
    cb.appendChild(track);
    const cap = el('div', 'cap');
    cap.appendChild(el('span', 'muted', lv ? `混雑予想 ${lv[1]}` : '混雑予想 データなし'));
    cap.appendChild(el('span', 'muted', crowd.crowd_pct != null ? `${crowd.crowd_pct}%` : '—'));
    cb.appendChild(cap);
    body.appendChild(cb);
    card.appendChild(body);
    frag.appendChild(card);
  }
  return frag;
}

// ---------- 鮮度 ----------
function renderFreshness(d, official) {
  const rows = [
    ['最新値（Worker）', live ? live.at : null],
    ['公式サイト', (official || {}).fetched_at],
    ['待ち時間', d.waits_fetched_at],
    ['DPA', (d.dpa_today || {}).last_polled_at],
    ['混雑カレンダー', d.crowd_fetched_at],
  ];
  const frag = document.createDocumentFragment();
  const stale = rows.filter(([, iso]) => {
    const a = ageMinutes(iso);
    return a === null || a >= STALE_MIN;
  });
  if (stale.length) {
    frag.appendChild(el('div', 'alert warn',
      `${stale.length}件のデータが${STALE_MIN}分以上古いか未取得です。表示中の値は最新でない可能性があります。`));
  }
  const failing = Object.entries(d.health || {}).filter(([, v]) => (v.consecutive_failures || 0) >= 2);
  if (failing.length) {
    frag.appendChild(el('div', 'alert bad',
      '連続失敗中: ' + failing.map(([k, v]) => `${k}（${v.consecutive_failures}回）`).join(' / ')));
  }
  const det = el('details');
  det.className = 'card';
  const sm = el('summary');
  sm.append('データの取得時刻');
  sm.appendChild(el('span', 'cnt', stale.length ? `${stale.length}件が古い` : 'すべて最新'));
  det.appendChild(sm);
  const body = el('div', 'detBody');
  const ul = el('ul');
  for (const [label, iso] of rows) {
    const age = ageMinutes(iso);
    const t = fmtClock(iso);
    const li = el('li', null, `${label}　${t ? t + (age >= STALE_MIN ? `（${age}分前）` : '') : '取得できていません'}`);
    ul.appendChild(li);
  }
  body.appendChild(ul);
  det.appendChild(body);
  frag.appendChild(det);
  return frag;
}

// ---------- 変更 ----------
const fmtVal = (v) => (Array.isArray(v) ? (v.length ? v.join(' / ') : '（なし）') : (v == null ? '—' : String(v)));

function renderChanges(d, date) {
  const rows = ((d.changes || {})[date] || []).filter((r) => activeKeys().includes(r.park));
  const frag = document.createDocumentFragment();
  frag.appendChild(el('h2', null, 'この日の変更'));
  if (!rows.length) {
    frag.appendChild(el('p', 'note',
      '前回の取得から変更はありません。公式サイトは現在の状態しか出さないので、ここは蓄積した過去との差分です。'));
    return frag;
  }
  const card = el('div', 'card');
  for (const r of rows.slice(0, 30)) {
    const item = el('div', 'item');
    const bl = el('div', 'badgeRow');
    bl.appendChild(parkTag(r.park));
    bl.appendChild(badge(CHANGE_JA[r.kind] || r.kind, 'b-info'));
    item.appendChild(bl);
    item.appendChild(el('div', 'name', r.label + (r.category ? `（${r.category}）` : '')));
    if (r.before !== undefined || r.after !== undefined) {
      const line = el('div', 'times');
      if (r.before !== undefined) { line.append(fmtVal(r.before)); line.append(' → '); }
      line.append(fmtVal(r.after));
      item.appendChild(line);
    }
    const at = new Date(r.at);
    item.appendChild(el('div', 'metaRow',
      isNaN(at) ? '' : `${at.getMonth() + 1}/${at.getDate()} ${fmtClock(r.at)} 検知`));
    card.appendChild(item);
  }
  frag.appendChild(card);
  return frag;
}

// ---------- ショー ----------
function renderShows(official, date) {
  const frag = document.createDocumentFragment();
  frag.appendChild(el('h2', null, 'ショースケジュール'));
  if (!official) {
    frag.appendChild(el('div', 'alert warn',
      'この日の公式スケジュールは取得していません。取得するのは今日・明日・来園予定日の3日分です。'));
    return frag;
  }
  for (const [pk, name] of PARKS_()) {
    const entry = ((official.parks || {})[pk]) || {};
    const shows = entry.shows || [];
    const card = el('div', 'card');
    const head = el('div', 'cardHead');
    head.appendChild(parkTag(pk));
    head.appendChild(el('h3', null, name));
    card.appendChild(head);
    if (!shows.length) {
      card.appendChild(el('div', 'cardBody')).appendChild(
        el('p', 'note', entry.note === 'not_published' ? '未掲載' : '公演の掲載がありません。'));
    }
    for (const s of shows) {
      const item = el('div', 'item');
      item.appendChild(el('div', 'name', s.name));
      const bl = el('div', 'badgeRow');
      if (s.dpa) bl.appendChild(badge('DPA対象', 'b-info'));
      if (s.entry) bl.appendChild(badge('エントリー受付', 'b-info'));
      if (s.reservation_only) bl.appendChild(badge('要事前予約', 'b-warn'));
      if (bl.childNodes.length) item.appendChild(bl);
      item.appendChild(el('div', 'times' + (s.changed ? ' changed' : ''),
        s.times && s.times.length ? s.times.join('　') : '時刻の記載なし'));
      if (s.changed) item.appendChild(el('div', 'metaRow', '当日変更あり'));
      card.appendChild(item);
    }
    const greet = entry.greetings || [];
    if (greet.length) {
      const det = el('details');
      const sm = el('summary');
      sm.append('キャラクターグリーティング');
      sm.appendChild(el('span', 'cnt', `${greet.length}件`));
      det.appendChild(sm);
      const body = el('div', 'detBody');
      const ul = el('ul');
      for (const g of greet) {
        const li = el('li', null, g.name);
        li.appendChild(el('span', 'period', (g.times || []).join(' / ') || '—'));
        ul.appendChild(li);
      }
      body.appendChild(ul);
      det.appendChild(body);
      card.appendChild(det);
    }
    frag.appendChild(card);
  }
  return frag;
}

// ---------- 休止 ----------
function renderClosures(closures, date, scheduleOnly) {
  const frag = document.createDocumentFragment();
  frag.appendChild(el('h2', null, '休止情報'));
  if (!closures) {
    frag.appendChild(el('p', 'note', 'この日の休止情報がありません。'));
    return frag;
  }
  if (scheduleOnly) {
    frag.appendChild(el('div', 'alert info',
      '公式の日次ページを取得していない日なので、期間が決まっている長期休止だけを出しています。当日限りの休止は含まれません。'));
  }
  for (const [pk, name] of PARKS_()) {
    const [live, permanent] = splitPermanent(closures[pk]);
    const total = Object.values(live).reduce((a, v) => a + v.length, 0);
    const card = el('div', 'card');
    const head = el('div', 'cardHead');
    head.appendChild(parkTag(pk));
    head.appendChild(el('h3', null, `${name}　${total}件`));
    card.appendChild(head);
    if (!total) card.appendChild(el('div', 'cardBody')).appendChild(el('p', 'note', '来園日に効く休止はありません'));
    for (const key of Object.keys(CAT_JA)) {
      const items = live[key] || [];
      if (!items.length) continue;
      const det = el('details');
      if (key === 'attraction') det.open = true;   // 一番効くカテゴリだけ開けておく
      const sm = el('summary');
      sm.append(CAT_JA[key]);
      sm.appendChild(el('span', 'cnt', `${items.length}件`));
      det.appendChild(sm);
      const body = el('div', 'detBody');
      const ul = el('ul');
      for (const it of items) {
        const li = el('li', null, it.name);
        let period = null;
        if (it.undecided) period = `${it.from || '?'} 〜 終了未定`;
        else if (it.from || it.to) period = `${it.from || '?'} 〜 ${it.to || '?'}`;
        if (period) li.appendChild(el('span', 'period', period));
        ul.appendChild(li);
      }
      body.appendChild(ul);
      det.appendChild(body);
      card.appendChild(det);
    }
    if (permanent.length) {
      const det = el('details');
      const sm = el('summary');
      sm.append('恒久的に終了しているもの');
      sm.appendChild(el('span', 'cnt', `${permanent.length}件`));
      det.appendChild(sm);
      const body = el('div', 'detBody');
      body.appendChild(el('p', 'note',
        `${PERMANENT_YEARS}年以上「終了日未定」のまま休止しているため、来園日の判断材料から外しています。`));
      const ul = el('ul');
      for (const it of permanent) {
        const li = el('li', null, it.name);
        li.appendChild(el('span', 'period', `${CAT_JA[it.category] || it.category}　${it.from || '?'} 〜`));
        ul.appendChild(li);
      }
      body.appendChild(ul);
      det.appendChild(body);
      card.appendChild(det);
    }
    frag.appendChild(card);
  }
  return frag;
}

// ---------- DPA ----------
function renderDpa(d, date) {
  const frag = document.createDocumentFragment();
  frag.appendChild(el('h2', null, 'ディズニー・プレミアアクセス'));
  const act = activeKeys();
  const meta = d.curve_meta || {};
  const rows = (d.attractions || [])
    .filter((a) => a.dpa && act.includes(a.park))
    .map((a) => ({ a, adv: (d.dpa_advice || {})[a.key] || {}, curve: (d.wait_curve || {})[a.key] }));
  const order = { buy: 0, depends: 1, skip: 2, insufficient: 3 };
  rows.sort((x, y) => (order[x.adv.verdict] ?? 9) - (order[y.adv.verdict] ?? 9)
    || (y.adv.saved_minutes || 0) - (x.adv.saved_minutes || 0));

  if (rows.every((r) => r.adv.verdict === 'insufficient')) {
    frag.appendChild(el('div', 'alert warn',
      `同じ混雑度の日の待ち時間がまだ${meta.min_days || 3}日分たまっていないため、買う価値の判定を出せません。`
      + `現在${meta.days_used || 0}日分。たまり次第ここに出ます。`));
  }
  const card = el('div', 'card');
  for (const { a, adv, curve } of rows) {
    const item = el('div', 'item');
    const head = el('div', 'badgeRow');
    head.appendChild(parkTag(a.park));
    const [label, kind] = VERDICT[adv.verdict] || VERDICT.insufficient;
    head.appendChild(badge(label, kind));
    if (adv.yen_per_minute && adv.verdict !== 'skip') head.appendChild(badge(`1分あたり約${adv.yen_per_minute}円`));
    item.appendChild(head);
    item.appendChild(el('div', 'name', a.name_ja));
    const price = ((d.prices || {})[a.key] || {}).amount;
    const meta2 = el('div', 'metaRow');
    meta2.appendChild(el('span', null, price ? `¥${price.toLocaleString()}` : '価格不明'));
    if (adv.band) meta2.appendChild(el('span', null, `混雑帯 ${adv.band}%`));
    if (adv.sold_out_at) meta2.appendChild(el('span', null, `売切目安 ${adv.sold_out_at}頃`));
    item.appendChild(meta2);
    if (adv.reason) item.appendChild(el('div', 'note', adv.reason));
    if (curve && Object.keys(curve).length >= 2) {
      const sp = sparkline(curve);
      if (sp) item.appendChild(sp);
    }
    card.appendChild(item);
  }
  frag.appendChild(card);
  frag.appendChild(el('p', 'note',
    `待ち時間は、来園日と同じ混雑度帯の日を${meta.min_days || 3}日以上集めた時間帯別の中央値です。`
    + `「買わなくてよい」は${meta.late_from_hour || 15}時以降に並び直す前提の判定なので、閉園前に他を回る予定なら当てはまりません。`));

  // 今日の販売状況
  const today = d.dpa_today;
  const names = Object.fromEntries((d.attractions || []).map((x) => [x.key, x]));
  if (today && today.attractions) {
    const det = el('details');
    det.className = 'card';
    const sm = el('summary');
    sm.append(`今日（${fmtDate(d.dates.today)}）の販売状況`);
    if (live) sm.appendChild(el('span', 'cnt', `${fmtClock(live.at)} 時点`));
    det.appendChild(sm);
    const body = el('div', 'detBody');
    const ul = el('ul');
    const entries = Object.entries(today.attractions)
      .filter(([k]) => (names[k] || {}).dpa && act.includes((names[k] || {}).park))
      .sort((x, y) => (x[1].first_sold_out_at || 'z').localeCompare(y[1].first_sold_out_at || 'z'));
    const ld = liveDpa(d);
    for (const [k, rec] of entries) {
      const t = fmtClock(rec.first_sold_out_at);
      const resale = (rec.events || []).some((e) => e.note === 'resale');
      const cur = ld && ld[k] ? ld[k].state : null;
      const nowLabel = cur === null ? (rec.status_at_close === 'on_sale' ? '販売中' : '売切')
        : (cur === 'AVAILABLE' ? '販売中' : '売切');
      const li = el('li', null, (names[k] || {}).name_ja || k);
      li.appendChild(el('span', 'period',
        `${nowLabel}${t ? `　最初の売切 ${t}頃` : ''}${resale ? '　再販あり' : ''}`));
      ul.appendChild(li);
    }
    body.appendChild(ul);
    det.appendChild(body);
    frag.appendChild(det);
  }
  return frag;
}

// ---------- 待ち時間 ----------
function renderWaits(d) {
  const frag = document.createDocumentFragment();
  frag.appendChild(el('h2', null, `待ち時間（今日 ${fmtDate(d.dates.today)}）`));
  if (live) {
    frag.appendChild(el('p', 'muted',
      `「現在」は ${fmtClock(live.at)} 時点（5分ごとに取得）。「当日最大」は取り込み済みの範囲。`));
  }
  const names = Object.fromEntries((d.attractions || []).map((a) => [a.key, a]));
  const lw = liveWaits(data);
  let any = false;
  for (const [pk, name] of PARKS_()) {
    const p = (d.waits || {})[pk];
    if (!p) continue;
    const max = p.daily_max || {};
    const last = lw ? lw.waits : ((p.last || {}).waits || {});
    const closed = lw ? (lw.closed[pk] || []) : ((p.last || {}).closed || []);
    // 当日最大は取り込み済み（最大20分遅れ）、現在は /live（5分遅れ）。
    // 当日最大だけで行を組むと、開園直後の「まだ取り込まれていないが今は動いている」
    // 時間帯にアトラクションが1件も出ない。両方の和集合で組む。
    const keys = [...new Set([...Object.keys(max), ...Object.keys(last)])]
      .filter((k) => (names[k] || {}).watch && (names[k] || {}).park === pk);
    if (!keys.length && !closed.length) continue;
    any = true;
    keys.sort((a, b) => ((max[b] || {}).minutes || last[b] || 0) - ((max[a] || {}).minutes || last[a] || 0));
    const card = el('div', 'card');
    const head = el('div', 'cardHead');
    head.appendChild(parkTag(pk));
    head.appendChild(el('h3', null, name));
    card.appendChild(head);
    for (const k of keys) {
      const item = el('div', 'item');
      item.appendChild(el('div', 'name', (names[k] || {}).name_ja || k));
      const m = el('div', 'metaRow');
      m.appendChild(el('span', null, max[k]
        ? `当日最大 ${max[k].minutes}分（${fmtClock(max[k].at) || '—'}）`
        : '当日最大 —'));
      m.appendChild(el('span', null, `現在 ${last[k] != null ? last[k] + '分' : '—'}`));
      item.appendChild(m);
      card.appendChild(item);
    }
    if (closed.length) {
      card.appendChild(el('div', 'item')).appendChild(el('div', 'note',
        '運営休止中: ' + closed.map((k) => (names[k] || {}).name_ja || k).join('、')));
    }
    frag.appendChild(card);
  }
  if (!any) frag.appendChild(el('p', 'note', '今日の待ち時間はまだ記録されていません。'));
  return frag;
}

// ---------- 起動 ----------
async function loadJson(path) {
  const r = await fetch(path, { cache: 'no-store' });
  if (!r.ok) throw new Error(`${path}: HTTP ${r.status}`);
  return r.json();
}
function go(date) { currentDate = date; syncUrl(); render(); }
function setPark(mode) {
  parkMode = mode;
  try { localStorage.setItem(STORE_KEY, mode); } catch (e) { /* プライベートモード等 */ }
  syncUrl(); render();
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
    if ((d.official_dates || []).includes(currentDate)) {
      try { official = await loadJson(`data/official/${currentDate}.json`); } catch { official = null; }
    } else official = null;
  }
  let closures = (d.closures || {})[currentDate];
  const scheduleOnly = !official;
  if (!closures) {
    closures = official ? closuresFromOfficial(official, currentDate)
      : closuresFromSchedule(d.closures_schedule, currentDate);
  }

  app.textContent = '';
  app.appendChild(renderControls());

  const title = el('div', 'dayTitle');
  title.appendChild(el('h1', null, fmtDate(currentDate)
    + (currentDate === d.dates.target ? ' — 来園日' : '')));
  title.appendChild(el('span', 'muted sub',
    `今日 ${fmtDate(d.dates.today)}　更新 ${fmtClock(d.generated_at) || '—'}`));
  app.appendChild(title);

  const kp = renderKeyPoints(keyPoints(d, currentDate, official, closures));
  if (kp) app.appendChild(kp);
  app.appendChild(renderParkStat(d, currentDate, official));
  app.appendChild(renderFreshness(d, official));
  app.appendChild(renderChanges(d, currentDate));
  app.appendChild(renderShows(official, currentDate));
  app.appendChild(renderClosures(closures, currentDate, scheduleOnly));
  app.appendChild(renderDpa(d, currentDate));
  app.appendChild(renderWaits(d));
  window.scrollTo(0, 0);
}

async function main() {
  const app = document.getElementById('app');
  try { data = await loadJson('data/latest.json'); }
  catch (e) {
    app.textContent = '';
    app.appendChild(el('div', 'alert bad', 'データを読み込めませんでした: ' + e.message));
    return;
  }
  let stored = null;
  try { stored = localStorage.getItem(STORE_KEY); } catch (e) { /* 読めなくても既定で動く */ }
  const fromUrl = q('park');
  const valid = [...PARK_KEYS, 'both'];
  parkMode = valid.includes(fromUrl) ? fromUrl : (valid.includes(stored) ? stored : 'both');
  currentDate = /^\d{4}-\d{2}-\d{2}$/.test(q('date') || '') ? q('date') : data.dates.target;
  live = await loadLive(data);
  syncUrl();
  await render();
}

main();
