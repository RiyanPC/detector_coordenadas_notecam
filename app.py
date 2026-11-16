import os
import io
import threading
import webbrowser
import tkinter as tk
from tkinter import filedialog
from pathlib import Path
from datetime import datetime
from typing import List, Dict

import flet as ft
from PIL import Image as PILImage

from extractor_ocr import NoteCamExtractor
from exportador import export_to_excel, export_pdf_compact, export_pdf_photographic
from geo_utils import get_lat_lon, get_google_maps_url, generate_interactive_html_map, export_to_kml

BASE_DIR = Path(__file__).parent.resolve()
DEFAULT_IMAGES_DIR = BASE_DIR / "images-para-extraer-letras"
REPORTS_DIR = BASE_DIR / "reportes"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)


def _pick_folder_dialog(initial_dir: str) -> str:
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    folder = filedialog.askdirectory(initialdir=initial_dir, title="Seleccionar carpeta con imágenes NoteCam")
    root.destroy()
    return folder or ""


def _pick_files_dialog(initial_dir: str) -> List[str]:
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    files = filedialog.askopenfilenames(
        initialdir=initial_dir,
        title="Seleccionar imágenes para extraer texto",
        filetypes=[("Imágenes", "*.jpg *.jpeg *.png *.bmp *.webp *.tif *.tiff"), ("Todos los archivos", "*.*")],
    )
    root.destroy()
    return list(files) if files else []


def main(page: ft.Page):
    page.title = "Sistema de Detección NoteCam — Coordenadas, Zonas de Plantación y Reportes"
    page.theme_mode = ft.ThemeMode.LIGHT
    page.padding = 14
    page.bgcolor = "#F4F7F5"
    page.window.width = 1380
    page.window.height = 880

    extractor = NoteCamExtractor(use_cache=True)
    all_records: List[Dict[str, str]] = list(extractor.cache.values()) if extractor.cache else []
    filtered_records: List[Dict[str, str]] = []
    selected_record: Dict[str, str] | None = None

    # Controles de estado y progreso
    status_text = ft.Text("Listo para procesar o visualizar.", size=13, color="#1B4332", weight=ft.FontWeight.W_500)
    progress_bar = ft.ProgressBar(value=0, width=320, color="#2D6A4F", bgcolor="#D8F3DC", visible=False)

    # Indicador de carga activo, dinámico y con notificación visual prominente
    loading_spinner = ft.ProgressRing(width=28, height=28, stroke_width=3, color="#2D6A4F")
    loading_title = ft.Text("Procesando...", size=13, weight=ft.FontWeight.BOLD, color="#1B4332")
    loading_subtitle = ft.Text("Iniciando tarea...", size=11, color="#2D6A4F")
    loading_pct_badge = ft.Container(
        content=ft.Text("0%", size=11, weight=ft.FontWeight.BOLD, color="#FFFFFF"),
        bgcolor="#2D6A4F",
        padding=ft.Padding.symmetric(horizontal=8, vertical=3),
        border_radius=12,
    )
    loading_count_label = ft.Text("[ 0 / 0 ]", size=12, weight=ft.FontWeight.W_600, color="#1B4332")
    loading_progress_bar = ft.ProgressBar(
        value=0,
        height=7,
        color="#2D6A4F",
        bgcolor="#D8F3DC",
        border_radius=4,
    )

    loading_banner = ft.Container(
        content=ft.Column(
            controls=[
                ft.Row(
                    controls=[
                        ft.Row(
                            controls=[
                                loading_spinner,
                                ft.Column(
                                    controls=[
                                        loading_title,
                                        loading_subtitle,
                                    ],
                                    spacing=1,
                                ),
                            ],
                            spacing=12,
                        ),
                        ft.Row(
                            controls=[
                                loading_count_label,
                                loading_pct_badge,
                            ],
                            spacing=8,
                        ),
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                ),
                loading_progress_bar,
            ],
            spacing=8,
        ),
        bgcolor="#EBF5EE",
        padding=ft.Padding.symmetric(horizontal=16, vertical=10),
        border_radius=10,
        border=ft.Border.all(1.5, "#52B788"),
        shadow=ft.BoxShadow(
            spread_radius=1,
            blur_radius=8,
            color="#22000000",
            offset=ft.Offset(0, 2),
        ),
        visible=False,
    )

    def start_loading(title: str, subtitle: str = "Procesando registros...", total: Optional[int] = None):
        loading_title.value = title
        loading_subtitle.value = subtitle
        if total and total > 0:
            loading_progress_bar.value = 0
            loading_count_label.value = f"[ 0 / {total} ]"
            loading_pct_badge.content.value = "0%"
            loading_pct_badge.visible = True
            loading_count_label.visible = True
        else:
            loading_progress_bar.value = None
            loading_count_label.visible = False
            loading_pct_badge.visible = False
        loading_banner.visible = True
        page.update()

    def update_loading(current: int, total: int, step_desc: str):
        pct = int((current / max(total, 1)) * 100)
        loading_progress_bar.value = current / max(total, 1)
        loading_count_label.value = f"[ {current} / {total} ]"
        loading_count_label.visible = True
        loading_pct_badge.content.value = f"{pct}%"
        loading_pct_badge.visible = True
        loading_subtitle.value = step_desc
        page.update()

    def finish_loading(success_msg: Optional[str] = None):
        loading_banner.visible = False
        if success_msg:
            show_message(success_msg)
        page.update()

    # Banner interactivo de archivo generado (con botón opcional para abrir de una vez)
    last_exported_file: Optional[Path] = None
    export_banner_text = ft.Text("", size=12, weight=ft.FontWeight.W_600, color="#1B4332")
    btn_open_file = ft.FilledButton(
        content="Abrir Archivo",
        icon=ft.Icons.FILE_OPEN,
        bgcolor="#1B4332",
        color="#FFFFFF",
        height=32,
    )
    btn_open_dir = ft.OutlinedButton(
        content="Ver en Carpeta",
        icon=ft.Icons.FOLDER_OPEN,
        height=32,
        on_click=lambda _: os.startfile(str(REPORTS_DIR)),
    )

    def on_click_open_exported_file(ev):
        if last_exported_file and last_exported_file.exists():
            os.startfile(str(last_exported_file))

    btn_open_file.on_click = on_click_open_exported_file

    def hide_export_banner(ev=None):
        export_banner.visible = False
        page.update()

    btn_close_banner = ft.IconButton(
        icon=ft.Icons.CLOSE,
        icon_size=18,
        tooltip="Cerrar notificación",
        on_click=hide_export_banner,
    )

    export_banner = ft.Container(
        content=ft.Row(
            controls=[
                ft.Row(
                    controls=[
                        ft.Icon(ft.Icons.CHECK_CIRCLE, color="#2D6A4F", size=22),
                        export_banner_text,
                    ],
                    spacing=8,
                ),
                ft.Row(
                    controls=[
                        btn_open_file,
                        btn_open_dir,
                        btn_close_banner,
                    ],
                    spacing=8,
                ),
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        ),
        bgcolor="#E8F5E9",
        padding=ft.Padding.symmetric(horizontal=14, vertical=7),
        border_radius=8,
        border=ft.Border.all(1, "#A3D9A5"),
        visible=False,
    )

    def show_export_result(prefix_msg: str, file_path: Path):
        nonlocal last_exported_file
        last_exported_file = Path(file_path).resolve()
        ext = file_path.suffix.upper()[1:]
        export_banner_text.value = f"{prefix_msg}: {file_path.name}"
        btn_open_file.content = f"Abrir {ext}"
        export_banner.visible = True
        page.update()

    # Tarjetas de resumen (KPIs)
    kpi_total_val = ft.Text("0", size=22, weight=ft.FontWeight.BOLD, color="#1B4332")
    kpi_folders_val = ft.Text("0", size=22, weight=ft.FontWeight.BOLD, color="#2D6A4F")
    kpi_cats_val = ft.Text("0", size=22, weight=ft.FontWeight.BOLD, color="#40916C")
    kpi_coords_val = ft.Text("0 / 0", size=17, weight=ft.FontWeight.BOLD, color="#1B4332")

    def make_kpi_card(title: str, value_ctrl: ft.Control, icon_data):
        return ft.Container(
            content=ft.Row(
                controls=[
                    ft.Container(
                        content=ft.Icon(icon_data, color="#1B4332", size=26),
                        bgcolor="#D8F3DC",
                        padding=10,
                        border_radius=10,
                    ),
                    ft.Column(
                        controls=[
                            ft.Text(title, size=11, color="#555555"),
                            value_ctrl,
                        ],
                        spacing=2,
                    ),
                ],
                spacing=12,
            ),
            bgcolor="#FFFFFF",
            padding=12,
            border_radius=10,
            border=ft.Border.all(1, "#D8E2DC"),
            expand=True,
        )

    # Filtros
    folder_dropdown = ft.Dropdown(
        label="Filtrar Tabla por Zona",
        value="TODAS",
        options=[ft.DropdownOption(key="TODAS", text="Todas las zonas")],
        width=210,
    )
    cat_dropdown = ft.Dropdown(
        label="Filtrar por Categoría (Nota)",
        value="TODAS",
        options=[ft.DropdownOption(key="TODAS", text="Todas las categorías")],
        width=210,
    )
    search_field = ft.TextField(
        label="Buscar por nota, archivo, coordenadas o fecha...",
        prefix_icon=ft.Icons.SEARCH,
        width=300,
        height=46,
    )
    append_switch = ft.Switch(label="Acumular al importar", value=True)

    # Selector de Zona para Exportar a Excel y PDF
    export_zone_dropdown = ft.Dropdown(
        label="Zona para Exportar (Excel / PDF)",
        value="TODAS",
        options=[ft.DropdownOption(key="TODAS", text="Todas las Zonas (Completo)")],
        width=240,
    )

    # Panel lateral de vista previa y edición rápida
    preview_full_img = ft.Image(src="", width=220, height=140, border_radius=8, visible=False)
    preview_crop_img = ft.Image(src="", width=250, height=110, border_radius=8, visible=False)
    preview_title = ft.Text("Selecciona una fila para ver detalles", size=12, color="#555555", italic=True)

    edit_categoria = ft.TextField(label="Categoría (Agrupación)", dense=True)
    edit_nota = ft.TextField(label="Nota Extraída", dense=True)
    edit_lat = ft.TextField(label="Latitud / Este", dense=True)
    edit_lon = ft.TextField(label="Longitud / Norte", dense=True)
    edit_elev = ft.TextField(label="Elevación", dense=True)
    edit_prec = ft.TextField(label="Precisión", dense=True)
    edit_tiempo = ft.TextField(label="Fecha y Hora", dense=True)

    def show_message(msg: str, is_error: bool = False):
        status_text.value = msg
        status_text.color = "#B00020" if is_error else "#1B4332"
        page.update()

    def open_current_point_in_gmaps(e):
        if not selected_record:
            show_message("Selecciona primero una imagen de la lista.", is_error=True)
            return
        lat, lon = get_lat_lon(selected_record)
        if lat is not None and lon is not None:
            url = get_google_maps_url(lat, lon)
            webbrowser.open(url)
            show_message(f"Abriendo coordenadas ({lat:.6f}, {lon:.6f}) en Google Maps...")
        else:
            show_message("Coordenada no válida para abrir en Google Maps.", is_error=True)

    btn_open_gmaps = ft.FilledButton(
        content="Abrir en Google Maps",
        icon=ft.Icons.MAP,
        bgcolor="#1A73E8",
        color="#FFFFFF",
        on_click=open_current_point_in_gmaps,
    )

    def select_record(rec: Dict[str, str]):
        nonlocal selected_record
        selected_record = rec
        preview_title.value = f"{rec.get('carpeta', '')} / {rec.get('archivo', '')}"
        preview_title.italic = False
        preview_title.weight = ft.FontWeight.BOLD

        img_path = Path(rec.get("ruta", ""))
        if img_path.exists():
            preview_full_img.src = str(img_path)
            preview_full_img.visible = True
            try:
                pil_im = PILImage.open(img_path).convert("RGB")
                crop_im = NoteCamExtractor.get_bottom_left_crop(pil_im)
                buf = io.BytesIO()
                crop_im.save(buf, format="JPEG", quality=90)
                preview_crop_img.src = buf.getvalue()
                preview_crop_img.visible = True
            except Exception:
                preview_crop_img.visible = False
        else:
            preview_full_img.visible = False
            preview_crop_img.visible = False

        edit_categoria.value = rec.get("categoria", "")
        edit_nota.value = rec.get("nota", "")
        edit_lat.value = rec.get("latitud_este", "")
        edit_lon.value = rec.get("longitud_norte", "")
        edit_elev.value = rec.get("elevacion", "")
        edit_prec.value = rec.get("precision", "")
        edit_tiempo.value = rec.get("tiempo", "")
        page.update()

    def on_save_edits(e):
        if not selected_record:
            return
        selected_record["categoria"] = edit_categoria.value.strip()
        selected_record["nota"] = edit_nota.value.strip()
        selected_record["latitud_este"] = edit_lat.value.strip()
        selected_record["longitud_norte"] = edit_lon.value.strip()
        selected_record["elevacion"] = edit_elev.value.strip()
        selected_record["precision"] = edit_prec.value.strip()
        selected_record["tiempo"] = edit_tiempo.value.strip()
        extractor.save_cache()
        refresh_filters_and_table()
        show_message(f"Cambios guardados en '{selected_record.get('archivo', '')}'.")

    save_edit_btn = ft.FilledButton(
        content="Guardar Cambios",
        icon=ft.Icons.SAVE,
        bgcolor="#2D6A4F",
        color="#FFFFFF",
        on_click=on_save_edits,
    )

    # Tabla de datos
    data_table = ft.DataTable(
        columns=[
            ft.DataColumn(label=ft.Text("N°", weight=ft.FontWeight.BOLD)),
            ft.DataColumn(label=ft.Text("Zona / Carpeta", weight=ft.FontWeight.BOLD)),
            ft.DataColumn(label=ft.Text("Categoría", weight=ft.FontWeight.BOLD)),
            ft.DataColumn(label=ft.Text("Archivo", weight=ft.FontWeight.BOLD)),
            ft.DataColumn(label=ft.Text("Lat / Este", weight=ft.FontWeight.BOLD)),
            ft.DataColumn(label=ft.Text("Lon / Norte", weight=ft.FontWeight.BOLD)),
            ft.DataColumn(label=ft.Text("Elev.", weight=ft.FontWeight.BOLD)),
            ft.DataColumn(label=ft.Text("Fecha/Hora", weight=ft.FontWeight.BOLD)),
            ft.DataColumn(label=ft.Text("Nota Extraída", weight=ft.FontWeight.BOLD)),
            ft.DataColumn(label=ft.Text("Google Maps", weight=ft.FontWeight.BOLD)),
        ],
        rows=[],
        heading_row_color="#E8F5E9",
        heading_row_height=40,
        data_row_min_height=36,
        data_row_max_height=46,
        column_spacing=14,
        show_checkbox_column=False,
    )

    table_count_text = ft.Text("Mostrando 0 registros", size=12, color="#555555")

    def update_kpis():
        kpi_total_val.value = str(len(all_records))
        folders = set(r.get("carpeta", "") for r in all_records if r.get("carpeta"))
        cats = set(r.get("categoria", "") for r in all_records if r.get("categoria"))
        geo_cnt = sum(1 for r in all_records if "Geográfica" in r.get("tipo_coordenada", ""))
        utm_cnt = sum(1 for r in all_records if r.get("tipo_coordenada", "") == "UTM")
        kpi_folders_val.value = str(len(folders))
        kpi_cats_val.value = str(len(cats))
        kpi_coords_val.value = f"{geo_cnt} LatLon / {utm_cnt} UTM"

    def refresh_dropdown_options():
        folders = sorted(set(r.get("carpeta", "") for r in all_records if r.get("carpeta")))
        cats = sorted(set(r.get("categoria", "") for r in all_records if r.get("categoria")))

        cur_f = folder_dropdown.value or "TODAS"
        folder_dropdown.options = [ft.DropdownOption(key="TODAS", text="Todas las zonas")] + [
            ft.DropdownOption(key=f, text=f) for f in folders
        ]
        folder_dropdown.value = cur_f if cur_f in folders or cur_f == "TODAS" else "TODAS"

        cur_c = cat_dropdown.value or "TODAS"
        cat_dropdown.options = [ft.DropdownOption(key="TODAS", text="Todas las categorías")] + [
            ft.DropdownOption(key=c, text=c) for c in cats
        ]
        cat_dropdown.value = cur_c if cur_c in cats or cur_c == "TODAS" else "TODAS"

        cur_ez = export_zone_dropdown.value or "TODAS"
        export_zone_dropdown.options = [ft.DropdownOption(key="TODAS", text="Todas las Zonas (Completo)")] + [
            ft.DropdownOption(key=f, text=f"Zona: {f}") for f in folders
        ]
        export_zone_dropdown.value = cur_ez if cur_ez in folders or cur_ez == "TODAS" else "TODAS"

    def refresh_filters_and_table(e=None):
        nonlocal filtered_records
        update_kpis()
        refresh_dropdown_options()

        f_val = folder_dropdown.value or "TODAS"
        c_val = cat_dropdown.value or "TODAS"
        q = (search_field.value or "").strip().lower()

        filtered = []
        for r in all_records:
            if f_val != "TODAS" and r.get("carpeta") != f_val:
                continue
            if c_val != "TODAS" and r.get("categoria") != c_val:
                continue
            if q:
                haystack = " ".join(
                    [
                        r.get("carpeta", ""),
                        r.get("categoria", ""),
                        r.get("archivo", ""),
                        r.get("latitud_este", ""),
                        r.get("longitud_norte", ""),
                        r.get("tiempo", ""),
                        r.get("nota", ""),
                    ]
                ).lower()
                if q not in haystack:
                    continue
            filtered.append(r)

        filtered_records = filtered
        rows = []
        for idx, rec in enumerate(filtered_records, start=1):
            def make_tap_handler(record=rec):
                return lambda _: select_record(record)

            lat, lon = get_lat_lon(rec)
            def make_gmaps_handler(record=rec):
                def _click(ev):
                    la, lo = get_lat_lon(record)
                    if la is not None and lo is not None:
                        webbrowser.open(get_google_maps_url(la, lo))
                return _click

            gmaps_btn = (
                ft.TextButton(
                    content=ft.Text("Ver Mapa", size=11, color="#1A73E8", weight=ft.FontWeight.BOLD),
                    on_click=make_gmaps_handler(rec),
                )
                if lat is not None and lon is not None
                else ft.Text("-", size=11)
            )

            rows.append(
                ft.DataRow(
                    cells=[
                        ft.DataCell(ft.Text(str(idx), size=12), on_tap=make_tap_handler()),
                        ft.DataCell(ft.Text(rec.get("carpeta", ""), size=12, weight=ft.FontWeight.W_500), on_tap=make_tap_handler()),
                        ft.DataCell(ft.Text(rec.get("categoria", ""), size=12, color="#1B4332"), on_tap=make_tap_handler()),
                        ft.DataCell(ft.Text(rec.get("archivo", ""), size=12), on_tap=make_tap_handler()),
                        ft.DataCell(ft.Text(rec.get("latitud_este", ""), size=12), on_tap=make_tap_handler()),
                        ft.DataCell(ft.Text(rec.get("longitud_norte", ""), size=12), on_tap=make_tap_handler()),
                        ft.DataCell(ft.Text(rec.get("elevacion", ""), size=12), on_tap=make_tap_handler()),
                        ft.DataCell(ft.Text(rec.get("tiempo", ""), size=12), on_tap=make_tap_handler()),
                        ft.DataCell(
                            ft.Text(rec.get("nota", ""), size=12, weight=ft.FontWeight.BOLD, color="#2D6A4F"),
                            on_tap=make_tap_handler(),
                        ),
                        ft.DataCell(gmaps_btn),
                    ],
                )
            )
        data_table.rows = rows
        table_count_text.value = f"Mostrando {len(filtered_records)} de {len(all_records)} imágenes procesadas"
        if filtered_records and selected_record is None:
            select_record(filtered_records[0])
        page.update()

    folder_dropdown.on_select = refresh_filters_and_table
    cat_dropdown.on_select = refresh_filters_and_table
    search_field.on_change = refresh_filters_and_table

    def run_extraction_in_background(paths_to_process: List[str | Path], append: bool = True):
        def worker():
            nonlocal all_records
            start_loading(
                title="Extrayendo texto NoteCam y coordenadas GPS",
                subtitle="Iniciando escaneo y análisis...",
                total=None,
            )

            def on_prog(idx, total, fname, rec):
                note_preview = rec.get("nota", "") or rec.get("categoria", "")
                step_desc = f"{rec.get('carpeta', '')} / {fname}  →  {note_preview}"
                update_loading(idx, total, step_desc)

            new_recs = extractor.process_paths(paths_to_process, progress_callback=on_prog)
            if append:
                existing_by_path = {r["ruta"]: r for r in extractor.cache.values()}
                for r in all_records:
                    existing_by_path[r["ruta"]] = r
                for nr in new_recs:
                    existing_by_path[nr["ruta"]] = nr
                all_records = list(existing_by_path.values())
            else:
                all_records = new_recs

            # Persistencia 100% automática en caché y regeneración de mapa y reportes
            extractor.save_cache()
            refresh_filters_and_table()

            update_loading(len(all_records), len(all_records), "Regenerando mapa satelital y capas KML/Excel...")
            generate_interactive_html_map(all_records, REPORTS_DIR / "mapa_plantaciones.html")
            export_to_kml(all_records, REPORTS_DIR / "plantaciones_zonas.kml")
            export_to_excel(all_records, REPORTS_DIR / "Reporte_NoteCam_Categorizado.xlsx")

            finish_loading(f"¡Completado! {len(new_recs)} imágenes procesadas (Total: {len(all_records)} árboles). Mapa y reportes sincronizados automáticamente.")

        threading.Thread(target=worker, daemon=True).start()

    def on_import_folder(e):
        def _choose():
            folder = _pick_folder_dialog(str(BASE_DIR))
            if folder:
                run_extraction_in_background([folder], append=bool(append_switch.value))

        threading.Thread(target=_choose, daemon=True).start()

    def on_import_files(e):
        def _choose():
            files = _pick_files_dialog(str(BASE_DIR))
            if files:
                run_extraction_in_background(files, append=bool(append_switch.value))

        threading.Thread(target=_choose, daemon=True).start()

    def on_clear_records(e):
        nonlocal all_records, selected_record
        all_records = []
        selected_record = None
        refresh_filters_and_table()
        show_message("Lista limpiada. Puedes importar una nueva carpeta o fotos.")

    def on_export_excel(e):
        sel_zone = export_zone_dropdown.value or "TODAS"
        target_list = [r for r in all_records if r.get("carpeta") == sel_zone] if sel_zone != "TODAS" else all_records
        if not target_list:
            show_message(f"No hay registros disponibles para la zona {sel_zone}.", is_error=True)
            return

        def _excel_worker():
            zone_desc = f"Zona '{sel_zone}'" if sel_zone != "TODAS" else "Todas las Zonas"
            start_loading(
                title=f"Generando Reporte Excel ({len(target_list)} árboles)",
                subtitle=f"Formateando hojas, resúmenes y enlaces a Google Maps para {zone_desc}...",
                total=None,
            )
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            if sel_zone != "TODAS":
                clean_z = re.sub(r'[^a-zA-Z0-9_-]', '_', sel_zone)
                out_file = REPORTS_DIR / f"Reporte_NoteCam_{clean_z}_{ts}.xlsx"
                export_to_excel(target_list, out_file, zone_name=sel_zone)
                finish_loading()
                show_export_result(f"Excel de Zona '{sel_zone}' generado", out_file)
            else:
                out_file = REPORTS_DIR / f"Reporte_NoteCam_Completo_{ts}.xlsx"
                export_to_excel(all_records, out_file)
                export_to_excel(all_records, REPORTS_DIR / "Reporte_NoteCam_Categorizado.xlsx")
                finish_loading()
                show_export_result("Excel Completo generado", out_file)

        threading.Thread(target=_excel_worker, daemon=True).start()

    def on_export_pdf_compact(e):
        sel_zone = export_zone_dropdown.value or "TODAS"
        target_list = [r for r in all_records if r.get("carpeta") == sel_zone] if sel_zone != "TODAS" else all_records
        if not target_list:
            show_message(f"No hay registros disponibles para la zona {sel_zone}.", is_error=True)
            return

        def _compact_worker():
            zone_desc = f"Zona '{sel_zone}'" if sel_zone != "TODAS" else "Todas las Zonas"
            start_loading(
                title=f"Generando PDF Compacto ({len(target_list)} árboles)",
                subtitle=f"Construyendo tabla formal para {zone_desc}...",
                total=None,
            )
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            if sel_zone != "TODAS":
                clean_z = re.sub(r'[^a-zA-Z0-9_-]', '_', sel_zone)
                out_file = REPORTS_DIR / f"Reporte_Compacto_{clean_z}_{ts}.pdf"
                export_pdf_compact(target_list, out_file, zone_name=sel_zone)
                finish_loading()
                show_export_result(f"PDF Compacto de Zona '{sel_zone}' generado", out_file)
            else:
                out_file = REPORTS_DIR / f"Reporte_Compacto_NoteCam_{ts}.pdf"
                export_pdf_compact(all_records, out_file)
                finish_loading()
                show_export_result("PDF Compacto generado", out_file)

        threading.Thread(target=_compact_worker, daemon=True).start()

    def on_export_pdf_photo(e):
        sel_zone = export_zone_dropdown.value or "TODAS"
        target_list = [r for r in all_records if r.get("carpeta") == sel_zone] if sel_zone != "TODAS" else all_records
        if not target_list:
            show_message(f"No hay registros disponibles para la zona {sel_zone}.", is_error=True)
            return

        def _worker():
            zone_desc = f"Zona '{sel_zone}'" if sel_zone != "TODAS" else "Todas las Zonas"
            start_loading(
                title=f"Generando PDF Fotográfico ({len(target_list)} árboles)",
                subtitle=f"Compilando miniaturas y metadatos para {zone_desc}...",
                total=None,
            )
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            if sel_zone != "TODAS":
                clean_z = re.sub(r'[^a-zA-Z0-9_-]', '_', sel_zone)
                out_file = REPORTS_DIR / f"Reporte_Fotografico_{clean_z}_{ts}.pdf"
                export_pdf_photographic(target_list, out_file, zone_name=sel_zone)
                finish_loading()
                show_export_result(f"PDF Fotográfico de Zona '{sel_zone}' generado", out_file)
            else:
                out_file = REPORTS_DIR / f"Reporte_Fotografico_NoteCam_{ts}.pdf"
                export_pdf_photographic(all_records, out_file)
                export_pdf_photographic(all_records, REPORTS_DIR / "Reporte_Fotografico_NoteCam.pdf")
                finish_loading()
                show_export_result("PDF Fotográfico generado", out_file)

        threading.Thread(target=_worker, daemon=True).start()

    def on_open_interactive_map(e):
        target_list = all_records if all_records else list(extractor.cache.values())
        if not target_list:
            show_message("No hay registros disponibles para mostrar en el mapa.", is_error=True)
            return

        def _map_worker():
            start_loading(
                title="Generando y Abriendo Mapa Interactivo",
                subtitle=f"Sincronizando capas y {len(target_list)} árboles para Satélite Google...",
                total=None,
            )
            map_path = REPORTS_DIR / "mapa_plantaciones.html"
            generate_interactive_html_map(target_list, map_path)
            finish_loading()
            webbrowser.open(map_path.as_uri())
            show_message(f"Mapa satelital abierto en tu navegador ({len(target_list)} árboles cargados).")

        threading.Thread(target=_map_worker, daemon=True).start()

    def on_export_kml(e):
        target_list = filtered_records if filtered_records else all_records
        kml_path = REPORTS_DIR / "plantaciones_zonas.kml"
        export_to_kml(target_list, kml_path)
        show_export_result("Capa KML generada con éxito", kml_path)

    def on_open_reports_folder(e):
        os.startfile(str(REPORTS_DIR))

    # Barra superior de navegación y acciones
    header_bar = ft.Container(
        content=ft.Row(
            controls=[
                ft.Column(
                    controls=[
                        ft.Text(
                            "Sistema de Plantaciones y Coordenadas",
                            size=20,
                            weight=ft.FontWeight.BOLD,
                            color="#1B4332",
                        ),
                        ft.Text(
                            "Delimitación de zonas",
                            size=12,
                            color="#1B4332",
                        ),
                    ],
                    spacing=2,
                ),
                ft.Row(
                    controls=[
                        ft.FilledButton(
                            content="Ver Mapa de Plantaciones",
                            icon=ft.Icons.TRAVEL_EXPLORE,
                            bgcolor="#0D6EFD",
                            color="#FFFFFF",
                            on_click=on_open_interactive_map,
                        ),
                        ft.FilledButton(
                            content="Importar Carpeta",
                            icon=ft.Icons.CREATE_NEW_FOLDER,
                            bgcolor="#1B4332",
                            color="#FFFFFF",
                            on_click=on_import_folder,
                        ),
                        ft.FilledButton(
                            content="Importar Fotos",
                            icon=ft.Icons.ADD_PHOTO_ALTERNATE,
                            bgcolor="#2D6A4F",
                            color="#FFFFFF",
                            on_click=on_import_files,
                        ),
                        ft.OutlinedButton(
                            content="Limpiar",
                            icon=ft.Icons.DELETE_OUTLINE,
                            on_click=on_clear_records,
                        ),
                    ],
                    spacing=8,
                ),
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        ),
        bgcolor="#FFFFFF",
        padding=14,
        border_radius=10,
        border=ft.Border.all(1, "#D8E2DC"),
    )

    kpi_row = ft.Row(
        controls=[
            make_kpi_card("Total Árboles Plantados", kpi_total_val, ft.Icons.FOREST),
            make_kpi_card("Zonas de Plantación", kpi_folders_val, ft.Icons.FENCE),
            make_kpi_card("Categorías / Especies", kpi_cats_val, ft.Icons.CATEGORY),
            make_kpi_card("Georreferenciación", kpi_coords_val, ft.Icons.LOCATION_ON),
        ],
        spacing=12,
    )

    toolbar_row = ft.Container(
        content=ft.Column(
            controls=[
                ft.Row(
                    controls=[
                        folder_dropdown,
                        cat_dropdown,
                        search_field,
                        append_switch,
                    ],
                    spacing=10,
                    wrap=True,
                ),
                ft.Row(
                    controls=[
                        export_zone_dropdown,
                        ft.FilledButton(
                            content="Excel (.xlsx)",
                            icon=ft.Icons.TABLE_VIEW,
                            bgcolor="#1D6F42",
                            color="#FFFFFF",
                            on_click=on_export_excel,
                        ),
                        ft.FilledButton(
                            content="PDF Tabla",
                            icon=ft.Icons.PICTURE_AS_PDF,
                            bgcolor="#B02A37",
                            color="#FFFFFF",
                            on_click=on_export_pdf_compact,
                        ),
                        ft.FilledButton(
                            content="PDF Fotos",
                            icon=ft.Icons.COLLECTIONS,
                            bgcolor="#842029",
                            color="#FFFFFF",
                            on_click=on_export_pdf_photo,
                        ),
                        ft.FilledButton(
                            content="KML Google Earth",
                            icon=ft.Icons.PUBLIC,
                            bgcolor="#4A5568",
                            color="#FFFFFF",
                            on_click=on_export_kml,
                        ),
                        ft.OutlinedButton(
                            content="Carpeta Reportes",
                            icon=ft.Icons.FOLDER_OPEN,
                            on_click=on_open_reports_folder,
                        ),
                    ],
                    spacing=8,
                    wrap=True,
                ),
            ],
            spacing=10,
        ),
        bgcolor="#FFFFFF",
        padding=12,
        border_radius=10,
        border=ft.Border.all(1, "#D8E2DC"),
    )

    # Cuerpo principal
    table_container = ft.Container(
        content=ft.Column(
            controls=[
                ft.Row(
                    controls=[table_count_text, progress_bar, status_text],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                ),
                ft.Column(
                    controls=[
                        ft.Row(controls=[data_table], scroll=ft.ScrollMode.ADAPTIVE)
                    ],
                    scroll=ft.ScrollMode.ADAPTIVE,
                    expand=True,
                ),
            ],
            expand=True,
        ),
        bgcolor="#FFFFFF",
        padding=12,
        border_radius=10,
        border=ft.Border.all(1, "#D8E2DC"),
        expand=3,
    )

    inspector_container = ft.Container(
        content=ft.Column(
            controls=[
                ft.Text("Detalle del Árbol / Planta", size=15, weight=ft.FontWeight.BOLD, color="#1B4332"),
                preview_title,
                btn_open_gmaps,
                ft.Row(controls=[preview_full_img], alignment=ft.MainAxisAlignment.CENTER),
                ft.Text("Recorte de Marca de Agua:", size=11, weight=ft.FontWeight.W_600, color="#2D6A4F"),
                ft.Row(controls=[preview_crop_img], alignment=ft.MainAxisAlignment.CENTER),
                ft.Divider(height=6),
                edit_categoria,
                edit_nota,
                ft.Row(controls=[ft.Container(edit_lat, expand=1), ft.Container(edit_lon, expand=1)], spacing=6),
                ft.Row(controls=[ft.Container(edit_elev, expand=1), ft.Container(edit_prec, expand=1)], spacing=6),
                edit_tiempo,
                save_edit_btn,
            ],
            scroll=ft.ScrollMode.ADAPTIVE,
            spacing=7,
        ),
        bgcolor="#FFFFFF",
        padding=14,
        border_radius=10,
        border=ft.Border.all(1, "#D8E2DC"),
        width=340,
    )

    main_content = ft.Row(
        controls=[table_container, inspector_container],
        spacing=12,
        expand=True,
    )

    page.add(
        ft.Column(
            controls=[
                header_bar,
                kpi_row,
                toolbar_row,
                loading_banner,
                export_banner,
                main_content,
            ],
            spacing=10,
            expand=True,
        )
    )

    # Inicializar con todos los registros de caché y regenerar mapa y KML completos
    if all_records:
        refresh_filters_and_table()
        generate_interactive_html_map(all_records, REPORTS_DIR / "mapa_plantaciones.html")
        export_to_kml(all_records, REPORTS_DIR / "plantaciones_zonas.kml")

    # Si la carpeta por defecto existe, asegurar que sus imágenes estén procesadas (acumulando)
    if DEFAULT_IMAGES_DIR.exists():
        run_extraction_in_background([DEFAULT_IMAGES_DIR], append=True)


if __name__ == "__main__":
    ft.run(main)
