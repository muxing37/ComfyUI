#!/usr/bin/env python3
"""
ComfyUI MCP Bridge — 使用 API 格式工作流
在 Cherry Studio 中配置 MCP 服务器，调用 generate_image_tool 工具。
"""

import json
import os
import random
import time
import base64
import requests
from mcp.server.fastmcp import FastMCP

# ==================== 配置区 ====================
COMFYUI_API_URL = "http://127.0.0.1:8188"
WORKFLOW_PATH = os.path.expanduser("~/AI/ComfyUI/user/default/workflows/illustriousapi.json")  # API 格式文件
TIMEOUT = 600

# ==================== FastMCP 实例 ====================
mcp = FastMCP("ComfyUI Bridge")

# ==================== ComfyUI 调用逻辑（适配 API 格式） ====================
def modify_api_prompt(prompt_text: str, negative_prompt_text: str = "") -> dict:
    """加载 API 格式 prompt，修改正面/负面提示词，并随机化种子"""
    with open(WORKFLOW_PATH, "r", encoding="utf-8") as f:
        prompt = json.load(f)

    # 正面提示词 -> 节点 "3"
    if "3" in prompt and "inputs" in prompt["3"]:
        prompt["3"]["inputs"]["text"] = prompt_text

    # 负面提示词 -> 节点 "4"（可选）
    if "4" in prompt and "inputs" in prompt["4"] and negative_prompt_text.strip():
        prompt["4"]["inputs"]["text"] = negative_prompt_text

    # 随机化两个 KSampler 的种子
    for ksampler_id in ["5", "14"]:
        node = prompt.get(ksampler_id)
        if node and node["class_type"] == "KSampler":
            if "seed" in node["inputs"]:
                node["inputs"]["seed"] = random.randint(0, 2**63 - 1)

    return prompt

def queue_prompt(prompt: dict) -> str:
    resp = requests.post(f"{COMFYUI_API_URL}/prompt", json={"prompt": prompt})
    if resp.status_code != 200:
        raise RuntimeError(f"ComfyUI 提交失败: {resp.text}")
    return resp.json()["prompt_id"]

def generate_image(prompt_text: str, negative_prompt_text: str = "") -> str:
    prompt = modify_api_prompt(prompt_text, negative_prompt_text)
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
                    # 构造本地图片服务的 URL
                    if subfolder:
                        view_url = f"http://127.0.0.1:8189/{subfolder}/{filename}"
                    else:
                        view_url = f"http://127.0.0.1:8189/{filename}"
                    return view_url
    raise TimeoutError(f"图片生成超时（{TIMEOUT}秒）")

# ==================== MCP 工具 ====================
@mcp.tool()
async def generate_image_tool(prompt_en: str, negative_prompt: str = "", num_images: int = 1) -> str:
    """
    根据英文提示词生成二次元图片，可一次生成多张。
    参数：
        prompt_en: 正面提示词
        negative_prompt: 负面提示词（可选）
        num_images: 生成图片数量，默认1，最大4
    """
    if not prompt_en.strip():
        return "错误：正面提示词不能为空。"

    # 限制最大数量，防止误操作
    num_images = max(1, min(num_images, 4))

    try:
        import asyncio
        loop = asyncio.get_running_loop()

        urls = []
        for i in range(num_images):
            # 每次调用 generate_image 都会随机种子，保证变体不同
            img_url = await loop.run_in_executor(None, generate_image, prompt_en, negative_prompt)
            urls.append(f"![图{i+1}]({img_url})")

        if num_images == 1:
            return urls[0]
        else:
            return "\n".join(urls)
    except Exception as e:
        return f"生成失败：{str(e)}"

# ==================== 启动服务 ====================
if __name__ == "__main__":
    mcp.run(transport="streamable-http")