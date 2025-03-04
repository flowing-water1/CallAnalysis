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

# 应用配置
APP_CONFIG = {
    "page_title": "分析通话记录Demo",
    "page_icon": "📞",
    "title": "分析通话记录📞",
    "help_button_text": "📚 查看教程",
    "help_button_tooltip": "点击查看详细使用教程",
    "upload_label": "请上传通话录音文件",
    "supported_audio_types": ['wav', 'mp3', 'm4a', 'ogg'],
    "start_analysis_button": "开始分析",
    "download_report_button": "📥 下载完整分析报告",
    "download_excel_button": "📊 下载电话开拓分析表",
    "excel_template_path": "电话开拓分析表.xlsx"
}

# 教程配置
TUTORIAL_CONFIG = {
    "title": "欢迎使用通话分析工具！",
    "width": "large",
    "content": {
        "header": "## 📚 使用教程",
        "format_warning": {
            "title": "### ⚠️ 重要格式要求",
            "description": "上传文件的格式必须是 :red[**\"公司名称-联系人-电话号码\"**] 的形式。中间有无空格不影响，但必须使用 :red[**\"-\"**] 作为分隔符。（此格式要求将在后续版本中优化）"
        },
        "workflow": {
            "title": "### 使用流程",
            "steps": [
                {
                    "title": "#### 1️⃣ 上传文件",
                    "description": "点击下方按钮上传您的通话录音文件：",
                    "image": "tutorial/上传文件按钮.png",
                    "note": ":green[✅] 支持批量上传多个文件",
                    "second_image": "tutorial/上传文件.png"
                },
                {
                    "title": "#### 2️⃣ 确认上传状态",
                    "description": "成功上传后，您将看到如下界面：",
                    "image": "tutorial/上传之后的样子.png"
                },
                {
                    "title": "#### 3️⃣ 开始分析流程",
                    "description": "点击 :blue[**\"开始分析\"**] 按钮启动处理：",
                    "image": "tutorial/开始分析.png"
                },
                {
                    "title": "#### 4️⃣ 等待处理完成",
                    "description": "系统正在处理中，请保持页面打开。您可以暂时切换到其他工作，处理完成后回来查看结果。"
                },
                {
                    "title": "#### 5️⃣ 查看分析结果",
                    "image": "tutorial/最终结果.png"
                },
                {
                    "title": "#### 6️⃣ 导出分析报告",
                    "description": "您可以下载：",
                    "options": [
                        "• :blue[完整分析报告] - 包含所有通话记录和详细分析",
                        "• :green[电话开拓分析表] - 自动填写好的分析数据表格"
                    ],
                    "table_note": "表格中已自动填写好对应数据项：",
                    "table_image": "tutorial/分析结果表格.png",
                    "report_note": "分析报告采用Markdown格式，建议使用Markdown编辑器打开以获得最佳阅读体验：",
                    "report_image": "tutorial/分析结果文档.png"
                }
            ]
        },
        "close_instruction": {
            "title": "### ❓ 如何关闭本教程",
            "description": "点击对话框外任意位置，或滚动至顶部点击右上角的\"❌\"即可关闭本教程。"
        }
    }
}

# UI界面配置
UI_CONFIG = {
    "column_ratio": [5, 1.2],  # 标题列和按钮列的比例
    "tabs": {
        "tab_names": ["📝 所有对话记录", "📊 所有分析结果", "📈 汇总分析"],
        "tab1_title": "### 📝 对话记录 {idx}",
        "tab2_title": "📊 {file_name} 通话分析",
        "tab3_title": "### 📈 汇总分析报告"
    },
    "progress": {
        "upload_phase": "**📤 正在上传文件...**",
        "upload_complete": "**📤 上传完成！**",
        "transcription_phase": "**🔄 正在转写文件...**",
        "transcription_complete": "**✅ 文件转写完成！**",
        "analysis_phase": "**🧠 正在进行LLM分析...**",
        "summary_phase": "**🔄 正在生成汇总分析...**",
        "complete": "**✅ 所有文件处理完成！**",
        "progress_text": "⏳ 已完成 {count}/{total} 个文件转写"
    },
    "file_pattern": {
        "new_pattern": r"^(.*?)-(.*?)-(.*)$",
        "old_pattern": r"^(.*?)-(.*?)$"
    }
}

# 获取全部配置
def get_config() -> Dict[str, Any]:
    return {
        "xfyun": XFYUN_CONFIG,
        "openai": OPENAI_CONFIG,
        "logging": LOGGING_CONFIG,
        "excel": EXCEL_CONFIG,
        "app": APP_CONFIG,
        "tutorial": TUTORIAL_CONFIG,
        "ui": UI_CONFIG
    } 