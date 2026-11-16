import sys
import time
from pathlib import Path
from collections import Counter
from extractor_ocr import NoteCamExtractor
from exportador import export_to_excel, export_pdf_compact, export_pdf_photographic
from geo_utils import generate_interactive_html_map, export_to_kml


def main():
    base_dir = Path(__file__).parent
    input_dir = base_dir / "images-para-extraer-letras"
    if len(sys.argv) > 1:
        input_dir = Path(sys.argv[1]).resolve()

    output_dir = base_dir / "reportes"
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Iniciando extracción OCR y georreferenciación desde: {input_dir}")
    t0 = time.time()
    extractor = NoteCamExtractor(use_cache=True)

    def on_progress(idx, total, filename, rec):
        if idx % 20 == 0 or idx == total or idx == 1:
            print(f"[{idx}/{total}] {rec['carpeta']} / {filename} -> Nota: '{rec['nota']}' | Coord: {rec['latitud_este']} {rec['longitud_norte']}")

    records = extractor.process_paths([input_dir], progress_callback=on_progress)
    elapsed = time.time() - t0
    print(f"\nExtracción completada: {len(records)} imágenes procesadas en {elapsed:.1f}s.")

    # Resumen por carpeta y categoría
    counts = Counter((r["carpeta"], r["categoria"]) for r in records)
    print("\n=== Resumen por Carpeta y Categoría ===")
    for (carpeta, cat), count in sorted(counts.items()):
        print(f" - {carpeta} | Categoría: {cat}: {count} fotos")

    # 1. Excel con enlaces interactivos a Google Maps
    excel_path = export_to_excel(records, output_dir / "Reporte_NoteCam_Categorizado.xlsx")
    print(f"\nExcel generado: {excel_path}")

    # 2. PDF Compacto (Tabla)
    pdf_compact_path = export_pdf_compact(records, output_dir / "Reporte_Compacto_NoteCam.pdf")
    print(f"PDF Compacto (Tabla) generado: {pdf_compact_path}")

    # 3. PDF Fotográfico
    pdf_photo_path = export_pdf_photographic(records, output_dir / "Reporte_Fotografico_NoteCam.pdf")
    print(f"PDF Fotográfico generado: {pdf_photo_path}")

    # 4. Mapa Interactivo HTML con Polígonos de Zona y Puntos de Plantación
    map_html_path = generate_interactive_html_map(records, output_dir / "mapa_plantaciones.html")
    print(f"Mapa Interactivo HTML generado: {map_html_path}")

    # 5. KML para Google Earth y Google My Maps
    kml_path = export_to_kml(records, output_dir / "plantaciones_zonas.kml")
    print(f"Capa KML (Google Earth / My Maps) generada: {kml_path}")


if __name__ == "__main__":
    main()
