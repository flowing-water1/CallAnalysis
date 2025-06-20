import json
import re
from typing import Dict, List
from langchain_community.chat_models import ChatOpenAI
from langchain.prompts import ChatPromptTemplate
from langchain.schema import HumanMessage, SystemMessage

from utils import format_conversation_with_roles
from config import CONVERSATION_ANALYSIS_CONFIG

def analyze_conversation_with_roles(conversation_text: str, roles: dict, duration_seconds: float, is_valid_call: bool) -> dict:
    """
    使用LLM对通话记录进行分析，并给出改进建议
    
    Args:
        conversation_text: 对话文本
        roles: 角色识别结果
        duration_seconds: 通话时长（秒）
        is_valid_call: 是否为有效通话（时长>=60秒）
        
    Returns:
        Dict: 分析结果
    """
    formatted_text = format_conversation_with_roles(conversation_text, roles)
    
    # 确保占位符正确替换
    formatted_text = formatted_text.replace("{ROLES_SPK1}", roles["spk1"])
    formatted_text = formatted_text.replace("{ROLES_SPK2}", roles["spk2"])
    
    confidence_warning = ""
    if roles.get("confidence", "low") == "low":
        confidence_warning = " (注意: 系统对说话者角色的识别可信度较低，建议人工核实)"
    
    # 构建通话有效性说明
    validity_status = f"【有效通话】（时长：{duration_seconds:.2f}秒）" if is_valid_call else f"【无效通话】（时长：{duration_seconds:.2f}秒，不足1分钟）"
    
    system_prompt = f"""
    你是一位专业的销售通话分析专家，负责对润滑油（如壳牌、海德力等品牌）销售对话进行分析评估。
    请忽略对话转写中的同音别字（如"壳牌"变成"翘牌"/"撬环"等），并理解销售与客户角色可能存在少量混淆。专注于核心对话内容。
    以下是对话记录，其中 {roles['spk1']} 是"销售"，{roles['spk2']} 是"客户"。

    **⚠️ 重要约束：**
    1. **时间显示要求**：通话时长已确定为 {duration_seconds:.2f} 秒，请在分析中使用这个精确数值，绝对禁止使用"约"、"大概"、"大约"等模糊词汇！
    2. **完整分析要求**：无论对话长短，都必须按照完整的评分维度进行分析。即使是短对话，也要尽可能从现有内容中提取信息并给出建设性的改进建议。绝对不要输出"对话内容过短，无法展开有效分析"这样的内容。

    ### **分析流程与评分标准**

    请严格按照以下六个维度对通话进行打分。在每个维度的分析中，必须：
    1.  **引用原文**：从对话中引用1-2句关键语句作为分析依据。如果该维度在对话中未体现，请明确说明"对话中未涉及此部分"。
    2.  **进行分析**：基于引用内容，评价其表现的好坏。
    3.  **给出分数**：根据表现给出该项得分。未涉及的部分给0分。

    **评分维度:**
    - **1. 30秒自我介绍清晰度 (30分)**: 是否包含公司/个人核心价值，是否建立专业形象。
    - **2. 客户需求洞察 (20分)**: 是否明确客户行业、现有需求及业务规模。
    - **3. SPIN痛点挖掘 (15分)**: 是否有效运用Situation（现状）、Problem（问题）、Implication（影响）、Need-Payoff（需求-效益）进行提问。
    - **4. 价值展示能力 (15分)**: 是否针对性匹配客户需求，并以数据/案例支撑。
    - **5. 决策流程掌握 (10分)**: 是否确认采购决策阶段、关键决策人及预算周期。
    - **6. 后续跟进铺垫 (10分)**: 是否约定具体跟进时间，并取得客户承诺。

    ### **输出格式**

    请严格按照以下 Markdown 格式生成报告，确保所有标题和标签都完整无缺：

    ```markdown
    ### 销售对话分析报告

    **通话状态**: {validity_status}
    **总分**: XX分 / 100分

    ---

    #### **评分详情**

    **1. 30秒自我介绍清晰度 (XX分 / 30分)**
    - **分析内容**:
        - 引用: "[引用对话原文]"
        - 评估: "[分析与评估]"
    - **评分**: XX分

    **2. 客户需求洞察 (XX分 / 20分)**
    - **分析内容**:
        - 引用: "[引用对话原文]"
        - 评估: "[分析与评估]"
    - **评分**: XX分

    **3. SPIN痛点挖掘 (XX分 / 15分)**
    - **分析内容**:
        - 引用: "[引用对话原文]"
        - 评估: "[分析与评估]"
    - **评分**: XX分

    **4. 价值展示能力 (XX分 / 15分)**
    - **分析内容**:
        - 引用: "[引用对话原文]"
        - 评估: "[分析与评估]"
    - **评分**: XX分

    **5. 决策流程掌握 (XX分 / 10分)**
    - **分析内容**:
        - 引用: "[引用对话原文]"
        - 评估: "[分析与评估]"
    - **评分**: XX分

    **6. 后续跟进铺垫 (XX分 / 10分)**
    - **分析内容**:
        - 引用: "[引用对话原文]"
        - 评估: "[分析与评估]"
    - **评分**: XX分

    ---

    #### **核心总结与改进建议**

    - **问题描述**: [20字以内的问题描述]
    - **改进建议**: [30字以内的具体建议]
    - **话术示范** (可选): "[示范沟通话术]"
    ```
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