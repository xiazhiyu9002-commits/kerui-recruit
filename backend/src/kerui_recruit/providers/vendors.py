from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class VendorPreset:
    key: str
    label: str
    base_url: str
    text_model: str = ""
    vision_model: str = ""
    embedding_model: str = ""
    rerank_model: str = ""


# 内置供应商预设，供设置页按「能力」自动填充 base_url / model。
# 仅列出有把握的国内主流供应商与模型；visual 为空表示不承诺该能力。
VENDORS: dict[str, VendorPreset] = {
    "deepseek": VendorPreset(
        key="deepseek",
        label="DeepSeek",
        base_url="https://api.deepseek.com",
        text_model="deepseek-v4-flash",
        vision_model="deepseek-v4-flash-vision-exp",
    ),
    "siliconflow": VendorPreset(
        key="siliconflow",
        label="SiliconFlow",
        base_url="https://api.siliconflow.cn/v1",
        text_model="deepseek-ai/DeepSeek-V3",
        vision_model="Qwen/Qwen2.5-VL-72B-Instruct",
        embedding_model="BAAI/bge-m3",
        rerank_model="BAAI/bge-reranker-v2-m3",
    ),
    "zhipu": VendorPreset(
        key="zhipu",
        label="智谱 GLM",
        base_url="https://open.bigmodel.cn/api/paas/v4",
        text_model="glm-4-plus",
        vision_model="glm-4v-plus",
    ),
    "qwen": VendorPreset(
        key="qwen",
        label="通义千问 DashScope",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        text_model="qwen-plus",
        vision_model="qwen-vl-plus",
    ),
    "moonshot": VendorPreset(
        key="moonshot",
        label="月之暗面 Kimi",
        base_url="https://api.moonshot.cn/v1",
        text_model="moonshot-v1-32k",
    ),
    "minimax": VendorPreset(
        key="minimax",
        label="MiniMax",
        base_url="https://api.minimax.chat/v1",
        text_model="abab6.5s-chat",
    ),
    "openai": VendorPreset(
        key="openai",
        label="OpenAI 兼容",
        base_url="https://api.openai.com/v1",
        text_model="gpt-4o-mini",
        vision_model="gpt-4o-mini",
    ),
    "custom": VendorPreset(
        key="custom",
        label="自定义",
        base_url="",
    ),
}
