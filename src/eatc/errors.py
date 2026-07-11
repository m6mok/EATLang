"""Ошибки компилятора.

Правило 10: класса warning не существует — любая проблема это ошибка.
"""


class EatError(Exception):
    def __init__(self, filename: str, line: int, col: int, message: str):
        self.filename = filename
        self.line = line
        self.col = col
        self.message = message
        super().__init__(str(self))

    def __str__(self) -> str:
        return f"{self.filename}:{self.line}:{self.col}: error: {self.message}"


class CapacityError(EatError):
    """Превышен предел компилятора (SPEC.md §6) — штатная ошибка,
    модель TeX."""

    def __init__(
        self, filename: str, line: int, col: int, what: str, limit: int
    ):
        super().__init__(
            filename, line, col, f"capacity exceeded: {what} (предел {limit})"
        )
