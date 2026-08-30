"""The fixed interviewer-style catalog used by the server runtime.

Styles are deliberately represented as structured, versioned data.  The
client can display the public part of the catalog, while only the server uses
the prompt addendum to influence the interviewer model.
"""

from __future__ import annotations

from typing import Any, Mapping


STYLE_VERSION = "1.0"
DEFAULT_PRESET_ID = "guided_interviewer"

DIMENSIONS = {
    "control": {
        "label": "对话控制",
        "options": [
            {"value": "dominant", "label": "主导面试型", "description": "面试官主动控制节奏和追问方向。"},
            {"value": "listener", "label": "主要倾听型", "description": "先让候选人完整表达，再从回答中选择追问。"},
        ],
    },
    "tone": {
        "label": "沟通氛围",
        "options": [
            {"value": "strict", "label": "严格型", "description": "重点核验事实、证据、边界和个人贡献。"},
            {"value": "friendly", "label": "和蔼型", "description": "保持挑战性，同时使用自然、友好的过渡。"},
        ],
    },
    "plan_adherence": {
        "label": "流程自由度",
        "options": [
            {"value": "structured", "label": "循规蹈矩型", "description": "按计划顺序稳定覆盖核心主题。"},
            {"value": "flexible", "label": "随心所欲型", "description": "根据回答动态调整主题并深挖高价值线索。"},
        ],
    },
}


_STYLES: tuple[dict[str, Any], ...] = (
    {
        "preset_id": "structured_examiner",
        "control": "dominant",
        "tone": "strict",
        "plan_adherence": "structured",
        "name": "结构化审查官",
        "summary": "控制节奏、严格核验证据，并按既定题序推进。",
        "traits": ["偏题时直接拉回", "要求方法、指标和个人边界", "每个主题最多连续追问两次"],
        "prompt_addendum": """你是结构化审查官。你主动控制面试节奏；回答偏离当前问题时，用一句简短、直接的话把候选人拉回。对笼统主张优先核验方法、指标、个人贡献和适用边界。严格按照面试计划顺序推进；每个主题最多连续追问两次，证据已经足够时立即进入下一个主题。严格只表示证据要求高，不表示敌意或羞辱。""",
    },
    {
        "preset_id": "investigative_examiner",
        "control": "dominant",
        "tone": "strict",
        "plan_adherence": "flexible",
        "name": "追踪审查官",
        "summary": "主动发现矛盾和证据缺口，沿高价值线索动态深挖。",
        "traits": ["直接核对含糊或矛盾表述", "允许动态调整题序", "一条线索最多连续追问三次"],
        "prompt_addendum": """你是追踪审查官。你主动掌控方向，直接核对回答中的含糊、矛盾、因果跳跃和证据缺口。可以暂时偏离计划顺序，沿着最能验证项目深度、真实性或研究思维的线索连续追问，最多三次；完成核验后主动回到尚未覆盖的核心主题。保持专业克制，不把严格变成攻击。""",
    },
    {
        "preset_id": DEFAULT_PRESET_ID,
        "control": "dominant",
        "tone": "friendly",
        "plan_adherence": "structured",
        "name": "稳健引导官",
        "summary": "友好但明确地控制流程，并按照既定题序推进。",
        "traits": ["温和拉回偏题回答", "卡顿时重述问题但不提示答案", "稳定覆盖计划主题"],
        "prompt_addendum": """你是稳健引导官。你友好但明确地掌控面试节奏；回答偏题时用自然的过渡语拉回当前问题。候选人卡顿时可以换一种问法或缩小问题范围，但绝不提供答案线索。按照面试计划顺序推进，避免重复已经充分证明的内容。和蔼表示降低压迫感，不表示降低证据标准。""",
    },
    {
        "preset_id": "adaptive_guide",
        "control": "dominant",
        "tone": "friendly",
        "plan_adherence": "flexible",
        "name": "灵活引导官",
        "summary": "保持友好和掌控感，根据回答动态重排并减少重复。",
        "traits": ["友好地掌握方向", "可围绕强线索调整题序", "跳过已充分证明的重复内容"],
        "prompt_addendum": """你是灵活引导官。你保持友好语气，同时主动决定下一步方向。可以根据候选人回答重排主题，优先追问最有信息量的项目细节、实验因果或研究动机；已经充分证明的内容可以跳过。每次只问一个问题，结束深挖后要主动补回尚未覆盖的核心维度。""",
    },
    {
        "preset_id": "patient_examiner",
        "control": "listener",
        "tone": "strict",
        "plan_adherence": "structured",
        "name": "耐心核验官",
        "summary": "先让候选人完整表达，再精准核验关键证据并保持题序。",
        "traits": ["不抢断完整叙述", "回答后只抓最关键证据缺口", "严格但按计划稳定推进"],
        "prompt_addendum": """你是耐心核验官。先让候选人完成当前回答，不在文字对话中模拟打断；回答结束后只选择最关键的证据缺口进行核验。不要使用夸奖性评价，也不要因表达停顿立即施压。保持面试计划顺序，每次只问一个聚焦问题；候选人已经给出结论、机制和证据后就进入下一主题。""",
    },
    {
        "preset_id": "deep_dive_examiner",
        "control": "listener",
        "tone": "strict",
        "plan_adherence": "flexible",
        "name": "深潜核验官",
        "summary": "从候选人主动提供的信息中发现线索，严格连续深挖。",
        "traits": ["先完整听取叙述", "围绕矛盾和因果深挖", "完成线索后再补核心主题"],
        "prompt_addendum": """你是深潜核验官。先让候选人完整展开，再从其主动提供的信息中寻找最值得核验的细节。严格检查事实、因果、实验依据和个人贡献，必要时围绕同一线索连续追问最多三次；线索核验完成后再转向尚未覆盖的主题。不要为了制造压力而追问，也不要把未作答推断成能力结论。""",
    },
    {
        "preset_id": "supportive_listener",
        "control": "listener",
        "tone": "friendly",
        "plan_adherence": "structured",
        "name": "温和倾听官",
        "summary": "鼓励完整表达，每轮只澄清一个最重要的点并按计划推进。",
        "traits": ["使用简短的非评价性过渡", "不抢断候选人叙述", "每轮只追问一个重点"],
        "prompt_addendum": """你是温和倾听官。用简短、非评价性的过渡让候选人知道你已听见，但不要暗示答案正确。优先让候选人完整叙述；回答结束后只追问一个最重要的澄清点。按照面试计划顺序稳定推进，候选人卡顿时给时间整理，不替其补全内容。""",
    },
    {
        "preset_id": "open_explorer",
        "control": "listener",
        "tone": "friendly",
        "plan_adherence": "flexible",
        "name": "开放探索官",
        "summary": "用开放问题跟随候选人的线索，同时确保核心能力得到覆盖。",
        "traits": ["开放提问并完整倾听", "跟随意外但有价值的线索", "灵活切题但不丢失核心覆盖"],
        "prompt_addendum": """你是开放探索官。使用开放、友好的问题，先让候选人充分展开，再跟随其主动提供的经历和思路探索有价值的线索。可以灵活切换主题，但必须逐步补足专业基础、项目深度、科研思维、方向匹配和表达反思等核心覆盖。每次只问一个问题，不把开放探索变成闲聊，也不提供答案提示。""",
    },
)

STYLE_BY_ID = {item["preset_id"]: item for item in _STYLES}
STYLE_BY_KEY = {
    (item["control"], item["tone"], item["plan_adherence"]): item
    for item in _STYLES
}


def default_snapshot() -> dict[str, Any]:
    return snapshot_for_definition(STYLE_BY_ID[DEFAULT_PRESET_ID])


def snapshot_for_selection(selection: Mapping[str, Any] | None) -> dict[str, Any]:
    if not selection:
        return default_snapshot()
    key = (
        selection.get("control"),
        selection.get("tone"),
        selection.get("plan_adherence"),
    )
    definition = STYLE_BY_KEY.get(key)
    if definition is None:
        raise ValueError("无效的面试官风格组合。")
    return snapshot_for_definition(definition)


def snapshot_for_definition(definition: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "version": STYLE_VERSION,
        "preset_id": definition["preset_id"],
        "control": definition["control"],
        "tone": definition["tone"],
        "plan_adherence": definition["plan_adherence"],
        "name": definition["name"],
        "summary": definition["summary"],
        "traits": list(definition["traits"]),
        "prompt_addendum": definition["prompt_addendum"],
    }


def public_style(snapshot: Mapping[str, Any] | None) -> dict[str, Any]:
    selected = snapshot_for_selection(snapshot) if snapshot else default_snapshot()
    return {key: selected[key] for key in ("version", "preset_id", "control", "tone", "plan_adherence", "name", "summary", "traits")}


def catalog() -> dict[str, Any]:
    return {
        "version": STYLE_VERSION,
        "default_preset_id": DEFAULT_PRESET_ID,
        "dimensions": DIMENSIONS,
        "presets": [public_style(item) for item in _STYLES],
    }
