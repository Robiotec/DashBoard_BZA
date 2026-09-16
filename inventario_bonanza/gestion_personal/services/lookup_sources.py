"""Carga segura de conectores de consulta externos."""

import importlib.util
from pathlib import Path


def load_source_module(directory, module_name):
    module_path = Path(directory) / f'{module_name}.py'
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f'No se pudo cargar la fuente {module_name}.')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def call_source(directory, module_name, method_name, value, error_key):
    """Ejecuta un conector y siempre devuelve una estructura apta para persistir."""
    try:
        result = getattr(load_source_module(directory, module_name), method_name)(value)
        if not isinstance(result, dict):
            return {error_key: value, 'error': 'La fuente no devolvió un diccionario.'}
        return result
    except Exception as exc:  # Los conectores son sistemas externos no confiables.
        return {error_key: value, 'error': str(exc)}
