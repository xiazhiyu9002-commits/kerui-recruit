from dataclasses import dataclass


@dataclass(eq=False)
class ApiError(RuntimeError):
    status_code: int
    code: str
    message: str

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"
