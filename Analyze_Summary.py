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
    # 首先统计有效和无效通话
    valid_calls = []
    invalid_calls = []
    
    for result in all_analysis_results:
        if result.get("is_valid_call", True):  # 默认为有效（兼容旧数据）
            valid_calls.append(result)
        else:
            invalid_calls.append(result)
    
    total_calls = len(all_analysis_results)
    valid_count = len(valid_calls)
    invalid_count = len(invalid_calls)
    
    system_prompt = f"""
    你是一位专业的销售培训专家，负责汇总分析当日所有销售对话，并生成一份结构化的汇总报告。

    ### **分析流程**

    1.  **数据提取**:
        -   仔细提取所有通话记录的评分数据，确保每个评分都有对话文本支撑。
        -   认真识别每份报告中的关键改进点，避免主观臆断，仅基于对话事实。

    2.  **计算与统计**:
        -   **计算平均分**: 仅基于通话的分析报告，计算总分的平均值（保留两位小数）。
        -   **建议分析筛选**:       
            - 分析推断出频率最高的前3个改进领域。
            - 确保每条建议满足以下条件：
            a) 基于至少3个通话记录的共同问题。
            b) 聚焦可量化的行为改进。
            c) 包含具体的提升方向。。

    3.  **报告生成**:
        -   严格按照下方指定的Markdown格式输出报告。
        -   确保所有数据准确无误，建议必须基于多份报告的共性问题。

    ### **输出格式要求**

    请严格按照以下 Markdown 格式生成报告，确保所有标题和标签都完整无缺。直接输出报告内容，不要包含任何额外的解释或引言。

    ```markdown
    ### 当日销售对话汇总分析报告

    #### 一、通话整体统计
    - **总通话数**: {total_calls}
    - **有效通话数**: {valid_count} (时长 ≥ 1分钟)
    - **无效通话数**: {invalid_count} (时长 < 1分钟)

    #### 二、整体表现评估
    - **平均分**: [计算所有通话的平均总分，结果保留两位小数]

    #### 三、核心改进建议

    **1. 改进点一**
    - **问题描述**: [基于多个通话总结出的、最常见的问题点，25字以内]
    - **改进措施**: [针对该问题的具体、可执行的改进方法，50字以内]

    **2. 改进点二**
    - **问题描述**: [第二常见的问题点，25字以内]
    - **改进措施**: [具体、可执行的改进方法，50字以内]

    **3. 改进点三**
    - **问题描述**: [第三常见的问题点，25字以内]
    - **改进措施**: [具体、可执行的改进方法，50字以内]
    ```
    """
    
    llm = ChatOpenAI(
        openai_api_key=SUMMARY_ANALYSIS_CONFIG["api_key"],
        openai_api_base=SUMMARY_ANALYSIS_CONFIG["api_base"],
        model_name=SUMMARY_ANALYSIS_CONFIG["model_name"],
        temperature=SUMMARY_ANALYSIS_CONFIG["temperature"]
    )

    # 收集所有通话的分析结果（包括有效和无效）
    all_analyses = []
    for idx, result in enumerate(all_analysis_results, 1):
        if result["status"] == "success" and result["analysis_result"].get("status") == "success":
            all_analyses.append(f"对话 {idx} 的分析结果：\n{result['analysis_result']['analysis']}")

    if not all_analyses:
        return f"""### [销售分析报告]
1. **通话统计**：
   - 总通话数：{total_calls}个
   - 有效通话数：{valid_count}个（时长≥1分钟）
   - 无效通话数：{invalid_count}个（时长<1分钟）
2. **平均评分**：无分析数据
3. **改进建议**：无分析数据，无法生成改进建议"""

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