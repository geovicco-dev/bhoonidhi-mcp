/* sim.js — shared simulator: transcript animation + real Leaflet basemap.
 * Reads window.RUNS, window.CLIENTS, and window.BHOONIDHI_THEME (set per page).
 * Availability colours and map tiles come from the theme so the dark and light
 * variants share one engine.
 */
(function () {
  var THEME = window.BHOONIDHI_THEME || {};
  var REDUCED = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  /* ---- copy buttons (delegated) ---- */
  document.addEventListener('click', function (e) {
    var b = e.target.closest('.copy'); if (!b) return;
    var txt = b.dataset.copy || (b.parentElement.querySelector('code,pre') || {}).innerText || '';
    if (navigator.clipboard) navigator.clipboard.writeText(txt).then(function () {
      var o = b.textContent; b.textContent = 'Copied'; b.classList.add('ok');
      setTimeout(function () { b.textContent = o; b.classList.remove('ok'); }, 1300);
    });
  });

  /* ---- Leaflet map ---- */
  var map = null, layer = null, currentBounds = null, resizeRaf = 0;
  function initMap() {
    if (!window.L || !document.getElementById('map')) return;
    map = L.map('map', { zoomControl: false, attributionControl: true, scrollWheelZoom: false, dragging: true });
    map.setView([22, 82], 4);
    L.tileLayer(THEME.tiles, {
      attribution: THEME.attribution || '&copy; OpenStreetMap &copy; CARTO',
      maxZoom: 19
    }).addTo(map);
    layer = L.layerGroup().addTo(map);

    // The map has a fixed height, so it never gets stretched by the growing
    // transcript. A light invalidateSize on container resize (e.g. mobile
    // reflow) keeps tiles crisp without re-framing.
    var mapEl = document.getElementById('map');
    if (window.ResizeObserver) {
      new ResizeObserver(function () {
        if (!map) return;
        cancelAnimationFrame(resizeRaf);
        resizeRaf = requestAnimationFrame(function () { map.invalidateSize({ animate: false }); });
      }).observe(mapEl);
    }
  }

  // Build a rotated rectangular footprint (4 corners) around a scene centre.
  // w/h are ground extents in degrees-of-latitude equivalent; the longitude
  // delta is divided by cos(lat) so the drawn shape isn't Mercator-stretched.
  function footprintCorners(lat, lon, fp) {
    var hw = fp.w / 2, hh = fp.h / 2;
    var th = (fp.rot || 0) * Math.PI / 180;
    var cos = Math.cos(th), sin = Math.sin(th);
    var coslat = Math.max(Math.cos(lat * Math.PI / 180), 0.2);
    var local = [[-hw, -hh], [hw, -hh], [hw, hh], [-hw, hh]];
    return local.map(function (p) {
      var xr = p[0] * cos - p[1] * sin;
      var yr = p[0] * sin + p[1] * cos;
      return [lat + yr, lon + xr / coslat];
    });
  }

  function drawScene(run, s, opts) {
    if (!map) return;
    opts = opts || {};
    var color = (THEME.avail && THEME.avail[s.st]) || '#888';
    var fp = run.footprint || { w: 0.2, h: 0.24, rot: -10 };
    var full = opts.dim ? 0.32 : 1;               // prior scenes draw faint
    var poly = L.polygon(footprintCorners(s.lat, s.lon, fp), {
      color: color, weight: opts.dim ? 1 : 2, opacity: full,
      fillColor: color, fillOpacity: 0.12 * full, lineJoin: 'miter',
      dashArray: opts.dim ? '3 4' : null
    }).addTo(layer);
    if (REDUCED || opts.dim) return;
    // Fade the footprint in, with a brief outline flash on arrival.
    poly.setStyle({ opacity: 0, fillOpacity: 0 });
    var t0 = performance.now();
    (function fade(now) {
      var k = Math.min((now - t0) / 360, 1);
      poly.setStyle({ opacity: k, fillOpacity: 0.12 * k, weight: 2 + (1 - k) * 2 });
      if (k < 1) requestAnimationFrame(fade);
    })(t0);
  }

  // The map has a fixed height; the space below it holds capture-summary
  // insights the agent would read off the result — how many scenes, what share
  // is downloadable now, which platforms, the date window, and the sensor.
  var insEl = document.getElementById('map-insights');
  function resetInsights() {
    if (!insEl) return;
    insEl.innerHTML = '<div class="ins-idle">The agent\u2019s findings land here — coverage, how many scenes you can download now, and what they are — as the search comes back.</div>';
  }
  function ORDER() { return ['Ready', 'Archived', 'OnOrder', 'Priced']; }
  function labelFor(st) { return st === 'OnOrder' ? 'On order' : st; }
  function renderInsights(run, step) {
    if (!insEl) return;
    var scenes = step.scenes || [];
    var counts = {};
    scenes.forEach(function (s) { counts[s.st] = (counts[s.st] || 0) + 1; });
    // Prefer the run's full-result summary counts (over all matched scenes),
    // falling back to the plotted sample.
    var summaryCounts = {};
    (step.summary || []).forEach(function (p) {
      var n = parseInt(p[1], 10); if (!isNaN(n)) summaryCounts[p[0]] = n;
    });
    var total = step.total || scenes.length;
    var byState = {};
    ORDER().forEach(function (st) { byState[st] = summaryCounts[st] || 0; });
    var sumAll = ORDER().reduce(function (a, st) { return a + byState[st]; }, 0) || total;
    var ready = byState.Ready || 0;
    var openData = (byState.Ready || 0) + (byState.Archived || 0);

    // Availability bar segments.
    var bar = ORDER().filter(function (st) { return byState[st] > 0; }).map(function (st) {
      var pct = Math.round((byState[st] / sumAll) * 100);
      return '<span class="seg ' + st + '" style="width:' + pct + '%" title="' + labelFor(st) + ': ' + byState[st] + '"></span>';
    }).join('');
    var legend = ORDER().filter(function (st) { return byState[st] > 0; }).map(function (st) {
      return '<span class="ins-lg"><i class="' + st + '"></i>' + byState[st] + ' ' + labelFor(st) + '</span>';
    }).join('');

    // A plain-language takeaway on what you can actually pull now.
    var takeaway;
    if (ready > 0) {
      takeaway = '<b>' + ready + ' of ' + total + '</b> ready to download now' +
        (openData > ready ? ', ' + (openData - ready) + ' more open once requested' : '') + '.';
    } else if (openData > 0) {
      takeaway = '<b>0 staged</b> right now — ' + openData + ' are open data you request on the portal first.';
    } else {
      takeaway = '<b>All ' + total + '</b> are commercial (priced or on order) — none are free downloads.';
    }

    insEl.innerHTML =
      '<div class="ins-grid">' +
        '<div class="ins-stat"><div class="v">' + total + '</div><div class="k">scenes found</div></div>' +
        '<div class="ins-stat"><div class="v">' + ready + '</div><div class="k">ready now</div></div>' +
        '<div class="ins-stat"><div class="v">' + run.res + '</div><div class="k">resolution</div></div>' +
      '</div>' +
      '<div class="ins-bar-wrap"><div class="ins-bar-lbl">Availability</div>' +
        '<div class="ins-bar">' + bar + '</div>' +
        '<div class="ins-legend">' + legend + '</div>' +
      '</div>' +
      '<div class="ins-takeaway">' + takeaway + '</div>' +
      '<div class="ins-meta">' +
        '<div><span class="mk">Platforms</span><span class="mv">' + step.matched + '</span></div>' +
        '<div><span class="mk">Sensor</span><span class="mv">' + run.sensor + '</span></div>' +
        '<div><span class="mk">Window</span><span class="mv">' + run.window + '</span></div>' +
      '</div>';
  }

  function setMapForRun(run) {
    if (!map) return;
    layer.clearLayers();
    resetInsights();
    map.invalidateSize();
    var b = run.bbox;
    var bounds = [[b.miny, b.minx], [b.maxy, b.maxx]];
    currentBounds = bounds;  // remembered so the resize observer can re-frame
    map.fitBounds(bounds, { padding: [30, 30], maxZoom: 9, animate: !REDUCED });
    // The search area of interest — neutral, so scene outlines carry the colour.
    L.rectangle(bounds, {
      color: THEME.bbox || '#e0602c', weight: 1.4, dashArray: '5 5',
      fill: false
    }).addTo(layer);
  }

  /* ---- transcript ---- */
  var T = document.getElementById('transcript');
  var promptsEl = document.getElementById('prompts');
  var mapLabel = document.getElementById('map-label');
  var current = 0, timers = [];
  function clearTimers() { timers.forEach(clearTimeout); timers = []; }
  function at(ms, fn) { timers.push(setTimeout(fn, REDUCED ? 0 : ms)); }
  function argLine(a) {
    return a.map(function (p) { return '<span class="k">' + p[0] + ':</span> <span class="' + p[2] + '">' + p[1] + '</span>'; })
            .join('<span class="arw">, </span>');
  }
  function pill(st) {
    var lbl = st === 'OnOrder' ? 'On order' : st;
    return '<span class="pill ' + st + '">' + lbl + '</span>';
  }

  function stepDuration(step) {
    if (step.type === 'agent') return 900;
    if (step.type === 'answer') return 600;
    if (step.type === 'download') return 3200;
    if (step.type === 'cart') return 1500;
    if (step.type === 'refresh') return (step.newScenes ? step.newScenes.length : 0) * 300 + 1400;
    if (step.type === 'tool') return step.scenes ? step.scenes.length * 280 + 750 : 1100;
    return 800;
  }

  function scrollChat() {
    if (!T || REDUCED) return;
    T.scrollTop = T.scrollHeight;
  }

  function renderStep(run, step) {
    var m = document.createElement('div'); m.className = 'msg agent';
    if (step.type === 'agent') {
      m.innerHTML = '<div class="who">Agent</div><div class="txt">' + step.txt + '</div>';
      T.appendChild(m); scrollChat(); return;
    }
    if (step.type === 'answer') {
      m.innerHTML = '<div class="who">Agent · answer</div><div class="answer">' + step.html + '</div>';
      T.appendChild(m); scrollChat(); return;
    }
    if (step.type === 'download') { renderDownload(m, step); return; }
    if (step.type === 'cart') { renderCart(m, step); return; }
    if (step.type === 'refresh') { renderRefresh(run, m, step); return; }
    // tool call
    var tc = document.createElement('div'); tc.className = 'toolcall';
    tc.innerHTML = '<div class="tc-h"><span class="fn">' + step.fn + '()</span>' +
      '<span class="st"><span class="led"></span>calling</span></div>' +
      '<div class="tc-b"><span class="k">args</span> · ' + argLine(step.args) + '</div>';
    m.className = 'msg agent tool';
    m.innerHTML = '<div class="who">Agent · tool call</div>';
    m.appendChild(tc); T.appendChild(m); scrollChat();

    at(REDUCED ? 0 : 700, function () {
      tc.classList.add('done');
      tc.querySelector('.st').innerHTML = '<span class="led"></span>done';
      var b = tc.querySelector('.tc-b');
      if (step.result) {
        b.innerHTML += '<div class="scene-rows"><span class="k">returns</span><br>' + step.result.join('<br>') + '</div>';
      }
      if (step.scenes) {
        setMapForRun(run);
        var h = document.createElement('div'); h.className = 'scene-rows';
        h.innerHTML = '<span class="k">token</span> <span class="s">' + step.token + '</span><br>' +
          '<span class="k">matched</span> <span class="s">' + step.matched + '</span> &nbsp;·&nbsp; ' +
          '<span class="k">total</span> <span class="n">' + step.total + '</span>';
        b.appendChild(h);
        step.scenes.forEach(function (s, i) {
          at(i * 280, function () {
            var row = document.createElement('div'); row.className = 'scene-row';
            row.innerHTML = '<span class="id">' + s.id + '</span><span class="dop">' + s.dop + '</span>' + pill(s.st);
            h.appendChild(row); drawScene(run, s);
          });
        });
        at(step.scenes.length * 280 + 120, function () {
          var sm = document.createElement('div'); sm.className = 'summary';
          sm.innerHTML = step.summary.map(function (p) { return '<span class="pill ' + p[0] + '">' + p[1] + '</span>'; }).join('');
          b.appendChild(sm);
          renderInsights(run, step);
        });
      }
    });
  }

  // A download step: the tool returns a job_id, then a background job streams
  // progress. Animate a progress bar with MB and rate, then settle to complete.
  function renderDownload(m, step) {
    var tc = document.createElement('div'); tc.className = 'toolcall dl';
    tc.innerHTML = '<div class="tc-h"><span class="fn">' + step.fn + '()</span>' +
      '<span class="st"><span class="led"></span>starting</span></div>' +
      '<div class="tc-b"><span class="k">args</span> · ' + argLine(step.args) + '</div>';
    m.className = 'msg agent tool';
    m.innerHTML = '<div class="who">Agent · download</div>';
    m.appendChild(tc); T.appendChild(m); scrollChat();

    at(REDUCED ? 0 : 650, function () {
      var b = tc.querySelector('.tc-b');
      tc.querySelector('.st').innerHTML = '<span class="led"></span>downloading';
      if (step.result) {
        b.innerHTML += '<div class="scene-rows"><span class="k">job</span><br>' + step.result.join('<br>') + '</div>';
      }
      var prog = document.createElement('div'); prog.className = 'dlprog';
      prog.innerHTML =
        '<div class="dl-top"><span class="dl-files">' + step.files + ' scenes · download_status</span><span class="dl-pct">0%</span></div>' +
        '<div class="dl-bar"><span class="dl-fill"></span></div>' +
        '<div class="dl-meta"><span class="dl-mb">0 / ' + step.totalMb + ' MB</span><span class="dl-rate">— MB/s</span></div>';
      b.appendChild(prog); scrollChat();
      var fill = prog.querySelector('.dl-fill'), pct = prog.querySelector('.dl-pct'),
          mb = prog.querySelector('.dl-mb'), rate = prog.querySelector('.dl-rate');
      if (REDUCED) {
        fill.style.width = '100%'; pct.textContent = '100%';
        mb.textContent = step.totalMb + ' / ' + step.totalMb + ' MB'; rate.textContent = 'done';
        tc.classList.add('done'); tc.querySelector('.st').innerHTML = '<span class="led"></span>completed';
        return;
      }
      var t0 = performance.now(), dur = 2200;
      (function tick(now) {
        var k = Math.min((now - t0) / dur, 1);
        var e = 1 - Math.pow(1 - k, 2);           // ease-out
        fill.style.width = (e * 100).toFixed(0) + '%';
        pct.textContent = (e * 100).toFixed(0) + '%';
        mb.textContent = (e * step.totalMb).toFixed(0) + ' / ' + step.totalMb + ' MB';
        rate.textContent = (28 + Math.sin(now / 90) * 6).toFixed(1) + ' MB/s';
        if (k < 1) { requestAnimationFrame(tick); }
        else {
          rate.textContent = 'verified';
          tc.classList.add('done');
          tc.querySelector('.st').innerHTML = '<span class="led"></span>completed';
          scrollChat();
        }
      })(t0);
    });
  }

  // A cart step: stage the saved query, routing each scene to the cart its
  // access type needs. Show the routing result as it lands.
  function renderCart(m, step) {
    var tc = document.createElement('div'); tc.className = 'toolcall cart';
    tc.innerHTML = '<div class="tc-h"><span class="fn">' + step.fn + '()</span>' +
      '<span class="st"><span class="led"></span>staging</span></div>' +
      '<div class="tc-b"><span class="k">args</span> · ' + argLine(step.args) + '</div>';
    m.className = 'msg agent tool';
    m.innerHTML = '<div class="who">Agent · cart</div>';
    m.appendChild(tc); T.appendChild(m); scrollChat();

    at(REDUCED ? 0 : 800, function () {
      tc.classList.add('done');
      tc.querySelector('.st').innerHTML = '<span class="led"></span>staged';
      var b = tc.querySelector('.tc-b');
      if (step.result) {
        b.innerHTML += '<div class="scene-rows"><span class="k">returns</span><br>' + step.result.join('<br>') + '</div>';
      }
      scrollChat();
    });
  }

  // A refresh step: re-check a saved query for scenes published since. Prior
  // scenes are drawn faint on the map; genuinely new ones plot highlighted and
  // stream into the transcript, so "what changed" is obvious.
  function renderRefresh(run, m, step) {
    var tc = document.createElement('div'); tc.className = 'toolcall refresh';
    tc.innerHTML = '<div class="tc-h"><span class="fn">' + step.fn + '</span>' +
      '<span class="st"><span class="led"></span>checking</span></div>' +
      '<div class="tc-b"><span class="k">args</span> · ' + argLine(step.args) + '</div>';
    m.className = 'msg agent tool';
    m.innerHTML = '<div class="who">Agent · refresh</div>';
    m.appendChild(tc); T.appendChild(m); scrollChat();

    // Seed the map: prior scenes faint, so new ones stand out against them.
    setMapForRun(run);
    (step.priorScenes || []).forEach(function (s) { drawScene(run, s, { dim: true }); });

    at(REDUCED ? 0 : 750, function () {
      tc.classList.add('done');
      tc.querySelector('.st').innerHTML = '<span class="led"></span>' + step.newScenes.length + ' new';
      var b = tc.querySelector('.tc-b');
      if (step.result) {
        b.innerHTML += '<div class="scene-rows"><span class="k">returns</span><br>' + step.result.join('<br>') + '</div>';
      }
      var h = document.createElement('div'); h.className = 'scene-rows';
      h.innerHTML = '<span class="k">new scenes</span> <span class="s">since last check</span>';
      b.appendChild(h);
      step.newScenes.forEach(function (s, i) {
        at(i * 300, function () {
          var row = document.createElement('div'); row.className = 'scene-row';
          row.innerHTML = '<span class="id"><span class="newdot"></span>' + s.id + '</span><span class="dop">' + s.dop + '</span>' + pill(s.st);
          h.appendChild(row); drawScene(run, s); scrollChat();
        });
      });
      at(step.newScenes.length * 300 + 120, function () { renderInsights(run, step); });
    });
  }

  function renderRun(idx) {
    clearTimers(); current = idx;
    var run = window.RUNS[idx];
    T.innerHTML = '';
    if (mapLabel) mapLabel.textContent = run.place;
    setMapForRun(run);
    Array.prototype.forEach.call(promptsEl.children, function (c, i) { c.classList.toggle('active', i === idx); });
    var u = document.createElement('div'); u.className = 'msg user';
    u.innerHTML = '<div class="who">You</div><div class="bub">' + run.prompt + '</div>';
    T.appendChild(u);
    var delay = 420;
    run.steps.forEach(function (step) { at(delay, function () { renderStep(run, step); }); delay += stepDuration(step); });
  }

  /* ---- build controls ---- */
  window.RUNS.forEach(function (r, i) {
    var c = document.createElement('button'); c.className = 'chip'; c.textContent = r.chip;
    c.onclick = function () { renderRun(i); };
    promptsEl.appendChild(c);
  });
  var replay = document.getElementById('replay');
  if (replay) replay.onclick = function () { renderRun(current); };

  /* ---- client configurator ---- */
  var tabsEl = document.getElementById('cfg-tabs'), bodyEl = document.getElementById('cfg-body');
  if (tabsEl && bodyEl) {
    window.CLIENTS.forEach(function (c, i) {
      var t = document.createElement('div'); t.className = 'cfg-tab' + (i === 0 ? ' active' : ''); t.textContent = c.name;
      t.onclick = function () {
        Array.prototype.forEach.call(tabsEl.children, function (x) { x.classList.remove('active'); });
        Array.prototype.forEach.call(bodyEl.children, function (x) { x.classList.remove('active'); });
        t.classList.add('active'); bodyEl.children[i].classList.add('active');
      };
      tabsEl.appendChild(t);
      var plain = c.code.replace(/<[^>]+>/g, '').replace(/"/g, '&quot;');
      var p = document.createElement('div'); p.className = 'cfg-panel' + (i === 0 ? ' active' : '');
      p.innerHTML = '<p class="desc">' + c.desc + '</p>' +
        '<div class="codewrap"><button class="copy" data-copy="' + plain + '">Copy</button><pre>' + c.code + '</pre></div>' +
        '<div class="cfg-note"><span class="b">note</span><span>' + c.note + '</span></div>';
      bodyEl.appendChild(p);
    });
  }

  /* ---- boot ---- */
  function startFlow() {
    // Optional ?flow=N deep-link so a specific flow can be opened/linked directly.
    var n = 0, mq = (location.search.match(/[?&]flow=(\d+)/));
    if (mq) { var i = parseInt(mq[1], 10) - 1; if (i >= 0 && i < window.RUNS.length) n = i; }
    renderRun(n);
  }
  function boot() {
    initMap();
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) { if (e.isIntersecting) { startFlow(); io.disconnect(); } });
    }, { threshold: 0.2 });
    io.observe(document.querySelector('.sim'));
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
})();
