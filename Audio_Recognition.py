import os
import json
import time
import uuid
import datetime
import copy
import asyncio
import aiohttp
import logging
import subprocess
import tempfile
import re
import urllib.parse
from typing import List, Dict, Any, Optional
import tos
from pydub import AudioSegment
from LLM_Workflow import llm_workflow
from config import VOLCANO_CONFIG  # 从config导入火山引擎配置

def sanitize_filename(filename: str) -> str:
    """
    清理文件名，移除特殊字符，确保URL安全
    根据实际测试结果：
    1. "微信"等词汇被转写服务商禁止，需要替换
    2. 特殊字符会影响下载，需要全面处理
    3. 长度不是主要问题，可以保持较长的文件名
    
    Args:
        filename: 原始文件名
        
    Returns:
        str: 清理后的安全文件名
    """
    # 移除扩展名进行处理
    name_part = os.path.splitext(filename)[0]
    ext_part = os.path.splitext(filename)[1]
    
    # 先处理敏感词汇（基于实际测试结果）
    sensitive_words = {
        '微信': 'wechat',
        '微信录音': 'wechat_audio',
        # 可能的其他敏感词汇（如果发现问题可以继续添加）
        'WeChat': 'wechat',
        'WECHAT': 'wechat',
    }
    
    # 应用敏感词汇替换
    clean_name = name_part
    for sensitive, replacement in sensitive_words.items():
        if sensitive in clean_name:
            logging.debug(f"文件名敏感词替换: '{sensitive}' → '{replacement}'")
        clean_name = clean_name.replace(sensitive, replacement)
    
    logging.debug(f"敏感词处理后: {clean_name}")
    
    # 处理所有特殊字符（基于测试：特殊字符确实会影响）
    special_chars = {
        # 括号类
        '【': '_',
        '】': '_',
        '（': '_',
        '）': '_',
        '(': '_',
        ')': '_',
        '[': '_',
        ']': '_',
        '{': '_',
        '}': '_',
        
        # 空格和连接符
        ' ': '_',
        '-': '_',
        '—': '_',
        '–': '_',
        
        # 标点符号
        '+': '_',
        '=': '_',
        '#': '_',
        '@': '_',
        '&': '_',
        '%': '_',
        '$': '_',
        '!': '_',
        '？': '_',
        '?': '_',
        '*': '_',
        '/': '_',
        '\\': '_',
        ':': '_',
        '：': '_',
        ';': '_',
        '；': '_',
        '<': '_',
        '>': '_',
        '|': '_',
        '"': '_',
        '"': '_',
        '"': '_',
        "'": '_',
        ''': '_',
        ''': '_',
        '`': '_',
        '~': '_',
        
        # 中文标点
        '，': '_',
        '。': '_',
        '！': '_',
        '、': '_',
        '《': '_',
        '》': '_',
        '〈': '_',
        '〉': '_',
        '「': '_',
        '」': '_',
        '『': '_',
        '』': '_',
        
        # 其他可能有问题的符号
        '^': '_',
    }
    
    # 应用特殊字符替换
    original_clean_name = clean_name
    for char, replacement in special_chars.items():
        if char in clean_name:
            logging.debug(f"发现特殊字符 '{char}'，将替换为 '{replacement}'")
        clean_name = clean_name.replace(char, replacement)
    
    logging.debug(f"特殊字符处理前: {original_clean_name}")
    logging.debug(f"特殊字符处理后: {clean_name}")
    
    # 移除连续的下划线
    clean_name = re.sub(r'_{2,}', '_', clean_name)
    
    # 移除首尾的下划线
    clean_name = clean_name.strip('_')
    
    # 如果清理后为空，使用默认名称
    if not clean_name:
        clean_name = 'audio_file'
    
    # 根据测试结果，长度不是主要问题，所以移除严格的长度限制
    # 但保留一个合理的上限以防意外
    if len(clean_name) > 50:
        clean_name = clean_name[:50].rstrip('_')
    
    return clean_name + ext_part

async def upload_to_tos_async(file_path: str) -> str:
    """
    异步将本地文件上传到TOS并获取URL
    
    Args:
        file_path: 本地文件路径
        
    Returns:
        str: 文件在TOS上的URL
    """
    logging.debug(f"开始上传文件到TOS: {file_path}")
    
    # 由于tos库不支持异步操作，使用run_in_executor在线程池中执行
    return await asyncio.to_thread(upload_to_tos_sync, file_path)
    
def upload_to_tos_sync(local_file_path: str) -> str:
    """
    同步将本地文件上传到TOS（在异步函数中通过线程池调用）
    
    Args:
        local_file_path: 本地文件路径
        
    Returns:
        str: 文件在TOS上的URL
    """
    # TOS凭证信息
    ak = VOLCANO_CONFIG["tos"]["ak"]
    sk = VOLCANO_CONFIG["tos"]["sk"]
    endpoint = VOLCANO_CONFIG["tos"]["endpoint"]
    region = VOLCANO_CONFIG["tos"]["region"]
    bucket_name = VOLCANO_CONFIG["tos"]["bucket_name"]
    
    logging.debug("创建 TOS 客户端...")
    # 创建客户端
    client = tos.TosClientV2(ak, sk, endpoint, region)
    
    # 生成唯一的对象键名（使用清理后的文件名+时间戳+随机ID）
    file_name = os.path.basename(local_file_path)
    clean_filename = sanitize_filename(file_name)
    file_ext = os.path.splitext(clean_filename)[1]
    clean_name_part = os.path.splitext(clean_filename)[0]
    
    current_time = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    random_id = str(uuid.uuid4())[:8]  # 使用UUID的前8位作为随机ID
    
    # 避免重复的temp前缀，如果文件名已经有temp前缀就直接使用
    if clean_name_part.startswith('temp_'):
        object_key = f"{clean_name_part}_{current_time}_{random_id}{file_ext}"
    else:
        object_key = f"temp_{clean_name_part}_{current_time}_{random_id}{file_ext}"
    
    # 移除过度的URL编码，保持原有的中文字符
    # object_key = urllib.parse.quote(object_key, safe='._-')  # 移除这行，避免过度编码
    
    logging.debug(f"原始文件名: {file_name}")
    logging.debug(f"清理后文件名: {clean_filename}")
    logging.debug(f"对象键名: {object_key}")
    
    try:
        # 上传对象
        logging.debug(f"上传对象: {object_key}...")
        with open(local_file_path, 'rb') as f:
            resp = client.put_object(bucket_name, object_key, content=f)
        logging.debug(f"上传对象响应状态码: {resp.status_code}")
        
        # 使用正确的方法生成公共URL
        # 方法1：设置对象的ACL为public-read（修复ACL设置）
        try:
            from tos.enum import ACLType
            client.put_object_acl(bucket_name, object_key, acl=ACLType.ACL_Public_Read)
            # 生成公共URL
            file_url = f"https://{bucket_name}.{endpoint}/{object_key}"
            logging.debug(f"公共URL: {file_url}")
            return file_url
        except Exception as acl_error:
            logging.error(f"设置对象ACL失败: {acl_error}")
            
            # 方法2：尝试使用签名URL（修复签名URL生成）
            try:
                # 使用签名URL工具类签名URL
                current_time = int(time.time())
                expiration = current_time + 24 * 60 * 60  # 24小时后过期
                
                # 修复签名URL生成
                try:
                    from tos.enum import HttpMethodEnum
                    signed_url = client.pre_signed_url(HttpMethodEnum.Http_Method_Get, bucket_name, object_key, expires=expiration)
                except ImportError:
                    try:
                        # 尝试使用其他可能的方法
                        signed_url = client.generate_presigned_url('GET', bucket_name, object_key, expiration)
                    except:
                        # 最后的备选方案 - 使用正确的对象键名构造URL
                        # 对于URL中的中文字符，只在必要时进行编码
                        encoded_object_key = urllib.parse.quote(object_key.encode('utf-8'), safe='._-/')
                        signed_url = f"https://{bucket_name}.{endpoint}/{encoded_object_key}"
                
                logging.debug(f"签名URL: {signed_url}")
                return signed_url
            except Exception as sign_error:
                logging.error(f"生成签名URL失败: {sign_error}")
                
                # 方法3：如果以上方法都失败，使用临时公开URL（正确编码）
                # 只在URL中对中文字符进行编码，不改变object_key本身
                encoded_object_key = urllib.parse.quote(object_key.encode('utf-8'), safe='._-/')
                temp_url = f"https://{bucket_name}.{endpoint}/{encoded_object_key}"
                logging.warning(f"无法生成正确的签名URL，使用普通URL: {temp_url}")
                logging.warning(f"请确保该存储桶有公共读取权限，否则转写服务可能无法访问")
                return temp_url
    except Exception as e:
        logging.error(f"上传文件过程中发生错误: {e}")
        raise

async def submit_task_async(session: aiohttp.ClientSession, file_url: str) -> Dict[str, Any]:
    """
    异步提交语音转写任务
    
    Args:
        session: aiohttp会话
        file_url: 文件URL
        
    Returns:
        Dict: 包含task_id和x_tt_logid的字典
    """
    logging.debug(f"开始提交转写任务，文件URL: {file_url}")
    submit_url = "https://openspeech.bytedance.com/api/v3/auc/bigmodel/submit"

    task_id = str(uuid.uuid4())

    headers = {
        "X-Api-App-Key": VOLCANO_CONFIG["appid"],
        "X-Api-Access-Key": VOLCANO_CONFIG["token"],
        "X-Api-Resource-Id": "volc.bigasr.auc",
        "X-Api-Request-Id": task_id,
        "X-Api-Sequence": "-1"
    }

    request = {
        "user": {
            "uid": "fake_uid"
        },
        "audio": {
            "url": file_url,
            "format": "wav",  # 优先使用wav格式，转换更稳定且质量更好
            "codec": "raw",
            "rate": 16000,
            "bits": 16,
            "channel": 1      # 如果是双声道音频，改为2
        },
        "request": {
            "model_name": "bigmodel",
            "enable_itn": True,       # 启用文本规范化
            "enable_punc": True,      # 启用标点
            "enable_ddc": True,       # 启用语义顺滑
            "show_utterances": True,  # 输出语音停顿、分句、分词信息
            "enable_speaker_info": True,  # 启用说话人聚类分离
            "vad_segment": True,      # 使用vad分句
            "corpus": {
                "correct_table_name": "",
                "context": ""
            }
        }
    }
    
    logging.debug(f'提交转写任务，任务ID: {task_id}')
    try:
        async with session.post(submit_url, data=json.dumps(request), headers=headers) as response:
            # 检查响应头
            if 'X-Api-Status-Code' in response.headers and response.headers["X-Api-Status-Code"] == "20000000":
                logging.debug(f'提交任务响应状态码: {response.headers["X-Api-Status-Code"]}')
                logging.debug(f'提交任务响应消息: {response.headers["X-Api-Message"]}')
                x_tt_logid = response.headers.get("X-Tt-Logid", "")
                logging.debug(f'提交任务日志ID: {x_tt_logid}')
                return {"task_id": task_id, "x_tt_logid": x_tt_logid}
            else:
                error_msg = f'提交任务失败，响应头信息: {response.headers}'
                logging.error(error_msg)
                raise Exception(error_msg)
    except Exception as e:
        logging.error(f"提交转写任务时发生错误: {e}")
        raise

async def query_task_async(session: aiohttp.ClientSession, task_id: str, x_tt_logid: str) -> Dict[str, Any]:
    """
    异步查询转写任务状态
    
    Args:
        session: aiohttp会话
        task_id: 任务ID
        x_tt_logid: 日志ID
    
    Returns:
        Dict: 查询结果
    """
    query_url = "https://openspeech.bytedance.com/api/v3/auc/bigmodel/query"

    headers = {
        "X-Api-App-Key": VOLCANO_CONFIG["appid"],
        "X-Api-Access-Key": VOLCANO_CONFIG["token"],
        "X-Api-Resource-Id": "volc.bigasr.auc",
        "X-Api-Request-Id": task_id,
        "X-Tt-Logid": x_tt_logid  # 固定传递 x-tt-logid
    }

    async with session.post(query_url, data=json.dumps({}), headers=headers) as response:
        if 'X-Api-Status-Code' in response.headers:
            status_code = response.headers["X-Api-Status-Code"]
            logging.debug(f'查询任务响应状态码: {status_code}')
            logging.debug(f'查询任务响应消息: {response.headers["X-Api-Message"]}')
            logging.debug(f'查询任务日志ID: {response.headers["X-Tt-Logid"]}')
            
            result = {
                "status_code": status_code,
                "message": response.headers["X-Api-Message"],
                "data": None
            }
            
            if status_code == "20000000":  # 任务完成
                # 获取响应体内容
                result["data"] = await response.json()
            
            return result
        else:
            error_msg = f'查询任务失败，响应头信息: {response.headers}'
            logging.error(error_msg)
            raise Exception(error_msg)

def process_transcription_result(result_json: Dict[str, Any]) -> Dict[str, Any]:
    """
    处理转写结果，去除words字段并返回处理后的结果
    
    Args:
        result_json: 原始转写结果JSON
        
    Returns:
        Dict: 处理后的转写结果（无words字段）
    """
    # 创建结果的深拷贝，避免修改原始数据
    processed_result = copy.deepcopy(result_json)
    
    # 检查并处理utterances字段
    if 'result' in processed_result and 'utterances' in processed_result['result']:
        for utterance in processed_result['result']['utterances']:
            if 'words' in utterance:
                del utterance['words']  # 删除words字段
    
    return processed_result

def save_to_txt(result_json: Dict[str, Any], output_file: str) -> None:
    """
    将转写结果保存为txt文件
    
    Args:
        result_json: 转写结果JSON
        output_file: 输出文件路径
    """
    with open(output_file, 'w', encoding='utf-8') as f:
        # 写入完整文本
        if 'result' in result_json and 'text' in result_json['result']:
            f.write("【完整文本】\n")
            f.write(result_json['result']['text'])
            f.write("\n\n")
        
        # 写入分句和说话人信息
        if 'result' in result_json and 'utterances' in result_json['result']:
            f.write("【分句信息】\n")
            for i, utterance in enumerate(result_json['result']['utterances']):
                speaker = utterance.get('additions', {}).get('speaker', '未知')
                start_time = utterance.get('start_time', 0) / 1000  # 毫秒转秒
                end_time = utterance.get('end_time', 0) / 1000
                text = utterance.get('text', '')
                
                f.write(f"说话人 {speaker} [{start_time:.2f}s-{end_time:.2f}s]: {text}\n")
        
        # 写入音频信息（使用改进的时长提取逻辑）
        f.write("\n【音频信息】\n")
        duration_seconds = extract_duration_from_result(result_json)
        f.write(f"总时长: {duration_seconds:.2f}秒\n")
        
        # 添加讯飞格式的转写结果用于LLM处理
        if 'result' in result_json and 'utterances' in result_json['result']:
            speakers = {}
            # 先将说话人ID映射到说话人序号（spk1, spk2）
            for utterance in result_json['result']['utterances']:
                speaker_id = utterance.get('additions', {}).get('speaker', '1')
                if speaker_id not in speakers:
                    speakers[speaker_id] = f"spk{len(speakers) + 1}"
            
            # 生成讯飞API兼容格式
            for utterance in result_json['result']['utterances']:
                speaker_id = utterance.get('additions', {}).get('speaker', '1')
                spk_prefix = speakers.get(speaker_id, "spk1")
                text = utterance.get('text', '')
                f.write(f"{spk_prefix}##{text}\n")

def extract_duration_from_result(result_json: Dict[str, Any]) -> float:
    """
    从转写结果中提取音频时长
    
    Args:
        result_json: 火山引擎转写结果JSON
        
    Returns:
        float: 音频时长（秒）
    """
    duration_seconds = 0
    
    # 详细记录输入数据结构用于调试
    logging.debug(f"extract_duration_from_result 输入数据: {json.dumps(result_json, indent=2, ensure_ascii=False)[:500]}...")
    
    # 方法1: 从audio_info.duration获取
    if 'audio_info' in result_json and 'duration' in result_json['audio_info']:
        duration_ms = result_json['audio_info'].get('duration', 0)
        if duration_ms > 0:
            duration_seconds = duration_ms / 1000  # 毫秒转秒
            logging.info(f"✅ 从audio_info获取时长: {duration_seconds:.2f}秒")
            return duration_seconds
    
    # 方法2: 从utterances的最大end_time计算
    if 'result' in result_json and 'utterances' in result_json['result']:
        utterances = result_json['result']['utterances']
        if utterances and len(utterances) > 0:
            max_end_time = 0
            for utterance in utterances:
                end_time = utterance.get('end_time', 0)
                if end_time > max_end_time:
                    max_end_time = end_time
            
            if max_end_time > 0:
                duration_seconds = max_end_time / 1000  # 毫秒转秒
                logging.info(f"✅ 从utterances计算时长: {duration_seconds:.2f}秒")
                return duration_seconds
    
    # 方法3: 检查其他可能的字段
    if 'duration' in result_json:
        duration_value = result_json['duration']
        if isinstance(duration_value, (int, float)) and duration_value > 0:
            # 判断单位（如果值很大可能是毫秒，否则可能是秒）
            if duration_value > 1000:  # 假设超过1000的是毫秒
                duration_seconds = duration_value / 1000
            else:
                duration_seconds = duration_value
            logging.info(f"✅ 从根级duration字段获取时长: {duration_seconds:.2f}秒")
            return duration_seconds
    
    # 方法4: 如果转写结果中有文本，估算时长（作为最后的备选方案）
    if 'result' in result_json and 'text' in result_json['result']:
        text = result_json['result']['text']
        if text:
            # 根据文本长度粗略估算时长（每分钟大约150-200字）
            estimated_duration = len(text) / 3  # 粗略估算：每3个字符约1秒
            if estimated_duration > 0:
                logging.warning(f"⚠️ 使用文本长度估算时长: {estimated_duration:.2f}秒 (文本长度: {len(text)}字符)")
                return estimated_duration
    
    # 如果所有方法都失败，记录详细警告信息
    logging.error(f"❌ 无法从转写结果中提取时长信息！")
    logging.error(f"result_json 主要字段: {list(result_json.keys())}")
    if 'result' in result_json:
        logging.error(f"result 字段内容: {list(result_json['result'].keys())}")
    if 'audio_info' in result_json:
        logging.error(f"audio_info 字段内容: {result_json['audio_info']}")
    
    # 如果完全无法获取时长，返回一个很小的正值，避免显示0秒
    logging.warning("使用默认时长1秒")
    return 1.0  # 返回1秒而不是0秒

async def process_file(file_path: str) -> Dict[str, Any]:
    """
    异步处理单个文件：上传、提交转写任务、查询结果，保存转写文本并启动LLM工作流
    
    Args:
        file_path: 文件路径
    
    Returns:
        Dict: 处理结果，包含转写文本和分析结果
    """
    logging.debug(f"开始处理文件: {file_path}")
    
    if not os.path.exists(file_path):
        return {
            "file_path": file_path,
            "status": "error",
            "message": f"文件不存在: {file_path}"
        }
    
    try:
        # 验证文件大小和基本信息
        file_size = os.path.getsize(file_path)
        if file_size == 0:
            return {
                "file_path": file_path,
                "status": "error",
                "message": f"文件为空: {file_path}"
            }
        
        logging.debug(f"处理文件: {file_path} (大小: {file_size} 字节)")
        
        # 检查文件格式并进行预处理
        file_ext = os.path.splitext(file_path)[1].lower()
        temp_converted_file = None
        
        # 先验证音频文件的有效性
        try:
            # 尝试读取音频文件进行基本验证
            test_audio = AudioSegment.from_file(file_path)
            duration_ms = len(test_audio)
            
            if duration_ms < 100:  # 少于100ms的音频文件可能有问题
                logging.warning(f"⚠️ 音频文件时长过短: {duration_ms}ms，可能存在问题")
                return {
                    "file_path": file_path,
                    "status": "error",
                    "message": f"音频文件时长过短: {duration_ms}ms"
                }
            
            logging.debug(f"音频文件验证通过，时长: {duration_ms}ms")
            
        except Exception as e:
            logging.error(f"音频文件验证失败: {e}")
            return {
                "file_path": file_path,
                "status": "error",
                "message": f"音频文件格式无效或损坏: {e}"
            }
        
        # 根据文件格式进行处理
        if file_ext == '.aac':
            logging.debug(f"检测到AAC格式文件，开始转换为WAV格式...")
            try:
                converted_path = await convert_aac_to_wav_async(file_path)
                logging.debug(f"AAC文件已转换为WAV: {converted_path}")
                file_to_upload = converted_path
                temp_converted_file = converted_path
            except Exception as conv_error:
                logging.error(f"AAC文件转换失败: {conv_error}")
                return {
                    "file_path": file_path,
                    "status": "error",
                    "message": f"AAC文件转换失败: {conv_error}"
                }
        else:
            # 对于其他格式，直接使用原文件，但可能需要格式转换以确保兼容性
            if file_ext not in ['.mp3', '.wav', '.m4a', '.ogg']:
                logging.warning(f"⚠️ 不常见的音频格式: {file_ext}，尝试转换为WAV")
                try:
                    converted_path = await _convert_to_wav_async(file_path)
                    logging.debug(f"音频文件已转换为WAV: {converted_path}")
                    file_to_upload = converted_path
                    temp_converted_file = converted_path
                except Exception as conv_error:
                    logging.warning(f"格式转换失败，尝试使用原文件: {conv_error}")
                    file_to_upload = file_path
            else:
                file_to_upload = file_path
        
        # 最终验证要上传的文件
        if not os.path.exists(file_to_upload):
            return {
                "file_path": file_path,
                "status": "error",
                "message": f"处理后的文件不存在: {file_to_upload}"
            }
        
        upload_file_size = os.path.getsize(file_to_upload)
        if upload_file_size == 0:
            return {
                "file_path": file_path,
                "status": "error",
                "message": f"处理后的文件为空: {file_to_upload}"
            }
        
        logging.debug(f"准备上传文件: {file_to_upload} (大小: {upload_file_size} 字节)")
        
        # 记录转换文件信息（如果有转换）
        conversion_info = None
        if temp_converted_file and temp_converted_file != file_path:
            try:
                # 验证转换后的文件
                test_audio = AudioSegment.from_wav(temp_converted_file)
                conversion_info = {
                    "converted_file_path": temp_converted_file,
                    "original_file_path": file_path,
                    "original_size_bytes": os.path.getsize(file_path),
                    "converted_size_bytes": upload_file_size,
                    "converted_duration_seconds": len(test_audio) / 1000.0,
                    "converted_format": "WAV",
                    "converted_sample_rate": test_audio.frame_rate,
                    "converted_channels": test_audio.channels,
                    "conversion_success": True
                }
                logging.info(f"📄 转换文件信息: {conversion_info['converted_file_path']}")
                logging.info(f"📊 转换详情: {conversion_info['converted_size_bytes']} 字节, "
                           f"{conversion_info['converted_duration_seconds']:.2f}秒, "
                           f"{conversion_info['converted_sample_rate']}Hz, "
                           f"{conversion_info['converted_channels']}声道")
            except Exception as e:
                conversion_info = {
                    "converted_file_path": temp_converted_file,
                    "original_file_path": file_path,
                    "conversion_success": False,
                    "conversion_error": str(e)
                }
                logging.warning(f"转换文件信息获取失败: {e}")

        # 1. 上传文件到TOS
        file_url = await upload_to_tos_async(file_to_upload)
        logging.debug(f"文件已上传到TOS: {file_url}")
        
        # 2. 提交转写任务
        async with aiohttp.ClientSession() as session:
            submit_result = await submit_task_async(session, file_url)
            task_id = submit_result["task_id"]
            x_tt_logid = submit_result["x_tt_logid"]
            
            # 3. 轮询查询任务结果
            max_retries = 60  # 最多等待5分钟（60次 × 5秒）
            retry_count = 0
            
            while retry_count < max_retries:
                query_result = await query_task_async(session, task_id, x_tt_logid)
                status_code = query_result["status_code"]
                
                if status_code == "20000000":  # 任务完成
                    logging.debug("转写结果获取成功!")
                    result_json = query_result["data"]
                    break
                elif status_code != "20000001" and status_code != "20000002":  # 任务失败
                    error_msg = f"转写失败: {query_result['message']}"
                    logging.error(error_msg)
                    # 清理临时文件
                    if temp_converted_file and os.path.exists(temp_converted_file):
                        try:
                            os.remove(temp_converted_file)
                        except:
                            pass
                    return {
                        "file_path": file_path,
                        "status": "error",
                        "message": error_msg
                    }
                else:  # 任务处理中
                    retry_count += 1
                    logging.debug(f"任务处理中，状态码: {status_code}，等待5秒后重试... ({retry_count}/{max_retries})")
                    await asyncio.sleep(5)
            
            # 检查是否超时
            if retry_count >= max_retries:
                error_msg = f"转写任务超时，超过最大等待时间 ({max_retries * 5} 秒)"
                logging.error(error_msg)
                # 清理临时文件
                if temp_converted_file and os.path.exists(temp_converted_file):
                    try:
                        os.remove(temp_converted_file)
                    except:
                        pass
                return {
                    "file_path": file_path,
                    "status": "error",
                    "message": error_msg
                }
        
        # 4. 处理转写结果
        processed_result = process_transcription_result(result_json)
        
        # 5. 生成输出文件名（基于原文件名）
        file_name = os.path.basename(file_path)
        output_file_path = f"{file_name}_output.txt"
        
        # 6. 保存处理后的结果到txt文件
        save_to_txt(processed_result, output_file_path)
        logging.debug(f"已将转写结果保存至: {output_file_path}")
        
        # 7. 读取转写文本，准备进行LLM分析
        with open(output_file_path, 'r', encoding='utf-8') as f:
            conversation_text = f.read()
        
        # 7.1 改进的音频时长提取
        duration_seconds = extract_duration_from_result(result_json)
        logging.debug(f"提取到的音频时长: {duration_seconds:.2f}秒")
        
        # 7.2 判断是否为有效通话（时长>=60秒）
        is_valid_call = duration_seconds >= 60
        
        # 8. 调用LLM工作流进行分析
        logging.debug(f"开始调用LLM工作流分析，文件 {file_path}，时长 {duration_seconds:.2f}秒，有效通话: {is_valid_call}")
        analysis_result = await llm_workflow(conversation_text, duration_seconds, is_valid_call)
        logging.debug(f"LLM工作流分析完成，文件 {file_path}")
        
        # 9. 准备返回结果（包含转换文件信息）
        result = {
            "file_path": file_path,
            "status": "success",
            "analysis_result": analysis_result,
            "conversation_text": conversation_text,
            "output_file_path": output_file_path,
            "duration_seconds": duration_seconds,
            "is_valid_call": is_valid_call
        }
        
        # 添加转换文件信息到结果中
        if conversion_info:
            result["conversion_info"] = conversion_info
            # 为了让用户能够验证，暂时不删除转换文件
            # 改为在结果中标记文件路径，由调用者决定何时清理
            if conversion_info.get("conversion_success", False):
                logging.info(f"💾 转换文件已保留供验证: {conversion_info['converted_file_path']}")
                logging.info(f"⚠️  注意：转换文件将在程序结束时自动清理")
        else:
            # 如果没有转换，立即清理临时文件（如果有）
            if temp_converted_file and os.path.exists(temp_converted_file) and temp_converted_file != file_path:
                try:
                    os.remove(temp_converted_file)
                    logging.debug(f"已删除临时转换文件: {temp_converted_file}")
                except Exception as e:
                    logging.warning(f"删除临时文件失败: {e}")
        
        return result
    
    except Exception as e:
        # 出错时清理临时转换文件
        if 'temp_converted_file' in locals() and temp_converted_file and os.path.exists(temp_converted_file) and temp_converted_file != file_path:
            try:
                os.remove(temp_converted_file)
                logging.debug(f"错误处理：已删除临时转换文件: {temp_converted_file}")
            except:
                pass
        
        logging.error(f"处理文件 {file_path} 时发生错误: {e}")
        return {
            "file_path": file_path,
            "status": "error", 
            "message": str(e)
        }

async def convert_aac_to_wav_async(aac_file_path: str) -> str:
    """
    异步将AAC格式音频文件转换为WAV格式
    
    Args:
        aac_file_path: AAC文件路径
        
    Returns:
        str: 转换后的WAV文件路径
    """
    # 使用线程池执行同步的音频转换操作
    return await asyncio.to_thread(convert_aac_to_wav_sync, aac_file_path)

def convert_aac_to_wav_sync(aac_file_path: str) -> str:
    """
    同步将AAC格式音频文件转换为WAV格式（在异步函数中通过线程池调用）
    修复版本：使用英文临时文件名避免FFmpeg编码问题
    
    Args:
        aac_file_path: AAC文件路径
        
    Returns:
        str: 转换后的WAV文件路径
    """
    try:
        # 验证输入文件
        if not os.path.exists(aac_file_path):
            raise Exception(f"输入文件不存在: {aac_file_path}")
        
        file_size = os.path.getsize(aac_file_path)
        if file_size == 0:
            raise Exception(f"输入文件为空: {aac_file_path}")
        
        logging.info(f"开始转换AAC文件: {aac_file_path}")
        logging.info(f"原始文件大小: {file_size} 字节")
        
        # 记录文件基本信息
        _log_file_info(aac_file_path)
        
        # 创建临时的英文文件名，避免FFmpeg编码问题
        temp_dir = os.path.dirname(aac_file_path)
        temp_id = str(uuid.uuid4())[:8]
        
        # 使用英文临时文件名进行转换
        temp_aac_path = os.path.join(temp_dir, f"temp_aac_{temp_id}.aac")
        temp_wav_path = os.path.join(temp_dir, f"temp_wav_{temp_id}.wav")
        
        try:
            # 复制原文件到临时英文文件名
            import shutil
            shutil.copy2(aac_file_path, temp_aac_path)
            logging.debug(f"已复制到临时文件: {temp_aac_path}")
            
            # 使用英文文件名进行转换
            logging.info("🔄 使用英文临时文件名转换AAC文件，避免编码问题")
            success = _try_universal_format_conversion(temp_aac_path, temp_wav_path)
            
            if not success:
                raise Exception("AAC文件转换失败")
            
            # 生成最终输出文件名（基于原始文件名）
            final_output_path = os.path.splitext(aac_file_path)[0] + "_converted.wav"
            
            # 如果最终输出文件已存在，先删除
            if os.path.exists(final_output_path):
                os.remove(final_output_path)
                logging.debug(f"已删除已存在的输出文件: {final_output_path}")
            
            # 将转换结果移动到最终位置
            shutil.move(temp_wav_path, final_output_path)
            logging.debug(f"转换结果已移动到: {final_output_path}")
            
            # 详细验证输出文件
            validation_result = _validate_converted_file(final_output_path, aac_file_path)
            if not validation_result["valid"]:
                raise Exception(f"转换后文件验证失败: {validation_result['error']}")
            
            logging.info(f"🎉 AAC转换完成！")
            logging.info(f"转换结果: {validation_result['info']}")
            
            return final_output_path
            
        finally:
            # 清理临时文件
            for temp_file in [temp_aac_path, temp_wav_path]:
                if os.path.exists(temp_file):
                    try:
                        os.remove(temp_file)
                        logging.debug(f"已清理临时文件: {temp_file}")
                    except Exception as e:
                        logging.warning(f"清理临时文件失败: {temp_file}, 错误: {e}")
        
    except Exception as e:
        error_msg = f"转换AAC文件失败: {str(e)}"
        logging.error(error_msg)
        raise Exception(error_msg)

def _try_universal_format_conversion(input_path: str, output_path: str) -> bool:
    """
    通用格式转换方法：检测文件实际格式并转换
    这个方法经过验证，对各种"伪装"的AAC文件都有很好的兼容性
    """
    try:
        logging.debug("尝试通用格式转换")
        
        # 首先尝试直接以WAV格式读取（有些AAC文件实际是WAV）
        try:
            audio = AudioSegment.from_wav(input_path)
            if len(audio) > 1000:  # 音频时长至少1秒
                # 文件实际是WAV格式，标准化参数
                audio = audio.set_frame_rate(16000).set_channels(1)
                audio.export(output_path, format="wav", parameters=["-ar", "16000", "-ac", "1"])
                logging.debug("✅ 文件实际为WAV格式，已标准化")
                return True
            else:
                logging.debug("WAV读取成功但时长过短")
        except:
            # 不是WAV格式，继续尝试通用读取
            pass
        
        # 尝试通用格式读取（让pydub自动检测格式）
        try:
            logging.debug("尝试通用格式自动检测")
            audio = AudioSegment.from_file(input_path)
            if len(audio) > 1000:
                # 标准化并导出为WAV
                audio = audio.set_frame_rate(16000).set_channels(1)
                audio.export(output_path, format="wav", parameters=["-ar", "16000", "-ac", "1"])
                
                # 验证输出文件
                if os.path.exists(output_path) and os.path.getsize(output_path) > 1000:
                    try:
                        test_audio = AudioSegment.from_wav(output_path)
                        if len(test_audio) > 1000:
                            logging.debug("✅ 通用格式读取并转换成功")
                            return True
                    except:
                        pass
                
                logging.debug("通用格式读取成功但验证失败")
                return False
            else:
                logging.debug("通用格式读取成功但时长过短")
                return False
        except Exception as e:
            logging.debug(f"通用格式读取失败: {e}")
        
        # 尝试指定不同格式读取（备选方案）
        formats_to_try = ['aac', 'm4a', 'mp4', 'ogg', 'flac', 'mp3']
        for fmt in formats_to_try:
            try:
                logging.debug(f"尝试以 {fmt} 格式读取")
                audio = AudioSegment.from_file(input_path, format=fmt)
                
                if len(audio) > 1000:  # 至少1秒
                    # 标准化并导出
                    audio = audio.set_frame_rate(16000).set_channels(1)
                    audio.export(output_path, format="wav", parameters=["-ar", "16000", "-ac", "1"])
                    
                    # 验证输出
                    if os.path.exists(output_path) and os.path.getsize(output_path) > 1000:
                        test_audio = AudioSegment.from_wav(output_path)
                        if len(test_audio) > 1000:
                            logging.debug(f"✅ 以 {fmt} 格式读取并转换成功")
                            return True
                
            except Exception as e:
                logging.debug(f"以 {fmt} 格式读取失败: {e}")
                continue
        
        logging.debug("❌ 所有转换方法都失败")
        return False
        
    except Exception as e:
        logging.debug(f"通用转换方法异常: {e}")
        return False

def _log_file_info(file_path: str) -> None:
    """记录文件的详细信息，修复版本：避免中文文件名的编码问题"""
    try:
        # 记录文件基本信息
        stat = os.stat(file_path)
        logging.debug(f"文件修改时间: {datetime.datetime.fromtimestamp(stat.st_mtime)}")
        
        # 尝试读取文件头
        with open(file_path, 'rb') as f:
            header = f.read(16)
            header_hex = header.hex()
            logging.debug(f"文件头 (hex): {header_hex}")
        
        # 检查文件名是否包含非ASCII字符
        try:
            file_path.encode('ascii')
            has_non_ascii = False
        except UnicodeEncodeError:
            has_non_ascii = True
            
        # 如果文件名包含中文等非ASCII字符，跳过FFprobe分析或使用临时文件
        if has_non_ascii:
            logging.debug("文件名包含非ASCII字符，跳过FFprobe分析以避免编码问题")
            return
            
        # 尝试使用ffprobe获取文件信息（仅对ASCII文件名）
        try:
            result = subprocess.run([
                'ffprobe', '-v', 'quiet', '-print_format', 'json', 
                '-show_format', '-show_streams', file_path
            ], capture_output=True, text=True, timeout=10, encoding='utf-8')
            
            if result.returncode == 0 and result.stdout:
                probe_info = json.loads(result.stdout)
                if 'format' in probe_info:
                    format_info = probe_info['format']
                    logging.debug(f"FFprobe格式信息: {format_info.get('format_name', 'unknown')}")
                    logging.debug(f"FFprobe时长: {format_info.get('duration', 'unknown')}秒")
                if 'streams' in probe_info:
                    for stream in probe_info['streams']:
                        if stream.get('codec_type') == 'audio':
                            logging.debug(f"音频编码: {stream.get('codec_name', 'unknown')}")
                            logging.debug(f"采样率: {stream.get('sample_rate', 'unknown')}")
                            logging.debug(f"声道数: {stream.get('channels', 'unknown')}")
            else:
                logging.debug("FFprobe未返回有效信息")
        except Exception as e:
            logging.debug(f"FFprobe分析失败 (这是正常的): {e}")
            
    except Exception as e:
        logging.debug(f"文件信息记录失败: {e}")

def _validate_converted_file(output_path: str, original_path: str) -> Dict[str, Any]:
    """
    详细验证转换后的文件
    """
    try:
        if not os.path.exists(output_path):
            return {"valid": False, "error": "输出文件不存在"}
        
        output_size = os.path.getsize(output_path)
        if output_size == 0:
            return {"valid": False, "error": "输出文件为空"}
        
        if output_size < 1000:
            return {"valid": False, "error": f"输出文件过小: {output_size} 字节"}
        
        # 验证音频文件的有效性
        try:
            test_audio = AudioSegment.from_wav(output_path)
            duration_ms = len(test_audio)
            duration_seconds = duration_ms / 1000.0
            
            if duration_seconds < 1.0:
                return {"valid": False, "error": f"音频时长过短: {duration_seconds:.2f}秒"}
            
            # 获取音频参数
            frame_rate = test_audio.frame_rate
            channels = test_audio.channels
            sample_width = test_audio.sample_width
            
            # 验证音频内容不是静音
            max_amplitude = test_audio.max
            if max_amplitude == 0:
                return {"valid": False, "error": "音频文件是静音"}
            
            # 记录原始文件大小用于对比
            original_size = os.path.getsize(original_path)
            
            validation_info = {
                "output_size_bytes": output_size,
                "original_size_bytes": original_size,
                "duration_seconds": round(duration_seconds, 2),
                "frame_rate": frame_rate,
                "channels": channels,
                "sample_width": sample_width,
                "max_amplitude": max_amplitude,
                "compression_ratio": round(original_size / output_size, 2) if output_size > 0 else 0
            }
            
            info_text = (f"文件大小: {output_size} 字节, "
                        f"时长: {duration_seconds:.2f}秒, "
                        f"采样率: {frame_rate}Hz, "
                        f"声道: {channels}, "
                        f"位深: {sample_width*8}bit")
            
            return {
                "valid": True, 
                "info": info_text,
                "details": validation_info
            }
            
        except Exception as audio_error:
            return {"valid": False, "error": f"音频文件无效: {audio_error}"}
        
    except Exception as e:
        return {"valid": False, "error": f"验证过程出错: {e}"}

async def _convert_to_wav_async(input_file_path: str) -> str:
    """
    异步将任意格式音频文件转换为WAV格式
    """
    return await asyncio.to_thread(_convert_to_wav_sync, input_file_path)

def _convert_to_wav_sync(input_file_path: str) -> str:
    """
    同步将任意格式音频文件转换为WAV格式
    """
    try:
        output_path = os.path.splitext(input_file_path)[0] + "_converted.wav"
        
        # 如果输出文件已存在，先删除
        if os.path.exists(output_path):
            os.remove(output_path)
        
        logging.debug(f"转换音频文件格式: {input_file_path} -> {output_path}")
        
        # 加载音频文件
        audio = AudioSegment.from_file(input_file_path)
        
        # 标准化音频参数
        audio = audio.set_frame_rate(16000)  # 16kHz采样率
        audio = audio.set_channels(1)        # 单声道
        
        # 导出为WAV格式
        audio.export(
            output_path, 
            format="wav",
            parameters=["-ar", "16000", "-ac", "1"]
        )
        
        # 验证输出文件
        if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
            raise Exception("转换后的文件无效")
        
        # 验证音频有效性
        test_audio = AudioSegment.from_wav(output_path)
        if len(test_audio) < 100:
            raise Exception("转换后的音频时长过短")
        
        logging.debug(f"音频格式转换完成: {output_path}")
        return output_path
        
    except Exception as e:
        error_msg = f"音频格式转换失败: {str(e)}"
        logging.error(error_msg)
        raise Exception(error_msg)

async def process_all_files(temp_files: List[str], progress_placeholder) -> List[Dict[str, Any]]:
    """
    异步处理所有文件：并发处理每个文件，每完成一个文件更新进度
    进度条划分：
      文件处理阶段：0 ~ 1.0
      
    Args:
        temp_files: 临时文件路径列表
        progress_placeholder: Streamlit进度显示容器
        
    Returns:
        List[Dict]: 处理结果列表
    """
    progress_bar = progress_placeholder.progress(0)
    status_text = progress_placeholder.empty()
    phase_text = progress_placeholder.empty()

    # 处理文件阶段
    phase_text.markdown("**🔄 正在转写文件...**")
    tasks = [process_file(file_path) for file_path in temp_files]
    results = []
    total = len(tasks)
    count = 0
    
    for task in asyncio.as_completed(tasks):
        result = await task
        count += 1
        progress = count / total
        progress_bar.progress(progress)
        status_text.markdown(f"⏳ 已完成 {count}/{total} 个文件转写")
        results.append(result)

    phase_text.markdown("**✅ 文件转写完成！**")
    progress_bar.progress(1.0)
    return results 

def _try_pydub_conversion_wav(input_path: str, output_path: str) -> bool:
    """
    方法1: 使用pydub默认参数转换
    """
    try:
        logging.debug("尝试方法1: pydub默认转换")
        audio = AudioSegment.from_file(input_path, format="aac")
        audio.export(output_path, format="wav")
        
        # 增强验证
        if os.path.exists(output_path) and os.path.getsize(output_path) > 1000:  # 至少1KB
            try:
                test_audio = AudioSegment.from_wav(output_path)
                if len(test_audio) > 1000:  # 至少1秒
                    logging.debug("方法1成功：pydub默认转换成功")
                    return True
                else:
                    logging.debug("方法1失败：音频时长过短")
                    return False
            except Exception as e:
                logging.debug(f"方法1失败：输出文件验证失败: {e}")
                return False
        else:
            logging.debug("方法1失败：输出文件无效或过小")
            return False
            
    except Exception as e:
        logging.debug(f"方法1失败: {e}")
        return False

def _try_pydub_with_params_wav(input_path: str, output_path: str) -> bool:
    """
    方法2: 使用pydub的特定参数转换
    """
    try:
        logging.debug("尝试方法2: pydub特定参数转换")
        audio = AudioSegment.from_file(input_path, format="aac")
        
        # 标准化音频参数
        audio = audio.set_frame_rate(16000)  # 设置采样率为16kHz
        audio = audio.set_channels(1)        # 设置为单声道
        
        # 导出为WAV格式
        audio.export(
            output_path, 
            format="wav",
            parameters=["-ar", "16000", "-ac", "1"]
        )
        
        # 增强验证
        if os.path.exists(output_path) and os.path.getsize(output_path) > 1000:
            try:
                test_audio = AudioSegment.from_wav(output_path)
                if len(test_audio) > 1000:  # 至少1秒
                    logging.debug("方法2成功：pydub特定参数转换成功")
                    return True
                else:
                    logging.debug("方法2失败：音频时长过短")
                    return False
            except Exception as e:
                logging.debug(f"方法2失败：输出文件验证失败: {e}")
                return False
        else:
            logging.debug("方法2失败：输出文件无效或过小")
            return False
            
    except Exception as e:
        logging.debug(f"方法2失败: {e}")
        return False

def _try_wav_standard_params(input_path: str, output_path: str) -> bool:
    """
    方法3: 使用标准化WAV参数进行转换
    """
    try:
        logging.debug("尝试方法3: 使用标准化WAV参数转换")
        
        # 加载文件
        audio = AudioSegment.from_file(input_path, format="aac")
        
        # 标准化参数
        audio = audio.set_frame_rate(16000)
        audio = audio.set_channels(1)
        
        # 导出为标准WAV格式
        audio.export(
            output_path,
            format="wav",
            parameters=["-ar", "16000", "-ac", "1", "-sample_fmt", "s16"]
        )
        
        # 增强验证
        if os.path.exists(output_path) and os.path.getsize(output_path) > 1000:
            try:
                test_audio = AudioSegment.from_wav(output_path)
                if len(test_audio) > 1000:  # 至少1秒
                    logging.debug("方法3成功：标准化WAV参数转换成功")
                    return True
                else:
                    logging.debug("方法3失败：音频时长过短")
                    return False
            except Exception as e:
                logging.debug(f"方法3失败：输出文件验证失败: {e}")
                return False
        else:
            logging.debug("方法3失败：输出文件无效或过小")
            return False
            
    except Exception as e:
        logging.debug(f"方法3失败: {e}")
        return False

def _try_direct_rename_wav(input_path: str, output_path: str) -> bool:
    """
    方法4: 检查文件是否实际为WAV格式，或使用通用格式读取
    """
    try:
        logging.debug("尝试方法4: 检查是否为WAV格式或通用格式读取")
        
        # 首先尝试直接以WAV格式读取原文件
        try:
            audio = AudioSegment.from_wav(input_path)
            if len(audio) > 1000:  # 音频时长至少1秒
                # 文件实际是WAV格式，直接复制但可能需要标准化
                audio = audio.set_frame_rate(16000).set_channels(1)
                audio.export(output_path, format="wav", parameters=["-ar", "16000", "-ac", "1"])
                logging.debug("方法4成功：文件为WAV格式，已标准化并复制")
                return True
            else:
                logging.debug("方法4失败：WAV文件时长过短")
                return False
        except:
            # 不是WAV格式，尝试通用格式读取
            try:
                logging.debug("尝试通用格式读取文件")
                audio = AudioSegment.from_file(input_path)
                if len(audio) > 1000:
                    # 可以读取，标准化并导出为WAV
                    audio = audio.set_frame_rate(16000).set_channels(1)
                    audio.export(output_path, format="wav", parameters=["-ar", "16000", "-ac", "1"])
                    
                    # 验证输出文件
                    if os.path.exists(output_path) and os.path.getsize(output_path) > 1000:
                        try:
                            test_audio = AudioSegment.from_wav(output_path)
                            if len(test_audio) > 1000:
                                logging.debug("方法4成功：使用通用格式读取并转换成功")
                                return True
                        except:
                            pass
                    
                    logging.debug("方法4失败：转换后文件验证失败")
                    return False
                else:
                    logging.debug("方法4失败：通用格式读取音频时长过短")
                    return False
            except Exception as e:
                logging.debug(f"方法4失败：无法以通用格式读取音频文件: {e}")
                return False
                
    except Exception as e:
        logging.debug(f"方法4失败: {e}")
        return False 