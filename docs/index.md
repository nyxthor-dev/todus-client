# Documentación de todus-client

Bienvenido a la documentación de `todus-client`, un cliente S3 ligero y optimizado para `s3.todus.cu`.

## Introducción

`todus-client` es una librería de bajo nivel diseñada para interactuar directamente con el bucket público de ToDus. Elimina abstracciones innecesarias, enfocándose en la velocidad y la eficiencia.

## Instalación

```bash
pip install .
```

## Guía rápida

```python
from todus.client import S3Client

with S3Client() as client:
    # Subir un archivo
    client.put("archivo.txt", "uploads/archivo.txt")
    
    # Listar objetos
    for item in client.list_iter(prefix="uploads/"):
        print(item['Key'])
```
