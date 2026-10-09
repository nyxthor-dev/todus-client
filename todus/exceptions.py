"""
Excepciones personalizadas del cliente ToDus.
"""

from __future__ import annotations


class ToDusError(Exception):
    """Excepción base."""


class ToDusConnectionError(ToDusError):
    """Error de red al conectar con el bucket."""


class ToDusTimeoutError(ToDusError):
    """Timeout de red."""


class ToDusNotFoundError(ToDusError):
    """El archivo o namespace solicitado no existe."""


class ToDusAlreadyExistsError(ToDusError):
    """El archivo o namespace ya existe."""


class ToDusPermissionError(ToDusError):
    """Permiso denegado."""


class ToDusServerError(ToDusError):
    """Error del servidor (5xx)."""
    def __init__(self, status_code: int, message: str = ""):
        self.status_code = status_code
        super().__init__(f"HTTP {status_code}: {message}")


class ToDusParseError(ToDusError):
    """Error parseando respuesta XML."""


class NamespaceError(ToDusError):
    """Error relacionado con un namespace."""


class NamespaceNotFoundError(NamespaceError):
    """El namespace no existe."""


class NamespaceAlreadyExistsError(NamespaceError):
    """El namespace ya existe."""


class FileNotFoundError(ToDusNotFoundError):
    """El archivo no existe en el namespace."""
