"""
Constantes del cliente ToDus.
"""

from __future__ import annotations

# URL del bucket público de ToDus
DEFAULT_BASE_URL = "https://s3.todus.cu/stream"

# Namespace S3 prefix por defecto (todos los archivos van bajo este prefix)
DEFAULT_NAMESPACE_PREFIX = "users"

# Namespace de sistema (no se lista normalmente)
SYSTEM_NAMESPACE = "_system"

# Timeouts y reintentos por defecto
DEFAULT_TIMEOUT = 60
DEFAULT_MAX_RETRIES = 3
DEFAULT_CHUNK_SIZE = 64 * 1024  # 64 KB
MAX_KEYS_PER_PAGE = 1000  # límite de S3 por página

# Configuración async
DEFAULT_ASYNC_CONCURRENCY = 10

# Directorio raíz para metadatos locales
DEFAULT_DATA_DIR = "~/.todus"

# Colores ANSI (se desactivan si no es TTY)
import sys
_USE_COLORS = sys.stdout.isatty()


class _C:
    """Códigos de color ANSI (vacíos si no es TTY)."""
    RESET   = "\033[0m"   if _USE_COLORS else ""
    BOLD    = "\033[1m"   if _USE_COLORS else ""
    DIM     = "\033[2m"   if _USE_COLORS else ""
    RED     = "\033[31m"  if _USE_COLORS else ""
    GREEN   = "\033[32m"  if _USE_COLORS else ""
    YELLOW  = "\033[33m"  if _USE_COLORS else ""
    BLUE    = "\033[34m"  if _USE_COLORS else ""
    MAGENTA = "\033[35m"  if _USE_COLORS else ""
    CYAN    = "\033[36m"  if _USE_COLORS else ""
    GRAY    = "\033[90m"  if _USE_COLORS else ""


# Mapeo extensión → Content-Type (los más comunes)
CONTENT_TYPES = {
    # Audio
    ".mp3":  "audio/mpeg",
    ".wav":  "audio/wav",
    ".ogg":  "audio/ogg",
    ".flac": "audio/flac",
    ".m4a":  "audio/mp4",
    ".aac":  "audio/aac",
    ".opus": "audio/opus",
    # Video
    ".mp4":  "video/mp4",
    ".mkv":  "video/x-matroska",
    ".avi":  "video/x-msvideo",
    ".mov":  "video/quicktime",
    ".webm": "video/webm",
    ".m3u8": "application/vnd.apple.mpegurl",
    ".ts":   "video/mp2t",
    # Imagen
    ".jpg":  "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png":  "image/png",
    ".gif":  "image/gif",
    ".bmp":  "image/bmp",
    ".webp": "image/webp",
    ".svg":  "image/svg+xml",
    # Documentos
    ".pdf":  "application/pdf",
    ".doc":  "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xls":  "application/vnd.ms-excel",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".ppt":  "application/vnd.ms-powerpoint",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".txt":  "text/plain",
    ".md":   "text/markdown",
    ".csv":  "text/csv",
    ".json": "application/json",
    ".xml":  "application/xml",
    ".html": "text/html",
    ".css":  "text/css",
    ".js":   "application/javascript",
    # Archivos
    ".zip":  "application/zip",
    ".rar":  "application/vnd.rar",
    ".7z":   "application/x-7z-compressed",
    ".tar":  "application/x-tar",
    ".gz":   "application/gzip",
    ".bz2":  "application/x-bzip2",
    ".xz":   "application/x-xz",
    # Aplicaciones
    ".apk":  "application/vnd.android.package-archive",
    ".exe":  "application/x-msdownload",
    ".dmg":  "application/x-apple-diskimage",
    ".deb":  "application/vnd.debian.binary-package",
    ".rpm":  "application/x-rpm",
}

# Categorías para display
CATEGORIES = {
    "audio":     {".mp3", ".wav", ".ogg", ".flac", ".m4a", ".aac", ".opus", ".wma"},
    "video":     {".mp4", ".mkv", ".avi", ".mov", ".flv", ".webm", ".m3u8", ".ts", ".m4v", ".wmv"},
    "imagen":    {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".svg", ".tiff", ".heic"},
    "documento": {".pdf", ".doc", ".docx", ".txt", ".rtf", ".odt", ".epub", ".md",
                  ".xls", ".xlsx", ".ppt", ".pptx", ".csv", ".json", ".xml"},
    "archivo":   {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz"},
    "app":       {".apk", ".exe", ".dmg", ".deb", ".rpm"},
}


def guess_content_type(filename: str) -> str:
    """Adivina Content-Type a partir del nombre del archivo."""
    from pathlib import Path
    ext = Path(filename).suffix.lower()
    return CONTENT_TYPES.get(ext, "application/octet-stream")


def categorize(filename: str) -> str:
    """Categoriza un archivo por su extensión."""
    from pathlib import Path
    ext = Path(filename).suffix.lower()
    for cat, exts in CATEGORIES.items():
        if ext in exts:
            return cat
    return "otro"


# User-Agent para todas las peticiones
USER_AGENT = "todus-client/2.0 (+https://s3.todus.cu)"
