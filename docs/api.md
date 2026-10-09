# API Reference

## S3Client

`class S3Client(base_url=DEFAULT_BASE_URL, timeout=DEFAULT_TIMEOUT, max_retries=DEFAULT_MAX_RETRIES, chunk_size=DEFAULT_CHUNK_SIZE, session=None)`

### Métodos principales

- `put(local_path, key, ...)`: Sube un archivo.
- `get(key, local_path=None, ...)`: Descarga un archivo.
- `head(key)`: Obtiene metadata.
- `exists(key)`: Verifica existencia.
- `delete(key)`: Elimina un objeto.
- `list(prefix=None, max_keys=None)`: Lista paginada.
- `list_iter(prefix=None)`: Iterador perezoso.
