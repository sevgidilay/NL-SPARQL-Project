"""
viz.py — PyVis graph builder extracted from app.py.

Pure functions: no Streamlit imports; no side effects.
"""
from __future__ import annotations

import re

_ENTITY_RE = re.compile(r'^(?:https?://|Q\d+$)')

_LIGHT_PALETTE = ["#0F4C81", "#2E7D32", "#6A1B9A", "#BF360C", "#00695C"]
_DARK_PALETTE  = ["#5BA4D4", "#66BB6A", "#AB47BC", "#FF7043", "#26A69A"]

_PATH_COLOR   = "#FFD700"
_PATH_BORDER  = "#FFA000"
_CENTER_LIGHT = "#D4380D"
_CENTER_DARK  = "#E76F51"


def detect_label_uri_columns(rows: list) -> tuple:
    """Classify columns as URI or label columns.

    Returns:
        uri_cols  (list[str]) — columns whose values look like URIs
        label_map (dict[str, str]) — maps each URI col to its companion label col
    """
    if not rows:
        return [], {}

    keys = list(rows[0].keys())
    label_map: dict[str, str] = {}
    label_cols: set[str] = set()

    for k in keys:
        if k.endswith("Label"):
            label_map[k[:-5]] = k
            label_cols.add(k)

    sample = rows[:10]
    for k in keys:
        if k in label_cols:
            continue
        vals = [str(r.get(k, "")) for r in sample if r.get(k)]
        if vals and not any(_ENTITY_RE.match(v) for v in vals):
            paired = next(
                (u for u in keys
                 if u not in label_cols and u != k and u not in label_map),
                None,
            )
            if paired:
                label_map[paired] = k
            label_cols.add(k)

    uri_cols = [k for k in keys if k not in label_cols]
    return uri_cols, label_map


def _humanize_var_name(value: str) -> str:
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", str(value or ""))
    text = re.sub(r"[_-]+", " ", text).strip()
    return text.title() or "Entity"


def _scale_size(degree: int, min_deg: int, max_deg: int,
                base: float = 14, top: float = 36) -> float:
    if max_deg == min_deg:
        return base
    return base + (degree - min_deg) / (max_deg - min_deg) * (top - base)


def _inject_enhancements(html: str, accent: str = "#7C5CFC",
                         show_physics: bool = False) -> str:
    """Inject search/highlight overlay, zoom-to-fit, and optional physics sliders."""
    physics_panel = ""
    if show_physics:
        physics_panel = f"""
    // Physics controls panel
    var physPanel = document.createElement('div');
    physPanel.style.cssText = [
      'position:absolute','bottom:10px','right:10px','z-index:999',
      'background:rgba(255,255,255,0.93)','border:1.5px solid {accent}',
      'border-radius:10px','padding:10px 14px','font-size:12px',
      'color:#2D2640','min-width:180px','box-shadow:0 2px 8px rgba(124,92,252,0.15)'
    ].join(';');
    physPanel.innerHTML = `
      <div style="font-weight:600;margin-bottom:6px;color:{accent}">Physics</div>
      <label>Repulsion
        <input type="range" id="ph-grav" min="-200" max="-10" value="-60"
          style="width:100%;accent-color:{accent}">
      </label>
      <label style="margin-top:4px;display:block">Spring length
        <input type="range" id="ph-spring" min="50" max="400" value="120"
          style="width:100%;accent-color:{accent}">
      </label>
      <button id="ph-stabilize" style="margin-top:6px;width:100%;padding:4px;
        background:{accent};color:#fff;border:none;border-radius:6px;cursor:pointer;
        font-size:11px">Stabilize</button>
    `;
    container.appendChild(physPanel);
    document.getElementById('ph-grav').addEventListener('input', function() {{
      network.setOptions({{physics:{{forceAtlas2Based:{{gravitationalConstant: +this.value}}}}}});
    }});
    document.getElementById('ph-spring').addEventListener('input', function() {{
      network.setOptions({{physics:{{forceAtlas2Based:{{springLength: +this.value}}}}}});
    }});
    document.getElementById('ph-stabilize').addEventListener('click', function() {{
      network.stabilize(100);
    }});
"""

    js = f"""
<style>
#graph-search-wrap {{
  position: absolute;
  top: 10px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 999;
  display: flex;
  gap: 6px;
  align-items: center;
}}
#graph-search {{
  padding: 6px 14px;
  border: 1.5px solid {accent};
  border-radius: 20px;
  font-size: 13px;
  width: 210px;
  background: rgba(255,255,255,0.93);
  color: #2D2640;
  outline: none;
  box-shadow: 0 2px 8px rgba(124,92,252,0.18);
}}
#graph-search::placeholder {{ color: #9B93AD; }}
#graph-search-clear {{
  padding: 5px 11px;
  border: 1.5px solid {accent};
  border-radius: 20px;
  font-size: 12px;
  background: {accent};
  color: #fff;
  cursor: pointer;
  display: none;
}}
</style>
<script>
(function() {{
  var _poll = setInterval(function() {{
    if (typeof network === 'undefined' || !network) return;
    clearInterval(_poll);

    network.once('stabilizationIterationsDone', function() {{
      network.fit({{ animation: {{ duration: 700, easingFunction: 'easeInOutQuad' }} }});
    }});
    setTimeout(function() {{
      network.fit({{ animation: {{ duration: 700, easingFunction: 'easeInOutQuad' }} }});
    }}, 400);

    var container = document.getElementById('mynetwork');
    container.style.position = 'relative';

    var wrap = document.createElement('div');
    wrap.id = 'graph-search-wrap';

    var inp = document.createElement('input');
    inp.type = 'text';
    inp.id = 'graph-search';
    inp.placeholder = 'Search nodes…';

    var btn = document.createElement('button');
    btn.id = 'graph-search-clear';
    btn.textContent = 'Clear';

    wrap.appendChild(inp);
    wrap.appendChild(btn);
    container.appendChild(wrap);

    var origColors = {{}};
    nodes.getIds().forEach(function(id) {{
      var n = nodes.get(id);
      origColors[id] = {{ color: n.color, borderWidth: n.borderWidth || 1 }};
    }});

    function applySearch(q) {{
      var updates = [];
      nodes.getIds().forEach(function(id) {{
        var node = nodes.get(id);
        var lbl   = (node.label || '').toLowerCase();
        var title = (typeof node.title === 'string' ? node.title : '').toLowerCase();
        if (!q) {{
          updates.push({{ id: id, color: origColors[id].color,
                          opacity: 1.0, borderWidth: origColors[id].borderWidth }});
        }} else if (lbl.includes(q) || title.includes(q)) {{
          updates.push({{ id: id,
                          color: {{ background: '{accent}', border: '#5A3DE0',
                                    highlight: {{ background: '{accent}', border: '#3D1F99' }} }},
                          opacity: 1.0, borderWidth: 3 }});
        }} else {{
          updates.push({{ id: id, opacity: 0.12 }});
        }}
      }});
      nodes.update(updates);
    }}

    inp.addEventListener('input', function() {{
      var q = this.value.toLowerCase().trim();
      btn.style.display = q ? 'block' : 'none';
      applySearch(q);
    }});

    btn.addEventListener('click', function() {{
      inp.value = '';
      btn.style.display = 'none';
      applySearch('');
    }});

    {physics_panel}
  }}, 80);
}})();
</script>
"""
    return html.replace("</body>", js + "\n</body>")


def build_pyvis_html(
    rows: list,
    sparql: str,
    dark: bool = False,
    height_px: int = 480,
    layout: str = "force",
    show_physics_controls: bool = False,
    highlight_path: list[str] | None = None,
) -> str:
    """Build an enhanced PyVis network from SPARQL result rows.

    Args:
        rows:                  result dicts from sparql_executor.execute
        sparql:                original SPARQL query
        dark:                  True for dark-mode palette
        height_px:             iframe height
        layout:                "force" | "hierarchical"
        show_physics_controls: show vis.js physics sliders
        highlight_path:        list of node IDs to highlight as a path (gold)

    Returns the HTML string produced by net.generate_html().
    """
    from pyvis.network import Network

    uri_cols, label_map = detect_label_uri_columns(rows)

    bg           = "#12110F" if dark else "#FFFFFF"
    fc           = "#EDEAE4" if dark else "#1A1917"
    palette      = _DARK_PALETTE if dark else _LIGHT_PALETTE
    center_color = _CENTER_DARK  if dark else _CENTER_LIGHT
    accent       = "#7C5CFC"

    net = Network(
        height=f"{height_px}px", width="100%",
        bgcolor=bg, font_color=fc,
        directed=True,
    )

    if layout == "hierarchical":
        net.set_options(
            '{"layout":{"hierarchical":{"enabled":true,"direction":"UD",'
            '"sortMethod":"directed","levelSeparation":120,"nodeSpacing":100}},'
            '"physics":{"enabled":false},'
            '"edges":{"arrows":{"to":{"enabled":true,"scaleFactor":0.6}},'
            '"smooth":{"type":"straightCross"}}}'
        )
    else:
        net.set_options(
            '{"physics":{"solver":"forceAtlas2Based",'
            '"forceAtlas2Based":{"gravitationalConstant":-60,"springLength":120},'
            '"stabilization":{"iterations":150}},'
            '"edges":{"arrows":{"to":{"enabled":true,"scaleFactor":0.6}},'
            '"smooth":{"type":"curvedCW","roundness":0.1}}}'
        )


    path_set = set(highlight_path or [])

    if len(uri_cols) >= 2:
        src_k  = uri_cols[0]
        tgt_k  = uri_cols[1]
        edge_k = uri_cols[2] if len(uri_cols) > 2 else None
        src_lk  = label_map.get(src_k)
        tgt_lk  = label_map.get(tgt_k)
        edge_lk = label_map.get(edge_k, edge_k) if edge_k else None

        _edge_label_default = ""
        if not edge_k:
            m = re.search(r'wdt:(P\d+)', sparql)
            _edge_label_default = m.group(1) if m else ""

        degree: dict[str, int] = {}
        for row in rows:
            s = row.get(src_k, "")
            t = row.get(tgt_k, "")
            if s:
                degree[s] = degree.get(s, 0) + 1
            if t:
                degree[t] = degree.get(t, 0) + 1
        min_deg = min(degree.values(), default=1)
        max_deg = max(degree.values(), default=1)

        src_color = palette[0]
        tgt_color = palette[1] if len(palette) > 1 else palette[0]

        added: set[str]      = set()
        edge_set: set[tuple] = set()

        for row in rows:
            sid  = row.get(src_k, "")
            slbl = (row.get(src_lk, "") or sid)[:40] if src_lk else sid[:40]
            tid  = row.get(tgt_k, "")
            tlbl = (row.get(tgt_lk, "") or tid)[:40] if tgt_lk else tid[:40]
            elbl = (row.get(edge_lk, "") or "")[:30] if edge_lk else _edge_label_default

            if sid and sid not in added:
                sz = _scale_size(degree.get(sid, 1), min_deg, max_deg)
                color = {
                    "background": _PATH_COLOR, "border": _PATH_BORDER,
                    "highlight": {"background": _PATH_COLOR, "border": _PATH_BORDER}
                } if sid in path_set else src_color
                net.add_node(
                    sid, label=slbl,
                    title=f"<b>{slbl}</b><br><small>{sid}</small>",
                    color=color, size=sz,
                )
                added.add(sid)

            if tid and tid not in added:
                sz = _scale_size(degree.get(tid, 1), min_deg, max_deg)
                color = {
                    "background": _PATH_COLOR, "border": _PATH_BORDER,
                    "highlight": {"background": _PATH_COLOR, "border": _PATH_BORDER}
                } if tid in path_set else tgt_color
                net.add_node(
                    tid, label=tlbl,
                    title=f"<b>{tlbl}</b><br><small>{tid}</small>",
                    color=color, size=sz,
                )
                added.add(tid)

            if sid and tid and (sid, tid) not in edge_set:
                on_path = sid in path_set and tid in path_set
                net.add_edge(
                    sid, tid,
                    label=elbl,
                    title=elbl,
                    color=_PATH_COLOR if on_path else ("#888" if dark else "#CBD5E1"),
                    width=4 if on_path else 1,
                )
                edge_set.add((sid, tid))

    else:
        keys      = list(rows[0].keys()) if rows else []
        entity_k  = uri_cols[0] if uri_cols else (keys[0] if keys else "")
        entity_lk = label_map.get(entity_k)

        base        = _humanize_var_name(entity_k)
        center_name = base if base.lower().endswith("s") else base + "s"
        center_id   = "__center__"

        net.add_node(
            center_id,
            label=center_name,
            title=f"<b>{center_name}</b><br>Central concept",
            color=center_color,
            size=34,
            font={"size": 15, "color": fc, "bold": True},
            shape="dot",
        )

        added: set[str] = {center_id}
        for row in rows:
            nid  = row.get(entity_k, "")
            nlbl = ((row.get(entity_lk, "") or nid) if entity_lk else nid)[:40]
            if nid and nid not in added:
                on_path = nid in path_set
                net.add_node(
                    nid, label=nlbl,
                    title=f"<b>{nlbl}</b><br><small>{nid}</small>",
                    color={
                        "background": _PATH_COLOR, "border": _PATH_BORDER
                    } if on_path else palette[1],
                    size=14,
                )
                added.add(nid)
                net.add_edge(
                    center_id, nid,
                    color=_PATH_COLOR if on_path else ("#888" if dark else "#CBD5E1"),
                    width=3 if on_path else 1,
                )

    html = net.generate_html()
    return _inject_enhancements(html, accent=accent, show_physics=show_physics_controls)
