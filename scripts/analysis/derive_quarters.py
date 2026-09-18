"""Camada 6 — desacúmulo (docstring completa na Task 2)."""
from datetime import date


def meses(ini: str, fim: str) -> int:
    """Meses cobertos por [ini, fim]: 2024-01-01..2024-03-31 → 3."""
    a, b = date.fromisoformat(ini), date.fromisoformat(fim)
    return (b.year - a.year) * 12 + b.month - a.month + 1


def trimestre_de(ini: str, fim: str):
    """Posição do acumulado no exercício social (1..4) ou None se a duração não é 3/6/9/12 meses."""
    m = meses(ini, fim)
    return m // 3 if m in (3, 6, 9, 12) else None


def inicio_trimestre(exercicio_ini: str, n: int) -> str:
    """Primeiro dia do trimestre n do exercício que começa em exercicio_ini."""
    y, m = int(exercicio_ini[:4]), int(exercicio_ini[5:7]) + 3 * (n - 1)
    y, m = y + (m - 1) // 12, (m - 1) % 12 + 1
    return f"{y:04d}-{m:02d}-01"
