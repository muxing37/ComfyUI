#!/usr/bin/env python3
"""
极简本地图片服务器，用于 Cherry Studio 跨域加载 ComfyUI 生成的图片。
监听 8189 端口，根目录为 ComfyUI 输出目录。
"""

import http.server
import os

# ComfyUI 输出目录（根据你的实际路径修改）
OUTPUT_DIR = os.path.expanduser("~/AI/ComfyUI/output")

class CORSHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        # 设置服务器的根目录为 ComfyUI 输出目录
        super().__init__(*args, directory=OUTPUT_DIR, **kwargs)

    def end_headers(self):
        # 允许所有来源访问
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.end_headers()

if __name__ == "__main__":
    server = http.server.HTTPServer(("0.0.0.0", 8189), CORSHTTPRequestHandler)
    print(f"图片服务已启动，监听 0.0.0.0:8189，根目录：{OUTPUT_DIR}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("图片服务已停止")
        server.server_close()