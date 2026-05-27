#!/usr/bin/env python3
"""
知识库管理模块
负责偏好库 (my_preferences.json) 和作品档案库 (my_art_archive.json) 的读写
"""

import json
import subprocess
import os
import numpy as np
from datetime import datetime
from backup_utils import backup_file

PREF_PATH = os.path.expanduser("~/AI/comfydatabase/usr_preferences.json")
ARCHIVE_PATH = os.path.expanduser("~/AI/comfydatabase/art_archive.json")


# ==================== 偏好库 ====================
def load_preferences():
    """加载偏好库，如果不存在则返回默认结构"""
    if not os.path.exists(PREF_PATH):
        default = {
            "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "favorite_elements": {},
            "style_weights": {},
            "quality_standards": {
                "positive_tags": ["masterpiece", "best quality"],
                "negative_tags": ["lowres", "bad anatomy"]
            },
            "prompt_patterns": {}
        }
        save_preferences(default)
        return default
    with open(PREF_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_preferences(prefs):
    backup_file(PREF_PATH)
    prefs["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(PREF_PATH, 'w', encoding='utf-8') as f:
        json.dump(prefs, f, ensure_ascii=False, indent=2)


def update_preference(category, key, value):
    """更新偏好库的某个字段"""
    prefs = load_preferences()
    if category not in prefs:
        prefs[category] = {}
    prefs[category][key] = value
    save_preferences(prefs)


# ==================== 作品档案库 ====================
def load_archive():
    if not os.path.exists(ARCHIVE_PATH):
        return []
    with open(ARCHIVE_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_archive(archive):
    backup_file(ARCHIVE_PATH)
    with open(ARCHIVE_PATH, 'w', encoding='utf-8') as f:
        json.dump(archive, f, ensure_ascii=False, indent=2)


def add_artwork(description, liked_elements, effective_prompts, model_used, prompt_style):
    archive = load_archive()
    record = {
        "id": len(archive) + 1,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "description": description,
        "liked_elements": liked_elements,
        "effective_prompts": effective_prompts,
        "model_used": model_used,
        "prompt_style": prompt_style
    }
    archive.append(record)
    save_archive(archive)
    return record["id"]


def search_archive(query="", score_min=None, score_max=None, date_from=None, date_to=None, elements=None, top_n=10):
    archive = load_archive()
    results = []
    
    # 将查询拆分为关键词列表
    if query:
        keywords = query.lower().split()
    else:
        keywords = []
    
    for item in archive:
        # 关键词匹配：所有关键词必须至少出现在描述或某个元素中
        if keywords:
            # 构建这个记录的所有可搜索文本
            searchable_text = item["description"].lower()
            for elem in item.get("liked_elements", []):
                searchable_text += " " + elem.lower()
            
            # 检查是否所有关键词都出现
            all_match = True
            for kw in keywords:
                if kw not in searchable_text:
                    all_match = False
                    break
            
            if not all_match:
                continue
        
        # 评分筛选（保持不变）
        score = item.get("ds_evaluation", {}).get("score")
        if score is not None:
            if score_min is not None and score < score_min:
                continue
            if score_max is not None and score > score_max:
                continue
        
        # 日期筛选（保持不变）
        timestamp = item.get("timestamp", "")
        if date_from and timestamp < date_from:
            continue
        if date_to and timestamp > date_to + " 23:59:59":
            continue
        
        # 元素筛选（保持不变）
        if elements:
            item_elements = [e.lower() for e in item.get("liked_elements", [])]
            if not any(e.lower() in item_elements for e in elements):
                continue
        
        results.append(item)
        if len(results) >= top_n:
            break
    
    return results

def get_embedding(text: str, is_query: bool = False) -> list[float]:
    """调用 Ollama 的 nomic-embed-text-v2-moe 模型，将文本转为向量"""
    # 根据官方建议添加前缀
    if is_query:
        text = f"search_query: {text}"
    else:
        text = f"search_document: {text}"
        
    result = subprocess.run(
        ["ollama", "run", "nomic-embed-text-v2-moe"],
        input=text,
        capture_output=True,
        text=True,
        timeout=30
    )
    if result.returncode != 0:
        raise RuntimeError(f"Embedding failed: {result.stderr}")
    # 只取前256维，节省存储和计算
    embedding = json.loads(result.stdout.strip())
    return embedding[:256] 


def build_search_text(record: dict) -> str:
    """从记录中提取用于搜索的文本"""
    parts = [
        record.get("description", ""),
        " ".join(record.get("liked_elements", [])),
        " ".join(record.get("effective_prompts", [])),
        record.get("prompt_style", "")
    ]
    return " ".join(parts)


def ensure_embeddings(archive_path: str):
    """为档案库中所有缺少嵌入的记录生成向量"""
    archive = load_archive()
    updated = False
    for item in archive:
        if "embedding" not in item:
            text = build_search_text(item)
            item["embedding"] = get_embedding(text)
            updated = True
    if updated:
        save_archive(archive)


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """计算两个向量的余弦相似度"""
    a = np.array(a)
    b = np.array(b)
    return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))


def semantic_search(query: str, top_n: int = 5, score_min: float = None, score_max: float = None):
    """语义搜索"""
    ensure_embeddings(ARCHIVE_PATH)  # 确保所有记录都有嵌入
    query_embedding = get_embedding(query)
    archive = load_archive()
    
    scored = []
    for item in archive:
        # 评分筛选
        score = item.get("ds_evaluation", {}).get("score")
        if score_min is not None and score is not None and score < score_min:
            continue
        if score_max is not None and score is not None and score > score_max:
            continue
        
        similarity = cosine_similarity(query_embedding, item["embedding"])
        scored.append((similarity, item))
    
    # 按相似度降序
    scored.sort(key=lambda x: x[0], reverse=True)
    return [item for _, item in scored[:top_n]]