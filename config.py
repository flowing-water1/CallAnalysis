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

# PostgreSQL 数据库配置
DATABASE_CONFIG = {
    # 生产环境配置
    "production": {
        "host": "117.72.54.192",
        "port": 5432,
        "database": "callanalysis",
        "username": "callanalysis",
        "password": "callanalysis",
        "sync_url": "postgresql://callanalysis:callanalysis@117.72.54.192:5432/callanalysis",
        "async_url": "postgresql+asyncpg://callanalysis:callanalysis@117.72.54.192:5432/callanalysis",
    },
    
    # 测试环境配置
    "test": {
        "host": "117.72.54.192",
        "port": 5432,
        "database": "testcall",
        "username": "testcall",
        "password": "testcall",
        "sync_url": "postgresql://testcall:testcall@117.72.54.192:5432/testcall",
        "async_url": "postgresql+asyncpg://testcall:testcall@117.72.54.192:5432/testcall",
    },
    
    # 当前使用的环境（可以切换为 'production' 或 'test'）
    "current_env": "production",  # 数据库更新完成，恢复测试环境
    
    # 连接池配置（通用）
    "pool_config": {
        "min_size": 1,      # 最小连接数
        "max_size": 10,     # 最大连接数
        "max_queries": 50000,  # 每个连接最大查询数
        "max_inactive_connection_lifetime": 300,  # 非活跃连接生命周期（秒）
        "timeout": 60,      # 连接超时（秒）
        "command_timeout": 60,  # 命令超时（秒）
    },
    
    # SSL配置（生产环境建议开启）
    "ssl_config": {
        "ssl": "prefer",  # 可选值: disable, allow, prefer, require, verify-ca, verify-full
        "sslmode": "prefer"
    },
    
    # 连接选项
    "connect_args": {
        "server_settings": {
            "jit": "off",  # 关闭JIT以提高连接速度
            "application_name": "call_analysis_app"  # 应用标识
        }
    }
}

# OpenAI配置
ROLE_IDENTIFY_CONFIG = {
    "api_key": decode_key("c2stTDNidWl5TXZXOUdOMkRnTTM0QTY2MDViQzYwNDRmOWFCZDcxRTc1N0I2NjQ4Njg1"),
    "api_base": "https://api.pumpkinaigc.online/v1",
    "model_name": "gemini-2.5-pro-preview-06-05",
    "temperature": 0.5  # 角色识别需要更确定的结果
}

CONVERSATION_ANALYSIS_CONFIG = {
    "api_key": decode_key("c2stTDNidWl5TXZXOUdOMkRnTTM0QTY2MDViQzYwNDRmOWFCZDcxRTc1N0I2NjQ4Njg1"),
    "api_base": "https://api.pumpkinaigc.online/v1",
    "model_name": "gemini-2.5-pro-preview-06-05",
    "temperature": 0.68  # 对话分析需要一定的创造性
}

SUMMARY_ANALYSIS_CONFIG = {
    "api_key": decode_key("c2stTDNidWl5TXZXOUdOMkRnTTM0QTY2MDViQzYwNDRmOWFCZDcxRTc1N0I2NjQ4Njg1"),
    "api_base": "https://api.pumpkinaigc.online/v1",
    "model_name": "gemini-2.5-pro-preview-06-05",
    "temperature": 0.7  # 汇总分析也需要一定的创造性
}

# 图片识别配置
IMAGE_RECOGNITION_CONFIG = {
    "api_key": decode_key("c2stTDNidWl5TXZXOUdOMkRnTTM0QTY2MDViQzYwNDRmOWFCZDcxRTc1N0I2NjQ4Njg1"),
    "api_base": "https://api.pumpkinaigc.online/v1",
    "model_name": "gemini-2.5-pro-preview-06-05",
    "temperature": 0.1  # 图片识别需要精确性，降低随机性
}

# 企业微信配置
WECHAT_WORK_CONFIG = {
    "monthly_report_webhook": "8f1cce28-5078-47f0-b24c-192e67b44b22",  # 月度销售报告推送群
    "daily_report_webhook": "8f1cce28-5078-47f0-b24c-192e67b44b22",  # 每日销售报告推送群（暂时使用同一个群）
    "api_base_url": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send"
}

# 月度销售报告配置
MONTHLY_REPORT_CONFIG = {
    "test_mode": True,  # 测试模式：True=查询当月数据, False=查询上月数据
    "include_zero_calls": True,  # 是否包含有效通话数为0的记录
    "show_total_calls": True,  # 是否显示总通话数
}

# 每日销售报告配置
DAILY_REPORT_CONFIG = {
    "test_mode": True,  # 测试模式：True=可查询当天数据, False=只查询昨天数据
    "test_date": None,  # 测试模式下指定查询日期（格式：'2024-01-15'），None则查询当天
    "top_count": 10,  # 显示前N名销售人员的详细数据
    "show_inactive": True,  # 是否显示无通话记录的销售人员统计
    "show_inactive_names": False,  # 是否显示无通话记录的销售人员姓名
    "include_weekends": False,  # 是否包含周末数据（可用于控制周末是否发送报告）
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

# 便捷获取当前环境配置的函数
def get_current_db_config():
    """获取当前环境的数据库配置"""
    env = DATABASE_CONFIG["current_env"]
    return DATABASE_CONFIG[env]

