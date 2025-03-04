import json
import re
from typing import Dict, List
from langchain_community.chat_models import ChatOpenAI
from langchain.prompts import ChatPromptTemplate
from langchain.schema import HumanMessage, SystemMessage

from utils import format_conversation_with_roles
from config import OPENAI_CONFIG

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
    confidence_warning = ""
    if roles.get("confidence", "low") == "low":
        confidence_warning = "\n\n 注意：系统对说话者角色的识别可信度较低，请人工核实。"
    
    system_prompt = f"""
    你是一位专业的销售通话分析专家，负责对销售对话进行分析评估。
    以下是对话记录，其中 {roles['spk1']} 的发言以 "{roles['spk1']}：" 开头，{roles['spk2']} 的发言以 "{roles['spk2']}：" 开头。

    <角色标识>
    {roles['spk1']}: {{ROLES_SPK1}}
    {roles['spk2']}: {{ROLES_SPK2}}
    </角色标识>

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

    完成所有标准评估后：
    1. 计算总分（满分 100 分）
    2. 在【总结】标签中：
        - 指出 1 个最关键改进点
        - 改进点包含：
            * 问题描述（20 字内）
            * 具体建议（30 字内）
            * 示范话术（可选）
    """
    
    llm = ChatOpenAI(
        openai_api_key=OPENAI_CONFIG["api_key"],
        openai_api_base=OPENAI_CONFIG["api_base"],
        model_name=OPENAI_CONFIG["model_name"],
        temperature=0.7
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

def analyze_summary(all_analysis_results: List[Dict]) -> str:
    """
    对所有对话的分析结果进行汇总分析
    
    Args:
        all_analysis_results: 所有对话的分析结果列表
        
    Returns:
        str: 汇总分析报告
    """
    system_prompt = """
    你是一位专业的销售培训专家，需要根据当日销售对话分析报告进行汇总分析，生成一份结构化的销售分析报告。

    请按照以下步骤处理数据：
    1. 数据解析阶段：
        - 仔细提取所有通话记录的评分数据，确保每个评分都有对话文本支撑。
        - 认真识别每份报告中的关键改进点，避免主观臆断，仅基于对话事实。
    2. 计算分析阶段：
        - 计算平均评分，结果保留两位小数。
        - 统计重复出现的改进建议频次。
    3. 建议筛选阶段：
        - 选择出现频率最高的前3个改进领域。
        - 确保每条建议满足以下条件：
          a) 基于至少3个通话记录的共同问题。
          b) 聚焦可量化的行为改进。
          c) 包含具体的提升方向。

    输出要求：
    请在[销售分析报告]标签下输出以下内容，以Markdown形式呈现：
    ### [销售分析报告]
    1. **平均评分**：数值结果
    2. **改进建议**：
        - 每条建议单独列出，问题描述简明（不超过25字），改进措施具体可执行，整体控制在50字左右。
    """
    
    llm = ChatOpenAI(
        openai_api_key=OPENAI_CONFIG["api_key"],
        openai_api_base=OPENAI_CONFIG["api_base"],
        model_name=OPENAI_CONFIG["model_name"],
        temperature=0.7
    )

    all_analyses = []
    for idx, result in enumerate(all_analysis_results, 1):
        if result["status"] == "success" and result["analysis_result"].get("status") == "success":
            all_analyses.append(f"对话 {idx} 的分析结果：\n{result['analysis_result']['analysis']}")

    combined_analyses = "\n\n".join(all_analyses)

    prompt = ChatPromptTemplate.from_messages([
        SystemMessage(content=system_prompt),
        HumanMessage(content=f"以下是{len(all_analyses)}个销售对话的分析结果，请进行汇总分析：\n\n{combined_analyses}")
    ])

    try:
        response = llm(prompt.format_messages())
        return response.content
    except Exception as e:
        return f"汇总分析过程中出现错误: {str(e)}" 