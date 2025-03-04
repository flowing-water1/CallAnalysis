import os
from typing import Dict, Any, List

# API配置
XFYUN_CONFIG = {
    "lfasr_host": "https://raasr.xfyun.cn/v2/api",
    "api_upload": "/upload",
    "api_get_result": "/getResult",
    "appid": "8d2e895b",
    "secret_key": "8d5c02bd69345f504761da6b818b423f"
}

# OpenAI配置
OPENAI_CONFIG = {
    "api_key": "sk-OdCoqKCvctCJaPHUF2Ea9eF9C01940D8Aa7cB82889EaE165",
    "api_base": "https://api.pumpkinaigc.online/v1",
    "model_name": "gpt-4o"
}

# 日志配置
LOGGING_CONFIG = {
    "level": "DEBUG",
    "format": "%(asctime)s %(levelname)s: %(message)s"
}

# Excel模板配置
EXCEL_CONFIG = {
    "template_file": "电话开拓分析表.xlsx",
    "summary_row": 33,  # 默认总结行
    "columns": {
        "客户名称": None,  # 将在运行时填充
        "联系人": None,
        "联系电话": None,
        "评分": None,
        "通话优化建议": None
    }
}

