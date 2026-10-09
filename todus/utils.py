"""
Utilidades del cliente ToDus.

Funciones para:
    - Formatear tamaños, fechas, duraciones
    - Sanitizar nombres de archivo para S3
    - Detectar content-types
    - Calcular MD5
    - Parsear XML de listing de S3
"""

from __future__ import annotations

import os
import re
import hashlib
from pathlib import Path
from typing import Optional, List, Dict, Iterable, Iterator
from urllib.parse import quote

from .constants import CONTENT_TYPES, CATEGORIES, guess_content_type, categorize


# ─── Formato ────────────────────────────────────────────────────────────────

def format_size(size_bytes: int) -> str:
    """Convierte bytes a formato legible."""
    if size_bytes is None or size_bytes < 0:
        return "—"
    if size_bytes == 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    size = float(size_bytes)
    idx = 0
    while size >= 1024 and idx < len(units) - 1:
        size /= 1024
        idx += 1
    if idx == 0:
        return f"{int(size)} {units[idx]}"
    return f"{size:.2f} {units[idx]}"


def format_speed(bytes_per_sec: float) -> str:
    return f"{format_size(int(bytes_per_sec))}/s"


def format_date(iso_date: Optional[str]) -> str:
    """Formatea fecha ISO o HTTP-date a 'YYYY-MM-DD HH:MM'."""
    if not iso_date:
        return "—"
    # HTTP-date: "Wed, 12 Aug 2026 17:51:19 GMT"
    if iso_date.startswith(("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")):
        try:
            from email.utils import parsedate_to_datetime
            dt = parsedate_to_datetime(iso_date)
            return dt.strftime("%Y-%m-%d %H:%M")
        except Exception:
            return iso_date[:25]
    # ISO 8601
    try:
        from datetime import datetime
        dt = datetime.fromisoformat(iso_date.replace("Z", "+00:00")[:19])
        return dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return iso_date[:19]


def format_duration(seconds: float) -> str:
    if seconds < 1:
        return f"{seconds*1000:.0f}ms"
    if seconds < 60:
        return f"{seconds:.1f}s"
    m, s = divmod(seconds, 60)
    if m < 60:
        return f"{int(m)}m {int(s)}s"
    h, m = divmod(m, 60)
    return f"{int(h)}h {int(m)}m"


def human_count(n: int) -> str:
    if n < 1000:
        return str(n)
    if n < 1_000_000:
        return f"{n/1000:.1f}K"
    return f"{n/1_000_000:.1f}M"


# ─── Sanitización de nombres ───────────────────────────────────────────────

# Caracteres que S3 NO permite en keys (o que causan problemas)
_INVALID_S3_CHARS = re.compile(r"[\x00-\x1f\x7f]")
# Caracteres que requieren encoding en URL pero son válidos en S3
_URL_UNSAFE = re.compile(r"[^\w\-._~/]")


def sanitize_filename(name: str, replacement: str = "_") -> str:
    """
    Sanitiza un nombre de archivo para usarlo en S3 de forma segura.

    Reglas:
        - Reemplaza caracteres de control y nulos.
        - Reemplaza caracteres no ASCII por '_' (S3 los permite pero causan problemas).
        - Reemplaza espacios por '_' (opcional, pero más portable).
        - Mantiene extensiones y slashes para paths.

    Args:
        name: Nombre original (puede tener tildes, espacios, etc.).
        replacement: Carácter de reemplazo.

    Returns:
        Nombre sanitizado seguro para S3.

    Examples:
        >>> sanitize_filename("mi archivo.txt")
        'mi_archivo.txt'
        >>> sanitize_filename("foto verano (1).jpg")
        'foto_verano__1_.jpg'
        >>> sanitize_filename("docs/sub/file.pdf")
        'docs/sub/file.pdf'
    """
    if not name:
        return "unnamed"
    # Reemplazar caracteres de control
    name = _INVALID_S3_CHARS.sub(replacement, name)
    # Reemplazar caracteres no ASCII
    name = re.sub(r"[^\x20-\x7E]", replacement, name)
    # Espacios → replacement
    name = name.replace(" ", replacement)
    # Limitar longitud total (S3 permite 1024, pero 255 es razonable)
    if len(name) > 255:
        stem, ext = os.path.splitext(name)
        max_stem = 255 - len(ext)
        name = stem[:max_stem] + ext
    return name or "unnamed"


def sanitize_path(path: str, replacement: str = "_") -> str:
    """
    Sanitiza un path completo (varios componentes separados por /).

    Mantiene la estructura de carpetas pero sanitiza cada componente.
    """
    if not path:
        return ""
    parts = path.split("/")
    sanitized = [sanitize_filename(p, replacement) for p in parts if p]
    return "/".join(sanitized)


def build_s3_key(
    namespace_prefix: str,
    path: Optional[str],
    filename: str,
    sanitize: bool = True,
) -> str:
    """
    Construye la key completa en S3 para un archivo.

    Args:
        namespace_prefix: Prefix del namespace (ej: "users/alice").
        path: Subcarpeta virtual dentro del namespace (ej: "docs" o "docs/2024").
        filename: Nombre del archivo.
        sanitize: Si True, sanitiza path y filename.

    Returns:
        Key completa en S3 (ej: "users/alice/docs/reporte.pdf").

    Examples:
        >>> build_s3_key("users/alice", "docs", "reporte.pdf")
        'users/alice/docs/reporte.pdf'
        >>> build_s3_key("users/alice", None, "foto.jpg")
        'users/alice/foto.jpg'
        >>> build_s3_key("users/alice", "fotos/2024", "imagen.png")
        'users/alice/fotos/2024/imagen.png'
    """
    parts = [namespace_prefix.rstrip("/")]
    if path:
        path = sanitize_path(path) if sanitize else path.strip("/")
        if path:
            parts.append(path)
    fname = sanitize_filename(filename) if sanitize else filename
    parts.append(fname)
    return "/".join(parts)


def normalize_key(key: str) -> str:
    """
    Normaliza una key removiendo './', './/' y slashes duplicados.
    """
    while "//" in key:
        key = key.replace("//", "/")
    if key.startswith("./"):
        key = key[2:]
    return key.strip("/")


def url_encode_key(key: str) -> str:
    """URL-encode una key S3 preservando slashes."""
    return quote(key, safe="/")


# ─── Content-Disposition ────────────────────────────────────────────────────

def content_disposition(filename: str, inline: bool = False) -> str:
    """
    Genera el header Content-Disposition para forzar el nombre correcto
    al descargar.

    Args:
        filename: Nombre original del archivo (puede tener caracteres especiales).
        inline: Si True, usar 'inline' (muestra en browser); si False, 'attachment'.

    Returns:
        Header value listo para usar.

    Examples:
        >>> content_disposition("reporte.pdf")
        'attachment; filename="reporte.pdf"'
        >>> content_disposition("mi archivo.txt")
        'attachment; filename="mi archivo.txt"; filename*=UTF-8''mi%20archivo.txt'
    """
    disposition = "inline" if inline else "attachment"
    # Si el filename es ASCII simple, usar filename=
    try:
        filename.encode("ascii")
        return f'{disposition}; filename="{filename}"'
    except UnicodeEncodeError:
        # No ASCII: usar filename* con encoding RFC 5987
        from urllib.parse import quote
        encoded = quote(filename, safe="")
        return f'{disposition}; filename="{filename.encode("ascii", "replace").decode()}"; filename*=UTF-8\'\'{encoded}'


# ─── Hashing ────────────────────────────────────────────────────────────────

def md5_file(path: str, chunk_size: int = 64 * 1024) -> str:
    """Calcula MD5 de un archivo leyendo en chunks."""
    h = hashlib.md5()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def md5_bytes(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


def normalize_etag(etag: Optional[str]) -> str:
    """Quita comillas del ETag de S3."""
    if not etag:
        return ""
    return etag.strip().strip('"')


# ─── Parsing XML S3 ─────────────────────────────────────────────────────────

def parse_listing(xml_text: str) -> tuple:
    """
    Parsea XML de listing de S3.

    Returns:
        Tupla (items, is_truncated, next_marker).
        Cada item es dict: Key, Size, LastModified, ETag.
    """
    import xml.etree.ElementTree as ET
    from .constants import DEFAULT_BASE_URL  # evitar import circular

    NS = {"s3": "http://s3.amazonaws.com/doc/2006-03-01/"}

    root = ET.fromstring(xml_text)
    items = []
    for contents in root.findall("s3:Contents", NS):
        key_elem = contents.find("s3:Key", NS)
        size_elem = contents.find("s3:Size", NS)
        date_elem = contents.find("s3:LastModified", NS)
        etag_elem = contents.find("s3:ETag", NS)
        items.append({
            "Key": key_elem.text if key_elem is not None else "",
            "Size": int(size_elem.text) if size_elem is not None and size_elem.text else 0,
            "LastModified": date_elem.text if date_elem is not None else None,
            "ETag": normalize_etag(etag_elem.text) if etag_elem is not None else None,
        })

    truncated_elem = root.find("s3:IsTruncated", NS)
    is_truncated = truncated_elem is not None and truncated_elem.text == "true"

    next_marker_elem = root.find("s3:NextMarker", NS)
    next_marker = next_marker_elem.text if next_marker_elem is not None else None

    if is_truncated and not next_marker and items:
        next_marker = items[-1]["Key"]

    return items, is_truncated, next_marker


# ─── Helpers de paths ───────────────────────────────────────────────────────

def split_path_key(key: str) -> tuple:
    """
    Separa una key en (dirname, basename).

    Examples:
        >>> split_path_key("docs/reporte.pdf")
        ('docs', 'reporte.pdf')
        >>> split_path_key("foto.jpg")
        ('', 'foto.jpg')
    """
    if "/" in key:
        dirname, basename = key.rsplit("/", 1)
        return dirname, basename
    return "", key


def join_path(*parts: str) -> str:
    """Une partes de un path normalizando slashes."""
    cleaned = []
    for p in parts:
        if p:
            cleaned.append(p.strip("/"))
    return "/".join(cleaned)


def is_subpath(parent: str, child: str) -> bool:
    """True si 'child' está dentro de 'parent' (paths virtuales)."""
    parent = parent.strip("/")
    child = child.strip("/")
    if not parent:
        return True
    return child == parent or child.startswith(parent + "/")


def relative_path(parent: str, child: str) -> str:
    """Path de child relativo a parent."""
    parent = parent.strip("/")
    child = child.strip("/")
    if not parent:
        return child
    if child == parent:
        return ""
    if child.startswith(parent + "/"):
        return child[len(parent) + 1:]
    return child


def batched(iterable: Iterable, n: int) -> Iterator[List]:
    """Divide iterable en lotes de tamaño n."""
    batch = []
    for item in iterable:
        batch.append(item)
        if len(batch) >= n:
            yield batch
            batch = []
    if batch:
        yield batch
