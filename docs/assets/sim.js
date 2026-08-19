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
  var map = null, layer = null;
  function initMap() {
    if (!window.L || !document.getElementById('map')) return;
    map = L.map('map', { zoomControl: false, attributionControl: true, scrollWheelZoom: false, dragging: true });
    map.setView([22, 82], 4);
    L.tileLayer(THEME.tiles, {
      attribution: THEME.attribution || '&copy; OpenStreetMap &copy; CARTO',
      subdomains: 'abcd', maxZoom: 18
    }).addTo(map);
    layer = L.layerGroup().addTo(map);
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

  function drawScene(run, s) {
    if (!map) return;
    var color = (THEME.avail && THEME.avail[s.st]) || '#888';
    var fp = run.footprint || { w: 0.2, h: 0.24, rot: -10 };
    var poly = L.polygon(footprintCorners(s.lat, s.lon, fp), {
      color: color, weight: 2, opacity: 1,
      fillColor: color, fillOpacity: 0.12, lineJoin: 'miter'
    }).addTo(layer);
    if (REDUCED) return;
    // Fade the footprint in, with a brief outline flash on arrival.
    poly.setStyle({ opacity: 0, fillOpacity: 0 });
    var t0 = performance.now();
    (function fade(now) {
      var k = Math.min((now - t0) / 360, 1);
      poly.setStyle({ opacity: k, fillOpacity: 0.12 * k, weight: 2 + (1 - k) * 2 });
      if (k < 1) requestAnimationFrame(fade);
    })(t0);
  }

  function setMapForRun(run) {
    if (!map) return;
    layer.clearLayers();
    map.invalidateSize();
    var b = run.bbox;
    var bounds = [[b.miny, b.minx], [b.maxy, b.maxx]];
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
    if (step.type === 'tool') return step.scenes ? step.scenes.length * 280 + 750 : 1100;
    return 800;
  }

  function renderStep(run, step) {
    var m = document.createElement('div'); m.className = 'msg agent';
    if (step.type === 'agent') {
      m.innerHTML = '<div class="who">Agent</div><div class="txt">' + step.txt + '</div>';
      T.appendChild(m); return;
    }
    if (step.type === 'answer') {
      m.innerHTML = '<div class="who">Agent · answer</div><div class="answer">' + step.html + '</div>';
      T.appendChild(m); return;
    }
    // tool call
    var tc = document.createElement('div'); tc.className = 'toolcall';
    tc.innerHTML = '<div class="tc-h"><span class="fn">' + step.fn + '()</span>' +
      '<span class="st"><span class="led"></span>calling</span></div>' +
      '<div class="tc-b"><span class="k">args</span> · ' + argLine(step.args) + '</div>';
    m.innerHTML = '<div class="who">Agent · tool call</div>';
    m.appendChild(tc); T.appendChild(m);

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
        });
      }
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
    u.innerHTML = '<div class="who">You · prompt</div><div class="txt">' + run.prompt + '</div>';
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
  function boot() {
    initMap();
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) { if (e.isIntersecting) { renderRun(0); io.disconnect(); } });
    }, { threshold: 0.2 });
    io.observe(document.querySelector('.sim'));
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
})();
