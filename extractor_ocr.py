import os
import re
import json
from pathlib import Path
from typing import List, Dict, Optional, Callable, Tuple
import numpy as np
from PIL import Image, ImageOps
from rapidocr_onnxruntime import RapidOCR

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tiff", ".tif"}
CACHE_FILE = Path(__file__).parent / "cache_extracciones.json"


class NoteCamExtractor:
    """
    Motor de extracción OCR para imágenes con marca de agua en la esquina inferior izquierda (NoteCam y similares).
    """

    def __init__(self, use_cache: bool = True):
        self.engine = RapidOCR()
        self.use_cache = use_cache
        self.cache: Dict[str, dict] = self._load_cache()

    def _load_cache(self) -> Dict[str, dict]:
        if self.use_cache and CACHE_FILE.exists():
            try:
                with open(CACHE_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def save_cache(self) -> None:
        if not self.use_cache:
            return
        try:
            with open(CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(self.cache, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    @staticmethod
    def get_bottom_left_crop(
        img: Image.Image,
        height_ratio_portrait: float = 0.20,
        width_ratio_portrait: float = 0.54,
        height_ratio_landscape: float = 0.27,
        width_ratio_landscape: float = 0.36,
    ) -> Image.Image:
        """
        Recorta la esquina inferior izquierda adaptándose automáticamente a orientación vertical u horizontal.
        """
        w, h = img.size
        if h >= w:
            # Vertical (Portrait)
            y0 = int(h * (1.0 - height_ratio_portrait))
            x1 = int(w * width_ratio_portrait)
        else:
            # Horizontal (Landscape)
            y0 = int(h * (1.0 - height_ratio_landscape))
            x1 = int(w * width_ratio_landscape)

        y0 = max(0, min(y0, h - 10))
        x1 = max(10, min(x1, w))
        return img.crop((0, y0, x1, h))

    @staticmethod
    def _clean_note_text(note: str) -> str:
        """
        Restaura espacios naturales en notas donde el OCR juntó palabras o números,
        y filtra textos basura de capturas de pantalla de WhatsApp.
        """
        s = note.strip()
        # Filtrar elementos de interfaz de WhatsApp
        if s.lower() in ("responder", "pnder", "justo ahora", "onder", "escribir un mensaje", "100"):
            return ""

        # Quitar prefijos como Nota:, NOta:, INota:, NOTA
        s = re.sub(r"(?i)^i?nota\s*[:\.\-]?\s*", "", s).strip()

        # Restaurar casos comunes pegados
        replacements = [
            (r"(?i)cc\.?\s*nn\.?\s*san\s*francisc[oa]?", "CC.NN SAN FRANCISCO"),
            (r"(?i)ccnn\s*san\s*francisc[oa]?", "CC.NN SAN FRANCISCO"),
            (r"(?i)jardines\s*de\s*manatay", "Jardines de Manatay"),
            (r"(?i)jardines\s*de\s*manantay", "Jardines de Manantay"),
            (r"(?i)la\s*florida", "la florida"),
            (r"(?i)pashaco\s*micaela", "pashaco Micaela"),
            (r"(?i)micaela", "Micaela"),
            (r"(?i)pashaco", "pashaco"),
        ]
        for pat, rep in replacements:
            s = re.sub(pat, rep, s)

        # Espacio entre letras y números pegados (ej. "Manatay10" -> "Manatay 10", "Micaela1." -> "Micaela 1.")
        s = re.sub(r"([A-Za-zÁÉÍÓÚáéíóúñÑ])(\d)", r"\1 \2", s)
        s = re.sub(r"(\d)([A-Za-zÁÉÍÓÚáéíóúñÑ])", r"\1 \2", s)
        # Espacio después de punto si sigue letra o número ("b.2" -> "b. 2", "1.pashaco" -> "1. pashaco")
        s = re.sub(r"([A-Za-z]\.)(\d)", r"\1 \2", s)
        s = re.sub(r"(\d\.)([A-Za-z])", r"\1 \2", s)
        # Espacio entre minúscula y mayúscula ("pashacoMicaela" -> "pashaco Micaela")
        s = re.sub(r"([a-záéíóúñ])([A-ZÁÉÍÓÚÑ])", r"\1 \2", s)
        # Limpiar espacios múltiples y puntos finales sueltos
        s = re.sub(r"\s+", " ", s).strip()
        if s.endswith(".") and not s.lower().endswith("b."):
            s = s[:-1].strip()
        return s

    @staticmethod
    def normalize_folder_name(folder_name: str) -> str:
        """
        Normaliza nombres de carpeta unificando variantes.
        """
        f = (folder_name or "").strip()
        f_low = f.lower()
        if "francisco" in f_low:
            return "CC.NN SAN FRANCISCO"
        if "abril" in f_low:
            return "2 de ABRIL"
        if "micaela" in f_low:
            return "MICAELA"
        if "manantay" in f_low or "manatay" in f_low:
            return "JARDINES DE MANANTAY"
        if "florida" in f_low:
            return "La Florida"
        if "noviembre" in f_low:
            return "20 de Noviembre"
        return f

    @staticmethod
    def derive_category_from_note(note: str, folder_name: str) -> str:
        """
        Agrupa las notas por su categoría base de forma 100% automática:
        - Aplica reglas consolidadas para proyectos oficiales conocidos.
        - Para cualquier nueva carpeta/zona futura, elimina numeraciones (#1, 88, 36, b. 2),
          prefijos de OCR (Nota:, INota:, Obs:) y ruido de chats.
        - Si la nota o la carpeta coinciden, agrupa de inmediato bajo la misma categoría.
        """
        norm_folder = NoteCamExtractor.normalize_folder_name(folder_name)
        folder_low = norm_folder.lower()

        # 1. Reglas directas para proyectos oficiales consolidados
        if "francisco" in folder_low:
            return "CC.NN. San Francisco"
        if "abril" in folder_low:
            return "2 de Abril"
        if "manatay" in folder_low or "manantay" in folder_low:
            return "Jardines de Manantay"
        if "florida" in folder_low:
            return "La Florida"
        if "micaela" in folder_low:
            return "Micaela - Pashaco"
        if "noviembre" in folder_low:
            return "GRFFS"

        # 2. Si la nota está vacía o es ruido de capturas de chat
        if not note:
            return norm_folder or "Sin Categoría"

        note_clean = note.strip()
        if note_clean.lower() in ["responder", "pnder", "justo ahora", "hoy", "ayer", "100", "100%"]:
            return norm_folder or "Sin Categoría"

        # 3. Limpieza automática universal para cualquier carpeta nueva:
        # Quitar prefijos comunes como 'Nota:', 'INota:', 'Obs:', 'Ref:', 'Nro:'
        note_clean = re.sub(r"^(?:inota|nota|obs|ref|nro|arbol|planta|sector)\s*[:\.\-]?\s*", "", note_clean, flags=re.IGNORECASE).strip()
        # Quitar 'planta de', 'arbol de', 'planton de'
        note_clean = re.sub(r"\b(?:planta|arbol|planton)\s+de\b", "", note_clean, flags=re.IGNORECASE).strip()
        # Quitar símbolos numerales con número (#12, № 4)
        note_clean = re.sub(r"[#№]\s*\d+", "", note_clean)
        # Quitar números de árbol, códigos de lote y sufijos numéricos (ej. '88', '36', '12', 'b. 2', '0')
        note_clean = re.sub(r"\b(?:b|n|nro|arbol|planta)?\s*\.?\s*\d+(?:[\.,]\d+)?\b", "", note_clean, flags=re.IGNORECASE)
        note_clean = re.sub(r"\s+", " ", note_clean).strip(" .,-_/:\t")

        if not note_clean:
            return norm_folder or "Sin Categoría"

        # Si tras la limpieza coincide o se contiene en el nombre de la carpeta, usar el nombre de la carpeta
        if norm_folder and (note_clean.lower() in folder_low or folder_low in note_clean.lower()):
            return norm_folder

        return note_clean.title()

    def parse_ocr_lines(self, lines: List[str], folder_name: str, filename: str, filepath: str) -> Dict[str, str]:
        """
        Analiza las líneas extraídas de la esquina inferior izquierda y las estructura en campos.
        """
        folder_name = self.normalize_folder_name(folder_name)
        tipo_coord = ""
        lat_este = ""
        lon_norte = ""
        elevacion = ""
        precision = ""
        tiempo = ""
        nota = ""

        cleaned_lines = [l.strip() for l in lines if l.strip()]

        for idx, line in enumerate(cleaned_lines):
            low = line.lower()

            # 1. Coordenadas UTM (ej. 543269mE9074542mN o 543266mE 9074558mN)
            utm_match = re.search(r"(\d{5,7})\s*m?\s*E\s*(\d{6,8})\s*m?\s*N", line, re.IGNORECASE)
            if utm_match:
                tipo_coord = "UTM"
                lat_este = f"{utm_match.group(1)} mE"
                lon_norte = f"{utm_match.group(2)} mN"
                continue

            # 2. Latitud
            if "latitud" in low or re.match(r"^lat", low):
                val = re.sub(r"^[Ll]atitud\s*[:\.\-]?\s*", "", line).strip()
                num_m = re.search(r"-?\d+[\.,]\d+", val)
                if num_m:
                    num_s = num_m.group(0).replace(",", ".")
                    if not num_s.startswith("-") and num_s.startswith("8."):
                        num_s = "-" + num_s
                    lat_este = num_s
                    tipo_coord = "Geográfica (Lat/Lon)"
                else:
                    lat_este = val
                continue

            # 3. Longitud
            if "longitud" in low or re.match(r"^lon", low):
                val = re.sub(r"^[Ll]ongitud\s*[:\.\-]?\s*", "", line).strip()
                num_m = re.search(r"-?\d+[\.,]\d+", val)
                if num_m:
                    num_s = num_m.group(0).replace(",", ".")
                    if not num_s.startswith("-") and num_s.startswith("74."):
                        num_s = "-" + num_s
                    lon_norte = num_s
                    if not tipo_coord:
                        tipo_coord = "Geográfica (Lat/Lon)"
                else:
                    lon_norte = val
                continue

            # 4. Elevación
            if "elevac" in low or "elev" in low:
                val = re.sub(r"^[Ee]levaci[oó]n\s*[:\.\-]?\s*", "", line).strip()
                # Normalizar ± y espacio antes de m
                val = re.sub(r"(\d)\s*\+\s*(\d)", r"\1±\2", val)
                val = re.sub(r"\.m$", " m", val)
                val = re.sub(r"(\d)\s*m$", r"\1 m", val)
                elevacion = val
                continue

            # 5. Precisión
            if "precis" in low:
                val = re.sub(r"^[Pp]recisi[oó]n\s*[:\.\-]?\s*", "", line).strip()
                val = re.sub(r"(\d)\s*m$", r"\1 m", val)
                precision = val
                continue

            # 6. Tiempo / Fecha y Hora
            if "tiempo" in low or re.search(r"\d{2}-\d{2}-\d{4}", line):
                val = re.sub(r"^[Tt]iempo\s*[:\.\-]?\s*", "", line).strip()
                # Asegurar espacio entre fecha (DD-MM-YYYY) y hora (HH:MM)
                val = re.sub(r"(\d{2}-\d{2}-\d{4})\s*(\d{2}:\d{2})", r"\1 \2", val)
                tiempo = val
                continue

            # 7. Nota
            if "nota" in low or (idx == len(cleaned_lines) - 1 and not nota and idx >= 3):
                nota = self._clean_note_text(line)
                continue

        # Si la nota se partió en una línea extra al final, unirla
        if not nota and cleaned_lines:
            last_l = cleaned_lines[-1]
            if not any(k in last_l.lower() for k in ["latitud", "longitud", "elevac", "precis", "tiempo"]):
                nota = self._clean_note_text(last_l)

        categoria_nota = self.derive_category_from_note(nota, folder_name)

        # Texto completo formateado limpio
        formatted_lines = []
        if tipo_coord == "UTM" and lat_este and lon_norte:
            formatted_lines.append(f"{lat_este} {lon_norte}")
        else:
            if lat_este:
                formatted_lines.append(f"Latitud: {lat_este}")
            if lon_norte:
                formatted_lines.append(f"Longitud: {lon_norte}")
        if elevacion:
            formatted_lines.append(f"Elevación: {elevacion}")
        if precision:
            formatted_lines.append(f"Precisión: {precision}")
        if tiempo:
            formatted_lines.append(f"Tiempo: {tiempo}")
        if nota:
            formatted_lines.append(f"Nota: {nota}")

        texto_completo = "\n".join(formatted_lines) if formatted_lines else "\n".join(cleaned_lines)

        return {
            "carpeta": folder_name,
            "categoria": categoria_nota,
            "archivo": filename,
            "tipo_coordenada": tipo_coord or "N/D",
            "latitud_este": lat_este,
            "longitud_norte": lon_norte,
            "elevacion": elevacion,
            "precision": precision,
            "tiempo": tiempo,
            "nota": nota,
            "texto_completo": texto_completo,
            "ruta": str(Path(filepath).resolve()),
        }

    def extract_from_image(
        self,
        image_path: str | Path,
        height_ratio_portrait: float = 0.20,
        width_ratio_portrait: float = 0.54,
        height_ratio_landscape: float = 0.27,
        width_ratio_landscape: float = 0.36,
        force_reprocess: bool = False,
    ) -> Dict[str, str]:
        p = Path(image_path).resolve()
        stat = p.stat()
        cache_key = f"{p}|{stat.st_mtime_ns}|{stat.st_size}|{height_ratio_portrait:.2f}|{width_ratio_portrait:.2f}|{height_ratio_landscape:.2f}|{width_ratio_landscape:.2f}"

        if self.use_cache and not force_reprocess and cache_key in self.cache:
            return self.cache[cache_key]

        img = Image.open(p).convert("RGB")
        crop = self.get_bottom_left_crop(
            img,
            height_ratio_portrait=height_ratio_portrait,
            width_ratio_portrait=width_ratio_portrait,
            height_ratio_landscape=height_ratio_landscape,
            width_ratio_landscape=width_ratio_landscape,
        )
        # Escalar 2x y añadir margen blanco para que caracteres al borde no se pierdan
        crop_up = crop.resize((int(crop.width * 2.0), int(crop.height * 2.0)), Image.Resampling.LANCZOS)
        crop_padded = ImageOps.expand(crop_up, border=20, fill=(255, 255, 255))

        res, _ = self.engine(np.array(crop_padded), unclip_ratio=2.2, box_thresh=0.3)
        lines: List[str] = []
        if res:
            # Ordenar de arriba hacia abajo según coordenada Y del cuadro detectado
            sorted_res = sorted(res, key=lambda item: (item[0][0][1] + item[0][2][1]) / 2.0)
            lines = [item[1] for item in sorted_res]

        folder_name = p.parent.name
        parsed = self.parse_ocr_lines(lines, folder_name, p.name, str(p))

        if self.use_cache:
            self.cache[cache_key] = parsed
        return parsed

    def process_paths(
        self,
        paths: List[str | Path],
        progress_callback: Optional[Callable[[int, int, str, Dict[str, str]], None]] = None,
        height_ratio_portrait: float = 0.20,
        width_ratio_portrait: float = 0.54,
        height_ratio_landscape: float = 0.27,
        width_ratio_landscape: float = 0.36,
        force_reprocess: bool = False,
    ) -> List[Dict[str, str]]:
        """
        Recibe una lista de archivos o carpetas, busca todas las imágenes y extrae los textos.
        """
        image_files: List[Path] = []
        seen = set()
        for item in paths:
            p = Path(item).resolve()
            if p.is_dir():
                for root, _, files in os.walk(p):
                    for f in sorted(files):
                        fp = Path(root) / f
                        if fp.suffix.lower() in IMAGE_EXTENSIONS and str(fp) not in seen:
                            seen.add(str(fp))
                            image_files.append(fp)
            elif p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS:
                if str(p) not in seen:
                    seen.add(str(p))
                    image_files.append(p)

        results: List[Dict[str, str]] = []
        total = len(image_files)
        for i, img_path in enumerate(image_files, start=1):
            try:
                rec = self.extract_from_image(
                    img_path,
                    height_ratio_portrait=height_ratio_portrait,
                    width_ratio_portrait=width_ratio_portrait,
                    height_ratio_landscape=height_ratio_landscape,
                    width_ratio_landscape=width_ratio_landscape,
                    force_reprocess=force_reprocess,
                )
            except Exception as e:
                rec = {
                    "carpeta": img_path.parent.name,
                    "categoria": "Error de Lectura",
                    "archivo": img_path.name,
                    "tipo_coordenada": "Error",
                    "latitud_este": "",
                    "longitud_norte": "",
                    "elevacion": "",
                    "precision": "",
                    "tiempo": "",
                    "nota": f"Error: {e}",
                    "texto_completo": f"Error procesando imagen: {e}",
                    "ruta": str(img_path),
                }
            results.append(rec)
            if progress_callback:
                progress_callback(i, total, img_path.name, rec)

        self.save_cache()
        return results

