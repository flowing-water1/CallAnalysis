import json
from typing import Dict, List
from langchain_community.chat_models import ChatOpenAI
from langchain.prompts import ChatPromptTemplate
from langchain.schema import HumanMessage, SystemMessage
from config import SUMMARY_ANALYSIS_CONFIG

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
        openai_api_key=SUMMARY_ANALYSIS_CONFIG["api_key"],
        openai_api_base=SUMMARY_ANALYSIS_CONFIG["api_base"],
        model_name=SUMMARY_ANALYSIS_CONFIG["model_name"],
        temperature=SUMMARY_ANALYSIS_CONFIG["temperature"]
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