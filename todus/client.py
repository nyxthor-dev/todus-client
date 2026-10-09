"""
Cliente S3 low-level.

Operaciones directas contra el bucket (sin abstracción de namespace):
    - put: subir con Content-Disposition y Content-Type
    - get: descargar a archivo o bytes
    - head: obtener metadata
    - delete: eliminar
    - list: listar con paginación
    - exists: verificar existencia

No maneja namespaces ni metadatos locales. Esa lógica está en
``Namespace`` y ``NamespaceManager``.
"""

from __future__ import annotations

import os
import time
import shutil
from pathlib import Path
from typing import Optional, Iterator, Dict, List, BinaryIO

import requests

from .constants import (
    DEFAULT_BASE_URL, DEFAULT_TIMEOUT, DEFAULT_MAX_RETRIES,
    DEFAULT_CHUNK_SIZE, MAX_KEYS_PER_PAGE, USER_AGENT,
    guess_content_type,
)
from .exceptions import (
    ToDusError, ToDusConnectionError, ToDusTimeoutError, ToDusServerError,
    ToDusNotFoundError, ToDusParseError,
)
from .utils import (
    parse_listing, normalize_etag, url_encode_key, md5_file,
    content_disposition, format_size,
)
from .progress import progress_bar


class S3Client:
    """
    Cliente S3 low-level sobre el bucket público de ToDus.

    Args:
        base_url: URL base del bucket.
        timeout: Timeout HTTP en segundos.
        max_retries: Reintentos ante errores transitorios.
        chunk_size: Tamaño de bloque para streaming (bytes).
        session: Sesión requests reutilizable.
    """

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        timeout: int = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        session: Optional[requests.Session] = None,
    ):
        self.base = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max(1, max_retries)
        self.chunk_size = chunk_size
        self.session = session or requests.Session()

        if not session:
            adapter = requests.adapters.HTTPAdapter(
                pool_connections=10, pool_maxsize=10, max_retries=0,
            )
            self.session.mount("https://", adapter)
            self.session.mount("http://", adapter)
            self.session.headers["User-Agent"] = USER_AGENT

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.session.close()

    # ─── Internos ─────────────────────────────────────────────────────

    def _build_url(self, key: str) -> str:
        """Construye URL completa para una key S3."""
        return f"{self.base}/{url_encode_key(key)}"

    def _request(self, method: str, url: str, **kwargs) -> requests.Response:
        """Petición con reintentos y backoff exponencial."""
        kwargs.setdefault("timeout", self.timeout)
        last_exc: Optional[Exception] = None

        for attempt in range(self.max_retries):
            try:
                r = self.session.request(method, url, **kwargs)
                if 500 <= r.status_code < 600 and attempt < self.max_retries - 1:
                    time.sleep(2 ** attempt)
                    continue
                return r
            except requests.Timeout as e:
                last_exc = ToDusTimeoutError(str(e))
                if attempt < self.max_retries - 1:
                    time.sleep(2 ** attempt)
                else:
                    raise last_exc
            except requests.ConnectionError as e:
                last_exc = ToDusConnectionError(str(e))
                if attempt < self.max_retries - 1:
                    time.sleep(2 ** attempt)
                else:
                    raise last_exc

        raise last_exc or ToDusError("Error desconocido")

    # ─── Operaciones ──────────────────────────────────────────────────

    def put(
        self,
        local_path: str,
        key: str,
        content_type: Optional[str] = None,
        filename: Optional[str] = None,
        inline: bool = False,
        show_progress: bool = True,
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> Dict:
        """
        Sube un archivo al bucket.

        Args:
            local_path: Ruta local del archivo a subir.
            key: Key completa en S3 (ej: "users/alice/docs/reporte.pdf").
            content_type: MIME type. Si None, se adivina por extensión.
            filename: Nombre original para Content-Disposition.
                      Si None, usa el basename de local_path.
            inline: Si True, el browser muestra el archivo en vez de descargar.
            show_progress: Mostrar barra de progreso.
            extra_headers: Headers adicionales para el PUT.

        Returns:
            Dict con: success, etag, size, duration, status_code, error.

        Raises:
            FileNotFoundError: Si local_path no existe.
            ToDusError: En errores de red o servidor.
        """
        if not os.path.isfile(local_path):
            raise FileNotFoundError(f"Archivo no encontrado: {local_path}")

        if content_type is None:
            content_type = guess_content_type(local_path)

        if filename is None:
            filename = os.path.basename(local_path)

        size = os.path.getsize(local_path)
        url = self._build_url(key)

        headers = {
            "Content-Type": content_type,
            "Content-Disposition": content_disposition(filename, inline=inline),
        }
        if extra_headers:
            headers.update(extra_headers)

        start = time.time()

        try:
            if size < 10 * 1024 * 1024:  # < 10MB: leer todo
                with open(local_path, "rb") as f:
                    data = f.read()
                r = self._request("PUT", url, data=data, headers=headers)
            else:
                r = self._put_streaming(local_path, url, headers, size, show_progress)
        except ToDusError:
            raise

        duration = time.time() - start
        success = r.status_code == 200
        etag = normalize_etag(r.headers.get("ETag", "")) if success else None

        return {
            "success": success,
            "etag": etag,
            "size": size,
            "duration": duration,
            "status_code": r.status_code,
            "error": None if success else f"HTTP {r.status_code}: {r.text[:200]}",
        }

    def _put_streaming(
        self,
        local_path: str,
        url: str,
        headers: Dict[str, str],
        size: int,
        show_progress: bool,
    ) -> requests.Response:
        """Sube archivo grande con streaming y barra de progreso."""
        chunk_size = self.chunk_size
        if show_progress:
            bar = progress_bar(
                total=size, desc=f"↑ {os.path.basename(local_path)}",
                color="green", enabled=show_progress,
            )
        else:
            bar = None

        class _StreamGen:
            def __init__(self, fileobj, bar):
                self._f = fileobj
                self._bar = bar
                self._chunk = chunk_size
            def read(self, size=-1):
                chunk = self._f.read(self._chunk if size == -1 else size)
                if chunk and self._bar:
                    self._bar.update(len(chunk))
                return chunk
            def __iter__(self):
                while True:
                    chunk = self._f.read(self._chunk)
                    if not chunk:
                        break
                    if self._bar:
                        self._bar.update(len(chunk))
                    yield chunk
            def __getattr__(self, name):
                return getattr(self._f, name)
            def close(self):
                self._f.close()

        try:
            with open(local_path, "rb") as f:
                wrapper = _StreamGen(f, bar)
                r = self._request("PUT", url, data=wrapper, headers=headers)
        finally:
            if bar:
                bar.close()
        return r

    def get(
        self,
        key: str,
        local_path: Optional[str] = None,
        show_progress: bool = True,
        overwrite: bool = False,
    ) -> Dict:
        """
        Descarga un archivo del bucket.

        Args:
            key: Key completa en S3.
            local_path: Ruta local destino. Si None, retorna bytes en memoria.
            show_progress: Barra de progreso (solo si local_path).
            overwrite: Si False y local_path existe, no sobrescribe.

        Returns:
            Dict con: success, size, duration, content_type, content_disposition,
                      status_code, error.

        Raises:
            ToDusNotFoundError: Si la key no existe.
            ToDusError: En otros errores.
        """
        url = self._build_url(key)

        try:
            r = self._request("GET", url, stream=bool(local_path))
        except ToDusError:
            raise

        if r.status_code == 404:
            r.close()
            raise ToDusNotFoundError(f"No encontrado: {key}")
        if r.status_code != 200:
            r.close()
            raise ToDusServerError(r.status_code, r.text[:200])

        start = time.time()
        content_type = r.headers.get("Content-Type")
        content_disposition_header = r.headers.get("Content-Disposition")

        if local_path is None:
            # Retornar bytes
            data = r.content
            r.close()
            return {
                "success": True,
                "data": data,
                "size": len(data),
                "duration": time.time() - start,
                "content_type": content_type,
                "content_disposition": content_disposition_header,
                "status_code": 200,
                "error": None,
            }

        # Escribir a archivo
        if os.path.exists(local_path) and not overwrite:
            r.close()
            return {
                "success": False,
                "size": 0,
                "duration": 0,
                "content_type": content_type,
                "content_disposition": content_disposition_header,
                "status_code": 200,
                "error": "Ya existe (usa overwrite=True)",
            }

        total = int(r.headers.get("Content-Length", 0))
        bar = progress_bar(
            total=total, desc=f"↓ {os.path.basename(local_path)}",
            color="blue", enabled=show_progress,
        )

        tmp_path = local_path + ".part"
        try:
            with open(tmp_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=self.chunk_size):
                    if chunk:
                        f.write(chunk)
                        if total:
                            bar.update(len(chunk))
        finally:
            bar.close()
            r.close()

        shutil.move(tmp_path, local_path)
        actual_size = os.path.getsize(local_path)

        return {
            "success": True,
            "size": actual_size,
            "duration": time.time() - start,
            "content_type": content_type,
            "content_disposition": content_disposition_header,
            "status_code": 200,
            "error": None,
        }

    def head(self, key: str) -> Optional[Dict]:
        """
        Obtiene metadata de un archivo sin descargarlo.

        Returns:
            Dict con: size, content_type, etag, last_modified, content_disposition.
            None si no existe.
        """
        url = self._build_url(key)
        try:
            r = self._request("HEAD", url)
        except ToDusError:
            return None
        if r.status_code != 200:
            return None
        return {
            "size": int(r.headers.get("Content-Length", 0)),
            "content_type": r.headers.get("Content-Type"),
            "etag": normalize_etag(r.headers.get("ETag", "")),
            "last_modified": r.headers.get("Last-Modified"),
            "content_disposition": r.headers.get("Content-Disposition"),
        }

    def exists(self, key: str) -> bool:
        """Verifica si una key existe en el bucket."""
        try:
            r = self._request("HEAD", self._build_url(key))
            return r.status_code == 200
        except ToDusError:
            return False

    def delete(self, key: str) -> bool:
        """Elimina una key del bucket."""
        url = self._build_url(key)
        try:
            r = self._request("DELETE", url)
            return r.status_code in (200, 204)
        except ToDusError:
            return False

    def list(
        self,
        prefix: Optional[str] = None,
        max_keys: Optional[int] = None,
    ) -> List[Dict]:
        """
        Lista objetos en el bucket con paginación.

        Returns:
            Lista de dicts: Key, Size, LastModified, ETag.
        """
        results: List[Dict] = []
        marker: Optional[str] = None

        while True:
            params = {"max-keys": MAX_KEYS_PER_PAGE}
            if prefix:
                params["prefix"] = prefix
            if marker:
                params["marker"] = marker

            url = f"{self.base}/"
            r = self._request("GET", url, params=params)
            if r.status_code != 200:
                raise ToDusServerError(r.status_code, r.text[:200])

            items, is_truncated, next_marker = parse_listing(r.text)
            results.extend(items)

            if max_keys and len(results) >= max_keys:
                return results[:max_keys]
            if not is_truncated or not next_marker:
                break
            marker = next_marker

        return results

    def list_iter(
        self,
        prefix: Optional[str] = None,
    ) -> Iterator[Dict]:
        """Iterador perezoso sobre objetos del bucket."""
        marker: Optional[str] = None
        while True:
            params: Dict[str, str | int] = {"max-keys": MAX_KEYS_PER_PAGE}
            if prefix:
                params["prefix"] = prefix
            if marker:
                params["marker"] = marker

            url = f"{self.base}/"
            r = self._request("GET", url, params=params)
            if r.status_code != 200:
                return

            items, is_truncated, next_marker = parse_listing(r.text)
            for item in items:
                yield item
            if not is_truncated or not next_marker:
                break
            marker = next_marker

    def build_url(self, key: str) -> str:
        """URL pública de una key."""
        return self._build_url(key)
