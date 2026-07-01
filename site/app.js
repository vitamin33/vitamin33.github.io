/* ============================================================
   vitamin33.github.io — dashboard renderer
   Vanilla JS, zero dependencies. Fetches ./data.json (rebuilt
   daily by the pipeline) and renders every section. All data
   values go through textContent — never innerHTML.
   ============================================================ */
(function () {
  'use strict';

  // Static fallbacks so the hero renders even before the first pipeline run.
  var FALLBACK = {
    login: 'vitamin33',
    name: 'Vitalii Serbyn',
    headline: 'MLOps · GenAI/LLM Engineer — I ship AI systems to production and prove it with data',
    email: 'serbyn.vitalii@gmail.com',
    linkedin: 'https://www.linkedin.com/in/vitalii-serbyn/'
  };

  var MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  var SVG_NS = 'http://www.w3.org/2000/svg';

  var state = { series: null };

  /* ---------------- tiny DOM helpers (XSS-safe by construction) -------- */

  function $(id) { return document.getElementById(id); }

  function el(tag, attrs) {
    var node = document.createElement(tag);
    if (attrs) {
      Object.keys(attrs).forEach(function (k) {
        var v = attrs[k];
        if (v === null || v === undefined) return;
        if (k === 'class') node.className = v;
        else if (k === 'text') node.textContent = v; // data always lands here
        else node.setAttribute(k, String(v));
      });
    }
    for (var i = 2; i < arguments.length; i++) {
      var c = arguments[i];
      if (c === null || c === undefined) continue;
      node.appendChild(typeof c === 'string' ? document.createTextNode(c) : c);
    }
    return node;
  }

  function svgEl(tag, attrs) {
    var node = document.createElementNS(SVG_NS, tag);
    if (attrs) {
      Object.keys(attrs).forEach(function (k) {
        node.setAttribute(k, String(attrs[k]));
      });
    }
    return node;
  }

  function clear(node) {
    if (!node) return;
    while (node.firstChild) node.removeChild(node.firstChild);
  }

  /* ---------------- formatting helpers -------------------------------- */

  function toInt(v) {
    var n = Number(v);
    return Number.isFinite(n) ? Math.max(0, Math.round(n)) : 0;
  }

  function fmtInt(v) {
    var n = toInt(v);
    return String(n).replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  }

  function parseYMD(s) {
    if (typeof s !== 'string') return null;
    var m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(s.trim());
    if (!m) return null;
    return { y: +m[1], mo: +m[2], d: +m[3] };
  }

  function fmtDateShort(s) { // "2026-06-12" -> "Jun 12"
    var p = parseYMD(s);
    return p ? MONTHS[p.mo - 1] + ' ' + p.d : String(s || '');
  }

  function fmtDateLong(s) { // "2026-06-12" -> "Jun 12, 2026"
    var p = parseYMD(s);
    return p ? MONTHS[p.mo - 1] + ' ' + p.d + ', ' + p.y : String(s || '');
  }

  function relTime(iso) {
    var t = Date.parse(iso);
    if (isNaN(t)) return 'recently';
    var s = Math.max(0, (Date.now() - t) / 1000);
    if (s < 90) return 'just now';
    if (s < 3600) return Math.round(s / 60) + 'm ago';
    if (s < 86400 * 2) return Math.round(s / 3600) + 'h ago';
    return Math.round(s / 86400) + 'd ago';
  }

  // Only ever emit http(s)/mailto links, no matter what data.json contains.
  function safeHref(url) {
    if (typeof url !== 'string') return null;
    var u = url.trim();
    return /^(https?:\/\/|mailto:)/i.test(u) ? u : null;
  }

  function emptyNote(text) {
    return el('p', { class: 'empty-note', text: text });
  }

  /* ---------------- boot ------------------------------------------------ */

  function init() {
    fetch('./data.json', { cache: 'no-store' })
      .then(function (res) {
        if (!res.ok) throw new Error('HTTP ' + res.status);
        return res.json();
      })
      .then(function (data) {
        if (!data || typeof data !== 'object') throw new Error('invalid payload');
        render(data);
      })
      .catch(function (err) {
        console.warn('[dashboard] data.json unavailable, showing warm-up state:', err.message);
        renderWarmup();
      });
  }

  function render(d) {
    var profile = (d.profile && typeof d.profile === 'object') ? d.profile : {};
    var cta = (d.cta && typeof d.cta === 'object') ? d.cta : {};
    var kpis = (d.kpis && typeof d.kpis === 'object') ? d.kpis : {};

    renderHero(profile, cta, d.generated_at);
    renderKpis(kpis);

    state.series = Array.isArray(d.traffic_series) ? d.traffic_series : [];
    renderTrafficChart(state.series);

    renderReferrers(Array.isArray(d.referrers) ? d.referrers : []);
    renderTopRepos(Array.isArray(d.top_repos_14d) ? d.top_repos_14d : [],
                   typeof profile.login === 'string' ? profile.login : FALLBACK.login);
    renderHeatmap((d.contributions && typeof d.contributions === 'object') ? d.contributions : {});
    renderLanguages(Array.isArray(d.languages) ? d.languages : []);
    renderFeatured(Array.isArray(d.featured) ? d.featured : []);
  }

  /* ---------------- 1 · hero ------------------------------------------- */

  function renderHero(profile, cta, generatedAt) {
    var name = typeof profile.name === 'string' && profile.name ? profile.name : FALLBACK.name;
    var headline = typeof profile.headline === 'string' && profile.headline ? profile.headline : FALLBACK.headline;
    var login = typeof profile.login === 'string' && profile.login ? profile.login : FALLBACK.login;

    $('hero-name').textContent = name;
    $('hero-headline').textContent = headline;
    document.title = name + ' — MLOps / GenAI Engineer';

    var avatar = $('avatar');
    var avatarUrl = safeHref(profile.avatar_url) || 'https://github.com/' + encodeURIComponent(login) + '.png';
    avatar.src = avatarUrl;
    avatar.alt = 'Avatar of ' + name;
    avatar.addEventListener('error', function () {
      avatar.style.visibility = 'hidden'; // offline / blocked: keep layout, hide broken glyph
    });

    if (generatedAt) {
      $('live-text').textContent = 'LIVE · updated ' + relTime(generatedAt);
    }

    var row = $('cta-row');
    clear(row);
    var email = typeof cta.email === 'string' && cta.email ? cta.email : FALLBACK.email;
    row.appendChild(el('a', { class: 'btn primary', href: 'mailto:' + email, text: 'Email me' }));
    var li = safeHref(cta.linkedin);
    if (li) {
      row.appendChild(el('a', { class: 'btn', href: li, rel: 'noopener', text: 'LinkedIn' }));
    }
    row.appendChild(el('a', {
      class: 'btn',
      href: 'https://github.com/' + encodeURIComponent(login),
      rel: 'noopener',
      text: 'GitHub'
    }));
    var cv = safeHref(cta.cv_url);
    if (cv) {
      row.appendChild(el('a', { class: 'btn', href: cv, rel: 'noopener', text: 'Résumé' }));
    }
  }

  /* ---------------- 2 · KPI strip --------------------------------------- */

  function renderKpis(k) {
    var since = parseYMD(k.tracking_since) ? fmtDateLong(k.tracking_since) : null;
    var cards = [
      { label: 'Reach · 14d', value: k.views_14d, sub: fmtInt(k.uniques_14d) + ' unique visitors' },
      { label: 'Clones · 14d', value: k.clones_14d, sub: 'repo clones' },
      { label: 'Tracked views', value: k.views_total_tracked, sub: since ? 'collecting since ' + since : 'all snapshots kept' },
      { label: 'Contributions', value: k.contributions_365d, sub: 'last 365 days' },
      { label: 'Followers', value: k.followers, sub: 'on GitHub' }
    ];
    var grid = $('kpi-grid');
    clear(grid);
    cards.forEach(function (c) {
      grid.appendChild(el('div', { class: 'kpi' },
        el('div', { class: 'kpi-label', text: c.label }),
        el('div', { class: 'kpi-value', text: fmtInt(c.value) }),
        el('div', { class: 'kpi-sub', text: c.sub })
      ));
    });
  }

  /* ---------------- 3 · traffic chart ----------------------------------- */

  function cleanSeries(raw) {
    return raw
      .filter(function (p) { return p && parseYMD(p.date); })
      .map(function (p) {
        return {
          date: p.date,
          views: toInt(p.views),
          uniques: toInt(p.uniques),
          clones: toInt(p.clones)
        };
      })
      .sort(function (a, b) { return a.date < b.date ? -1 : a.date > b.date ? 1 : 0; });
  }

  function renderTrafficChart(rawSeries) {
    var box = $('traffic-chart');
    var note = $('traffic-note');
    var legend = $('chart-legend');
    clear(box); clear(legend);
    note.hidden = true;
    lastChartWidth = Math.floor(box.clientWidth) || 0;

    var data = cleanSeries(rawSeries || []);

    if (data.length === 0) {
      box.appendChild(emptyNote('No traffic captured yet — the first snapshot lands with the next scheduled pipeline run.'));
      return;
    }

    legend.appendChild(el('span', { class: 'legend-item' },
      el('span', { class: 'legend-swatch' }), 'Views'));
    legend.appendChild(el('span', { class: 'legend-item' },
      el('span', { class: 'legend-swatch uniq' }), 'Unique visitors'));

    if (data.length < 3) {
      renderMiniBars(box, data);
      note.textContent = 'History accumulates daily — GitHub discards traffic after 14 days; this pipeline doesn’t.';
      note.hidden = false;
      return;
    }

    renderLineChart(box, data);
  }

  // 1–2 data points: honest bars instead of a silly line.
  function renderMiniBars(box, data) {
    var maxV = Math.max(1, Math.max.apply(null, data.map(function (p) { return p.views; })));
    var wrap = el('div', { class: 'mini-bars' });
    data.forEach(function (p) {
      var vh = Math.max(4, Math.round((p.views / maxV) * 116));
      var uh = Math.max(4, Math.round((p.uniques / maxV) * 116));
      var vBar = el('div', { class: 'mini-bar', title: p.views + ' views' });
      vBar.style.height = vh + 'px';
      var uBar = el('div', { class: 'mini-bar uniq', title: p.uniques + ' unique' });
      uBar.style.height = uh + 'px';
      var vals = el('div', { class: 'mini-vals' },
        el('b', { text: fmtInt(p.views) }), ' views · ' + fmtInt(p.uniques) + ' uniq');
      wrap.appendChild(el('div', { class: 'mini-day' },
        vals,
        el('div', { class: 'mini-cols' }, vBar, uBar),
        el('div', { class: 'mini-date', text: fmtDateShort(p.date) })
      ));
    });
    box.appendChild(wrap);
  }

  function niceCeil(v) {
    if (v <= 5) return 5;
    var pow = Math.pow(10, Math.floor(Math.log(v) / Math.LN10));
    var n = v / pow;
    var m = n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10;
    return m * pow;
  }

  function renderLineChart(box, data) {
    var W = Math.max(300, Math.floor(box.clientWidth || box.parentNode.clientWidth || 720));
    var H = 280;
    var padL = 46, padR = 14, padT = 14, padB = 34;
    var iw = W - padL - padR;
    var ih = H - padT - padB;
    var n = data.length;

    var maxY = niceCeil(Math.max(1, Math.max.apply(null, data.map(function (p) {
      return Math.max(p.views, p.uniques);
    }))));

    var x = function (i) { return padL + (n === 1 ? iw / 2 : (i / (n - 1)) * iw); };
    var y = function (v) { return padT + ih - (v / maxY) * ih; };

    var svg = svgEl('svg', {
      width: W, height: H, viewBox: '0 0 ' + W + ' ' + H,
      role: 'img', 'aria-label': 'Daily views and unique visitors across all repositories'
    });

    // area gradient
    var defs = svgEl('defs');
    var grad = svgEl('linearGradient', { id: 'areaFill', x1: 0, y1: 0, x2: 0, y2: 1 });
    grad.appendChild(svgEl('stop', { offset: '0%', 'stop-color': 'rgba(45,226,194,0.28)' }));
    grad.appendChild(svgEl('stop', { offset: '100%', 'stop-color': 'rgba(45,226,194,0)' }));
    defs.appendChild(grad);
    svg.appendChild(defs);

    // horizontal gridlines + y labels
    for (var g = 0; g <= 4; g++) {
      var gv = (maxY / 4) * g;
      var gy = y(gv);
      svg.appendChild(svgEl('line', {
        x1: padL, y1: gy, x2: W - padR, y2: gy,
        stroke: g === 0 ? '#28324a' : '#1c2433', 'stroke-width': 1
      }));
      var yl = svgEl('text', {
        x: padL - 8, y: gy + 3.5, 'text-anchor': 'end',
        fill: '#5e6a7e', 'font-size': 10,
        'font-family': 'ui-monospace, SF Mono, Menlo, monospace'
      });
      yl.textContent = fmtInt(gv);
      svg.appendChild(yl);
    }

    // x labels (~6 ticks)
    var step = Math.max(1, Math.ceil(n / 6));
    for (var i = 0; i < n; i += step) {
      var tx = svgEl('text', {
        x: x(i), y: H - 10, 'text-anchor': 'middle',
        fill: '#5e6a7e', 'font-size': 10,
        'font-family': 'ui-monospace, SF Mono, Menlo, monospace'
      });
      tx.textContent = fmtDateShort(data[i].date);
      svg.appendChild(tx);
    }

    // paths
    var viewsPts = data.map(function (p, idx) { return [x(idx), y(p.views)]; });
    var uniqPts = data.map(function (p, idx) { return [x(idx), y(p.uniques)]; });
    var lineOf = function (pts) {
      return pts.map(function (pt, idx) {
        return (idx === 0 ? 'M' : 'L') + pt[0].toFixed(1) + ' ' + pt[1].toFixed(1);
      }).join(' ');
    };

    var area = lineOf(viewsPts) +
      ' L' + viewsPts[n - 1][0].toFixed(1) + ' ' + (padT + ih) +
      ' L' + viewsPts[0][0].toFixed(1) + ' ' + (padT + ih) + ' Z';
    svg.appendChild(svgEl('path', { d: area, fill: 'url(#areaFill)', stroke: 'none' }));

    svg.appendChild(svgEl('path', {
      d: lineOf(uniqPts), fill: 'none', stroke: '#93a1b8',
      'stroke-width': 1.6, 'stroke-dasharray': '5 4',
      'stroke-linejoin': 'round', 'stroke-linecap': 'round'
    }));
    svg.appendChild(svgEl('path', {
      d: lineOf(viewsPts), fill: 'none', stroke: '#2de2c2',
      'stroke-width': 2.2, 'stroke-linejoin': 'round', 'stroke-linecap': 'round'
    }));

    if (n <= 45) {
      viewsPts.forEach(function (pt) {
        svg.appendChild(svgEl('circle', {
          cx: pt[0].toFixed(1), cy: pt[1].toFixed(1), r: 2.6,
          fill: '#0b0e14', stroke: '#2de2c2', 'stroke-width': 1.6
        }));
      });
    }

    // hover crosshair + tooltip
    var cross = svgEl('line', {
      x1: 0, y1: padT, x2: 0, y2: padT + ih,
      stroke: '#28324a', 'stroke-width': 1, 'stroke-dasharray': '3 3', visibility: 'hidden'
    });
    svg.appendChild(cross);

    var tip = el('div', { class: 'chart-tip', hidden: 'hidden' });
    var tipDate = el('div', { class: 'tip-date' });
    var tipViews = el('div', { class: 'tip-views' });
    var tipUniq = el('div');
    var tipClones = el('div');
    tip.appendChild(tipDate); tip.appendChild(tipViews);
    tip.appendChild(tipUniq); tip.appendChild(tipClones);

    function moveTip(evt) {
      var rect = svg.getBoundingClientRect();
      var mx = evt.clientX - rect.left;
      var idx = n === 1 ? 0 :
        Math.round(((mx - padL) / iw) * (n - 1));
      idx = Math.min(n - 1, Math.max(0, idx));
      var p = data[idx];
      var px = x(idx);
      cross.setAttribute('x1', px);
      cross.setAttribute('x2', px);
      cross.setAttribute('visibility', 'visible');
      tipDate.textContent = fmtDateLong(p.date);
      tipViews.textContent = fmtInt(p.views) + ' views';
      tipUniq.textContent = fmtInt(p.uniques) + ' unique';
      tipClones.textContent = fmtInt(p.clones) + ' clones';
      tip.hidden = false;
      var left = px + 14;
      if (left + 150 > W) left = px - 158;
      tip.style.left = Math.max(0, left) + 'px';
      tip.style.top = '18px';
    }
    function hideTip() {
      tip.hidden = true;
      cross.setAttribute('visibility', 'hidden');
    }
    svg.addEventListener('mousemove', moveTip);
    svg.addEventListener('mouseleave', hideTip);

    box.appendChild(svg);
    box.appendChild(tip);
  }

  // re-render the chart at the new width when its container resizes (debounced)
  var resizeTimer = null;
  var lastChartWidth = 0;
  function onChartResize() {
    if (!state.series) return;
    var box = $('traffic-chart');
    var w = box ? Math.floor(box.clientWidth) : 0;
    if (!w || w === lastChartWidth) return;
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(function () {
      lastChartWidth = Math.floor($('traffic-chart').clientWidth);
      renderTrafficChart(state.series);
    }, 160);
  }
  window.addEventListener('resize', onChartResize);
  if (typeof ResizeObserver === 'function') {
    var chartBoxEl = $('traffic-chart');
    if (chartBoxEl) new ResizeObserver(onChartResize).observe(chartBoxEl);
  }

  /* ---------------- 4 · referrers + top repos --------------------------- */

  function renderReferrers(refs) {
    var body = $('referrers-body');
    clear(body);
    var rows = refs.filter(function (r) { return r && typeof r.referrer === 'string'; });
    if (rows.length === 0) {
      body.appendChild(emptyNote('No referrer data yet — traffic sources appear once snapshots accumulate.'));
      return;
    }
    var maxC = Math.max(1, Math.max.apply(null, rows.map(function (r) { return toInt(r.count); })));
    rows.slice(0, 8).forEach(function (r) {
      var fill = el('div', { class: 'hbar-fill' });
      fill.style.width = Math.max(2, Math.round((toInt(r.count) / maxC) * 100)) + '%';
      var num = el('span', { class: 'hbar-num' },
        el('b', { text: fmtInt(r.count) }), ' · ' + fmtInt(r.uniques) + ' uniq');
      body.appendChild(el('div', { class: 'hbar-row' },
        el('div', { class: 'hbar-head' },
          el('span', { class: 'hbar-name', text: r.referrer }), num),
        el('div', { class: 'hbar-track' }, fill)
      ));
    });
  }

  function renderTopRepos(repos, login) {
    var body = $('toprepos-body');
    clear(body);
    var rows = repos.filter(function (r) { return r && typeof r.repo === 'string'; });
    if (rows.length === 0) {
      body.appendChild(emptyNote('No repo traffic recorded in the last 14 days yet.'));
      return;
    }
    rows.slice(0, 6).forEach(function (r, i) {
      var link = el('a', {
        href: 'https://github.com/' + encodeURIComponent(login) + '/' + encodeURIComponent(r.repo),
        rel: 'noopener',
        text: r.repo
      });
      body.appendChild(el('div', { class: 'repo-row' },
        el('span', { class: 'repo-idx', text: String(i + 1).padStart(2, '0') }),
        el('span', { class: 'repo-name' }, link),
        el('span', { class: 'repo-stats' },
          el('b', { text: fmtInt(r.views) }), ' views · ' + fmtInt(r.uniques) + ' uniq')
      ));
    });
  }

  /* ---------------- 5 · contribution heatmap ---------------------------- */

  var HM_CELL = 11, HM_GAP = 3;

  function renderHeatmap(contrib) {
    var body = $('heatmap-body');
    var totalEl = $('heatmap-total');
    clear(body);

    var days = (Array.isArray(contrib.days) ? contrib.days : [])
      .filter(function (d) { return d && parseYMD(d.date); })
      .sort(function (a, b) { return a.date < b.date ? -1 : 1; });

    if (days.length === 0) {
      totalEl.textContent = '';
      body.appendChild(emptyNote('Contribution data arrives with the first pipeline run.'));
      return;
    }

    var total = toInt(contrib.total);
    totalEl.textContent = fmtInt(total) + ' contributions in the last 365 days';

    // Build week columns, GitHub-style (rows = Sun..Sat).
    var first = parseYMD(days[0].date);
    var firstDow = new Date(Date.UTC(first.y, first.mo - 1, first.d)).getUTCDay();

    var grid = el('div', { class: 'hm-grid', role: 'img',
      'aria-label': fmtInt(total) + ' contributions in the last 365 days' });

    for (var p = 0; p < firstDow; p++) {
      grid.appendChild(el('div', { class: 'hm-cell pad', 'aria-hidden': 'true' }));
    }

    var monthMarks = [];
    var lastMonth = -1;
    days.forEach(function (d, i) {
      var lvl = Math.min(4, Math.max(0, toInt(d.level)));
      var count = toInt(d.count);
      var col = Math.floor((i + firstDow) / 7);
      var pd = parseYMD(d.date);
      if (pd.mo !== lastMonth) {
        lastMonth = pd.mo;
        monthMarks.push({ col: col, label: MONTHS[pd.mo - 1] });
      }
      grid.appendChild(el('div', {
        class: 'hm-cell' + (lvl > 0 ? ' l' + lvl : ''),
        title: count + ' contribution' + (count === 1 ? '' : 's') + ' on ' + fmtDateLong(d.date)
      }));
    });

    var monthsRow = el('div', { class: 'hm-months', 'aria-hidden': 'true' });
    var lastLabelCol = -10;
    monthMarks.forEach(function (m) {
      if (m.col - lastLabelCol < 3) return; // avoid crowding
      lastLabelCol = m.col;
      var span = el('span', { text: m.label });
      span.style.left = (m.col * (HM_CELL + HM_GAP)) + 'px';
      monthsRow.appendChild(span);
    });

    var dow = el('div', { class: 'hm-dow', 'aria-hidden': 'true' },
      el('span'), el('span', { text: 'Mon' }), el('span'),
      el('span', { text: 'Wed' }), el('span'),
      el('span', { text: 'Fri' }), el('span'));

    body.appendChild(el('div', { class: 'hm-flex' },
      dow,
      el('div', { class: 'hm-scroll' },
        el('div', { class: 'hm-inner' }, monthsRow, grid))
    ));

    var legend = el('div', { class: 'hm-legend' }, 'Less');
    ['', ' l1', ' l2', ' l3', ' l4'].forEach(function (cls) {
      legend.appendChild(el('span', { class: 'hm-cell' + cls }));
    });
    legend.appendChild(document.createTextNode('More'));
    body.appendChild(legend);
  }

  /* ---------------- 6 · languages --------------------------------------- */

  function renderLanguages(langs) {
    var body = $('languages-body');
    clear(body);
    var rows = langs.filter(function (l) {
      return l && typeof l.name === 'string' && Number.isFinite(Number(l.pct));
    });
    if (rows.length === 0) {
      body.appendChild(emptyNote('Language stats appear after the first pipeline run.'));
      return;
    }
    var maxPct = Math.max.apply(null, rows.map(function (l) { return Number(l.pct); })) || 1;
    rows.slice(0, 8).forEach(function (l) {
      var pct = Math.max(0, Number(l.pct));
      var fill = el('div', { class: 'hbar-fill' });
      fill.style.width = Math.max(2, Math.round((pct / maxPct) * 100)) + '%';
      body.appendChild(el('div', { class: 'lang-row' },
        el('div', { class: 'lang-head' },
          el('span', { class: 'lang-name', text: l.name }),
          el('span', { class: 'lang-pct', text: pct.toFixed(1) + '%' })),
        el('div', { class: 'hbar-track' }, fill)
      ));
    });
  }

  /* ---------------- 7 · featured (proof of work) ------------------------ */

  function renderFeatured(items) {
    var grid = $('featured-grid');
    clear(grid);
    var rows = items.filter(function (f) { return f && typeof f.name === 'string'; });
    if (rows.length === 0) {
      grid.appendChild(emptyNote('Featured projects appear after the first pipeline run.'));
      return;
    }
    rows.forEach(function (f) {
      var url = safeHref(f.url) ||
        'https://github.com/' + encodeURIComponent(FALLBACK.login) + '/' + encodeURIComponent(f.name);
      var head = el('div', { class: 'card-head' },
        el('span', { class: 'card-name' },
          el('a', { href: url, rel: 'noopener', text: f.name })));
      var stars = toInt(f.stars);
      if (stars > 0) {
        head.appendChild(el('span', { class: 'card-stars', text: '★ ' + fmtInt(stars) }));
      }

      var card = el('article', { class: 'card' }, head);
      if (typeof f.impact === 'string' && f.impact) {
        card.appendChild(el('p', { class: 'card-impact', text: f.impact }));
      }
      if (typeof f.description === 'string' && f.description) {
        card.appendChild(el('p', { class: 'card-desc', text: f.description }));
      }
      var tags = Array.isArray(f.tags) ? f.tags.filter(function (t) { return typeof t === 'string'; }) : [];
      if (tags.length) {
        var chips = el('div', { class: 'chip-row' });
        tags.forEach(function (t) { chips.appendChild(el('span', { class: 'chip', text: t })); });
        card.appendChild(chips);
      }
      if (parseYMD(f.pushed_at)) {
        card.appendChild(el('div', { class: 'card-updated', text: 'updated ' + fmtDateLong(f.pushed_at) }));
      }
      grid.appendChild(card);
    });
  }

  /* ---------------- warming-up state (no data.json yet) ------------------ */

  function renderWarmup() {
    renderHero({}, { email: FALLBACK.email, linkedin: FALLBACK.linkedin }, null);

    var pill = $('live-pill');
    pill.classList.add('warm');
    $('live-text').textContent = 'PIPELINE WARMING UP';
    $('live-sub').textContent = 'first snapshot lands after the next scheduled run';

    var main = $('main');
    clear(main);
    main.appendChild(el('section', { class: 'section reveal' },
      el('div', { class: 'warmup' },
        el('h2', { text: 'Pipeline warming up' }),
        el('p', { text: 'This dashboard is fed by a scheduled GitHub Action that snapshots repo traffic, stars, and contributions every day at 04:17 UTC — and keeps the history GitHub throws away. No data has landed yet. Check back after the first run.' }),
        el('div', { class: 'warmup-bars' },
          el('span'), el('span'), el('span'), el('span'))
      )));
  }

  /* ---------------- go --------------------------------------------------- */

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
