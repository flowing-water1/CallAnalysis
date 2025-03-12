import json
import re
from typing import Dict, List
from langchain_community.chat_models import ChatOpenAI
from langchain.prompts import ChatPromptTemplate
from langchain.schema import HumanMessage, SystemMessage

from utils import format_conversation_with_roles
from config import CONVERSATION_ANALYSIS_CONFIG

def analyze_conversation_with_roles(conversation_text: str, roles: dict) -> dict:
    """
    使用LLM对通话记录进行分析，并给出改进建议
    
    Args:
        conversation_text: 对话文本
        roles: 角色识别结果
        
    Returns:
        Dict: 分析结果
    """
    formatted_text = format_conversation_with_roles(conversation_text, roles)
    
    # 确保占位符正确替换
    formatted_text = formatted_text.replace("{ROLES_SPK1}", roles["spk1"])
    formatted_text = formatted_text.replace("{ROLES_SPK2}", roles["spk2"])
    
    confidence_warning = ""
    if roles.get("confidence", "low") == "low":
        confidence_warning = "\n\n 注意：系统对说话者角色的识别可信度较低，请人工核实。"
    
    system_prompt = f"""
    你是一位专业的销售通话分析专家，负责对销售对话进行分析评估。你擅长的领域是润滑油的销售，包括但不限于壳牌，海德力等知名品牌。
    因为转写出来的对话记录中可能因为口音等问题，可能有些同音字以不同的形式表现出来，包括但不限于“壳牌”变成“翘牌”/“撬环”等，请你不用太纠结，关注双方的对话即可。
    因为转写模型精度和现实对话的原因，可能有时候销售和客户的对话会混淆，包括但不限于，客户的对话在销售中出现，销售的对话在客户中出现，但是大体上，双方说话人的对话已经尽量分离，请你考虑这点再做出评估。
    以下是对话记录，其中 {roles['spk1']} 的发言以 "{roles['spk1']}：" 开头，{roles['spk2']} 的发言以 "{roles['spk2']}：" 开头。

    请按照以下评分标准对销售对话进行评估：
    1. 30 秒自我介绍清晰度（30 分）
        - 是否包含公司/个人核心价值
        - 是否控制在 30 秒中
        - 是否建立专业可信形象
    2. 客户需求洞察（20 分）
        - 是否明确客户行业类型
        - 是否确认现有需求
        - 是否量化客户业务规模
    3. SPIN 痛点挖掘（15 分）
        - Situation：是否确认现状
        - Problem：是否发现问题
        - Implication：是否阐明问题影响
        - Need - Payoff：是否引导解决方案需求
    4. 价值展示能力（15 分）
        - 是否针对性匹配客户需求
        - 是否使用数据/案例支撑
        - 是否说明ROI或成本效益
    5. 决策流程掌握（10 分）
        - 是否确认采购决策阶段
        - 是否识别关键决策人
        - 是否了解预算周期
    6. 后续跟进铺垫（10 分）
        - 是否约定具体跟进时间
        - 是否设置价值锚点
        - 是否取得客户承诺

    请按以下流程执行分析：
    1. 针对每个评分标准，先在[分析内容]中：
        - 引用对话中的具体语句
        - 分析是否符合标准要求
        - 指出存在/缺失的要素
    2. 在【评分】中给出该标准得分（0 - 满分）

    完成所有标准评估后以MarkDown形式呈现：
    1. 相加计算之后给出总分（满分 100 分）
    2. 在【总分】中写明总分（格式：【总分】XX分/100分）
    3. 在【总结】标签中：
        - 指出 1 个最关键改进点
        - 改进点包含：
            * 问题描述（20 字内）
            * 具体建议（30 字内）
            * 示范话术（可选）
    """
    
    llm = ChatOpenAI(
        openai_api_key=CONVERSATION_ANALYSIS_CONFIG["api_key"],
        openai_api_base = CONVERSATION_ANALYSIS_CONFIG["api_base"],
        model_name = CONVERSATION_ANALYSIS_CONFIG["model_name"],
        temperature = CONVERSATION_ANALYSIS_CONFIG["temperature"]

    )
    
    prompt = ChatPromptTemplate.from_messages([
        SystemMessage(content=system_prompt),
        HumanMessage(content=f"以下是需要分析的通话记录：\n\n{formatted_text}")
    ])
    
    try:
        response = llm(prompt.format_messages())
        analysis_text = response.content
        filtered_text = re.sub(r"(>?\s*Reasoning[\s\S]*?Reasoned for \d+\s*seconds\s*)", "", analysis_text, flags=re.IGNORECASE)
        return {
            "status": "success",
            "analysis": filtered_text,
            "formatted_text": formatted_text,
            "roles": roles
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"分析过程中出现错误: {str(e)}"
        } 