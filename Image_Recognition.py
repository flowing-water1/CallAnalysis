"""
图片识别核心模块
负责微信通话截图的识别、信息提取和数据处理
"""

import asyncio
import json
import logging
import re
from datetime import datetime, date
from typing import List, Dict, Any, Optional, Tuple
import openai
from config import IMAGE_RECOGNITION_CONFIG
from image_utils import optimize_image_for_llm, encode_image_to_base64, validate_image_format

logger = logging.getLogger(__name__)

# 配置OpenAI客户端用于图片识别
def get_image_recognition_client():
    """获取配置好的OpenAI客户端"""
    return openai.OpenAI(
        api_key=IMAGE_RECOGNITION_CONFIG["api_key"],
        base_url=IMAGE_RECOGNITION_CONFIG["api_base"]
    )

def create_image_recognition_prompt() -> str:
    """
    创建专门用于微信通话截图识别的提示词
    
    Returns:
        结构化的提示词
    """
    return """
你是一个专业的图片识别助手，专门识别微信聊天截图中的通话信息。

请仔细分析这张微信聊天截图，提取所有的通话记录信息。

**需要提取的信息：**
1. 通话时长（格式如："通话时长 01:39"、"通话时长 1:23"等）
2. 联系人信息（聊天对象的名称或备注）
3. 通话时间（如果可见，格式如："6月16日 下午15:46"）
4. 公司信息（如果聊天内容中提到公司名称）

**重要规则：**
- 通话时长≥60秒的为有效通话，<60秒的为无效通话
- 一张图可能包含多条通话记录，请全部提取
- 如果看不清楚某些信息，请标记为"未知"
- 时间格式要转换为标准格式

**返回格式（严格按照JSON格式）：**
```json
{
    "success": true,
    "total_calls_found": 2,
    "calls": [
        {
            "contact_info": "华文贸易 / HELI X壳牌",
            "duration_text": "01:39",
            "duration_seconds": 99,
            "is_effective": true,
            "call_time": "6月16日 下午15:46",
            "call_date": "2024-06-16",
            "company_name": "华文贸易",
            "additional_info": "HELI X壳牌 喜力（郑州）"
        }
    ],
    "error_message": null
}
```

如果识别失败，返回：
```json
{
    "success": false,
    "total_calls_found": 0,
    "calls": [],
    "error_message": "识别失败的具体原因"
}
```

现在请分析这张图片：
"""

def parse_duration_to_seconds(duration_text: str) -> Optional[int]:
    """
    解析通话时长文本为秒数
    
    Args:
        duration_text: 时长文本，如 "01:39", "1:23", "00:45"
    
    Returns:
        总秒数，解析失败返回None
    """
    try:
        # 清理文本，移除"通话时长"等前缀
        duration_text = re.sub(r'通话时长\s*', '', duration_text)
        duration_text = duration_text.strip()
        
        # 解析 MM:SS 格式
        if ':' in duration_text:
            parts = duration_text.split(':')
            if len(parts) == 2:
                minutes = int(parts[0])
                seconds = int(parts[1])
                return minutes * 60 + seconds
        
        # 如果只是数字，假设是秒
        if duration_text.isdigit():
            return int(duration_text)
            
        return None
        
    except (ValueError, IndexError) as e:
        logger.warning(f"解析时长失败: {duration_text}, 错误: {e}")
        return None

def parse_call_date(call_time_text: str, current_year: int = None) -> Optional[str]:
    """
    解析通话时间文本为标准日期格式
    
    Args:
        call_time_text: 时间文本，如 "6月16日 下午15:46", "今天 上午10:30"
        current_year: 当前年份，默认为今年
    
    Returns:
        标准日期格式 YYYY-MM-DD，解析失败返回None
    """
    try:
        if current_year is None:
            current_year = datetime.now().year
        
        # 处理"今天"、"昨天"等相对时间
        today = date.today()
        if "今天" in call_time_text:
            return today.strftime("%Y-%m-%d")
        elif "昨天" in call_time_text:
            yesterday = date(today.year, today.month, today.day - 1) if today.day > 1 else date(today.year, today.month - 1, 28)
            return yesterday.strftime("%Y-%m-%d")
        
        # 解析具体日期，如 "6月16日"
        month_day_match = re.search(r'(\d{1,2})月(\d{1,2})日', call_time_text)
        if month_day_match:
            month = int(month_day_match.group(1))
            day = int(month_day_match.group(2))
            return f"{current_year:04d}-{month:02d}-{day:02d}"
        
        # 如果包含年份，如 "2024年6月16日"
        year_month_day_match = re.search(r'(\d{4})年(\d{1,2})月(\d{1,2})日', call_time_text)
        if year_month_day_match:
            year = int(year_month_day_match.group(1))
            month = int(year_month_day_match.group(2))
            day = int(year_month_day_match.group(3))
            return f"{year:04d}-{month:02d}-{day:02d}"
        
        return None
        
    except (ValueError, AttributeError) as e:
        logger.warning(f"解析日期失败: {call_time_text}, 错误: {e}")
        return None

async def extract_call_info_from_image(image_content: bytes, filename: str) -> Dict[str, Any]:
    """
    从单张图片中提取通话信息
    
    Args:
        image_content: 图片字节数据
        filename: 图片文件名
    
    Returns:
        提取结果字典
    """
    try:
        # 优化图片
        optimized_content = optimize_image_for_llm(image_content)
        base64_image = encode_image_to_base64(optimized_content)
        
        # 创建客户端
        client = get_image_recognition_client()
        
        # 调用LLM进行图片识别
        response = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: client.chat.completions.create(
                model=IMAGE_RECOGNITION_CONFIG["model_name"],
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": create_image_recognition_prompt()
                            },
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{base64_image}"
                                }
                            }
                        ]
                    }
                ],
                temperature=IMAGE_RECOGNITION_CONFIG["temperature"],
                max_tokens=1000
            )
        )
        
        # 解析响应
        response_text = response.choices[0].message.content
        logger.info(f"LLM响应 ({filename}): {response_text}")
        
        # 尝试解析JSON响应
        try:
            # 提取JSON部分（去除可能的代码块标记）
            json_match = re.search(r'```json\s*(.*?)\s*```', response_text, re.DOTALL)
            if json_match:
                json_text = json_match.group(1)
            else:
                # 如果没有代码块，尝试找到JSON对象
                json_text = response_text.strip()
            
            result = json.loads(json_text)
            
            # 验证和补充数据
            if result.get("success", False) and result.get("calls"):
                validated_calls = []
                for call in result["calls"]:
                    # 解析时长
                    duration_seconds = parse_duration_to_seconds(call.get("duration_text", ""))
                    if duration_seconds is not None:
                        call["duration_seconds"] = duration_seconds
                        call["is_effective"] = duration_seconds >= 60
                    
                    # 解析日期
                    call_date = parse_call_date(call.get("call_time", ""))
                    if call_date:
                        call["call_date"] = call_date
                    
                    # 添加源图片文件名
                    call["source_image_filename"] = filename
                    
                    validated_calls.append(call)
                
                result["calls"] = validated_calls
                result["total_calls_found"] = len(validated_calls)
                
            return {
                "status": "success",
                "filename": filename,
                "result": result
            }
            
        except json.JSONDecodeError as e:
            logger.error(f"JSON解析失败 ({filename}): {e}")
            return {
                "status": "error",
                "filename": filename,
                "error": f"LLM响应格式错误: {str(e)}",
                "raw_response": response_text
            }
            
    except Exception as e:
        logger.error(f"图片识别失败 ({filename}): {e}")
        return {
            "status": "error",
            "filename": filename,
            "error": str(e)
        }

async def process_image_batch(uploaded_images: List[Any], progress_callback=None) -> Dict[str, Any]:
    """
    批量处理图片，提取通话信息
    
    Args:
        uploaded_images: Streamlit上传的图片文件列表
        progress_callback: 进度更新回调函数
    
    Returns:
        批处理结果
    """
    total_images = len(uploaded_images)
    successful_results = []
    failed_results = []
    all_calls = []
    
    logger.info(f"开始批量处理 {total_images} 张图片")
    
    # 创建异步任务
    tasks = []
    for i, image_file in enumerate(uploaded_images):
        # 验证图片格式
        is_valid, error_msg = validate_image_format(image_file)
        if not is_valid:
            failed_results.append({
                "filename": image_file.name,
                "error": error_msg
            })
            continue
        
        # 创建处理任务
        image_content = image_file.getvalue()
        task = extract_call_info_from_image(image_content, image_file.name)
        tasks.append((i, task))
    
    # 执行异步处理
    for i, task in tasks:
        try:
            # 更新进度
            if progress_callback:
                progress = (i + 1) / total_images
                progress_callback(progress, f"正在处理第 {i + 1}/{total_images} 张图片...")
            
            result = await task
            
            if result["status"] == "success":
                successful_results.append(result)
                # 收集所有通话记录
                if result["result"].get("calls"):
                    all_calls.extend(result["result"]["calls"])
            else:
                failed_results.append({
                    "filename": result["filename"],
                    "error": result["error"]
                })
                
        except Exception as e:
            logger.error(f"处理任务失败: {e}")
            failed_results.append({
                "filename": f"task_{i}",
                "error": str(e)
            })
    
    # 统计结果
    total_calls = len(all_calls)
    effective_calls = sum(1 for call in all_calls if call.get("is_effective", False))
    
    summary = {
        "total_images": total_images,
        "successful_images": len(successful_results),
        "failed_images": len(failed_results),
        "total_calls_found": total_calls,
        "effective_calls_found": effective_calls,
        "all_calls": all_calls,
        "successful_results": successful_results,
        "failed_results": failed_results
    }
    
    logger.info(f"批处理完成: {summary}")
    return summary

def prepare_database_update_data(processing_results: Dict[str, Any], salesperson_id: int) -> Dict[str, Any]:
    """
    准备数据库更新所需的数据，映射到call_details表格式
    
    Args:
        processing_results: 图片处理结果
        salesperson_id: 销售人员ID
    
    Returns:
        数据库更新数据
    """
    all_calls = processing_results.get("all_calls", [])
    
    # 准备 call_details 格式的数据列表
    call_details_list = []
    
    for call in all_calls:
        # 提取电话号码（从附加信息中）
        phone_number = extract_phone_from_text(call.get("additional_info", ""))
        
        # 格式化通话时间信息
        call_time_info = format_call_time_info(call)
        
        # 格式化通话统计信息
        call_statistics = format_call_statistics(call)
        
        # 映射到 call_details 表格式
        call_detail = {
            'original_filename': call.get('source_image_filename', '未知图片'),
            'company_name': call.get('company_name', '').strip() or None,
            'contact_person': call.get('contact_info', '').strip() or None,
            'phone_number': phone_number,
            'conversation_text': call_time_info,  # 存储通话时间信息
            'analysis_text': call_statistics,    # 存储通话统计信息
            'score': None,  # 图片板块不使用评分字段
            'is_effective': call.get('is_effective', False),
            'suggestions': None,  # 图片识别暂不生成建议
            'record_type': 'image'
        }
        
        call_details_list.append(call_detail)
    
    # 按日期分组统计（保持原有逻辑用于统计）
    daily_stats = {}
    for call in all_calls:
        call_date = call.get("call_date")
        if not call_date:
            call_date = date.today().strftime("%Y-%m-%d")  # 如果没有日期，使用今天
        
        if call_date not in daily_stats:
            daily_stats[call_date] = {
                "total_calls": 0,
                "effective_calls": 0,
                "calls_details": []
            }
        
        daily_stats[call_date]["total_calls"] += 1
        if call.get("is_effective", False):
            daily_stats[call_date]["effective_calls"] += 1
        
        daily_stats[call_date]["calls_details"].append(call)
    
    return {
        "salesperson_id": salesperson_id,
        "call_details_list": call_details_list,  # 新增：call_details格式的数据
        "daily_stats": daily_stats,
        "total_images_processed": processing_results["successful_images"],
        "total_calls_found": processing_results["total_calls_found"],
        "total_effective_calls": processing_results["effective_calls_found"],
        "processing_errors": processing_results["failed_results"]
    }

def extract_phone_from_text(text: str) -> Optional[str]:
    """
    从文本中提取电话号码
    
    Args:
        text: 要搜索的文本
    
    Returns:
        提取到的电话号码，如果没有找到返回None
    """
    if not text:
        return None
    
    import re
    # 匹配中国手机号和固定电话号码
    phone_patterns = [
        r'1[3-9]\d{9}',          # 手机号
        r'0\d{2,3}-?\d{7,8}',    # 固定电话
        r'\d{3}-?\d{8}',         # 简化固定电话
    ]
    
    for pattern in phone_patterns:
        match = re.search(pattern, text)
        if match:
            return match.group()
    
    return None

def format_call_time_info(call_data: Dict[str, Any]) -> Optional[str]:
    """
    格式化通话时间信息存储到conversation_text字段
    
    Args:
        call_data: 通话数据
    
    Returns:
        格式化的通话时间信息
    """
    info_parts = []
    
    if call_data.get('call_time'):
        info_parts.append(f"通话时间: {call_data['call_time']}")
    if call_data.get('call_date'):
        info_parts.append(f"通话日期: {call_data['call_date']}")
    
    return '\n'.join(info_parts) if info_parts else None

def format_call_statistics(call_data: Dict[str, Any]) -> str:
    """
    格式化通话统计信息存储到analysis_text字段
    
    Args:
        call_data: 通话数据
    
    Returns:
        格式化的通话统计信息
    """
    stats = []
    stats.append(f"通话时长: {call_data.get('duration_text', '未知')}")
    stats.append(f"时长秒数: {call_data.get('duration_seconds', 0)}")
    stats.append(f"是否有效: {'是' if call_data.get('is_effective') else '否'}")
    
    if call_data.get('additional_info'):
        stats.append(f"附加信息: {call_data['additional_info']}")
    
    return '\n'.join(stats)

# 导出主要函数
__all__ = [
    "extract_call_info_from_image",
    "process_image_batch", 
    "prepare_database_update_data",
    "parse_duration_to_seconds",
    "parse_call_date",
    "check_image_duplicates",  # 新增：图片去重检查
    "filter_duplicate_images",  # 新增：过滤重复图片
    "smart_duplicate_detection",  # 新增：智能去重检测
    "calculate_similarity"  # 新增：相似度计算
]

# 智能去重配置
DUPLICATE_DETECTION_WEIGHTS = {
    "call_time_match": 0.5,      # 通话时间匹配 (50%权重)
    "call_duration_match": 0.3,  # 通话时长匹配 (30%权重)
    "contact_name_match": 0.1,   # 联系人匹配 (10%权重)
    "company_name_match": 0.1    # 公司名称匹配 (10%权重)
}

DUPLICATE_THRESHOLD = 0.7  # ≥0.7自动跳过，<0.7正常处理

def calculate_time_similarity(time1: Optional[str], time2: Optional[str]) -> float:
    """
    计算通话时间相似度
    
    Args:
        time1: 通话时间1 (格式可能多样)
        time2: 通话时间2
    
    Returns:
        相似度分数 (0-1)
    """
    if not time1 or not time2:
        return 0.0
    
    try:
        from datetime import datetime
        import re
        
        # 标准化时间字符串：移除多余空格、统一格式
        time1 = re.sub(r'\s+', ' ', time1.strip())  # 将多个空格替换为单个空格
        time2 = re.sub(r'\s+', ' ', time2.strip())
        
        # 处理"上午/下午"前后的空格不一致问题
        time1 = re.sub(r'(上午|下午|AM|PM)\s*', r'\1', time1)  # 统一移除时段后的空格
        time2 = re.sub(r'(上午|下午|AM|PM)\s*', r'\1', time2)
        
        # 从conversation_text中提取具体的时间部分
        # 处理格式："通话时间: 6月24日 上午11:14\n通话日期: 2025-06-24"
        time1_match = re.search(r'通话时间[:：]\s*(.+?)(?:\n|$)', time1)
        if time1_match:
            time1 = time1_match.group(1).strip()
        
        time2_match = re.search(r'通话时间[:：]\s*(.+?)(?:\n|$)', time2)
        if time2_match:
            time2 = time2_match.group(1).strip()
        
        # 如果完全相同（标准化后），返回1.0
        if time1 == time2:
            return 1.0
        
        # 尝试解析时间
        # 提取日期和时间部分
        def parse_datetime(time_str):
            # 增加对中文时间格式的支持
            patterns = [
                # 中文格式：6月24日 上午11:14
                r'(\d{1,2}月\d{1,2}日)\s*(上午|下午)?(\d{1,2}[:：]\d{2})',
                # 标准格式：2025-06-24 11:14
                r'(\d{4}[-/年]\d{1,2}[-/月]\d{1,2}[日]?)\s*(\d{1,2}[:：]\d{2})',
                # 其他格式
                r'(\d{4}-\d{2}-\d{2})\s*(\d{2}:\d{2})',
                r'(\d{2}/\d{2})\s*(\d{2}:\d{2})'
            ]
            
            for pattern in patterns:
                match = re.search(pattern, time_str)
                if match:
                    if len(match.groups()) == 3:  # 中文格式
                        date_part = match.group(1)
                        am_pm = match.group(2) or ''
                        time_part = match.group(3)
                        return date_part, f"{am_pm}{time_part}"
                    else:
                        date_part = match.group(1)
                        time_part = match.group(2)
                        return date_part, time_part
            
            return None, None
        
        date1, time1_only = parse_datetime(time1)
        date2, time2_only = parse_datetime(time2)
        
        # 如果解析失败，进行更智能的字符串比较
        if not (date1 and time1_only and date2 and time2_only):
            # 确保time1和time2不是None
            if time1 is None or time2 is None:
                return 0.0
                
            # 移除所有空格后比较
            time1_no_space = time1.replace(' ', '')
            time2_no_space = time2.replace(' ', '')
            if time1_no_space == time2_no_space:
                return 0.95  # 只是空格差异，给高分
            
            # 检查是否只是细微差异
            if len(time1) == len(time2):
                diff_count = sum(1 for a, b in zip(time1, time2) if a != b)
                if diff_count <= 2:  # 只有1-2个字符不同
                    return 0.8
            
            return 0.0
        
        # 日期不同直接返回0
        if date1 != date2:
            return 0.0
        
        # 比较时间部分（忽略上午/下午的格式差异）
        # 统一格式：移除时段标记，只比较时间
        time1_clean = re.sub(r'(上午|下午|AM|PM)', '', time1_only).strip()
        time2_clean = re.sub(r'(上午|下午|AM|PM)', '', time2_only).strip()
        
        if time1_clean == time2_clean:
            return 1.0
        
        # 解析时间部分
        try:
            h1, m1 = map(int, time1_clean.replace('：', ':').split(':'))
            h2, m2 = map(int, time2_clean.replace('：', ':').split(':'))
            
            # 计算时间差（分钟）
            minutes1 = h1 * 60 + m1
            minutes2 = h2 * 60 + m2
            diff_minutes = abs(minutes1 - minutes2)
            
            # 根据时间差计算相似度
            if diff_minutes == 0:
                return 1.0
            elif diff_minutes <= 3:
                return 0.95
            elif diff_minutes <= 5:
                return 0.9
            elif diff_minutes <= 10:
                return 0.7
            elif diff_minutes <= 15:
                return 0.5
            else:
                return 0.2
        except:
            # 时间解析失败，但日期相同，给一个中等分数
            return 0.5
            
    except Exception as e:
        logger.error(f"计算时间相似度时出错: {e}")
        return 0.0

def calculate_duration_similarity(duration1: Optional[int], duration2: Optional[int]) -> float:
    """
    计算通话时长相似度
    
    Args:
        duration1: 通话时长1（秒）
        duration2: 通话时长2（秒）
    
    Returns:
        相似度分数 (0-1)
    """
    if duration1 is None or duration2 is None:
        return 0.0
    
    # 计算时长差（秒）
    diff_seconds = abs(duration1 - duration2)
    
    # 根据时长差计算相似度
    if diff_seconds == 0:
        return 1.0
    elif diff_seconds <= 3:
        return 0.95
    elif diff_seconds <= 5:
        return 0.9
    elif diff_seconds <= 10:
        return 0.8
    elif diff_seconds <= 15:
        return 0.6
    elif diff_seconds <= 30:
        return 0.4
    else:
        return 0.1

def calculate_text_similarity(text1: Optional[str], text2: Optional[str]) -> float:
    """
    计算文本相似度（联系人或公司名称）
    
    Args:
        text1: 文本1
        text2: 文本2
    
    Returns:
        相似度分数 (0-1)
    """
    # 处理空值情况
    if not text1 and not text2:
        return 0.5  # 都为空，给中等分数
    if not text1 or not text2:
        return 0.5  # 一个为空，给中等分数
    
    # 标准化文本
    text1 = text1.strip().lower()
    text2 = text2.strip().lower()
    
    # 完全匹配
    if text1 == text2:
        return 1.0
    
    # 包含关系
    if text1 in text2 or text2 in text1:
        return 0.8
    
    # 部分匹配（考虑姓氏等）
    if len(text1) > 0 and len(text2) > 0:
        if text1[0] == text2[0]:  # 首字相同（如姓氏）
            return 0.6
    
    # 计算编辑距离（简化版）
    try:
        # 简单的字符重合度
        common_chars = sum(1 for c in text1 if c in text2)
        similarity = common_chars / max(len(text1), len(text2))
        return min(0.5, similarity)
    except:
        return 0.0

def adjust_weights_for_missing_data(call1: Dict[str, Any], call2: Dict[str, Any]) -> Dict[str, float]:
    """
    根据缺失数据调整权重
    
    Args:
        call1: 通话记录1
        call2: 通话记录2
    
    Returns:
        调整后的权重字典
    """
    weights = DUPLICATE_DETECTION_WEIGHTS.copy()
    
    # 检查缺失情况
    contact_missing = not (call1.get('contact_person') and call2.get('contact_person'))
    company_missing = not (call1.get('company_name') and call2.get('company_name'))
    
    if contact_missing and company_missing:
        # 两个都缺失：时间权重提升到90%
        weights["call_time_match"] = 0.6
        weights["call_duration_match"] = 0.3
        weights["contact_name_match"] = 0.05
        weights["company_name_match"] = 0.05
    elif contact_missing:
        # 联系人缺失：时间权重提升5%
        weights["call_time_match"] = 0.55
        weights["call_duration_match"] = 0.3
        weights["contact_name_match"] = 0.05
        weights["company_name_match"] = 0.1
    elif company_missing:
        # 公司缺失：时间权重提升5%
        weights["call_time_match"] = 0.55
        weights["call_duration_match"] = 0.3
        weights["contact_name_match"] = 0.1
        weights["company_name_match"] = 0.05
    
    return weights

def calculate_similarity(call1: Dict[str, Any], call2: Dict[str, Any]) -> float:
    """
    计算两个通话记录的相似度
    
    Args:
        call1: 新的通话记录（从图片识别）
        call2: 现有的通话记录（从数据库）
    
    Returns:
        相似度分数 (0-1)
    """
    # 1. 时间相似度 (50%权重)
    time_sim = calculate_time_similarity(
        call1.get('call_time'),  # 新记录的时间
        call2.get('conversation_text')  # 数据库中的时间
    )
    
    # 2. 时长相似度 (30%权重)
    # 从数据库的analysis_text中提取时长
    duration2 = extract_duration_from_analysis(call2.get('analysis_text', ''))
    duration_sim = calculate_duration_similarity(
        call1.get('duration_seconds'),
        duration2
    )
    
    # 3. 联系人相似度 (10%权重)
    contact_sim = calculate_text_similarity(
        call1.get('contact_info'),  # 使用contact_info字段
        call2.get('contact_person')
    )
    
    # 4. 公司相似度 (10%权重)
    company_sim = calculate_text_similarity(
        call1.get('company_name'),
        call2.get('company_name')
    )
    
    # 动态权重调整（处理缺失数据）
    # 需要转换call1的字段名以匹配权重调整函数
    call1_adjusted = {
        'contact_person': call1.get('contact_info'),
        'company_name': call1.get('company_name')
    }
    weights = adjust_weights_for_missing_data(call1_adjusted, call2)
    
    # 加权计算总相似度
    total_similarity = (
        time_sim * weights["call_time_match"] +
        duration_sim * weights["call_duration_match"] +
        contact_sim * weights["contact_name_match"] +
        company_sim * weights["company_name_match"]
    )
    
    logger.debug(f"相似度计算详情: 时间={time_sim:.2f}, 时长={duration_sim:.2f}, "
                f"联系人={contact_sim:.2f}, 公司={company_sim:.2f}, 总分={total_similarity:.2f}")
    
    return total_similarity

def extract_duration_from_analysis(analysis_text: str) -> Optional[int]:
    """
    从analysis_text中提取通话时长（秒）
    
    Args:
        analysis_text: 分析文本
    
    Returns:
        时长（秒）或None
    """
    if not analysis_text:
        return None
    
    # 尝试匹配各种时长格式
    patterns = [
        r'时长秒数[:：]\s*(\d+)',      # 匹配 "时长秒数: 74"
        r'(\d+)\s*秒',                 # 匹配 "74秒"
        r'通话时长[:：]\s*(\d+)\s*秒',  # 匹配 "通话时长: 74秒"
    ]
    
    for pattern in patterns:
        match = re.search(pattern, analysis_text)
        if match:
            return int(match.group(1))
    
    # 如果没有直接的秒数，尝试解析时长文本（如 "01:14"）
    duration_pattern = r'通话时长[:：]\s*(\d{1,2}):(\d{2})'
    match = re.search(duration_pattern, analysis_text)
    if match:
        minutes = int(match.group(1))
        seconds = int(match.group(2))
        return minutes * 60 + seconds
    
    return None

def smart_duplicate_detection(new_calls: List[Dict[str, Any]], 
                            existing_calls: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    智能去重检测
    
    Args:
        new_calls: 新识别的通话列表
        existing_calls: 数据库中的现有通话记录
    
    Returns:
        {
            "processed_calls": [...],    # 将要处理的通话列表
            "skipped_calls": [...],      # 跳过的重复通话列表
            "skip_count": 3,             # 跳过数量
            "process_count": 7           # 处理数量
        }
    """
    processed_calls = []
    skipped_calls = []
    
    logger.info(f"🤖 开始智能去重检测: {len(new_calls)} 个新记录, {len(existing_calls)} 个现有记录")
    
    for new_call in new_calls:
        max_similarity = 0
        best_match = None
        
        # 与每个现有记录比较
        for existing_call in existing_calls:
            similarity = calculate_similarity(new_call, existing_call)
            if similarity > max_similarity:
                max_similarity = similarity
                best_match = existing_call
        
        # 根据相似度决定处理方式
        if max_similarity >= DUPLICATE_THRESHOLD:
            # 自动跳过
            skipped_calls.append({
                "call": new_call,
                "matched_call": best_match,
                "similarity": max_similarity
            })
            logger.info(f"📌 跳过重复记录: {new_call.get('contact_info', '未知')} "
                       f"(相似度: {max_similarity:.2f})")
        else:
            # 正常处理
            processed_calls.append(new_call)
    
    logger.info(f"✅ 智能去重完成: 处理 {len(processed_calls)} 个, 跳过 {len(skipped_calls)} 个")
    
    return {
        "processed_calls": processed_calls,
        "skipped_calls": skipped_calls,
        "skip_count": len(skipped_calls),
        "process_count": len(processed_calls)
    }

def check_image_duplicates(uploaded_images: List[Any], salesperson_id: int, db_manager) -> Dict[str, Any]:
    """
    检查上传图片的文件名重复情况
    
    Args:
        uploaded_images: Streamlit上传的图片文件列表
        salesperson_id: 销售人员ID
        db_manager: 数据库管理器实例
    
    Returns:
        去重检查结果字典
    """
    import logging
    
    logger = logging.getLogger(__name__)
    
    if not uploaded_images:
        return {
            "has_duplicates": False,
            "duplicates": [],
            "new_files": [],
            "duplicate_files": [],
            "clean_files": uploaded_images
        }
    
    # 提取文件名列表
    filenames = [img.name for img in uploaded_images]
    
    logger.info(f"🔍 开始检查图片文件名重复情况")
    logger.info(f"   销售人员ID: {salesperson_id}")
    logger.info(f"   图片文件数: {len(filenames)}")
    logger.info(f"   文件列表: {filenames}")
    
    try:
        # 调用数据库检查函数
        duplicate_result = db_manager.check_duplicate_filenames(
            salesperson_id=salesperson_id,
            filenames=filenames,
            days_back=30  # 检查最近30天
        )
        
        duplicates = duplicate_result.get("duplicates", [])
        new_files = duplicate_result.get("new_files", [])
        
        # 分离重复和非重复的图片文件对象
        duplicate_filenames = [dup["filename"] for dup in duplicates]
        duplicate_files = [img for img in uploaded_images if img.name in duplicate_filenames]
        clean_files = [img for img in uploaded_images if img.name in new_files]
        
        result = {
            "has_duplicates": len(duplicates) > 0,
            "duplicates": duplicates,  # 重复文件的详细信息
            "new_files": new_files,   # 新文件名列表
            "duplicate_files": duplicate_files,  # 重复的图片文件对象
            "clean_files": clean_files,  # 非重复的图片文件对象
            "total_images": len(uploaded_images),
            "duplicate_count": len(duplicates),
            "new_count": len(new_files)
        }
        
        logger.info(f"✅ 图片去重检查完成:")
        logger.info(f"   总图片数: {result['total_images']}")
        logger.info(f"   重复文件: {result['duplicate_count']} 个")
        logger.info(f"   新文件: {result['new_count']} 个")
        
        if duplicates:
            logger.info(f"📋 重复文件详情:")
            for dup in duplicates:
                logger.info(f"   - {dup['filename']} (上次上传: {dup['last_upload_date']}, {dup['days_ago']}天前)")
        
        return result
        
    except Exception as e:
        logger.error(f"❌ 图片去重检查失败: {str(e)}")
        # 发生错误时，将所有文件都视为新文件
        return {
            "has_duplicates": False,
            "duplicates": [],
            "new_files": filenames,
            "duplicate_files": [],
            "clean_files": uploaded_images,
            "total_images": len(uploaded_images),
            "duplicate_count": 0,
            "new_count": len(uploaded_images),
            "error": str(e)
        }

def filter_duplicate_images(uploaded_images: List[Any], duplicate_result: Dict[str, Any], user_choice: str) -> List[Any]:
    """
    根据用户选择过滤重复图片
    
    Args:
        uploaded_images: 原始上传的图片列表
        duplicate_result: 去重检查结果
        user_choice: 用户选择 ('skip_duplicates', 'force_all', 'manual_select')
    
    Returns:
        过滤后的图片文件列表
    """
    import logging
    
    logger = logging.getLogger(__name__)
    
    if user_choice == "skip_duplicates":
        # 跳过重复项，只处理新文件
        filtered_images = duplicate_result.get("clean_files", [])
        logger.info(f"📝 用户选择跳过重复项: 处理 {len(filtered_images)} 张新图片")
        
    elif user_choice == "force_all":
        # 强制处理所有文件
        filtered_images = uploaded_images
        logger.info(f"📝 用户选择强制处理所有文件: 处理 {len(filtered_images)} 张图片")
        
    else:
        # 默认情况：如果没有重复，处理所有文件；如果有重复，需要用户明确选择
        if not duplicate_result.get("has_duplicates", False):
            filtered_images = uploaded_images
            logger.info(f"📝 无重复文件: 处理 {len(filtered_images)} 张图片")
        else:
            # 有重复但用户未选择，返回空列表等待用户选择
            filtered_images = []
            logger.info(f"📝 有重复文件但用户未选择处理方式: 暂停处理")
    
    return filtered_images 