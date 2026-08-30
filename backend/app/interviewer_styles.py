"""Versioned interviewer-style catalog and server-owned behavior policies.

The browser only chooses three controlled dimensions.  The server resolves
that choice to a complete snapshot containing the prompt addendum and the
guardrails used by one interview run.  Keeping the mapping here means a
client cannot inject arbitrary instructions into a model prompt, and a run
stays stable when the catalog changes in a later deployment.
"""

from __future__ import annotations

from typing import Any, Mapping


STYLE_VERSION = "1.0"

# These are the canonical keys used by the current web client.  The legacy
# ``control``/``plan_adherence`` spelling is accepted at the API boundary too
# because an earlier server build exposed those names.
DEFAULT_SELECTION = {
    "initiative": "leading",
    "tone": "friendly",
    "structure": "structured",
}

_DIMENSION_DEFINITIONS: dict[str, dict[str, Any]] = {
    "initiative": {
        "label": "对话控制",
        "options": [
            {
                "value": "leading",
                "label": "主导面试型",
                "description": "主动控制节奏、追问方向和主题切换。",
            },
            {
                "value": "listening",
                "label": "主要倾听型",
                "description": "先让候选人完整表达，再从回答中选择重点。",
            },
        ],
    },
    "tone": {
        "label": "沟通氛围",
        "options": [
            {
                "value": "strict",
                "label": "严格型",
                "description": "重点核验事实、证据、边界和个人贡献。",
            },
            {
                "value": "friendly",
                "label": "和蔼型",
                "description": "保持挑战性，同时使用自然、友好的过渡。",
            },
        ],
    },
    "structure": {
        "label": "流程自由度",
        "options": [
            {
                "value": "structured",
                "label": "循规蹈矩型",
                "description": "按计划顺序稳定覆盖核心主题。",
            },
            {
                "value": "adaptive",
                "label": "随心所欲型",
                "description": "根据回答动态调整，但仍保底覆盖核心能力。",
            },
        ],
    },
}

# Compatibility dimensions for clients built against the first style API.
_LEGACY_DIMENSION_DEFINITIONS = {
    "control": {
        "label": "对话控制",
        "options": [
            {
                "value": "dominant",
                "label": "主导面试型",
                "description": "主动控制节奏、追问方向和主题切换。",
            },
            {
                "value": "listener",
                "label": "主要倾听型",
                "description": "先让候选人完整表达，再从回答中选择重点。",
            },
        ],
    },
    "plan_adherence": {
        "label": "流程自由度",
        "options": [
            {
                "value": "structured",
                "label": "循规蹈矩型",
                "description": "按计划顺序稳定覆盖核心主题。",
            },
            {
                "value": "flexible",
                "label": "随心所欲型",
                "description": "根据回答动态调整，但仍保底覆盖核心能力。",
            },
        ],
    },
}

_INITIATIVE_RULES = {
    "leading": {
        "label": "主导面试型",
        "summary": "主动掌握节奏，用简短问题推进核验。",
        "traits": ["主动控制节奏", "偏题时及时拉回", "优先追问高价值证据"],
        "prompt": "你主动控制面试节奏，用简短、直接的问题推进核验；回答偏题时礼貌地拉回当前目标，并在证据足够后主动切换主题。",
    },
    "listening": {
        "label": "主要倾听型",
        "summary": "给候选人完整展开空间，再聚焦最重要的缺口。",
        "traits": ["不抢断叙述", "先听完整表达", "只追问最关键的核验点"],
        "prompt": "优先让候选人完整展开，不模拟打断；回答结束后只选择最重要的证据缺口追问，不因停顿或口头语施压。",
    },
}

_TONE_RULES = {
    "strict": {
        "label": "严格型",
        "summary": "证据标准明确，持续核验事实、因果与边界。",
        "prompt": "对笼统主张优先要求事实、机制、指标、对照、个人贡献和适用边界；严格只表示证据要求高，不表示攻击、羞辱或武断下结论。",
    },
    "friendly": {
        "label": "和蔼型",
        "summary": "保持核验标准，同时降低压迫感。",
        "prompt": "使用简短、自然、非评价性的过渡和澄清，降低压迫感但不暗示答案、不教学，也不降低事实和证据标准。",
    },
}

_STRUCTURE_RULES = {
    "structured": {
        "label": "循规蹈矩型",
        "summary": "按计划顺序推进，稳定覆盖每个核心主题。",
        "prompt": "严格按照计划中的主题顺序推进；当前主题证据足够或达到追问上限后进入下一个未覆盖主题，不随意跳转。",
        "topic_order": "sequential",
        "max_followups_per_topic": 2,
        "max_followups_total": 4,
    },
    "adaptive": {
        "label": "随心所欲型",
        "summary": "跟随回答中的高价值线索灵活重排，但保留核心覆盖。",
        "prompt": "可以根据回答重排主题、沿高价值线索深挖或跳过已充分证明的重复内容；必须逐步补足专业基础、项目深度、科研思维、方向匹配和表达反思等核心维度，不能变成随机闲聊。",
        "topic_order": "adaptive",
        "max_followups_per_topic": 3,
        "max_followups_total": 4,
    },
}

# Stable IDs/names make a completed run understandable in logs and in a
# future UI, while the three dimensions remain independently selectable.
_PRESET_META: dict[tuple[str, str, str], tuple[str, str]] = {
    ("leading", "strict", "structured"): ("structured_examiner", "结构化审查官"),
    ("leading", "strict", "adaptive"): ("investigative_examiner", "追踪审查官"),
    ("leading", "friendly", "structured"): ("guided_interviewer", "稳健引导官"),
    ("leading", "friendly", "adaptive"): ("adaptive_guide", "灵活引导官"),
    ("listening", "strict", "structured"): ("patient_examiner", "耐心核验官"),
    ("listening", "strict", "adaptive"): ("deep_dive_examiner", "深潜核验官"),
    ("listening", "friendly", "structured"): ("supportive_listener", "温和倾听官"),
    ("listening", "friendly", "adaptive"): ("open_explorer", "开放探索官"),
}


def _legacy_value(raw: Any, *, field: str) -> str:
    if not isinstance(raw, str):
        raise ValueError(f"无效的面试官风格：{field}")
    return raw


def _canonical_selection(selection: Mapping[str, Any] | None) -> dict[str, str]:
    """Normalize canonical and first-generation API spellings."""

    if hasattr(selection, "model_dump"):
        selection = selection.model_dump()
    raw = dict(selection or {})

    if "control" in raw:
        control = _legacy_value(raw["control"], field="control")
        mapped = {"dominant": "leading", "listener": "listening"}.get(control, control)
        if "initiative" in raw and raw["initiative"] != mapped:
            raise ValueError("面试官风格的对话控制字段冲突。")
        raw["initiative"] = mapped
    if "plan_adherence" in raw:
        adherence = _legacy_value(raw["plan_adherence"], field="plan_adherence")
        mapped = {"flexible": "adaptive"}.get(adherence, adherence)
        if "structure" in raw and raw["structure"] != mapped:
            raise ValueError("面试官风格的流程字段冲突。")
        raw["structure"] = mapped

    values: dict[str, str] = {}
    for key, allowed, default in (
        ("initiative", set(_INITIATIVE_RULES), DEFAULT_SELECTION["initiative"]),
        ("tone", set(_TONE_RULES), DEFAULT_SELECTION["tone"]),
        ("structure", set(_STRUCTURE_RULES), DEFAULT_SELECTION["structure"]),
    ):
        value = raw.get(key, default)
        if not isinstance(value, str) or value not in allowed:
            raise ValueError("无效的面试官风格组合。")
        values[key] = value
    return values


def _preset_definition(selection: Mapping[str, Any] | None) -> dict[str, Any]:
    canonical = _canonical_selection(selection)
    key = (canonical["initiative"], canonical["tone"], canonical["structure"])
    preset_id, preset_name = _PRESET_META[key]
    initiative_rule = _INITIATIVE_RULES[canonical["initiative"]]
    tone_rule = _TONE_RULES[canonical["tone"]]
    structure_rule = _STRUCTURE_RULES[canonical["structure"]]
    return {
        **canonical,
        "version": STYLE_VERSION,
        "preset_id": preset_id,
        "name": preset_name,
        "summary": "；".join((initiative_rule["summary"], tone_rule["summary"], structure_rule["summary"])),
        "traits": list(dict.fromkeys([
            *initiative_rule["traits"],
            "按计划顺序稳定推进" if canonical["structure"] == "structured" else "可根据高价值线索重排",
        ])),
        "prompt_addendum": "\n".join((initiative_rule["prompt"], tone_rule["prompt"], structure_rule["prompt"])),
        "planner_addendum": "\n".join((initiative_rule["prompt"], tone_rule["prompt"], structure_rule["prompt"])),
        "policy": {
            "topic_order": structure_rule["topic_order"],
            "max_followups_per_topic": structure_rule["max_followups_per_topic"],
            "max_followups_total": structure_rule["max_followups_total"],
        },
    }


def snapshot_for_selection(selection: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Resolve a client selection to an immutable server-owned snapshot."""

    snapshot = _preset_definition(selection)
    # Keep compatibility fields in the stored snapshot so old operational
    # tooling can still identify the same combination.
    snapshot["control"] = "dominant" if snapshot["initiative"] == "leading" else "listener"
    snapshot["plan_adherence"] = "flexible" if snapshot["structure"] == "adaptive" else "structured"
    return snapshot


def default_snapshot() -> dict[str, Any]:
    return snapshot_for_selection(DEFAULT_SELECTION)


def _public_snapshot(snapshot: Mapping[str, Any] | None) -> dict[str, Any]:
    """Validate a snapshot while retaining its immutable display metadata."""

    selected = snapshot_for_selection(snapshot) if snapshot else default_snapshot()
    if not snapshot:
        return selected
    for key in ("version", "preset_id", "name", "summary"):
        value = snapshot.get(key)
        if isinstance(value, str) and value.strip():
            selected[key] = value
    traits = snapshot.get("traits")
    if isinstance(traits, list) and all(isinstance(item, str) for item in traits):
        selected["traits"] = list(traits)
    return selected


def public_style(snapshot: Mapping[str, Any] | None = None) -> dict[str, Any]:
    selected = _public_snapshot(snapshot)
    return {
        key: selected[key]
        for key in (
            "version",
            "preset_id",
            "initiative",
            "tone",
            "structure",
            "control",
            "plan_adherence",
            "name",
            "summary",
            "traits",
        )
    }


def catalog() -> dict[str, Any]:
    presets = [
        public_style({"initiative": initiative, "tone": tone, "structure": structure})
        for initiative in ("leading", "listening")
        for tone in ("strict", "friendly")
        for structure in ("structured", "adaptive")
    ]
    dimensions = {**_DIMENSION_DEFINITIONS, **_LEGACY_DIMENSION_DEFINITIONS}
    return {
        "version": STYLE_VERSION,
        "default_preset_id": default_snapshot()["preset_id"],
        "default_selection": dict(DEFAULT_SELECTION),
        "dimensions": dimensions,
        "presets": presets,
    }


STYLE_BY_ID = {
    preset["preset_id"]: snapshot_for_selection(preset)
    for preset in catalog()["presets"]
}
