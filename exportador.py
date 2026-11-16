import io
import re
from pathlib import Path
from datetime import datetime
from typing import List, Dict
from collections import Counter, defaultdict

import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

from PIL import Image as PILImage
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm, mm
from reportlab.platypus import (
    SimpleDocTemplate,
    Table,
    TableStyle,
    Paragraph,
    Spacer,
    Image as RLImage,
    PageBreak,
    KeepTogether,
)

from extractor_ocr import NoteCamExtractor
from geo_utils import get_lat_lon, get_google_maps_url, generate_interactive_html_map, export_to_kml


def _sanitize_sheet_name(name: str) -> str:
    clean = re.sub(r"[\[\]\:\*\?\/\\]", "", name).strip()
    return clean[:28] if clean else "Categoria"


def _normalize_records(records: List[Dict[str, str]]) -> List[Dict[str, str]]:
    norm = []
    for r in records:
        rc = dict(r)
        c = NoteCamExtractor.normalize_folder_name(rc.get("carpeta", "General"))
        rc["carpeta"] = c
        rc["categoria"] = NoteCamExtractor.derive_category_from_note(rc.get("nota", ""), c)
        norm.append(rc)
    return norm


def export_to_excel(records: List[Dict[str, str]], output_path: str | Path, zone_name: Optional[str] = None) -> str:
    """
    Exporta los registros extraídos a un archivo Excel (.xlsx) con:
    - Columna con enlace directo a Google Maps
    - Hoja 1: Datos Consolidados (o de la zona seleccionada)
    - Hoja 2: Resumen por Categorías y Zonas
    - Hojas individuales por cada Carpeta / Zona (si es reporte completo)
    """
    records = _normalize_records(records)
    if zone_name and zone_name != "TODAS":
        records = [r for r in records if r.get("carpeta") == zone_name]

    out = Path(output_path).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)

    wb = openpyxl.Workbook()
    header_fill = PatternFill(start_color="1B4332", end_color="1B4332", fill_type="solid")
    sub_fill = PatternFill(start_color="2D6A4F", end_color="2D6A4F", fill_type="solid")
    zebra_fill = PatternFill(start_color="F3F9F5", end_color="F3F9F5", fill_type="solid")
    header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    title_font = Font(name="Calibri", size=14, bold=True, color="1B4332")
    bold_font = Font(name="Calibri", size=10, bold=True)
    normal_font = Font(name="Calibri", size=10)
    link_font = Font(name="Calibri", size=10, color="004B91", underline="single")
    thin_border = Border(
        left=Side(style="thin", color="D0D7DE"),
        right=Side(style="thin", color="D0D7DE"),
        top=Side(style="thin", color="D0D7DE"),
        bottom=Side(style="thin", color="D0D7DE"),
    )

    headers = [
        "N°",
        "Carpeta / Zona",
        "Categoría (Nota)",
        "Archivo",
        "Tipo Coord.",
        "Latitud / Este",
        "Longitud / Norte",
        "Elevación",
        "Precisión",
        "Fecha y Hora",
        "Nota Extraída",
        "Google Maps",
        "Texto Completo (OCR)",
    ]

    def populate_data_sheet(ws, rows_data: List[Dict[str, str]], sheet_title: str):
        ws.views.sheetView[0].showGridLines = True
        ws.merge_cells("A1:M1")
        ws["A1"] = f"{sheet_title} — Total: {len(rows_data)} imágenes (Generado: {datetime.now().strftime('%d/%m/%Y %H:%M')})"
        ws["A1"].font = title_font
        ws["A1"].alignment = Alignment(vertical="center")
        ws.row_dimensions[1].height = 26

        for col_idx, h in enumerate(headers, start=1):
            cell = ws.cell(row=2, column=col_idx, value=h)
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            cell.border = thin_border
        ws.row_dimensions[2].height = 24

        for idx, rec in enumerate(rows_data, start=1):
            r = idx + 2
            lat, lon = get_lat_lon(rec)
            gmaps_formula = ""
            if lat is not None and lon is not None:
                url = get_google_maps_url(lat, lon)
                gmaps_formula = f'=HYPERLINK("{url}", "Ver en Google Maps")'

            vals = [
                idx,
                rec.get("carpeta", ""),
                rec.get("categoria", ""),
                rec.get("archivo", ""),
                rec.get("tipo_coordenada", ""),
                rec.get("latitud_este", ""),
                rec.get("longitud_norte", ""),
                rec.get("elevacion", ""),
                rec.get("precision", ""),
                rec.get("tiempo", ""),
                rec.get("nota", ""),
                gmaps_formula,
                rec.get("texto_completo", ""),
            ]
            for c_idx, val in enumerate(vals, start=1):
                c = ws.cell(row=r, column=c_idx, value=val)
                c.border = thin_border
                if idx % 2 == 0:
                    c.fill = zebra_fill
                if c_idx == 12 and gmaps_formula:
                    c.font = link_font
                    c.alignment = Alignment(horizontal="center", vertical="center")
                elif c_idx in (1, 5, 6, 7, 8, 9, 10):
                    c.font = normal_font
                    c.alignment = Alignment(horizontal="center", vertical="center")
                elif c_idx == 13:
                    c.font = normal_font
                    c.alignment = Alignment(vertical="top", wrap_text=True)
                else:
                    c.font = normal_font
                    c.alignment = Alignment(vertical="center")

        ws.auto_filter.ref = f"A2:M{len(rows_data) + 2}"
        ws.freeze_panes = "A3"

        col_widths = [6, 22, 22, 32, 16, 16, 16, 16, 13, 18, 25, 18, 38]
        for c_idx, width in enumerate(col_widths, start=1):
            ws.column_dimensions[get_column_letter(c_idx)].width = width

    # 1. Hoja Principal
    ws_all = wb.active
    if zone_name and zone_name != "TODAS":
        ws_all.title = _sanitize_sheet_name(f"Zona {zone_name}")
        populate_data_sheet(ws_all, records, f"REPORTE DE PLANTACIONES — ZONA: {zone_name.upper()}")
    else:
        ws_all.title = "Datos Consolidados"
        populate_data_sheet(ws_all, records, "REPORTE CONSOLIDADO DE TEXTOS Y COORDENADAS")

    # 2. Hoja Resumen por Categoría y Carpeta
    ws_sum = wb.create_sheet(title="Resumen Categorías")
    ws_sum.merge_cells("A1:F1")
    ws_sum["A1"] = "RESUMEN POR CARPETA / ZONA Y CATEGORÍA DE NOTA"
    ws_sum["A1"].font = title_font
    ws_sum.row_dimensions[1].height = 26

    sum_headers = [
        "Carpeta / Zona",
        "Categoría (Nota Base)",
        "Tipo de Coordenada",
        "Cantidad de Fotos",
        "% del Total",
        "Ejemplo de Nota",
    ]
    for c_idx, h in enumerate(sum_headers, start=1):
        c = ws_sum.cell(row=2, column=c_idx, value=h)
        c.fill = sub_fill
        c.font = header_font
        c.alignment = Alignment(horizontal="center", vertical="center")
        c.border = thin_border
    ws_sum.row_dimensions[2].height = 22

    grouped_summary = defaultdict(list)
    for rec in records:
        key = (rec.get("carpeta", "Sin Carpeta"), rec.get("categoria", "Sin Categoría"))
        grouped_summary[key].append(rec)

    total_recs = max(len(records), 1)
    r_idx = 3
    for (carpeta, categoria), group_rows in sorted(grouped_summary.items()):
        coord_types = ", ".join(sorted(set(x.get("tipo_coordenada", "") for x in group_rows if x.get("tipo_coordenada"))))
        sample_note = next((x.get("nota", "") for x in group_rows if x.get("nota")), "")
        pct = f"{(len(group_rows) / total_recs) * 100:.1f}%"
        row_vals = [carpeta, categoria, coord_types, len(group_rows), pct, sample_note]
        for c_idx, v in enumerate(row_vals, start=1):
            c = ws_sum.cell(row=r_idx, column=c_idx, value=v)
            c.font = normal_font
            c.border = thin_border
            if c_idx in (3, 4, 5):
                c.alignment = Alignment(horizontal="center", vertical="center")
        r_idx += 1

    ws_sum.cell(row=r_idx, column=1, value="TOTAL GENERAL").font = bold_font
    ws_sum.cell(row=r_idx, column=4, value=len(records)).font = bold_font
    ws_sum.cell(row=r_idx, column=4).alignment = Alignment(horizontal="center")
    ws_sum.cell(row=r_idx, column=5, value="100.0%").font = bold_font
    ws_sum.cell(row=r_idx, column=5).alignment = Alignment(horizontal="center")

    for c_idx, w in enumerate([26, 26, 22, 18, 14, 32], start=1):
        ws_sum.column_dimensions[get_column_letter(c_idx)].width = w

    # 3. Hojas separadas por Carpeta / Zona (solo si no es reporte de una sola zona)
    if not zone_name or zone_name == "TODAS":
        by_folder = defaultdict(list)
        for rec in records:
            by_folder[rec.get("carpeta", "General")].append(rec)

        used_names = {"datos consolidados", "resumen categorías"}
        for folder_name, folder_rows in sorted(by_folder.items()):
            s_name = _sanitize_sheet_name(folder_name)
            base_s = s_name
            cnt = 2
            while s_name.lower() in used_names:
                s_name = f"{base_s[:24]}_{cnt}"
                cnt += 1
            used_names.add(s_name.lower())
            ws_f = wb.create_sheet(title=s_name)
            populate_data_sheet(ws_f, folder_rows, f"ZONA / CARPETA: {folder_name.upper()}")

    wb.save(out)
    return str(out)


def _add_page_number(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#555555"))
    page_text = f"Página {doc.page}  |  Generado el {datetime.now().strftime('%d/%m/%Y %H:%M')}"
    canvas.drawRightString(doc.pagesize[0] - 1.2 * cm, 0.8 * cm, page_text)
    canvas.drawString(1.2 * cm, 0.8 * cm, "Sistema Extractor de Coordenadas y Plantaciones - Riyan")
    canvas.restoreState()


def export_pdf_compact(records: List[Dict[str, str]], output_path: str | Path, zone_name: Optional[str] = None) -> str:
    """
    Exporta un reporte PDF compacto en formato tabla (Horizontal A4) con enlace a Google Maps.
    """
    records = _normalize_records(records)
    if zone_name and zone_name != "TODAS":
        records = [r for r in records if r.get("carpeta") == zone_name]

    out = Path(output_path).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)

    doc = SimpleDocTemplate(
        str(out),
        pagesize=landscape(A4),
        leftMargin=1.2 * cm,
        rightMargin=1.2 * cm,
        topMargin=1.2 * cm,
        bottomMargin=1.4 * cm,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "DocTitle",
        parent=styles["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=15,
        textColor=colors.HexColor("#1B4332"),
        spaceAfter=6,
    )
    subtitle_style = ParagraphStyle(
        "DocSub",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9,
        textColor=colors.HexColor("#444444"),
        spaceAfter=10,
    )
    group_style = ParagraphStyle(
        "GroupHdr",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=11,
        textColor=colors.HexColor("#1B4332"),
        spaceBefore=10,
        spaceAfter=4,
    )
    cell_style = ParagraphStyle(
        "CellText",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=7.5,
        leading=9.5,
    )
    hdr_style = ParagraphStyle(
        "HdrText",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=8,
        leading=10,
        textColor=colors.white,
        alignment=1,
    )

    story = []
    doc_heading = f"REPORTE DE PLANTACIONES — ZONA: {zone_name.upper()}" if (zone_name and zone_name != "TODAS") else "REPORTE CATEGORIZADO DE PLANTACIONES"
    story.append(Paragraph(doc_heading, title_style))
    story.append(
        Paragraph(
            f"Total de imágenes procesadas: <b>{len(records)}</b> &nbsp;|&nbsp; Fecha de generación: {datetime.now().strftime('%d/%m/%Y %H:%M')}",
            subtitle_style,
        )
    )

    by_folder = defaultdict(list)
    for r in records:
        by_folder[r.get("carpeta", "General")].append(r)

    # Tabla Resumen Inicial
    sum_data = [
        [
            Paragraph("Carpeta / Zona", hdr_style),
            Paragraph("Categoría Principal", hdr_style),
            Paragraph("Tipo Coordenada", hdr_style),
            Paragraph("Cantidad de Imágenes", hdr_style),
        ]
    ]
    for folder_name, rows in sorted(by_folder.items()):
        cats = ", ".join(sorted(set(x.get("categoria", "") for x in rows if x.get("categoria"))))
        coords = ", ".join(sorted(set(x.get("tipo_coordenada", "") for x in rows if x.get("tipo_coordenada"))))
        sum_data.append(
            [
                Paragraph(f"<b>{folder_name}</b>", cell_style),
                Paragraph(cats, cell_style),
                Paragraph(coords, cell_style),
                Paragraph(f"<b>{len(rows)}</b>", cell_style),
            ]
        )

    sum_table = Table(sum_data, colWidths=[6.5 * cm, 8.5 * cm, 6.0 * cm, 4.0 * cm], hAlign="LEFT")
    sum_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2D6A4F")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#CCCCCC")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F3F9F5")]),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.append(sum_table)
    story.append(Spacer(1, 10))

    # Tablas detalladas por Zona con enlace a mapa
    col_widths = [1.0 * cm, 3.4 * cm, 4.8 * cm, 2.8 * cm, 2.8 * cm, 2.4 * cm, 2.0 * cm, 2.8 * cm, 3.2 * cm, 2.2 * cm]
    for folder_name, rows in sorted(by_folder.items()):
        story.append(
            Paragraph(f"Zona / Carpeta: {folder_name} ({len(rows)} imágenes)", group_style)
        )
        t_data = [
            [
                Paragraph("N°", hdr_style),
                Paragraph("Categoría", hdr_style),
                Paragraph("Archivo", hdr_style),
                Paragraph("Latitud / Este", hdr_style),
                Paragraph("Longitud / Norte", hdr_style),
                Paragraph("Elevación", hdr_style),
                Paragraph("Precisión", hdr_style),
                Paragraph("Fecha y Hora", hdr_style),
                Paragraph("Nota Extraída", hdr_style),
                Paragraph("Mapa", hdr_style),
            ]
        ]
        for idx, r in enumerate(rows, start=1):
            lat, lon = get_lat_lon(r)
            map_cell = Paragraph("-", cell_style)
            if lat is not None and lon is not None:
                gurl = get_google_maps_url(lat, lon)
                map_cell = Paragraph(f'<a href="{gurl}"><font color="#0B5ED7"><b>Ver Mapa</b></font></a>', cell_style)

            t_data.append(
                [
                    Paragraph(str(idx), cell_style),
                    Paragraph(r.get("categoria", ""), cell_style),
                    Paragraph(r.get("archivo", ""), cell_style),
                    Paragraph(r.get("latitud_este", ""), cell_style),
                    Paragraph(r.get("longitud_norte", ""), cell_style),
                    Paragraph(r.get("elevacion", ""), cell_style),
                    Paragraph(r.get("precision", ""), cell_style),
                    Paragraph(r.get("tiempo", ""), cell_style),
                    Paragraph(f"<b>{r.get('nota', '')}</b>", cell_style),
                    map_cell,
                ]
            )
        t = Table(t_data, colWidths=col_widths, repeatRows=1)
        t.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1B4332")),
                    ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#D0D7DE")),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F4F9F6")]),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("TOPPADDING", (0, 0), (-1, -1), 3),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ]
            )
        )
        story.append(t)
        story.append(Spacer(1, 8))

    doc.build(story, onFirstPage=_add_page_number, onLaterPages=_add_page_number)
    return str(out)


def _pil_to_rl_image(pil_img: PILImage.Image, max_w: float, max_h: float) -> RLImage:
    thumb = pil_img.copy()
    thumb.thumbnail((420, 420), PILImage.Resampling.LANCZOS)
    buf = io.BytesIO()
    thumb.save(buf, format="JPEG", quality=80)
    buf.seek(0)
    iw, ih = thumb.size
    ratio = min(max_w / max(iw, 1), max_h / max(ih, 1))
    return RLImage(buf, width=iw * ratio, height=ih * ratio)


def export_pdf_photographic(records: List[Dict[str, str]], output_path: str | Path, zone_name: Optional[str] = None) -> str:
    """
    Exporta un reporte PDF fotográfico con miniatura, recorte y botón a Google Maps.
    """
    records = _normalize_records(records)
    if zone_name and zone_name != "TODAS":
        records = [r for r in records if r.get("carpeta") == zone_name]

    out = Path(output_path).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)

    doc = SimpleDocTemplate(
        str(out),
        pagesize=A4,
        leftMargin=1.2 * cm,
        rightMargin=1.2 * cm,
        topMargin=1.2 * cm,
        bottomMargin=1.4 * cm,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "PhotoTitle",
        parent=styles["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=14,
        textColor=colors.HexColor("#1B4332"),
        spaceAfter=4,
    )
    subtitle_style = ParagraphStyle(
        "PhotoSub",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9,
        textColor=colors.HexColor("#444444"),
        spaceAfter=8,
    )
    group_style = ParagraphStyle(
        "PhotoGroup",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=11,
        textColor=colors.HexColor("#1B4332"),
        spaceBefore=8,
        spaceAfter=4,
    )
    info_style = ParagraphStyle(
        "PhotoInfo",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8.5,
        leading=11.5,
    )
    hdr_style = ParagraphStyle(
        "PhotoHdr",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=8.5,
        textColor=colors.white,
        alignment=1,
    )

    story = []
    doc_heading = f"REPORTE FOTOGRÁFICO — ZONA: {zone_name.upper()}" if (zone_name and zone_name != "TODAS") else "REPORTE FOTOGRÁFICO DE PLANTACIONES Y COORDENADAS"
    story.append(Paragraph(doc_heading, title_style))
    story.append(
        Paragraph(
            f"Total de registros: <b>{len(records)}</b> &nbsp;|&nbsp; Incluye foto, recorte OCR y enlace de ubicación en Google Maps.",
            subtitle_style,
        )
    )

    by_folder = defaultdict(list)
    for r in records:
        by_folder[r.get("carpeta", "General")].append(r)

    for folder_name, rows in sorted(by_folder.items()):
        story.append(Paragraph(f"Zona / Carpeta: {folder_name} ({len(rows)} fotos)", group_style))

        table_rows = [
            [
                Paragraph("Foto Original", hdr_style),
                Paragraph("Recorte Esquina Inf. Izq.", hdr_style),
                Paragraph("Datos Extraídos y Ubicación", hdr_style),
            ]
        ]

        for idx, r in enumerate(rows, start=1):
            img_path = Path(r.get("ruta", ""))
            full_rl = Paragraph("Sin vista previa", info_style)
            crop_rl = Paragraph("Sin recorte", info_style)
            if img_path.exists():
                try:
                    pil_img = PILImage.open(img_path).convert("RGB")
                    crop_img = NoteCamExtractor.get_bottom_left_crop(pil_img)
                    full_rl = _pil_to_rl_image(pil_img, max_w=3.8 * cm, max_h=3.2 * cm)
                    crop_rl = _pil_to_rl_image(crop_img, max_w=5.0 * cm, max_h=3.2 * cm)
                except Exception:
                    pass

            lat, lon = get_lat_lon(r)
            map_link = ""
            if lat is not None and lon is not None:
                gurl = get_google_maps_url(lat, lon)
                map_link = f' &nbsp;|&nbsp; <a href="{gurl}"><font color="#0B5ED7"><b>[Ver en Google Maps]</b></font></a>'

            details_html = (
                f"<b>#{idx} — {r.get('archivo', '')}</b>{map_link}<br/>"
                f"<b>Carpeta:</b> {r.get('carpeta', '')} &nbsp;|&nbsp; <b>Categoría:</b> {r.get('categoria', '')}<br/>"
                f"<b>Coordenadas ({r.get('tipo_coordenada', '')}):</b> {r.get('latitud_este', '')} , {r.get('longitud_norte', '')}<br/>"
                f"<b>Elevación:</b> {r.get('elevacion', '')} &nbsp;|&nbsp; <b>Precisión:</b> {r.get('precision', '')}<br/>"
                f"<b>Tiempo:</b> {r.get('tiempo', '')}<br/>"
                f"<b>Nota:</b> <font color='#1B4332'><b>{r.get('nota', '')}</b></font>"
            )
            table_rows.append([full_rl, crop_rl, Paragraph(details_html, info_style)])

        t = Table(table_rows, colWidths=[4.2 * cm, 5.4 * cm, 9.0 * cm], repeatRows=1)
        t.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1B4332")),
                    ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#D0D7DE")),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F6FAF7")]),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("ALIGN", (0, 1), (1, -1), "CENTER"),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ]
            )
        )
        story.append(t)
        story.append(Spacer(1, 10))

    doc.build(story, onFirstPage=_add_page_number, onLaterPages=_add_page_number)
    return str(out)
