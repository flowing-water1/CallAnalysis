import json
from typing import Dict, List
from langchain_community.chat_models import ChatOpenAI
from langchain.prompts import ChatPromptTemplate
from langchain.schema import HumanMessage, SystemMessage

from config import ROLE_IDENTIFY_CONFIG
from utils import format_conversation_with_roles

def identify_roles(raw_text: str) -> dict:
    """
    使用LLM识别对话中的角色
    
    Args:
        raw_text: 原始对话文本
        
    Returns:
        Dict: 包含角色识别结果的字典
    """
    lines = raw_text.strip().split('\n')
    sample_dialogue = '\n'.join(lines[:10])
    llm = ChatOpenAI(
        openai_api_key=ROLE_IDENTIFY_CONFIG["api_key"],
        openai_api_base=ROLE_IDENTIFY_CONFIG["api_base"],
        model_name=ROLE_IDENTIFY_CONFIG["model_name"],
        temperature=ROLE_IDENTIFY_CONFIG["temperature"]
    )
    system_prompt = """
    你是一位专业的对话分析专家。请分析以下对话内容，识别出spk1和spk2各自的角色（销售还是客户）。

    判断依据：
    1. 说话方式和语气（销售通常更主动、更正式）
    2. 提问方式（销售倾向于引导性提问）
    3. 专业术语的使用（销售更可能使用专业术语）
    4. 信息获取方向（销售倾向于获取客户需求信息）

    请只返回如下格式的JSON：
    {
        "spk1": "销售/客户",
        "spk2": "销售/客户",
        "confidence": "high/medium/low"
    }
    """
    prompt = ChatPromptTemplate.from_messages([
        SystemMessage(content=system_prompt),
        HumanMessage(content=f"对话内容：\n\n{sample_dialogue}")
    ])
    try:
        response = llm(prompt.format_messages())
        roles = json.loads(response.content)
        return roles
    except Exception as e:
        return {
            "spk1": "未知角色1",
            "spk2": "未知角色2",
            "confidence": "low"
        } 