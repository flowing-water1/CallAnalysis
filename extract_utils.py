"""
提取工具模块 - 用于从结构化的LLM输出中精确提取数据

基于Analyze_Conversation.py和Analyze_Summary.py的结构化Markdown输出格式
设计的精确提取函数，替代复杂的正则表达式匹配逻辑。
"""

import re
import logging
from typing import Optional, List, Dict, Tuple


def parse_filename_intelligently(filename: str) -> Tuple[str, str, str]:
    """
    智能解析文件名，提取公司名称、联系人、电话号码
    
    支持多种命名格式：
    1. "公司名-联系人-电话号码" (推荐格式)
    2. "公司名-联系人" (无电话号码)
    3. "公司名-电话号码" (无联系人名)
    4. "公司名" (仅公司名)
    
    Args:
        filename: 去除扩展名的文件名
        
    Returns:
        Tuple[str, str, str]: (公司名称, 联系人, 电话号码)
    """
    # 清理文件名，去除可能的前缀
    clean_filename = re.sub(r'^temp_', '', filename)
    
    # 按"-"分割
    parts = clean_filename.split('-')
    
    company_name = ""
    contact_person = ""
    phone_number = ""
    
    if len(parts) == 1:
        # 格式: "公司名"
        company_name = parts[0].strip()
        
    elif len(parts) == 2:
        # 格式: "公司名-联系人" 或 "公司名-电话号码"
        part1 = parts[0].strip()
        part2 = parts[1].strip()
        
        # 判断第二部分是电话号码还是联系人名
        if _is_phone_number(part2):
            # "公司名-电话号码"
            company_name = part1
            phone_number = _clean_phone_number(part2)
        else:
            # "公司名-联系人"
            company_name = part1
            contact_person = part2
            
    elif len(parts) == 3:
        # 格式: "公司名-联系人-电话号码"
        company_name = parts[0].strip()
        contact_person = parts[1].strip()
        potential_phone = parts[2].strip()
        
        # 验证第三部分是否为电话号码
        if _is_phone_number(potential_phone):
            phone_number = _clean_phone_number(potential_phone)
        else:
            # 如果第三部分不是电话号码，可能是更复杂的格式
            # 将后两部分合并作为联系人名
            contact_person = f"{contact_person}-{potential_phone}"
            
    else:
        # 格式: 超过3部分，可能是复杂的公司名或其他格式
        # 尝试从右往左查找电话号码
        phone_found = False
        for i in range(len(parts) - 1, -1, -1):
            if _is_phone_number(parts[i]):
                phone_number = _clean_phone_number(parts[i])
                # 电话号码前的部分作为联系人
                if i > 0:
                    contact_person = parts[i - 1].strip()
                # 电话号码和联系人之前的部分作为公司名
                company_name = "-".join(parts[:max(1, i - 1)]).strip()
                phone_found = True
                break
        
        if not phone_found:
            # 没有找到电话号码，将最后一部分作为联系人，其余作为公司名
            if len(parts) > 1:
                contact_person = parts[-1].strip()
                company_name = "-".join(parts[:-1]).strip()
            else:
                company_name = clean_filename
    
    # 确保至少有公司名称
    if not company_name and not contact_person and not phone_number:
        company_name = clean_filename
    elif not company_name:
        company_name = "未知公司"
    
    logging.debug(f"文件名解析结果: 公司='{company_name}', 联系人='{contact_person}', 电话='{phone_number}'")
    return company_name, contact_person, phone_number


def _is_phone_number(text: str) -> bool:
    """
    判断文本是否为电话号码
    
    Args:
        text: 待判断的文本
        
    Returns:
        bool: 是否为电话号码
    """
    # 清理空格和连字符
    clean_text = re.sub(r'[\s-]', '', text)
    
    # 电话号码模式：
    # 1. 11位手机号 (1开头)
    # 2. 8-15位数字 (包括座机等)
    # 3. 可能包含+86等国际前缀
    phone_patterns = [
        r'^(\+86)?1[3-9]\d{9}$',  # 手机号
        r'^(\+86)?\d{8,15}$',     # 一般电话号码
        r'^\d{3,4}-?\d{7,8}$',    # 座机格式
    ]
    
    for pattern in phone_patterns:
        if re.match(pattern, clean_text):
            return True
    
    # 如果文本全是数字且长度合理，也认为是电话号码
    if clean_text.isdigit() and 7 <= len(clean_text) <= 15:
        return True
    
    return False


def _clean_phone_number(phone: str) -> str:
    """
    清理电话号码格式
    
    Args:
        phone: 原始电话号码
        
    Returns:
        str: 清理后的电话号码
    """
    # 去除空格、连字符等
    clean_phone = re.sub(r'[\s-]', '', phone)
    return clean_phone


def extract_total_score(analysis_text: str) -> Optional[str]:
    """
    从对话分析结果中提取总分
    
    基于结构化输出格式：**总分**: XX分 / 100分
    
    Args:
        analysis_text: 对话分析文本
        
    Returns:
        str: 提取到的总分，如果未找到则返回None
    """
    # 精确匹配结构化输出格式
    patterns = [
        r'\*\*总分\*\*:\s*(\d+)分?\s*/\s*100分?',  # **总分**: XX分 / 100分
        r'\*\*总分\*\*:\s*(\d+)分?',  # **总分**: XX分
        r'总分\*\*:\s*(\d+)分?\s*/\s*100分?',  # 总分**: XX分 / 100分
        r'总分\*\*:\s*(\d+)分?',  # 总分**: XX分
        r'\*\*总分\*\*\s*(\d+)分?',  # **总分** XX分
        r'总分[:：]\s*(\d+)分?\s*/\s*100分?',  # 总分: XX分 / 100分
        r'总分[:：]\s*(\d+)分?'  # 总分: XX分
    ]
    
    for pattern in patterns:
        match = re.search(pattern, analysis_text)
        if match:
            score = match.group(1)
            logging.debug(f"提取到总分: {score}")
            return score
    
    logging.warning("未能从分析结果中提取到总分")
    return None


def extract_improvement_suggestion(analysis_text: str) -> Optional[str]:
    """
    从对话分析结果中提取改进建议
    
    基于结构化输出格式：- **改进建议**: [内容]
    
    Args:
        analysis_text: 对话分析文本
        
    Returns:
        str: 提取到的改进建议，如果未找到则返回None
    """
    # 精确匹配结构化输出格式
    patterns = [
        r'-\s*\*\*改进建议\*\*:\s*(.+?)(?:\n|$)',  # - **改进建议**: [内容]
        r'-\s*\*\*改进建议\*\*[:：]\s*(.+?)(?:\n|$)',  # - **改进建议**：[内容]
        r'\*\*改进建议\*\*:\s*(.+?)(?:\n|$)',  # **改进建议**: [内容]
        r'\*\*改进建议\*\*[:：]\s*(.+?)(?:\n|$)',  # **改进建议**：[内容]
        r'改进建议\*\*:\s*(.+?)(?:\n|$)',  # 改进建议**: [内容]
        r'改进建议\*\*[:：]\s*(.+?)(?:\n|$)',  # 改进建议**：[内容]
        r'改进建议[:：]\s*(.+?)(?:\n|$)'  # 改进建议: [内容]
    ]
    
    for pattern in patterns:
        match = re.search(pattern, analysis_text, re.MULTILINE)
        if match:
            suggestion = match.group(1).strip()
            # 清理Markdown格式
            suggestion = re.sub(r'\*\*(.+?)\*\*', r'\1', suggestion)
            suggestion = re.sub(r'\*(.+?)\*', r'\1', suggestion)
            suggestion = suggestion.strip('""''')
            logging.debug(f"提取到改进建议: {suggestion}")
            return suggestion
    
    logging.warning("未能从分析结果中提取到改进建议")
    return None


def extract_summary_measures(summary_text: str) -> List[str]:
    """
    从汇总分析结果中提取改进措施
    
    基于结构化输出格式：- **改进措施**: [内容]
    
    Args:
        summary_text: 汇总分析文本
        
    Returns:
        List[str]: 提取到的改进措施列表
    """
    measures = []
    
    # 精确匹配结构化输出格式
    patterns = [
        r'-\s*\*\*改进措施\*\*:\s*(.+?)(?:\n|$)',  # - **改进措施**: [内容]
        r'-\s*\*\*改进措施\*\*[:：]\s*(.+?)(?:\n|$)',  # - **改进措施**：[内容]
        r'\*\*改进措施\*\*:\s*(.+?)(?:\n|$)',  # **改进措施**: [内容]
        r'\*\*改进措施\*\*[:：]\s*(.+?)(?:\n|$)',  # **改进措施**：[内容]
    ]
    
    for pattern in patterns:
        matches = re.finditer(pattern, summary_text, re.MULTILINE)
        for match in matches:
            measure = match.group(1).strip()
            # 清理Markdown格式
            measure = re.sub(r'\*\*(.+?)\*\*', r'\1', measure)
            measure = re.sub(r'\*(.+?)\*', r'\1', measure)
            measure = measure.strip('""''')
            if measure and measure not in measures:
                measures.append(measure)
    
    logging.debug(f"提取到{len(measures)}个改进措施")
    return measures


def extract_average_score(summary_text: str) -> Optional[str]:
    """
    从汇总分析结果中提取平均分
    
    基于结构化输出格式：- **平均分**: [数值]
    
    Args:
        summary_text: 汇总分析文本
        
    Returns:
        str: 提取到的平均分，如果未找到则返回None
    """
    # 精确匹配结构化输出格式
    patterns = [
        r'-\s*\*\*平均分\*\*:\s*(\d+\.?\d*)',  # - **平均分**: [数值]
        r'-\s*\*\*平均分\*\*[:：]\s*(\d+\.?\d*)',  # - **平均分**：[数值]
        r'\*\*平均分\*\*:\s*(\d+\.?\d*)',  # **平均分**: [数值]
        r'\*\*平均分\*\*[:：]\s*(\d+\.?\d*)',  # **平均分**：[数值]
        r'平均分\*\*:\s*(\d+\.?\d*)',  # 平均分**: [数值]
        r'平均分\*\*[:：]\s*(\d+\.?\d*)',  # 平均分**：[数值]
        r'平均分[:：]\s*(\d+\.?\d*)',  # 平均分: [数值]
        r'平均评分[:：]\s*(\d+\.?\d*)'  # 平均评分: [数值]
    ]
    
    for pattern in patterns:
        match = re.search(pattern, summary_text)
        if match:
            score = match.group(1)
            logging.debug(f"提取到平均分: {score}")
            return score
    
    logging.warning("未能从汇总分析中提取到平均分")
    return None


def extract_all_conversation_data(analysis_text: str) -> Dict[str, Optional[str]]:
    """
    从对话分析结果中提取所有关键数据
    
    Args:
        analysis_text: 对话分析文本
        
    Returns:
        Dict[str, Optional[str]]: 包含总分和改进建议的字典
    """
    return {
        "score": extract_total_score(analysis_text),
        "suggestion": extract_improvement_suggestion(analysis_text)
    }


def extract_all_summary_data(summary_text: str) -> Dict[str, any]:
    """
    从汇总分析结果中提取所有关键数据
    
    Args:
        summary_text: 汇总分析文本
        
    Returns:
        Dict[str, any]: 包含平均分和改进措施的字典
    """
    return {
        "average_score": extract_average_score(summary_text),
        "improvement_measures": extract_summary_measures(summary_text)
    } 