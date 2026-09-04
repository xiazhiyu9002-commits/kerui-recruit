from __future__ import annotations

import json

import httpx

from kerui_recruit.direction.classifier import DirectionClassificationInput, DirectionProviderResult
from kerui_recruit.direction.models import DirectionLLMOutput
from kerui_recruit.direction.taxonomy import (
    BUSINESS_DOMAIN_LABELS,
    LEADERSHIP_LABELS,
    ROLE_FAMILIES,
)
from kerui_recruit.providers.errors import ProviderError
from kerui_recruit.providers.openai_compatible import OpenAICompatibleClient


class OpenAICompatibleDirectionProvider:
    """OpenAI-compatible 方向分类 Provider（由 settings 决定 base_url/model）。

    LLM 只返回编码、证据与自报置信度；label/source/版本/最终校准置信度由后端生成。
    """

    def __init__(self, *, base_url: str, api_key: str, model: str, http_client: httpx.AsyncClient) -> None:
        self.client = OpenAICompatibleClient(
            base_url=base_url, api_key=api_key, model=model, http_client=http_client,
        )

    async def classify_direction(self, payload: DirectionClassificationInput) -> DirectionProviderResult:
        try:
            output = await self.client.complete_json(
                self._messages(payload), DirectionLLMOutput, temperature=0.0,
            )
            return DirectionProviderResult(output=output, llm_attempts=1,
                                           schema_repair_attempts=0, success=True, error_code=None)
        except ProviderError as error:
            if error.code == "E_API_SCHEMA":
                # 最多一次格式修复重试。
                try:
                    output = await self.client.complete_json(
                        self._messages(payload, repair=True), DirectionLLMOutput, temperature=0.0,
                    )
                    return DirectionProviderResult(output=output, llm_attempts=2,
                                                   schema_repair_attempts=1, success=True, error_code=None)
                except Exception as repair_error:  # noqa: BLE001 - 修复后仍失败
                    code = repair_error.code if isinstance(repair_error, ProviderError) else type(repair_error).__name__
                    return DirectionProviderResult(output=None, llm_attempts=2,
                                                   schema_repair_attempts=1, success=False, error_code=code)
            return DirectionProviderResult(output=None, llm_attempts=1,
                                           schema_repair_attempts=0, success=False, error_code=error.code)
        except Exception as error:  # noqa: BLE001 - 非 Provider 异常也统一返回
            return DirectionProviderResult(output=None, llm_attempts=1,
                                           schema_repair_attempts=0, success=False, error_code=type(error).__name__)

    def _messages(self, payload: DirectionClassificationInput, *, repair: bool = False) -> list[dict[str, str]]:
        role_taxonomy = {rf.code: rf.label for rf in ROLE_FAMILIES}
        system = (
            "你是招聘领域的职业方向分类器。只根据给定结构化字段输出职业方向编码，"
            "不要输出 label、中文名、source、版本或任何额外字段。"
            "confidence 仅是你自报的置信度，不要求你解释。evidence 必须简短、"
            "不得包含姓名、电话、邮箱等个人信息。最多 3 个职业方向，必须且只能有 1 个主方向。"
        )
        instruction = (
            "请严格按给定 JSON 结构返回："
            '{"primary_role_code": "...", "role_family_codes": [{"code":"...","self_confidence":0.9,"evidence":["..."]}], '
            '"leadership_code": "...", "business_domains": [{"code":"...","self_confidence":0.9}], "is_unknown": false}。'
            "职业方向编码必须从给定 taxonomy 的 role_families 中选取；leadership_code 从 leadership 中选取；"
            "business_domains 从 business_domains 中选取。无法判断时 is_unknown 设为 true 且 role_family_codes 为空。"
        ) if not repair else (
            "你上次的输出不符合 JSON 结构要求。请重新严格按结构输出，只包含：primary_role_code、"
            "role_family_codes(code/self_confidence/evidence)、leadership_code、business_domains(code/self_confidence)、is_unknown。"
        )
        user = json.dumps({
            "recent_title": payload.recent_title,
            "recent_duties": payload.recent_duties,
            "history_titles": list(payload.history_titles),
            "project_summaries": list(payload.project_summaries),
            "skills": list(payload.skills),
            "industry": payload.industry,
            "business_scene": payload.business_scene,
            "taxonomy": {
                "role_families": role_taxonomy,
                "leadership": LEADERSHIP_LABELS,
                "business_domains": BUSINESS_DOMAIN_LABELS,
            },
        }, ensure_ascii=False)
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": instruction + "\n" + user},
        ]
