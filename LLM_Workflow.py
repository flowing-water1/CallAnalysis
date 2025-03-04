import asyncio
from typing import Dict
from Identify_Roles import identify_roles
from Analyze_Conversation import analyze_conversation_with_roles

async def llm_workflow(conversation_text: str) -> dict:
    """
    针对每个转写文件，先调用identify_roles，再调用analyze_conversation_with_roles，
    形成一个完整的LLM工作流
    
    Args:
        conversation_text: 对话文本
        
    Returns:
        Dict: 分析结果
    """
    roles = await asyncio.to_thread(identify_roles, conversation_text)
    analysis_result = await asyncio.to_thread(analyze_conversation_with_roles, conversation_text, roles)
    return analysis_result