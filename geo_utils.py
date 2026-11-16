import re
import math
import json
from pathlib import Path
from typing import List, Dict, Tuple, Optional
from collections import defaultdict


def utm_to_latlon(easting: float, northing: float, zone_number: int = 18, northern_hemisphere: bool = False) -> Tuple[float, float]:
    """
    Convierte coordenadas UTM (WGS84) a Latitud y Longitud decimales.
    Por defecto zona 18 Sur (Ucayali / Pucallpa y selva central de Perú).
    """
    a = 6378137.0
    f = 1 / 298.257223563
    e = math.sqrt(2 * f - f * f)
    e1 = (1 - math.sqrt(1 - e * e)) / (1 + math.sqrt(1 - e * e))
    k0 = 0.9996
    x = easting - 500000.0
    y = northing if northern_hemisphere else northing - 10000000.0
    m = y / k0
    mu = m / (a * (1 - e * e / 4 - 3 * (e ** 4) / 64 - 5 * (e ** 6) / 256))
    phi1_rad = (
        mu
        + (3 * e1 / 2 - 27 * (e1 ** 3) / 32) * math.sin(2 * mu)
        + (21 * (e1 ** 2) / 16 - 55 * (e1 ** 4) / 32) * math.sin(4 * mu)
        + (151 * (e1 ** 3) / 96) * math.sin(6 * mu)
    )
    n1 = a / math.sqrt(1 - e * e * math.sin(phi1_rad) ** 2)
    t1 = math.tan(phi1_rad) ** 2
    c1 = (e * e / (1 - e * e)) * math.cos(phi1_rad) ** 2
    r1 = a * (1 - e * e) / math.pow(1 - e * e * math.sin(phi1_rad) ** 2, 1.5)
    d = x / (n1 * k0)
    lat = phi1_rad - (n1 * math.tan(phi1_rad) / r1) * (
        d * d / 2
        - (5 + 3 * t1 + 10 * c1 - 4 * c1 * c1 - 9 * (e * e / (1 - e * e))) * math.pow(d, 4) / 24
        + (61 + 90 * t1 + 298 * c1 + 45 * t1 * t1 - 252 * (e * e / (1 - e * e)) - 3 * c1 * c1) * math.pow(d, 6) / 720
    )
    lon = (
        d
        - (1 + 2 * t1 + c1) * math.pow(d, 3) / 6
        + (5 - 2 * c1 + 28 * t1 - 3 * c1 * c1 + 8 * (e * e / (1 - e * e)) + 24 * t1 * t1) * math.pow(d, 5) / 120
    ) / math.cos(phi1_rad)
    lat_deg = math.degrees(lat)
    lon_deg = (zone_number - 1) * 6 - 180 + 3 + math.degrees(lon)
    return lat_deg, lon_deg


def get_lat_lon(record: Dict[str, str]) -> Tuple[Optional[float], Optional[float]]:
    """
    Extrae o convierte latitud y longitud decimales válidas desde un registro.
    """
    tc = record.get("tipo_coordenada", "")
    la = record.get("latitud_este", "")
    lo = record.get("longitud_norte", "")

    if tc == "UTM" or ("mE" in str(la) or "mN" in str(lo)):
        m_e = re.search(r"(\d{5,7})", str(la))
        m_n = re.search(r"(\d{6,8})", str(lo))
        if m_e and m_n:
            easting = float(m_e.group(1))
            northing = float(m_n.group(1))
            return utm_to_latlon(easting, northing, 18, False)

    try:
        m_la = re.search(r"-?\d+[\.,]\d+", str(la))
        m_lo = re.search(r"-?\d+[\.,]\d+", str(lo))
        if m_la and m_lo:
            lat = float(m_la.group(0).replace(",", "."))
            lon = float(m_lo.group(0).replace(",", "."))
            if not str(lat).startswith("-") and 0.0 < lat < 20.0:
                lat = -lat
            if not str(lon).startswith("-") and 60.0 < lon < 85.0:
                lon = -lon
            return lat, lon
    except Exception:
        pass

    return None, None


def get_google_maps_url(lat: float, lon: float) -> str:
    return f"https://www.google.com/maps?q={lat:.6f},{lon:.6f}"


def convex_hull_2d(points: List[Tuple[float, float]]) -> List[Tuple[float, float]]:
    pts = sorted(set(points))
    if len(pts) <= 2:
        return pts

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)

    upper = []
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)

    return lower[:-1] + upper[:-1]


ZONE_COLORS = [
    {"stroke": "#1B4332", "fill": "#2D6A4F", "marker": "#2D6A4F"},
    {"stroke": "#1D3557", "fill": "#457B9D", "marker": "#1D3557"},
    {"stroke": "#7B2CBF", "fill": "#9D4EDD", "marker": "#7B2CBF"},
    {"stroke": "#B02A37", "fill": "#E63946", "marker": "#B02A37"},
    {"stroke": "#D97706", "fill": "#F59E0B", "marker": "#D97706"},
    {"stroke": "#047857", "fill": "#10B981", "marker": "#047857"},
]


def generate_interactive_html_map(records: List[Dict[str, str]], output_path: str | Path) -> str:
    """
    Genera un mapa HTML interactivo usando EXCLUSIVAMENTE Satélite Google Híbrido,
    con iconos vectoriales SVG en lugar de emojis.
    """
    out = Path(output_path).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)

    by_zone = defaultdict(list)
    valid_points_all = []

    for r in records:
        lat, lon = get_lat_lon(r)
        if lat is not None and lon is not None:
            r_copy = dict(r)
            r_copy["lat"] = lat
            r_copy["lon"] = lon
            r_copy["gmaps_url"] = get_google_maps_url(lat, lon)
            zone_key = r.get("carpeta") or "Zona General"
            by_zone[zone_key].append(r_copy)
            valid_points_all.append((lat, lon))

    if not valid_points_all:
        center_lat, center_lon = -8.38, -74.55
    else:
        center_lat = sum(p[0] for p in valid_points_all) / len(valid_points_all)
        center_lon = sum(p[1] for p in valid_points_all) / len(valid_points_all)

    zones_data = []
    for idx, (zone_name, items) in enumerate(sorted(by_zone.items())):
        coords = [(item["lat"], item["lon"]) for item in items]
        hull = convex_hull_2d(coords) if len(coords) >= 3 else coords
        color = ZONE_COLORS[idx % len(ZONE_COLORS)]

        cat_counts = defaultdict(int)
        for it in items:
            cat_counts[it.get("categoria", "Sin especie")] += 1
        spec_summary = ", ".join([f"{k} ({v})" for k, v in cat_counts.items()])

        zones_data.append({
            "id": f"zone_{idx}",
            "name": zone_name,
            "count": len(items),
            "species_summary": spec_summary,
            "color": color,
            "polygon": [[round(p[0], 6), round(p[1], 6)] for p in hull],
            "items": [
                {
                    "archivo": it["archivo"],
                    "carpeta": it["carpeta"],
                    "categoria": it["categoria"],
                    "nota": it["nota"],
                    "lat": round(it["lat"], 6),
                    "lon": round(it["lon"], 6),
                    "elevacion": it["elevacion"],
                    "precision": it["precision"],
                    "tiempo": it["tiempo"],
                    "gmaps_url": it["gmaps_url"],
                    "ruta": str(Path(it["ruta"]).resolve()).replace("\\", "/"),
                }
                for it in items
            ],
        })

    zones_json = json.dumps(zones_data, ensure_ascii=False)

    html_content = f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <title>Mapa de Zonas y Puntos de Plantación (NoteCam)</title>
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; }}
    body, html {{ height: 100%; width: 100%; overflow: hidden; }}
    #app {{ display: flex; height: 100%; width: 100%; }}
    #sidebar {{
      width: 360px;
      min-width: 320px;
      background: #FFFFFF;
      box-shadow: 2px 0 10px rgba(0,0,0,0.18);
      display: flex;
      flex-direction: column;
      z-index: 1000;
    }}
    #header {{
      background: #1B4332;
      color: #FFFFFF;
      padding: 16px 18px;
    }}
    .header-title-row {{
      display: flex;
      align-items: center;
      gap: 10px;
      margin-bottom: 4px;
    }}
    .header-title-row h1 {{ font-size: 16px; font-weight: 700; }}
    #header p {{ font-size: 12px; opacity: 0.88; }}
    #stats-bar {{
      display: flex;
      background: #2D6A4F;
      color: #FFFFFF;
      padding: 10px 18px;
      font-size: 12px;
      justify-content: space-between;
      align-items: center;
    }}
    .stat-item {{ display: flex; align-items: center; gap: 6px; }}
    #zones-list {{
      flex: 1;
      overflow-y: auto;
      padding: 12px;
    }}
    .zone-card {{
      background: #F8F9FA;
      border: 1px solid #E5E7EB;
      border-radius: 8px;
      padding: 12px;
      margin-bottom: 10px;
      transition: all 0.2s ease;
    }}
    .zone-card:hover {{
      background: #EDF7F1;
      border-color: #2D6A4F;
    }}
    .zone-title {{
      font-size: 14px;
      font-weight: 700;
      color: #1B4332;
      display: flex;
      align-items: center;
      justify-content: space-between;
      margin-bottom: 6px;
    }}
    .zone-name-wrap {{ display: flex; align-items: center; gap: 6px; }}
    .badge {{
      background: #1B4332;
      color: #FFFFFF;
      border-radius: 12px;
      padding: 2px 8px;
      font-size: 11px;
      font-weight: 600;
    }}
    .zone-desc {{ font-size: 11.5px; color: #4B5563; line-height: 1.4; margin-bottom: 8px; }}
    .zone-actions {{ display: flex; gap: 6px; }}
    .btn {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 5px;
      background: #FFFFFF;
      border: 1px solid #D1D5DB;
      color: #1B4332;
      padding: 6px 10px;
      border-radius: 6px;
      font-size: 11px;
      font-weight: 600;
      cursor: pointer;
      transition: all 0.15s;
    }}
    .btn:hover {{ background: #E5E7EB; }}
    .btn-primary {{ background: #2D6A4F; color: #FFFFFF; border-color: #2D6A4F; }}
    .btn-primary:hover {{ background: #1B4332; }}
    #map {{ flex: 1; height: 100%; position: relative; }}
    
    /* Iconos SVG */
    .icon {{
      width: 15px;
      height: 15px;
      stroke-width: 2;
      stroke: currentColor;
      fill: none;
      stroke-linecap: round;
      stroke-linejoin: round;
      vertical-align: middle;
      display: inline-block;
    }}
    .icon-header {{ width: 20px; height: 20px; stroke: #FFFFFF; }}
    .icon-badge {{ width: 13px; height: 13px; }}

    /* Indicador fijo Satélite Google Híbrido */
    .map-layer-badge {{
      position: absolute;
      top: 12px;
      right: 12px;
      z-index: 1000;
      background: rgba(27, 67, 50, 0.90);
      color: #FFFFFF;
      backdrop-filter: blur(4px);
      padding: 7px 13px;
      border-radius: 20px;
      font-size: 12px;
      font-weight: 600;
      display: flex;
      align-items: center;
      gap: 7px;
      box-shadow: 0 2px 8px rgba(0,0,0,0.3);
      border: 1px solid rgba(255,255,255,0.25);
    }}

    .custom-popup {{ font-size: 12px; max-width: 280px; line-height: 1.4; }}
    .popup-title {{
      font-weight: 700;
      font-size: 13px;
      color: #1B4332;
      margin-bottom: 4px;
      display: flex;
      align-items: center;
      gap: 6px;
    }}
    .popup-note {{ font-size: 12px; color: #2D6A4F; font-weight: 600; margin-bottom: 4px; }}
    .popup-gmaps-btn {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      margin-top: 8px;
      background: #1A73E8;
      color: #FFFFFF !important;
      text-decoration: none;
      padding: 6px 11px;
      border-radius: 4px;
      font-weight: 600;
      font-size: 11px;
    }}
    .popup-gmaps-btn:hover {{ background: #1557B0; }}
  </style>
</head>
<body>
<div id="app">
  <div id="sidebar">
    <div id="header">
      <div class="header-title-row">
        <svg class="icon icon-header" viewBox="0 0 24 24"><path d="M12 22v-9"/><path d="M9 13a4.5 4.5 0 0 1-3-4 4.5 4.5 0 0 1 8.5-2A4.5 4.5 0 0 1 18 11a4.5 4.5 0 0 1-3 2H9z"/></svg>
        <h1>Zonas de Plantación</h1>
      </div>
    </div>
    <div id="stats-bar">
      <span class="stat-item">
        <svg class="icon icon-badge" viewBox="0 0 24 24"><path d="M12 22v-9"/><path d="M9 13a4.5 4.5 0 0 1-3-4 4.5 4.5 0 0 1 8.5-2A4.5 4.5 0 0 1 18 11a4.5 4.5 0 0 1-3 2H9z"/></svg>
        <strong>Total:</strong> {len(records)} árboles
      </span>
      <span class="stat-item">
        <svg class="icon icon-badge" viewBox="0 0 24 24"><polygon points="12 2 2 7 12 12 22 7 12 2"/><polyline points="2 17 12 22 22 17"/><polyline points="2 12 12 17 22 12"/></svg>
        <strong>Zonas:</strong> {len(zones_data)} sectores
      </span>
    </div>
    <div id="zones-list">
      <div style="margin-bottom: 12px; display: flex; gap: 8px;">
        <button class="btn btn-primary" onclick="fitAllZones()" style="flex:1;">
          <svg class="icon" viewBox="0 0 24 24" style="stroke:#FFFFFF;"><circle cx="12" cy="12" r="10"/><polygon points="16.24 7.76 14.12 14.12 7.76 16.24 9.88 9.88 16.24 7.76"/></svg>
          Ver Todo el Proyecto
        </button>
      </div>
      <div id="cards-container"></div>
    </div>
  </div>

  <div id="map">
    <div class="map-layer-badge">
      <svg class="icon" viewBox="0 0 24 24" style="stroke:#FFFFFF;"><circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>
      Satélite Google Híbrido
    </div>
  </div>
</div>

<script>
  const zonesData = {zones_json};

  // SVGs reutilizables para interfaz
  const SVG_PIN = '<svg class="icon" viewBox="0 0 24 24"><path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"/><circle cx="12" cy="10" r="3"/></svg>';
  const SVG_ZOOM = '<svg class="icon" viewBox="0 0 24 24" style="stroke:#FFFFFF;"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>';
  const SVG_EYE = '<svg class="icon" viewBox="0 0 24 24"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>';
  const SVG_EYE_OFF = '<svg class="icon" viewBox="0 0 24 24"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"/><line x1="1" y1="1" x2="23" y2="23"/></svg>';
  const SVG_GMAPS = '<svg class="icon" viewBox="0 0 24 24" style="stroke:#FFFFFF;"><polygon points="3 11 22 2 13 21 11 13 3 11"/></svg>';

  // 1. Inicializar mapa
  const map = L.map('map', {{
    center: [{center_lat}, {center_lon}],
    zoom: 13,
    zoomControl: true
  }});

  // 2. Capa única: Satélite Google Híbrido (etiquetas y calles superpuestas sobre satélite)
  L.tileLayer('https://mt{{s}}.google.com/vt/lyrs=y&x={{x}}&y={{y}}&z={{z}}', {{
    subdomains: ['0', '1', '2', '3'],
    attribution: '&copy; Google Maps',
    maxZoom: 20
  }}).addTo(map);

  // 3. Crear grupos de capas por cada Zona
  const zoneLayers = {{}};
  const allBounds = L.latLngBounds([]);

  zonesData.forEach((zone) => {{
    const group = L.featureGroup();
    const zoneColor = zone.color.stroke;
    const fillColor = zone.color.fill;

    // Polígono de delimitación de la zona de plantación ("Aquí plantamos")
    if (zone.polygon && zone.polygon.length >= 3) {{
      const polygon = L.polygon(zone.polygon, {{
        color: zoneColor,
        weight: 3,
        opacity: 0.95,
        fillColor: fillColor,
        fillOpacity: 0.24,
        dashArray: '6, 6'
      }});

      polygon.bindTooltip(`<b>Área de Plantación:</b> ${{zone.name}}<br/><b>${{zone.count}} plantones registrados</b>`, {{
        sticky: true
      }});
      group.addLayer(polygon);
    }}

    // Marcadores circulares para cada árbol/planta
    zone.items.forEach((item) => {{
      const marker = L.circleMarker([item.lat, item.lon], {{
        radius: 6,
        fillColor: zone.color.marker,
        color: '#FFFFFF',
        weight: 1.5,
        opacity: 1,
        fillOpacity: 0.90
      }});

      const popupHtml = `
        <div class="custom-popup">
          <div class="popup-title">${{SVG_PIN}} ${{item.archivo}}</div>
          <div class="popup-note"><b>Nota / Especie:</b> ${{item.nota || 'Sin nota'}}</div>
          <div style="font-size:11px; color:#555; margin-bottom: 6px;">
            <b>Zona / Carpeta:</b> ${{item.carpeta}}<br/>
            <b>Coordenadas:</b> ${{item.lat}}, ${{item.lon}}<br/>
            <b>Elevación:</b> ${{item.elevacion || 'N/D'}} &nbsp;|&nbsp; <b>Precisión:</b> ${{item.precision || 'N/D'}}<br/>
            <b>Fecha / Hora:</b> ${{item.tiempo || 'N/D'}}
          </div>
          <a class="popup-gmaps-btn" href="${{item.gmaps_url}}" target="_blank">
            ${{SVG_GMAPS}} Abrir en Google Maps
          </a>
        </div>
      `;
      marker.bindPopup(popupHtml);
      group.addLayer(marker);
      allBounds.extend([item.lat, item.lon]);
    }});

    group.addTo(map);
    zoneLayers[zone.id] = group;
  }});

  if (allBounds.isValid()) {{
    map.fitBounds(allBounds, {{ padding: [40, 40] }});
  }}

  // 4. Construir tarjetas en la barra lateral con iconos SVG
  const cardsContainer = document.getElementById('cards-container');
  zonesData.forEach(zone => {{
    const card = document.createElement('div');
    card.className = 'zone-card';
    card.innerHTML = `
      <div class="zone-title">
        <div class="zone-name-wrap">
          <span style="display:inline-block; width:10px; height:10px; border-radius:50%; background:${{zone.color.stroke}}"></span>
          <span>${{zone.name}}</span>
        </div>
        <span class="badge" style="background:${{zone.color.stroke}}">${{zone.count}} árboles</span>
      </div>
      <div class="zone-desc">
        <b>Especies / Notas:</b> ${{zone.species_summary || 'N/D'}}
      </div>
      <div class="zone-actions">
        <button class="btn btn-primary" onclick="zoomToZone('${{zone.id}}')">
          ${{SVG_ZOOM}} Enfocar
        </button>
        <button class="btn" onclick="toggleZone('${{zone.id}}', this)">
          ${{SVG_EYE}} Ocultar
        </button>
      </div>
    `;
    cardsContainer.appendChild(card);
  }});

  function zoomToZone(zoneId) {{
    const layer = zoneLayers[zoneId];
    if (layer) {{
      if (!map.hasLayer(layer)) map.addLayer(layer);
      map.fitBounds(layer.getBounds(), {{ padding: [50, 50] }});
    }}
  }}

  function toggleZone(zoneId, btn) {{
    const layer = zoneLayers[zoneId];
    if (map.hasLayer(layer)) {{
      map.removeLayer(layer);
      btn.innerHTML = `${{SVG_EYE_OFF}} Mostrar`;
      btn.style.opacity = '0.65';
    }} else {{
      map.addLayer(layer);
      btn.innerHTML = `${{SVG_EYE}} Ocultar`;
      btn.style.opacity = '1';
    }}
  }}

  function fitAllZones() {{
    if (allBounds.isValid()) {{
      map.fitBounds(allBounds, {{ padding: [40, 40] }});
    }}
  }}
</script>
</body>
</html>
"""
    with open(out, "w", encoding="utf-8") as f:
        f.write(html_content)

    return str(out)


def export_to_kml(records: List[Dict[str, str]], output_path: str | Path) -> str:
    """
    Exporta todas las plantaciones y polígonos delimitadores a formato KML
    compatible al 100% con Google Earth y Google My Maps.
    """
    out = Path(output_path).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)

    by_zone = defaultdict(list)
    for r in records:
        lat, lon = get_lat_lon(r)
        if lat is not None and lon is not None:
            r_c = dict(r)
            r_c["lat"] = lat
            r_c["lon"] = lon
            zone_key = r.get("carpeta") or "Zona General"
            by_zone[zone_key].append(r_c)

    kml = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<kml xmlns="http://www.opengis.net/kml/2.2">',
        '<Document>',
        '  <name>Registro de Plantaciones y Zonas (NoteCam)</name>',
        '  <description>Puntos de árboles plantados y polígonos perimetrales por zona</description>',
    ]

    kml_colors = ["7f1b4332", "7f1d3557", "7f7b2cbf", "7fb02a37", "7fd97706"]
    for idx, col in enumerate(kml_colors):
        kml.append(f'  <Style id="polyStyle_{idx}">')
        kml.append(f'    <PolyStyle><color>{col}</color><fill>1</fill><outline>1</outline></PolyStyle>')
        kml.append('    <LineStyle><color>ff00ff00</color><width>2</width></LineStyle>')
        kml.append('  </Style>')

    for idx, (zone_name, items) in enumerate(sorted(by_zone.items())):
        kml.append('  <Folder>')
        kml.append(f'    <name>Zona: {zone_name} ({len(items)} árboles)</name>')

        pts = [(it["lat"], it["lon"]) for it in items]
        if len(pts) >= 3:
            hull = convex_hull_2d(pts)
            hull_closed = hull + [hull[0]]
            coord_str = " ".join([f"{p[1]},{p[0]},0" for p in hull_closed])
            style_idx = idx % len(kml_colors)
            kml.append('    <Placemark>')
            kml.append(f'      <name>Perímetro de Plantación: {zone_name}</name>')
            kml.append(f'      <styleUrl>#polyStyle_{style_idx}</styleUrl>')
            kml.append('      <Polygon>')
            kml.append('        <outerBoundaryIs><LinearRing>')
            kml.append(f'          <coordinates>{coord_str}</coordinates>')
            kml.append('        </LinearRing></outerBoundaryIs>')
            kml.append('      </Polygon>')
            kml.append('    </Placemark>')

        for it in items:
            gmaps = get_google_maps_url(it["lat"], it["lon"])
            desc = (
                f"<b>Archivo:</b> {it.get('archivo')}<br/>"
                f"<b>Nota / Especie:</b> {it.get('nota')}<br/>"
                f"<b>Zona:</b> {it.get('carpeta')}<br/>"
                f"<b>Coordenadas:</b> {it['lat']}, {it['lon']}<br/>"
                f"<b>Elevación:</b> {it.get('elevacion')}<br/>"
                f"<b>Tiempo:</b> {it.get('tiempo')}<br/>"
                f'<a href="{gmaps}">Ver en Google Maps</a>'
            )
            kml.append('    <Placemark>')
            kml.append(f'      <name>{it.get("nota") or it.get("archivo")}</name>')
            kml.append(f'      <description><![CDATA[{desc}]]></description>')
            kml.append('      <Point>')
            kml.append(f'        <coordinates>{it["lon"]},{it["lat"]},0</coordinates>')
            kml.append('      </Point>')
            kml.append('    </Placemark>')

        kml.append('  </Folder>')

    kml.append('</Document>')
    kml.append('</kml>')

    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(kml))

    return str(out)
