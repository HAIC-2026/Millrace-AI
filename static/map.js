/* IA-1 boundary viewer. Full retained polygons; no basemap or external requests.
   Every district part is drawn. Parts are numbered on the overview and the chosen part is outlined;
   an enlarged view appears only when a district has more than one part. */
(() => {
  'use strict';
  const NS = 'http://www.w3.org/2000/svg';
  const COLORS = ['#eff3c6', '#c8df9b', '#86bd82', '#428b6c', '#175548'];
  const BINS = ['0–<5%', '5–<10%', '10–<15%', '15–<20%', '20% or more'];
  const NEUTRAL = '#e4e6e3';
  function indicatorState(data, identity) {
    const f = data.indicator;
    if (!f || ['snapshot_id','chamber','code','session'].some(k => f[k] !== identity[k]) || f.metric_id !== 'poverty_rate_all_people') return {available:false, reason:'Indicator unavailable for this boundary and evidence.'};
    if (identity.session === 2026 && (!data.compatibility || data.compatibility.equal !== true)) return {available:false, fact:f, reason:'The 2026 boundary is not confirmed exactly equal to the 2024 statistical boundary; it is not shaded.'};
    if (f.annotation || typeof f.estimate !== 'number' || !Number.isFinite(f.estimate) || f.estimate < 0) return {available:false, reason:'The estimate is unavailable or annotated; it is not treated as zero.'};
    const index = f.estimate < 5 ? 0 : f.estimate < 10 ? 1 : f.estimate < 15 ? 2 : f.estimate < 20 ? 3 : 4;
    return {available:true, index, label:BINS[index], color:COLORS[index], fact:f};
  }
  if (typeof module === 'object' && module.exports) module.exports = {indicatorState};
  function el(tag, text, cls) { const n = document.createElement(tag); if (text != null) n.textContent = text; if (cls) n.className = cls; return n; }
  function svgEl(tag, attrs) { const n = document.createElementNS(NS, tag); Object.keys(attrs || {}).forEach(k => n.setAttribute(k, attrs[k])); return n; }
  const K = Math.cos(24 * Math.PI / 180);
  const project = p => [p[0] * K, -p[1]];
  function bounds(polygons) {
    const pts = polygons.flat(2).map(project);
    const xs = pts.map(p => p[0]), ys = pts.map(p => p[1]);
    return {minX: Math.min(...xs), maxX: Math.max(...xs), minY: Math.min(...ys), maxY: Math.max(...ys)};
  }
  const pathData = polygon => polygon.map(ring => ring.map((p, i) => { const q = project(p); return `${i ? 'L' : 'M'}${q[0]},${q[1]}`; }).join(' ') + ' Z').join(' ');
  // polygons: list of district parts (each a list of rings). selected: index to outline, or -1.
  function drawing(polygons, label, fill, selected, numbered, maxHeight) {
    const b = bounds(polygons);
    const width = Math.max(b.maxX - b.minX, 0.001), height = Math.max(b.maxY - b.minY, 0.001);
    const span = Math.max(width, height), pad = span * (numbered ? 0.08 : 0.05);
    const node = svgEl('svg', {viewBox: `${b.minX - pad} ${b.minY - pad} ${width + 2 * pad} ${height + 2 * pad}`, role: 'img', 'aria-label': label, preserveAspectRatio: 'xMidYMid meet'});
    node.style.display = 'block'; node.style.width = '100%'; node.style.height = 'auto'; node.style.maxHeight = maxHeight;
    polygons.forEach((poly, i) => {
      const on = i === selected;
      node.append(svgEl('path', {d: pathData(poly), fill: fill || NEUTRAL, 'fill-rule': 'evenodd', stroke: on ? '#0b2a5b' : '#174e46', 'stroke-width': on ? '3' : '1.2', 'vector-effect': 'non-scaling-stroke'}));
    });
    if (numbered) {
      const r = span * 0.028, size = span * 0.034;
      polygons.forEach((poly, i) => {
        const pb = bounds([poly]), cx = (pb.minX + pb.maxX) / 2, cy = (pb.minY + pb.maxY) / 2, on = i === selected;
        const g = svgEl('g', {'aria-hidden': 'true'});
        g.append(svgEl('circle', {cx, cy, r: on ? r * 1.35 : r, fill: on ? '#0b2a5b' : '#ffffff', stroke: on ? '#ffffff' : '#0b2a5b', 'stroke-width': on ? '2' : '1.2', 'vector-effect': 'non-scaling-stroke'}));
        const t = svgEl('text', {x: cx, y: cy, 'text-anchor': 'middle', 'dominant-baseline': 'central', 'font-size': on ? size * 1.2 : size, 'font-weight': '700', fill: on ? '#ffffff' : '#0b2a5b', 'font-family': 'system-ui, sans-serif'});
        t.textContent = String(i + 1); g.append(t); node.append(g);
      });
    }
    return node;
  }
  function legend(indicator) {
    const list = el('ul', null, 'map-legend');
    BINS.forEach((bin, i) => {
      const on = indicator.available && indicator.index === i;
      const li = el('li', null, on ? 'is-current' : '');
      const sw = el('span', null, 'swatch'); sw.style.background = COLORS[i]; sw.setAttribute('aria-hidden', 'true');
      li.append(sw, el('span', bin + (on ? ' — this district' : '')));
      list.append(li);
    });
    const li = el('li', null, indicator.available ? '' : 'is-current');
    const sw = el('span', null, 'swatch'); sw.style.background = NEUTRAL; sw.setAttribute('aria-hidden', 'true');
    li.append(sw, el('span', 'Not shaded' + (indicator.available ? '' : ' — this district')));
    list.append(li);
    return list;
  }
  function mount(container, options) {
    const opts = options || {};
    const report = text => { if (typeof opts.onSummary === 'function') opts.onSummary(text); };
    let sequence = 0;
    const update = async identity => {
      const current = ++sequence;
      const name = `${identity.chamber === 'house' ? 'House' : 'Senate'} ${identity.code}`;
      // The previous district's drawing is removed at once, so it never shows under a new district.
      const loading = el('p', `Loading the ${name} boundary…`, 'loading'); loading.setAttribute('role', 'status');
      container.replaceChildren(loading); report('loading…');
      try {
        const query = new URLSearchParams({snapshot_id: identity.snapshot_id, chamber: identity.chamber, code: identity.code, session: String(identity.session)});
        const response = await fetch(`/api/geometry?${query}`, {credentials:'same-origin'});
        if (!response.ok) throw new Error('Boundary unavailable');
        const data = await response.json();
        if (current !== sequence) return;
        if (data.snapshot_id !== identity.snapshot_id || data.chamber !== identity.chamber || data.code !== identity.code || data.session !== identity.session) throw new Error('Boundary identity mismatch');
        const geometry = data.feature.geometry;
        const polys = geometry.type === 'Polygon' ? [geometry.coordinates] : geometry.coordinates;
        if (!Array.isArray(polys) || polys.length !== data.component_count) throw new Error('Boundary components unavailable');
        const indicator = indicatorState(data, identity), n = polys.length, multi = n > 1;
        const title = el('h3', `${name} boundary, ${data.session} session`, 'map-title');
        const compat = data.session === 2024 ? '' : data.compatibility && data.compatibility.equal ? ' This boundary matches the 2024 statistical boundary.' : ' This boundary is not confirmed to match the 2024 statistical boundary.';
        const parts = el('p', (multi ? `${n} separate parts, kept in the recorded order. Numbered circles mark each part; parts too small to see at this scale appear only as circles. Choose a part below to see its shape.` : 'One continuous part.') + compat + ' Boundary display only; not a service area.', 'hint');
        const factText = el('p', null, 'map-fact'); factText.id = 'ia-indicator-text';
        let shadeNote = '';
        if (indicator.fact && typeof indicator.fact.estimate === 'number' && Number.isFinite(indicator.fact.estimate) && !indicator.fact.annotation) {
          const f = indicator.fact, period = f.period || {};
          const moe = typeof f.margin_of_error === 'number' && Number.isFinite(f.margin_of_error) && !f.moe_annotation ? `±${f.margin_of_error} percentage points` : 'unavailable';
          factText.textContent = `Shading: poverty rate, all people (all ages), ${f.estimate}% (90% margin of error ${moe}); ACS ${period.start_year || 2020}–${period.end_year || 2024} 5-year; ${f.publisher || 'U.S. Census Bureau'}. Universe: ${f.universe}. This is not the age 65 and over poverty rate shown in older-adult findings.`;
          shadeNote = indicator.available ? indicator.label : 'not shaded';
        } else { factText.textContent = 'Shading: not shown.'; shadeNote = 'not shaded'; }
        const limit = el('p', (indicator.available ? '' : indicator.reason + ' ') + 'Bands are illustrative display intervals, not thresholds, rankings or statistical tests.', 'map-limit');
        const overviewBox = el('div', null, 'map-overview');
        const detailBox = el('div', null, 'map-detail');
        const where = el('p', null, 'hint');
        let select = null;
        function show() {
          const i = select ? Number(select.value) : 0;
          overviewBox.replaceChildren(drawing(polys, `${name} boundary, ${n} part${multi ? 's' : ''}` + (multi ? `; part ${i + 1} outlined` : ''), indicator.color, multi ? i : -1, multi, multi ? '220px' : '260px'));
          if (multi) {
            detailBox.replaceChildren(el('h4', `Part ${i + 1} of ${n}, enlarged (different scale)`, 'map-subtitle'), drawing([polys[i]], `Part ${i + 1} of ${n}, enlarged`, indicator.color, -1, false, '200px'));
          }
          const pts = polys[i].flat(), lon = pts.map(p => p[0]), lat = pts.map(p => p[1]);
          where.textContent = `${multi ? `Part ${i + 1} of ${n}` : 'The district'} lies between longitude ${Math.min(...lon).toFixed(4)} and ${Math.max(...lon).toFixed(4)}, latitude ${Math.min(...lat).toFixed(4)} and ${Math.max(...lat).toFixed(4)}.`;
        }
        const nodes = [title, parts, overviewBox];
        if (multi) {
          const field = el('div', null, 'field');
          const label = el('label', 'Show part'); label.htmlFor = 'ia-map-part';
          select = el('select'); select.id = 'ia-map-part';
          polys.forEach((_, i) => { const o = el('option', `Part ${i + 1} of ${n}`); o.value = String(i); select.append(o); });
          select.addEventListener('change', show);
          field.append(label, select); nodes.push(field, detailBox);
        }
        nodes.push(where, legend(indicator), factText, limit);
        show();
        container.replaceChildren(...nodes);
        report(`${name}, ${data.session} session boundary (display only) · ${n} part${multi ? 's' : ''} · shading: poverty rate for all ages (not the 65 and over rate): ${shadeNote}`);
      } catch (err) {
        if (current !== sequence) return;
        const box = el('div', null, 'notice notice-unsupported');
        const message = el('p', `The ${name} boundary map is unavailable. The district description below and all evidence remain available.`);
        message.setAttribute('role', 'status');
        const retry = el('button', 'Try the map again', 'btn btn-small'); retry.type = 'button';
        retry.addEventListener('click', () => update(identity));
        box.append(message, retry); container.replaceChildren(box); report('unavailable');
      }
    };
    return {update, destroy() { sequence++; container.replaceChildren(); }};
  }
  if (typeof window !== 'undefined') window.IA1Map = {mount};
})();
