#!/usr/bin/env python3
"""自动备份工具"""

import os
import shutil
from datetime import datetime

BACKUP_DIR = os.path.expanduser("~/AI/comfydatabase/knowledge_backups")

def backup_file(filepath, max_backups=20):
    """
    在保存前备份文件到备份目录。
    - filepath: 要备份的文件路径
    - max_backups: 该文件的最大备份数量，超出时删除最旧的
    """
    if not os.path.exists(filepath):
        return  # 文件不存在，无需备份
    
    os.makedirs(BACKUP_DIR, exist_ok=True)
    
    # 生成备份文件名：原文件名 + 时间戳
    filename = os.path.basename(filepath)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_name = f"{filename}.{timestamp}.bak"
    backup_path = os.path.join(BACKUP_DIR, backup_name)
    
    # 复制文件
    shutil.copy2(filepath, backup_path)
    
    # 清理旧备份：保留最近的 max_backups 个
    # 找出所有该文件的备份，按时间排序
    all_backups = sorted(
        [f for f in os.listdir(BACKUP_DIR) if f.startswith(filename) and f.endswith(".bak")],
        reverse=True
    )
    for old_backup in all_backups[max_backups:]:
        os.remove(os.path.join(BACKUP_DIR, old_backup))