#!/usr/bin/env python3
"""
经验库管理模块
负责树状经验库 (my_experiences.json) 的增删改查
"""

import json
import os
from datetime import datetime
from backup_utils import backup_file

EXP_PATH = os.path.expanduser("~/AI/comfydatabase/my_experiences.json")

# 默认的经验库结构（空库）
DEFAULT_EXP = {
    "_meta": {
        "version": "1.1",
        "last_updated": "",
        "deprecated_models": []
    }
    # 系列会动态添加，这里只给出空模板
}

def load_experiences():
    """加载经验库，如果不存在则创建默认结构"""
    if not os.path.exists(EXP_PATH):
        save_experiences(DEFAULT_EXP)
        return DEFAULT_EXP
    with open(EXP_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_experiences(exp):
    """保存经验库并更新元数据时间戳"""
    backup_file(EXP_PATH)
    exp.setdefault("_meta", {})["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(EXP_PATH, 'w', encoding='utf-8') as f:
        json.dump(exp, f, ensure_ascii=False, indent=2)

def get_node(exp, family, model=None):
    """
    根据系列和模型（可选）获取经验节点字典。
    如果 model=None 或 model='_common'，返回系列的 _common 节点。
    否则返回具体模型节点。
    节点不存在时会自动创建。
    """
    if family not in exp:
        exp[family] = {}
    family_data = exp[family]
    
    if model is None or model == "_common":
        if "_common" not in family_data:
            family_data["_common"] = {
                "prompt_template": [],
                "model_characteristics": [],
                "keyword_tips": [],
                "param_heuristics": [],
                "pitfalls": []
            }
        return family_data["_common"]
    else:
        if model not in family_data:
            family_data[model] = {
                "prompt_template": [],
                "model_characteristics": [],
                "keyword_tips": [],
                "param_heuristics": [],
                "pitfalls": []
            }
        return family_data[model]

# 经验条目的默认结构（用于规范化）
EXP_ENTRY_TEMPLATE = {
    "content": "",
    "confidence": 0.5,
    "source": "tested",      # tested, community, inferred, subjective
    "tags": [],
    "last_validated": datetime.now().strftime("%Y-%m-%d")
}

# source 的合法枚举值
VALID_SOURCES = {"tested", "community", "inferred", "subjective"}

def normalize_source(source):
    """将非标准 source 值自动映射为标准枚举值"""
    if source in VALID_SOURCES:
        return source
    source_lower = source.lower()
    if "反馈" in source_lower or "test" in source_lower or "确认" in source_lower:
        return "tested"
    if "社区" in source_lower or "公认" in source_lower or "community" in source_lower:
        return "community"
    if "推断" in source_lower or "推测" in source_lower or "infer" in source_lower:
        return "inferred"
    if "主观" in source_lower or "偏好" in source_lower or "个人" in source_lower:
        return "subjective"
    # 兜底：无法判断时，降级为 inferred
    return "inferred"

def create_entry(content, confidence=0.5, source="tested", tags=None):
    """创建一个规范的经验条目"""
    return {
        "content": content,
        "confidence": confidence,
        "source": normalize_source(source),
        "tags": tags if tags is not None else [],
        "last_validated": datetime.now().strftime("%Y-%m-%d")
    }

def validate_category(category):
    """验证经验类别是否合法"""
    valid = ["prompt_template", "model_characteristics", "keyword_tips", "param_heuristics", "pitfalls"]
    if category not in valid:
        raise ValueError(f"无效类别：{category}，必须是 {valid} 之一")
    return category

def manage_experiences_action(action, family, model, category, experience_str=None, index=-1, target="model"):
    """
    底层操作函数，可供 MCP 工具调用。
    参数：
        action: 'add', 'update', 'delete', 'list'
        family: 系列名，如 'illustrious'
        model: 模型名，如 'wai_v170' 或 '_common'
        category: 经验类别
        experience_str: 经验内容的 JSON 字符串 (用于 add/update)
        index: 要操作的条目索引 (用于 update/delete)
        target: 已弃用，保留兼容，实际由 model 参数决定写入哪个节点
    """
    try:
        # ========== 参数校验 ==========
        if not family or not family.strip():
            return "❌ family 不能为空，请指定系列名称（如 'illustrious', 'pony'）。"
        if not model or not model.strip():
            return "❌ model 不能为空，请指定模型名称或 '_common'。"
        allowed_families = ["illustrious", "pony"]  # 可在此扩展新系列
        if family not in allowed_families:
            return f"❌ 未知系列：{family}，当前支持的系列：{', '.join(allowed_families)}"
        
        exp = load_experiences()
        
        if action == "list":
            # 列出所有经验
            output_lines = []
            for fam, models in exp.items():
                if fam == "_meta":
                    continue
                for mod, cats in models.items():
                    output_lines.append(f"【{fam}/{mod}】")
                    for cat, items in cats.items():
                        for i, item in enumerate(items):
                            output_lines.append(
                                f"  [{cat}][{i}] confidence={item.get('confidence', '?')} "
                                f"| {item.get('content', '')[:80]}..."
                            )
            return "\n".join(output_lines) if output_lines else "📭 经验库为空。"
        
        # 确定操作的具体节点
        if model == "_common" or model is None:
            node = get_node(exp, family, model=None)  # 获取 _common
            actual_model = "_common"
        else:
            node = get_node(exp, family, model)
            actual_model = model
        
        category = validate_category(category)
        items = node.setdefault(category, [])
        
        if action == "add":
            if not experience_str:
                return "❌ 添加经验需要提供 experience 参数。"
            # 解析经验数据，可以是完整的条目对象或仅内容字符串
            try:
                exp_data = json.loads(experience_str)
            except json.JSONDecodeError:
                # 如果是纯文本，自动包装为条目对象
                entry = create_entry(experience_str)
            else:
                if isinstance(exp_data, dict):
                    entry = {**EXP_ENTRY_TEMPLATE, **exp_data}
                    entry["source"] = normalize_source(entry.get("source", "tested"))
                    entry["last_validated"] = entry.get("last_validated", datetime.now().strftime("%Y-%m-%d"))
                else:
                    return "❌ experience 必须是 JSON 对象或纯文本字符串。"
            items.append(entry)
            msg = f"✅ 已添加经验到【{family}/{actual_model}】的【{category}】"
            
        elif action == "update":
            if index < 0 or index >= len(items):
                return f"❌ 索引 {index} 超出范围，当前有 {len(items)} 条记录。"
            if not experience_str:
                return "❌ 更新经验需要提供 experience 参数。"
            try:
                exp_data = json.loads(experience_str)
            except json.JSONDecodeError:
                return "❌ 更新经验时 experience 必须是 JSON 对象。"
            if isinstance(exp_data, dict):
                # 合并更新，保留原有字段
                old_entry = items[index]
                new_entry = {**old_entry, **exp_data}
                new_entry["last_validated"] = datetime.now().strftime("%Y-%m-%d")
                items[index] = new_entry
            else:
                return "❌ experience 必须是 JSON 对象。"
            msg = f"✅ 已更新【{family}/{actual_model}】的【{category}】第 {index} 条经验"
            
        elif action == "delete":
            if index < 0 or index >= len(items):
                return f"❌ 索引 {index} 超出范围，当前有 {len(items)} 条记录。"
            removed = items.pop(index)
            msg = f"✅ 已删除【{family}/{actual_model}】的【{category}】第 {index} 条经验：{removed.get('content', '')[:80]}..."
            
        else:
            return "❌ 无效操作，支持 add, update, delete, list。"
        
        save_experiences(exp)
        return msg
    except Exception as e:
        return f"❌ 操作失败：{str(e)}"