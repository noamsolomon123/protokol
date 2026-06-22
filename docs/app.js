/* Knesset OSINT — static front-end logic.
   Fetches the JSON produced by scripts/export_site_data.py and renders it.
   All politician-supplied text is inserted via textContent (never innerHTML),
   so the page is safe even though the data originates from an external API. */
'use strict';

const STANCE_HE = { for: 'בעד', against: 'נגד', abstain: 'נמנע', absent: 'נעדר', na: 'לא ידוע' };

function $(id) { return document.getElementById(id); }
function show(el) { el.classList.remove('hidden'); }
function hide(el) { el.classList.add('hidden'); }

function el(tag, opts = {}) {
  const node = document.createElement(tag);
  if (opts.class) node.className = opts.class;
  if (opts.text != null) node.textContent = String(opts.text);
  if (opts.href) { node.href = opts.href; node.target = '_blank'; node.rel = 'noopener'; }
  return node;
}

async function pickDataFile() {
  const params = new URLSearchParams(location.search);
  const wanted = params.get('p'); // slug, e.g. person-965
  if (wanted) return `./data/${wanted}.json`;
  try {
    const res = await fetch('./data/politicians.json', { cache: 'no-cache' });
    if (res.ok) {
      const manifest = await res.json();
      if (Array.isArray(manifest) && manifest.length && manifest[0].file) {
        return `./data/${manifest[0].file}`;
      }
    }
  } catch (_) { /* fall through to default */ }
  return './data/person-965.json';
}

function renderHero(p) {
  $('p-name').textContent = p.full_name || '—';
  if (p.current_party) { $('p-party').textContent = p.current_party; show($('p-party')); }
  if (p.is_current) show($('p-current'));
  if (p.source_url) $('p-source').href = p.source_url; else hide($('p-source'));
}

function renderIndex(sc) {
  const idx = sc.index || {};
  const ring = $('idx-ring');
  if (idx.value != null) {
    $('idx-value').textContent = idx.value;
    ring.style.setProperty('--pct', idx.value);
  } else {
    $('idx-value').textContent = '—';
  }
  $('idx-coverage').textContent =
    `חלקי · ${idx.coverage_scored || 0}/${idx.coverage_total || 0} ממדים`;
  const noteBits = [];
  if (idx.label) noteBits.push(idx.label === 'preliminary' ? 'מקדמי' : idx.label === 'partial' ? 'חלקי' : 'מלא');
  if (Array.isArray(sc.notes) && sc.notes.length) noteBits.push(sc.notes.join(' '));
  $('idx-note').textContent = noteBits.join(' — ');
  $('idx-disclaimer').textContent = sc.disclaimer_he || '';
}

function renderCounts(counts) {
  const map = [
    ['roles', 'תפקידים'],
    ['bills', 'הצעות חוק'],
    ['votes', 'הצבעות'],
  ];
  const box = $('counts');
  box.replaceChildren();
  for (const [key, label] of map) {
    const b = el('div', { class: 'count-box' });
    b.appendChild(el('div', { class: 'count-num', text: counts && counts[key] != null ? counts[key] : 0 }));
    b.appendChild(el('div', { class: 'count-label', text: label }));
    box.appendChild(b);
  }
}

function renderDimensions(dims) {
  const wrap = $('dimensions');
  wrap.replaceChildren();
  (dims || []).forEach((d) => {
    const card = el('div', { class: 'dim' });
    const head = el('div', { class: 'dim-head' });
    head.appendChild(el('span', { class: 'dim-name', text: d.label_he || d.key }));
    if (d.scorable && d.score != null) {
      head.appendChild(el('span', { class: 'dim-score', text: `${d.score}` }));
    } else {
      head.appendChild(el('span', { class: 'dim-pending', text: 'ממתין למקור' }));
    }
    card.appendChild(head);

    if (d.scorable && d.score != null) {
      const bar = el('div', { class: 'bar' });
      const fill = el('i'); fill.style.width = `${Math.max(0, Math.min(100, d.score))}%`;
      bar.appendChild(fill); card.appendChild(bar);
    }

    // Raw receipts
    if (d.raw && Object.keys(d.raw).length) {
      const parts = [];
      if (d.raw.cast != null) parts.push(`הצביע: ${d.raw.cast}`);
      if (d.raw.absent != null) parts.push(`נעדר: ${d.raw.absent}`);
      if (d.raw.bills_sponsored != null) parts.push(`הצעות חוק: ${d.raw.bills_sponsored}`);
      if (d.raw.as_lead_initiator != null) parts.push(`כיוזם ראשי: ${d.raw.as_lead_initiator}`);
      if (parts.length) card.appendChild(el('div', { class: 'dim-raw', text: parts.join(' · ') }));
    }
    if (d.pending_reason && !(d.scorable && d.score != null)) {
      card.appendChild(el('div', { class: 'dim-meta', text: d.pending_reason }));
    }
    card.appendChild(el('div', { class: 'dim-meta', text: `מקור: ${d.source_note || '—'}` }));
    wrap.appendChild(card);
  });
}

function renderBills(bills) {
  const ul = $('bills');
  ul.replaceChildren();
  if (!bills || !bills.length) { ul.appendChild(el('li', { text: 'אין נתונים' })); return; }
  bills.forEach((b) => {
    const li = el('li');
    const main = el('div', { class: 'li-main' });
    main.appendChild(el('div', { class: 'li-title', text: b.name || '—' }));
    const sub = [];
    if (b.knesset_num) sub.push(`כנסת ${b.knesset_num}`);
    sub.push(b.is_lead_initiator ? 'יוזם ראשי' : 'חתום');
    main.appendChild(el('div', { class: 'li-sub', text: sub.join(' · ') }));
    li.appendChild(main);
    if (b.source_url) li.appendChild(el('a', { class: 'li-link', text: 'מקור ↗', href: b.source_url }));
    ul.appendChild(li);
  });
}

function renderVotes(votes) {
  const ul = $('votes');
  ul.replaceChildren();
  if (!votes || !votes.length) { ul.appendChild(el('li', { text: 'אין נתונים' })); return; }
  votes.forEach((v) => {
    const li = el('li');
    const main = el('div', { class: 'li-main' });
    main.appendChild(el('div', { class: 'li-title', text: v.event_title || '(נושא ההצבעה לא זמין)' }));
    if (v.date) main.appendChild(el('div', { class: 'li-sub', text: v.date }));
    li.appendChild(main);
    const right = el('div', { class: 'li-main' });
    const stance = v.stance || 'na';
    right.appendChild(el('span', { class: `stance stance-${stance}`, text: STANCE_HE[stance] || stance }));
    if (v.source_url) right.appendChild(el('a', { class: 'li-link', text: 'מקור ↗', href: v.source_url }));
    li.appendChild(right);
    ul.appendChild(li);
  });
}

function renderFooter(data) {
  const s = data.sources || {};
  $('footer-sources').textContent =
    'מקורות: ' + [s.parliamentinfo_v4, s.votes_v3].filter(Boolean).join(' · ');
  $('footer-date').textContent = data.generated_at || '—';
}

async function main() {
  try {
    const file = await pickDataFile();
    const res = await fetch(file, { cache: 'no-cache' });
    if (!res.ok) throw new Error(`לא ניתן לטעון נתונים (${res.status})`);
    const data = await res.json();

    renderHero(data.politician || {});
    renderIndex(data.scorecard || {});
    renderCounts(data.counts);
    renderDimensions((data.scorecard || {}).dimensions);
    renderBills(data.sample_bills);
    renderVotes(data.recent_votes);
    renderFooter(data);

    hide($('loading'));
    show($('content'));
  } catch (err) {
    hide($('loading'));
    const e = $('error');
    e.textContent = `שגיאה בטעינת הנתונים: ${err.message}`;
    show(e);
  }
}

main();
