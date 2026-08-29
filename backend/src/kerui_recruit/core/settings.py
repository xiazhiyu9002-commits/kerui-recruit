from pathlib import Path

from pydantic import BaseModel, ConfigDict, SecretStr

from kerui_recruit.core.paths import AppPaths


class Settings(BaseModel):
    model_config = ConfigDict(frozen=True)

    data_root: Path
    session_token: SecretStr

    # External AI providers. When both keys are absent the runtime uses
    # deterministic local providers so the app works fully offline.
    deepseek_api_key: SecretStr | None = None
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-v4-flash"
    siliconflow_api_key: SecretStr | None = None
    siliconflow_base_url: str = "https://api.siliconflow.cn/v1"
    siliconflow_embedding_model: str = "BAAI/bge-m3"
    siliconflow_reranker_model: str = "BAAI/bge-reranker-v2-m3"

    @property
    def paths(self) -> AppPaths:
        return AppPaths.from_root(self.data_root)

    @property
    def llm_enabled(self) -> bool:
        return bool(self.deepseek_api_key)

    @property
    def search_providers_enabled(self) -> bool:
        return bool(self.siliconflow_api_key)