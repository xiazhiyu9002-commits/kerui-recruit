from pathlib import Path

from pydantic import BaseModel, ConfigDict, SecretStr

from kerui_recruit.core.paths import AppPaths


class Settings(BaseModel):
    model_config = ConfigDict(frozen=True)

    data_root: Path
    session_token: SecretStr

    @property
    def paths(self) -> AppPaths:
        return AppPaths.from_root(self.data_root)
