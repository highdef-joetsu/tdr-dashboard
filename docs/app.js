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


// ---------- 待ちカーブのスパークライン ----------
// 単系列（1施設・1混雑帯）。系列名は行のタイトルとパークタグが担うので凡例は置かない。
// 直接ラベルはピークと夕方の最小の2点だけに絞る（全点に数字を置かない）。
const SPARK = { w: 300, h: 62, padT: 14, padB: 16, padX: 8, hue: '#1565c0' };

function sparkline(curve) {
  const hours = Object.keys(curve).map(Number).sort((a, b) => a - b);
  if (hours.length < 2) return null;
  const vals = hours.map((h) => curve[h]);
  const maxV = Math.max(...vals);
  const minH = hours[0], maxH = hours[hours.length - 1];
  const { w, h, padT, padB, padX, hue } = SPARK;
  const x = (hr) => padX + (w - padX * 2) * (maxH === minH ? 0.5 : (hr - minH) / (maxH - minH));
  const y = (v) => padT + (h - padT - padB) * (1 - v / (maxV || 1));

  const peakH = hours.reduce((a, b) => (curve[b] > curve[a] ? b : a));
  const late = hours.filter((hr) => hr >= 15);
  const lateH = late.length ? late.reduce((a, b) => (curve[b] < curve[a] ? b : a)) : null;

  const ns = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(ns, 'svg');
  svg.setAttribute('viewBox', `0 0 ${w} ${h}`);
  svg.setAttribute('class', 'spark');
  svg.setAttribute('role', 'img');
  svg.setAttribute('aria-label',
    `時間帯別の待ち時間。ピークは${peakH}時台の${curve[peakH]}分` +
    (lateH !== null ? `、${lateH}時台は${curve[lateH]}分。` : '。'));

  const mk = (tag, attrs) => {
    const n = document.createElementNS(ns, tag);
    for (const k in attrs) n.setAttribute(k, attrs[k]);
    return n;
  };
  // 基準線（控えめ）
  svg.appendChild(mk('line', { x1: 0, y1: h - padB, x2: w, y2: h - padB,
    stroke: '#e2e2e2', 'stroke-width': 1 }));
  const pts = hours.map((hr) => `${x(hr)},${y(curve[hr])}`).join(' ');
  svg.appendChild(mk('polygon', {
    points: `${x(minH)},${h - padB} ${pts} ${x(maxH)},${h - padB}`,
    fill: hue, 'fill-opacity': 0.10 }));
  svg.appendChild(mk('polyline', { points: pts, fill: 'none',
    stroke: hue, 'stroke-width': 2, 'stroke-linejoin': 'round', 'stroke-linecap': 'round' }));

  // ホバー用に全点へ透明な当たり判定と title を置く
  for (const hr of hours) {
    const g = mk('circle', { cx: x(hr), cy: y(curve[hr]), r: 9, fill: 'transparent' });
    const t = document.createElementNS(ns, 'title');
    t.textContent = `${hr}時台 ${curve[hr]}分`;
    g.appendChild(t);
    svg.appendChild(g);
  }
  // 直接ラベルはこの2点だけ。点が下寄りのときは下に置くと軸ラベルとぶつかるので上に出す。
  const mid = padT + (h - padT - padB) / 2;
  for (const hr of [peakH, lateH]) {
    if (hr === null || hr === undefined) continue;
    const py = y(curve[hr]);
    svg.appendChild(mk('circle', { cx: x(hr), cy: py, r: 4,
      fill: hue, stroke: '#fff', 'stroke-width': 2 }));
    const above = py > mid;   // 下寄りの点ほど上にラベルを出す
    const lbl = mk('text', {
      x: Math.min(w - 30, Math.max(26, x(hr))),
      y: above ? Math.max(10, py - 8) : Math.min(h - padB - 4, py + 16),
      'text-anchor': 'middle', class: 'sparkLabel' });
    lbl.textContent = `${hr}時 ${curve[hr]}分`;
    svg.appendChild(lbl);
  }
  // 直接ラベルが端の時刻を既に言っているなら、軸ラベルは重ねない
  if (peakH !== minH && lateH !== minH) {
    const ax = mk('text', { x: 0, y: h - 3, class: 'sparkAxis' });
    ax.textContent = `${minH}時`;
    svg.appendChild(ax);
  }
  if (peakH !== maxH && lateH !== maxH) {
    const ax2 = mk('text', { x: w, y: h - 3, 'text-anchor': 'end', class: 'sparkAxis' });
    ax2.textContent = `${maxH}時`;
    svg.appendChild(ax2);
  }
  return svg;
}

const VERDICT = {
  buy: '買う価値あり', skip: '買わなくてよい',
  depends: '滞在計画次第', insufficient: 'データ不足',
};

// ---------- 変更差分 ----------
const CHANGE_JA = {
  published: 'スケジュール掲載', hours: '開園時間', ticket: 'チケット価格',
  ticket_status: 'チケット販売状況', show_added: 'ショー追加', show_removed: 'ショー削除',
  show_times: '公演時刻', show_badges: '対象制度', closure_added: '休止に追加',
  closure_removed: '休止から復帰', long_closure_added: '長期休止に追加',
  long_closure_removed: '長期休止から復帰', long_closure_period: '休止期間',
};

function fmtVal(v) {
  if (Array.isArray(v)) return v.length ? v.join(' / ') : '（なし）';
  if (v === null || v === undefined) return '—';
  return String(v);
}

function renderChanges(d, date) {
  const rows = (d.changes || {})[date] || [];
  const active = PARKS_().map((x) => x[0]);
  const mine = rows.filter((r) => active.includes(r.park));
  const box = document.createDocumentFragment();
  box.appendChild(el('h2', null, `この日の変更（${mine.length}件）`));
  if (!mine.length) {
    box.appendChild(el('p', 'muted',
      '前回の取得から変更はありません。公式サイトは現在の状態しか出さないので、ここは蓄積した過去との差分です。'));
    return box;
  }
  const wrap = el('div', 'panel');
  for (const r of mine.slice(0, 30)) {
    const item = el('div', 'item');
    const head = el('div');
    head.appendChild(parkTag(r.park));
    head.appendChild(el('span', 'badge prov', CHANGE_JA[r.kind] || r.kind));
    item.appendChild(head);
    item.appendChild(el('div', 'name', r.label + (r.category ? `（${r.category}）` : '')));
    if (r.before !== undefined || r.after !== undefined) {
      const line = el('div', 'times');
      if (r.before !== undefined) { line.append(fmtVal(r.before)); line.append(' → '); }
      line.append(fmtVal(r.after));
      item.appendChild(line);
    }
    const at = new Date(r.at);
    item.appendChild(el('div', 'muted',
      isNaN(at) ? '' : `${at.getMonth() + 1}/${at.getDate()} ${fmtClock(r.at)} 検知`));
    wrap.appendChild(item);
  }
  box.appendChild(wrap);
  return box;
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
  const active = PARKS_().map((x) => x[0]);

  // 来園日：DPAを買う価値
  box.appendChild(el('h3', null, `${fmtDate(date)} に買う価値があるか`));
  const meta = d.curve_meta || {};
  const rows = [];
  for (const a of d.attractions || []) {
    if (!a.dpa || !active.includes(a.park)) continue;
    rows.push({ a, adv: (d.dpa_advice || {})[a.key] || {}, curve: (d.wait_curve || {})[a.key] });
  }
  const order = { buy: 0, depends: 1, skip: 2, insufficient: 3 };
  rows.sort((x, y) => (order[x.adv.verdict] ?? 9) - (order[y.adv.verdict] ?? 9)
    || (y.adv.saved_minutes || 0) - (x.adv.saved_minutes || 0));

  const lacking = rows.filter((r) => r.adv.verdict === 'insufficient').length;
  if (lacking === rows.length) {
    box.appendChild(el('div', 'warn',
      `同じ混雑度の日の待ち時間がまだ${meta.min_days || 3}日分たまっていないため、判定を出せません。`
      + `現在${meta.days_used || 0}日分。たまり次第ここに出ます。`));
  }

  const wrap = el('div', 'panel');
  for (const { a, adv, curve } of rows) {
    const item = el('div', 'item');
    const head = el('div');
    head.appendChild(parkTag(a.park));
    head.appendChild(el('b', null, a.name_ja));
    item.appendChild(head);

    const price = ((d.prices || {})[a.key] || {}).amount;
    const line = el('div', 'kv');
    line.appendChild(el('div', null, price ? `￥${price.toLocaleString()}` : '価格不明'));
    if (adv.band) line.appendChild(el('div', null, `混雑帯 ${adv.band}%`));
    if (adv.sold_out_at) line.appendChild(el('div', null, `売切目安 ${adv.sold_out_at}頃`));
    item.appendChild(line);

    const badge = el('span', 'badge v-' + (adv.verdict || 'insufficient'),
      VERDICT[adv.verdict] || 'データ不足');
    const brow = el('div');
    brow.appendChild(badge);
    // 「買わなくてよい」で単価を併記すると判定と矛盾して読めるので出さない
    if (adv.yen_per_minute && adv.verdict !== 'skip') {
      brow.appendChild(el('span', 'badge prov', `1分あたり約${adv.yen_per_minute}円`));
    }
    item.appendChild(brow);
    if (adv.reason) item.appendChild(el('div', 'muted', adv.reason));

    if (curve && Object.keys(curve).length >= 2) {
      const sp = sparkline(curve);
      if (sp) item.appendChild(sp);
    }
    wrap.appendChild(item);
  }
  box.appendChild(wrap);
  box.appendChild(el('p', 'muted',
    `待ち時間は、来園日と同じ混雑度帯の日を${meta.min_days || 3}日以上集めた時間帯別の中央値です。`
    + `「買わなくてよい」は${meta.late_from_hour || 15}時以降に並び直す前提の判定なので、閉園前に他を回る予定なら当てはまりません。`));

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
  app.appendChild(renderChanges(d, currentDate));
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
