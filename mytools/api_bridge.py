#!/usr/bin/env python3
"""
ComfyUI MCP Bridge — 使用 API 格式工作流
在 Cherry Studio 中配置 MCP 服务器，调用 generate_image_tool 工具。
"""

from __future__ import annotations
import json
import os
import random
import time
import base64
import requests
import datetime
from mcp.server.fastmcp import FastMCP

# ========== 导入知识库模块 ==========
import sys
sys.path.insert(0, os.path.dirname(__file__))
from my_knowledge_base import (
    load_preferences, 
    save_preferences, 
    search_archive, 
    load_archive, 
    save_archive, 
    semantic_search, 
    get_embedding, 
    build_search_text
)

# ==================== 配置区 ====================
COMFYUI_API_URL = "http://127.0.0.1:8188"
WORKFLOW_PATH = os.path.expanduser("~/AI/ComfyUI/user/default/workflows/illustriousapi.json")  # API 格式文件
TIMEOUT = 600

# ==================== FastMCP 实例 ====================
mcp = FastMCP("ComfyUI Bridge")

# ==================== ComfyUI 调用逻辑（适配 API 格式） ====================
from typing import Tuple
def modify_api_prompt(prompt_text: str, negative_prompt_text: str = "") -> Tuple[dict, int]:
    """修改工作流，返回修改后的 prompt 和实际使用的种子"""
    with open(WORKFLOW_PATH, "r", encoding="utf-8") as f:
        prompt = json.load(f)

    seed = random.randint(0, 2**63 - 1)

    # 正面提示词 -> 节点 "3"
    if "3" in prompt and "inputs" in prompt["3"]:
        prompt["3"]["inputs"]["text"] = prompt_text

    # 负面提示词 -> 节点 "4"（可选）
    if "4" in prompt and "inputs" in prompt["4"] and negative_prompt_text.strip():
        prompt["4"]["inputs"]["text"] = negative_prompt_text

    # 将同一个种子赋给两个 KSampler
    for ksampler_id in ["5", "14"]:
        node = prompt.get(ksampler_id)
        if node and node["class_type"] == "KSampler" and "seed" in node["inputs"]:
            node["inputs"]["seed"] = seed

    return prompt, seed

def queue_prompt(prompt: dict) -> str:
    resp = requests.post(f"{COMFYUI_API_URL}/prompt", json={"prompt": prompt})
    if resp.status_code != 200:
        raise RuntimeError(f"ComfyUI 提交失败: {resp.text}")
    return resp.json()["prompt_id"]

def generate_image(prompt_text: str, negative_prompt_text: str = "") -> dict:
    prompt, seed = modify_api_prompt(prompt_text, negative_prompt_text)
    prompt_id = queue_prompt(prompt)

    start = time.time()
    while time.time() - start < TIMEOUT:
        time.sleep(1)
        history_resp = requests.get(f"{COMFYUI_API_URL}/history/{prompt_id}")
        if history_resp.status_code != 200:
            continue
        history = history_resp.json()
        if prompt_id not in history:
            continue
        outputs = history[prompt_id]["outputs"]
        for node_id, output in outputs.items():
            if "images" in output:
                for img in output["images"]:
                    filename = img["filename"]
                    subfolder = img.get("subfolder", "")
                    if subfolder:
                        view_url = f"http://127.0.0.1:8189/{subfolder}/{filename}"
                    else:
                        view_url = f"http://127.0.0.1:8189/{filename}"
                    
                    # 提取模型名称
                    with open(WORKFLOW_PATH, "r", encoding="utf-8") as f:
                        workflow_data = json.load(f)
                    model_used = workflow_data.get("1", {}).get("inputs", {}).get("ckpt_name", "unknown")
                    
                    return {
                        "image_url": view_url,
                        "seed": seed,
                        "model_used": model_used
                    }
    raise TimeoutError(f"图片生成超时（{TIMEOUT}秒）")

# ==================== MCP 工具 ====================

@mcp.tool()
async def generate_image_tool(prompt_en: str, negative_prompt: str = "", num_images: int = 1) -> str:
    """
    根据英文提示词生成二次元图片，可一次生成多张。
    返回 JSON 字符串，包含每张图片的 URL、种子、模型名称等信息。
    """
    if not prompt_en.strip():
        return json.dumps({"error": "正面提示词不能为空。"})

    num_images = max(1, min(num_images, 4))
    try:
        import asyncio
        loop = asyncio.get_running_loop()

        images_info = []
        for i in range(num_images):
            result = await loop.run_in_executor(None, generate_image, prompt_en, negative_prompt)
            images_info.append({
                "index": i + 1,
                "url": result["image_url"],
                "seed": result["seed"],
                "model_used": result["model_used"]
            })

        response = {
            "status": "success",
            "images": images_info,
            "prompt_en": prompt_en,
            "negative_prompt": negative_prompt
        }
        return json.dumps(response, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
async def evaluate_artwork(
    description: str,
    liked_elements: str,
    effective_prompts: str,
    model_used: str,
    prompt_style: str,
    score: float,
    reason: str,
    image_url: str = "",
    seed: int = 0
) -> str:
    """
    由你调用，选择性地记录有价值的作品，并附上评分、理由、图片链接和种子。
    同时自动生成向量嵌入，以便后续语义检索。
    """
    try:
        elements = [e.strip() for e in liked_elements.split(",") if e.strip()]
        prompts = [p.strip() for p in effective_prompts.split(",") if p.strip()]
        archive = load_archive()
        
        # 构建用于嵌入的文本
        embedding_text = build_search_text({
            "description": description,
            "liked_elements": elements,
            "effective_prompts": prompts,
            "prompt_style": prompt_style
        })
        
        # 生成向量嵌入
        embedding = get_embedding(embedding_text, is_query=False)
        
        record = {
            "id": len(archive) + 1,
            "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "description": description,
            "liked_elements": elements,
            "effective_prompts": prompts,
            "model_used": model_used,
            "prompt_style": prompt_style,
            "image_url": image_url,
            "seed": seed,
            "ds_evaluation": {
                "score": score,
                "reason": reason
            },
            "embedding": embedding[:256]  # 用 256 维节省存储
        }
        
        archive.append(record)
        save_archive(archive)
        
        # 实时微调偏好库
        prefs = load_preferences()
        for elem in elements:
            prefs["favorite_elements"][elem] = prefs["favorite_elements"].get(elem, 0) + 1
        save_preferences(prefs)
        
        return f"✅ 已记录作品 #{record['id']}，评分 {score}/10。图片链接：{image_url}，种子：{seed}"
    except Exception as e:
        return f"❌ 记录失败：{str(e)}"


@mcp.tool()
async def get_usr_preferences() -> str:
    """读取用户当前的偏好库"""
    prefs = load_preferences()
    return json.dumps(prefs, ensure_ascii=False, indent=2)


@mcp.tool()
async def search_archive(
    query: str = "",
    score_min: float = None,
    score_max: float = None,
    date_from: str = "",
    date_to: str = "",
    elements: str = "",
    top_n: int = 10,
    use_semantic: bool = True  # 新增：是否使用语义搜索
) -> str:
    """
    在作品档案库中检索有记录的历史作品。
    - 默认使用语义搜索，用自然语言描述即可。
    - 支持按评分、日期、元素等维度精确筛选。
    - 返回最相关的作品列表，包含评分和喜欢元素。
    """
    try:
        if use_semantic and query:
            # 语义搜索模式
            results = semantic_search(
                query=query,
                top_n=top_n,
                score_min=score_min,
                score_max=score_max
            )
            # 如果需要日期或元素筛选，在语义结果上再过滤
            if date_from or date_to or elements:
                filtered = []
                for item in results:
                    # 日期筛选
                    timestamp = item.get("timestamp", "")
                    if date_from and timestamp < date_from:
                        continue
                    if date_to and timestamp > date_to + " 23:59:59":
                        continue
                    # 元素筛选
                    if elements:
                        elem_list = [e.strip().lower() for e in elements.split(",")]
                        item_elements = [e.lower() for e in item.get("liked_elements", [])]
                        if not any(e in item_elements for e in elem_list):
                            continue
                    filtered.append(item)
                results = filtered[:top_n]
        else:
            # 回退到关键词搜索
            results = search_archive(
                query=query,
                score_min=score_min,
                score_max=score_max,
                date_from=date_from if date_from else None,
                date_to=date_to if date_to else None,
                elements=[e.strip() for e in elements.split(",")] if elements else None,
                top_n=top_n
            )
        
        if not results:
            return "📭 没有找到符合条件的作品。"
        
        output = []
        for item in results:
            score = item.get("ds_evaluation", {}).get("score", "N/A")
            output.append(
                f"#{item['id']} | {item['timestamp']} | {item['description']}\n"
                f"   评分: {score}/10 | 喜欢: {', '.join(item.get('liked_elements', []))}"
            )
        return "📋 搜索结果：\n" + "\n".join(output)
    except Exception as e:
        return f"❌ 搜索失败：{str(e)}"


@mcp.tool()
async def update_usr_preferences(updates: str) -> str:
    """
    由你自主调用，用于写入、修改或删除用户偏好库的任何字段。
    updates: JSON 字符串，包含要更新的键值对。
    当某个字段的值为 null 时，会删除该字段及其所有子内容。
    示例：
    {
        "favorite_elements": {"floating_hair": 2, "god_rays": 1},
        "quality_standards": {"positive_tags": ["masterpiece", "best quality"]},
        "style_weights": null   // 删除整个 style_weights 字段
    }
    """
    try:
        import json
        updates_dict = json.loads(updates)
        prefs = load_preferences()
        
        def deep_merge(base, update):
            for key, value in update.items():
                if value is None:
                    # 值为 null，删除该键
                    if key in base:
                        del base[key]
                elif key in base and isinstance(base[key], dict) and isinstance(value, dict):
                    deep_merge(base[key], value)
                else:
                    base[key] = value
        
        deep_merge(prefs, updates_dict)
        save_preferences(prefs)
        return "✅ 偏好库已更新。"
    except Exception as e:
        return f"❌ 更新失败：{str(e)}"
    

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))
from experience_manager import manage_experiences_action

@mcp.tool()
async def manage_experiences(
    action: str,
    family: str = "",
    model: str = "_common",
    category: str = "",
    experience: str = "",
    index: int = -1
) -> str:
    """
    经验库管理（支持增删改查），用于记录你学习到的经验。
    - action: 'add', 'update', 'delete', 'list'
    - family: 系列名，如 'illustrious', 'pony'
    - model: 模型名，如 'wai_v170'，其中 '_common' 表示系列通用经验
    - category: 经验类别，如 'prompt_template', 'keyword_tips', 'param_heuristics', 'model_characteristics', 'pitfalls'
    - experience: 经验内容的 JSON 字符串（对 add/update 必需）。可包含 content, confidence, source, tags 等字段，也可以直接给纯文本
        其中 source 字段必须是以下标准枚举值之一：
        - "tested": 实际生成验证过
        - "community": 社区公认经验
        - "inferred": 从模型架构/论文推断
        - "subjective": 个人审美偏好
    - index: 要修改或删除的条目索引（对 update/delete 必需）
    """
    return manage_experiences_action(action, family, model, category, experience, index)

# ==================== 启动服务 ====================
if __name__ == "__main__":
    mcp.run(transport="streamable-http")