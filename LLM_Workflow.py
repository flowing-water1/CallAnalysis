import asyncio
from typing import Dict
from Identify_Roles import identify_roles
from Analyze_Conversation import analyze_conversation_with_roles

async def llm_workflow(conversation_text: str, duration_seconds: float, is_valid_call: bool) -> dict:
    """
    针对每个转写文件，先调用identify_roles，再调用analyze_conversation_with_roles，
    形成一个完整的LLM工作流
    
    Args:
        conversation_text: 对话文本
        duration_seconds: 通话时长（秒）
        is_valid_call: 是否为有效通话（时长>=60秒）
        
    Returns:
        Dict: 分析结果
    """
    roles = await asyncio.to_thread(identify_roles, conversation_text)
    analysis_result = await asyncio.to_thread(analyze_conversation_with_roles, conversation_text, roles, duration_seconds, is_valid_call)
    return analysis_result