/* IA-1 boundary viewer. Full retained polygons; no basemap or external requests. */
(() => {
  'use strict';
  const NS = 'http://www.w3.org/2000/svg';
  function el(tag, text) { const n = document.createElement(tag); if (text != null) n.textContent = text; return n; }
  function svg(polygons, label) {
    const points = polygons.flat(2);
    const xs = points.map(p => p[0] * Math.cos(24 * Math.PI / 180));
    const ys = points.map(p => -p[1]);
    const minX = Math.min(...xs), maxX = Math.max(...xs), minY = Math.min(...ys), maxY = Math.max(...ys);
    const width = Math.max(maxX - minX, 0.001), height = Math.max(maxY - minY, 0.001);
    const pad = Math.max(width, height) * 0.06;
    const node = document.createElementNS(NS, 'svg');
    node.setAttribute('viewBox', `${minX-pad} ${minY-pad} ${width+2*pad} ${height+2*pad}`);
    node.setAttribute('role', 'img'); node.setAttribute('aria-label', label);
    node.setAttribute('preserveAspectRatio', 'xMidYMid meet');
    node.style.display = 'block'; node.style.width = '100%'; node.style.height = 'auto'; node.style.maxHeight = '320px';
    const path = document.createElementNS(NS, 'path');
    path.setAttribute('d', polygons.map(poly => poly.map(ring => ring.map((p, i) => `${i ? 'L' : 'M'}${p[0]*Math.cos(24*Math.PI/180)},${-p[1]}`).join(' ') + ' Z').join(' ')).join(' '));
    path.setAttribute('fill', '#b9d8cb'); path.setAttribute('fill-rule', 'evenodd');
    path.setAttribute('stroke', '#174e46'); path.setAttribute('stroke-width', '1.2');
    path.setAttribute('vector-effect', 'non-scaling-stroke');
    node.append(path); return node;
  }
  function mount(container) {
    let sequence = 0;
    const update = async identity => {
      const current = ++sequence;
      container.replaceChildren(el('p', 'Loading boundary…'));
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
        const title = el('h3', `${data.chamber === 'house' ? 'House' : 'Senate'} ${data.code} boundary`);
        const meta = el('p', `Displayed session ${data.session}; statistics use 2024 boundaries. Source: ${data.source_id}, SHA-256 ${data.source_sha256}. Compatibility: ${data.compatibility.equal ? 'matching' : 'not confirmed matching'} by ${data.compatibility.method} (${data.compatibility.version}). Boundary display only; not a service area or distance measure.`);
        const overviewTitle = el('h4','Entire district overview');
        const overview = svg(polys, `Entire district, ${polys.length} components`);
        const label = el('label', 'Focus a component ');
        const select = el('select'); select.setAttribute('aria-label','Boundary component');
        polys.forEach((_,i) => { const o=el('option',`Component ${i+1} of ${polys.length}`); o.value=String(i); select.append(o); });
        label.append(select);
        const detailTitle = el('h4'); const detail = el('div'); const bounds = el('p');
        function show() {
          const i = Number(select.value), component=polys[i], pts=component.flat();
          detailTitle.textContent = `Component ${i+1} of ${polys.length} — detail (different scale)`;
          detail.replaceChildren(svg([component], detailTitle.textContent));
          const lon=pts.map(p=>p[0]), lat=pts.map(p=>p[1]);
          bounds.textContent = `Component bounds: longitude ${Math.min(...lon).toFixed(4)} to ${Math.max(...lon).toFixed(4)}; latitude ${Math.min(...lat).toFixed(4)} to ${Math.max(...lat).toFixed(4)}. All ${polys.length} components are available in the selector.`;
        }
        select.addEventListener('change',show); show();
        container.replaceChildren(title,meta,overviewTitle,overview,label,detailTitle,detail,bounds);
      } catch (err) {
        if (current !== sequence) return;
        const message=el('p','Boundary map unavailable. Other investigation evidence remains available; try again.');
        message.setAttribute('role','status'); container.replaceChildren(message);
      }
    };
    return {update, destroy() { sequence++; container.replaceChildren(); }};
  }
  window.IA1Map = {mount};
})();
