import os
from typing import Dict, Any, List
import base64

def decode_key(encoded_key: str) -> str:
    """解码加密的API密钥"""
    return base64.b64decode(encoded_key).decode('utf-8')

# API配置
XFYUN_CONFIG = {
    "lfasr_host": "https://raasr.xfyun.cn/v2/api",
    "api_upload": "/upload",
    "api_get_result": "/getResult",
    "appid": "8d2e895b",
    "secret_key": decode_key("OGQ1YzAyYmQ2OTM0NWY1MDQ3NjFkYTZiODE4YjQyM2Y=")  # 加密的密钥
}

# 火山引擎配置 - 直接使用原始值，不进行额外加密
VOLCANO_CONFIG = {
    "appid": "6164066630", 
    "token": "FRxS8saaoV7MNf1Z4-u_UDZzygInc-WW",
    "tos": {
        "ak": "AKLTNjE5MzU4OWExNjQ3NDc1Njk0YzEwNzk3YWE0YzA0YTI",
        "sk": "TTJKaVl6WTNZMk01WkRkaE5EQTVOVGhtT1dJNFptSXdOemd4T0dVeU16VQ==",
        "endpoint": "tos-cn-guangzhou.volces.com",
        "region": "cn-guangzhou",
        "bucket_name": "call-analysis0"
    }
}

# OpenAI配置
ROLE_IDENTIFY_CONFIG = {
    "api_key": decode_key("c2stT2RDb3FLQ3ZjdENKYVBIVUYyRWE5ZUY5QzAxOTQwRDhBYTdjQjgyODg5RWFFMTY1"),
    "api_base": "https://api.pumpkinaigc.online/v1",
    "model_name": "gpt-4o-mini",
    "temperature": 0.2  # 角色识别需要更确定的结果
}

CONVERSATION_ANALYSIS_CONFIG = {
    "api_key": decode_key("c2stT2RDb3FLQ3ZjdENKYVBIVUYyRWE5ZUY5QzAxOTQwRDhBYTdjQjgyODg5RWFFMTY1"),
    "api_base": "https://api.pumpkinaigc.online/v1",
    "model_name": "deepseek-v3",
    "temperature": 0.68  # 对话分析需要一定的创造性
}

SUMMARY_ANALYSIS_CONFIG = {
    "api_key": decode_key("ZjQ2NWMxZmMtNDgxZS00NjY4LWJmYTItZWM5MTg3YzJmMWU0"),
    "api_base": "https://ark.cn-beijing.volces.com/api/v3",
    "model_name": "deepseek-r1-250120",
    "temperature": 0.7  # 汇总分析也需要一定的创造性
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

