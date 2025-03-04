def format_conversation_with_roles(raw_text: str, roles: dict) -> str:
    """
    根据已有的角色信息，将原始的spk标记文本转换为更规范的对话格式
    
    Args:
        raw_text: 原始对话文本
        roles: 角色识别结果
        
    Returns:
        str: 格式化后的对话文本
    """
    lines = raw_text.strip().split('\n')
    formatted_lines = []
    current_speaker = None
    current_content = []
    
    for line in lines:
        if not line.strip() or '##' not in line:
            continue
        speaker, content = line.split('##', 1)
        content = content.strip()
        if not content or content.strip().replace('、', '').isdigit():
            continue
        speaker_role = roles.get(speaker, f"未知角色{speaker[-1]}")
        if speaker == current_speaker:
            current_content.append(content)
        else:
            if current_speaker and current_content:
                formatted_lines.append(f"{roles.get(current_speaker, f'未知角色{current_speaker[-1]}')}：{''.join(current_content)}")
            current_speaker = speaker
            current_content = [content]
            
    if current_speaker and current_content:
        formatted_lines.append(f"{roles.get(current_speaker, f'未知角色{current_speaker[-1]}')}：{''.join(current_content)}")
        
    formatted_text = '\n\n'.join(formatted_lines)
    return formatted_text 