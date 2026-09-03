/**
 * TDR 収集ワーカー
 *
 * GitHub Actions の cron は高頻度スケジュールの大半を実行しない
 * （実測 2026-09-03: 期待168本に対し発火1本、しかも87分遅れ）。
 * 待ち時間とDPAの取得だけをここに移す。
 *
 * このワーカーは「取得して生のまま溜める」以上のことをしない。
 * 施設の対応付け・売切判定・日次サマリーは GitHub 側の Python が担当する。
 * 同じロジックを2箇所に置かないため。
 */

const QUEUE_TIMES = { tdl: 274, tds: 275 };
const TP_DESTINATION = 'faff60df-c766-4470-8adb-dee78e813f42';
const UA = 'tdr-plan-dashboard/0.1 (personal use)';
const OPEN_HOUR = 8;      // JST。これ未満は収集しない
const CLOSE_HOUR = 22;    // JST。これ以上は収集しない
const PARK_DAY_BOUNDARY = 5;
const RETAIN_DAYS = 4;    // D1 に残す日数（Python が取り込んだ後は不要）

function jstNow() {
  return new Date(Date.now() + 9 * 3600 * 1000); // UTC値をJSTの壁時計として読む
}
function isoJst(d) {
  const p = (n) => String(n).padStart(2, '0');
  return `${d.getUTCFullYear()}-${p(d.getUTCMonth() + 1)}-${p(d.getUTCDate())}` +
    `T${p(d.getUTCHours())}:${p(d.getUTCMinutes())}:${p(d.getUTCSeconds())}+09:00`;
}
function parkDate(d) {
  const shifted = new Date(d.getTime() - PARK_DAY_BOUNDARY * 3600 * 1000);
  const p = (n) => String(n).padStart(2, '0');
  return `${shifted.getUTCFullYear()}-${p(shifted.getUTCMonth() + 1)}-${p(shifted.getUTCDate())}`;
}

async function getJson(url) {
  const r = await fetch(url, { headers: { 'User-Agent': UA, Accept: 'application/json' } });
  if (!r.ok) throw new Error(`${url}: HTTP ${r.status}`);
  return r.json();
}

async function beat(env, cron, note, ok) {
  await env.DB.prepare(
    `INSERT INTO heartbeat (cron, last_at, last_note, runs, errors)
     VALUES (?1, ?2, ?3, 1, ?4)
     ON CONFLICT(cron) DO UPDATE SET
       last_at = ?2, last_note = ?3, runs = runs + 1, errors = errors + ?4`
  ).bind(cron, isoJst(jstNow()), note, ok ? 0 : 1).run();
}

/** 待ち時間とDPAを1回ぶん取得して D1 に入れる。 */
async function collect(env) {
  const now = jstNow();
  const hour = now.getUTCHours();
  if (hour < OPEN_HOUR || hour >= CLOSE_HOUR) return '営業時間外のため取得しない';

  const at = isoJst(now);
  const date = parkDate(now);
  const rows = [];

  // 待ち時間（パークごと）。Python の parse_rides がそのまま食える形に削って持つ。
  for (const [park, pid] of Object.entries(QUEUE_TIMES)) {
    const d = await getJson(`https://queue-times.com/parks/${pid}/queue_times.json`);
    const rides = [
      ...(d.lands || []).flatMap((l) => l.rides || []),
      ...(d.rides || []),
    ].map((r) => ({ id: r.id, is_open: !!r.is_open, wait_time: r.wait_time }));
    rows.push({ kind: 'wait', payload: JSON.stringify({ park, rides }) });
  }

  // DPA。ThemeParks.wiki の live を、Python の snapshot() が食える形に削る。
  const live = await getJson(`https://api.themeparks.wiki/v1/entity/${TP_DESTINATION}/live`);
  const liveData = (live.liveData || []).map((x) => ({
    id: x.id,
    status: x.status,
    queue: { PAID_RETURN_TIME: (x.queue || {}).PAID_RETURN_TIME || null },
  }));
  rows.push({ kind: 'dpa', payload: JSON.stringify({ liveData }) });

  const stmt = env.DB.prepare(
    'INSERT INTO samples (at, park_date, kind, payload) VALUES (?1, ?2, ?3, ?4)');
  await env.DB.batch(rows.map((r) => stmt.bind(at, date, r.kind, r.payload)));
  return `${date} ${rows.length}行`;
}

/** GitHub に「取り込め」と伝え、古い行を捨てる。 */
async function publish(env) {
  const now = jstNow();
  const cutoff = parkDate(new Date(now.getTime() - RETAIN_DAYS * 86400 * 1000));
  await env.DB.prepare('DELETE FROM samples WHERE park_date < ?1').bind(cutoff).run();

  const r = await fetch(`https://api.github.com/repos/${env.GITHUB_REPO}/dispatches`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${env.GITHUB_TOKEN}`,
      Accept: 'application/vnd.github+json',
      'Content-Type': 'application/json',
      'User-Agent': UA,
    },
    body: JSON.stringify({ event_type: 'ingest', client_payload: { at: isoJst(now) } }),
  });
  if (!r.ok) throw new Error(`repository_dispatch: HTTP ${r.status} ${await r.text()}`);
  return `dispatch 送信 / ${cutoff} より前を削除`;
}

export default {
  async scheduled(event, env) {
    const isCollect = event.cron.startsWith('*/5');
    const name = isCollect ? 'collect' : 'publish';
    try {
      const note = await (isCollect ? collect(env) : publish(env));
      await beat(env, name, note, true);
    } catch (e) {
      await beat(env, name, String(e).slice(0, 300), false);
      throw e;   // Cloudflare 側のログにも残す
    }
  },

  async fetch(request, env) {
    const url = new URL(request.url);

    // 最新1件だけを認証なしで返す。中身は Queue-Times と ThemeParks.wiki の
    // 公開データそのままなので秘匿するものが無い。ダッシュボードはこれを読んで
    // 「現在の待ち時間」と「今日のDPA販売状況」を出し、GitHub 経由の遅延を回避する。
    // 施設の対応付けは行わない（対応表はダッシュボード側が latest.json から持つ）。
    if (url.pathname === '/live') {
      const date = parkDate(jstNow());
      const { results } = await env.DB.prepare(
        `SELECT at, kind, payload FROM samples
          WHERE park_date = ?1 AND at = (SELECT MAX(at) FROM samples WHERE park_date = ?1)`
      ).bind(date).all();
      const out = { date, at: results.length ? results[0].at : null, waits: {}, dpa: null };
      for (const r of results) {
        const d = JSON.parse(r.payload);
        if (r.kind === 'wait') out.waits[d.park] = d.rides;
        else out.dpa = d.liveData;
      }
      return Response.json(out, {
        headers: {
          'Cache-Control': 'public, max-age=60',
          'Access-Control-Allow-Origin': '*',
        },
      });
    }

    const auth = request.headers.get('Authorization') || '';
    if (auth !== `Bearer ${env.INGEST_TOKEN}`) {
      return new Response('unauthorized', { status: 401 });
    }
    if (url.pathname === '/health') {
      const { results } = await env.DB.prepare('SELECT * FROM heartbeat').all();
      return Response.json({ heartbeat: results });
    }
    if (url.pathname === '/samples') {
      const date = url.searchParams.get('date') || parkDate(jstNow());
      const { results } = await env.DB.prepare(
        'SELECT at, kind, payload FROM samples WHERE park_date = ?1 ORDER BY at, id'
      ).bind(date).all();
      return Response.json({
        date,
        count: results.length,
        samples: results.map((r) => ({ at: r.at, kind: r.kind, data: JSON.parse(r.payload) })),
      });
    }
    return new Response('not found', { status: 404 });
  },
};
