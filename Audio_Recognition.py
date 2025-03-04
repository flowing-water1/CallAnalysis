import os
import json
import time
import base64
import hashlib
import hmac
import urllib
import asyncio
import aiohttp
import logging
from typing import List, Dict
from config import XFYUN_CONFIG
from LLM_Workflow import llm_workflow

def get_signa(appid: str, secret_key: str, ts: str) -> str:
    """
    生成讯飞API请求签名
    
    Args:
        appid: 应用ID
        secret_key: 密钥
        ts: 时间戳
        
    Returns:
        str: 生成的签名
    """
    m2 = hashlib.md5()
    m2.update((appid + ts).encode('utf-8'))
    md5 = m2.hexdigest()
    md5 = bytes(md5, encoding='utf-8')
    signa = hmac.new(secret_key.encode('utf-8'), md5, hashlib.sha1).digest()
    signa = base64.b64encode(signa)
    return str(signa, 'utf-8')

async def upload_file_async(session: aiohttp.ClientSession, file_path: str) -> Dict:
    """异步上传单个文件到讯飞语音识别服务"""
    if not os.path.exists(file_path):
        return {
            "file_path": file_path,
            "status": "error",
            "message": f"文件不存在: {file_path}"
        }

    ts = str(int(time.time()))
    signa = get_signa(XFYUN_CONFIG["appid"], XFYUN_CONFIG["secret_key"], ts)
    file_len = os.path.getsize(file_path)
    file_name = os.path.basename(file_path)
    param_dict = {
        'appId': XFYUN_CONFIG["appid"],
        'signa': signa,
        'ts': ts,
        'fileSize': file_len,
        'fileName': file_name,
        'duration': "200",
        'roleNum': 2,
        'roleType': 1
    }
    url = XFYUN_CONFIG["lfasr_host"] + XFYUN_CONFIG["api_upload"] + "?" + urllib.parse.urlencode(param_dict)
    with open(file_path, 'rb') as f:
        data = f.read()
    async with session.post(url, headers={"Content-type": "application/json"}, data=data) as response:
        result = await response.json()
        logging.debug(f"上传文件 {file_name} 返回结果：{result}")
        return {"file_path": file_path, "result": result}

async def upload_files_async(file_paths: List[str]) -> List[Dict]:
    """并发上传多个文件"""
    async with aiohttp.ClientSession() as session:
        tasks = [upload_file_async(session, file_path) for file_path in file_paths]
        return await asyncio.gather(*tasks)

async def get_transcription_result_async(orderId: str) -> Dict:
    """
    异步获取转写结果
    
    Args:
        orderId: 讯飞API返回的订单ID
        
    Returns:
        Dict: 转写结果
    """
    ts = str(int(time.time()))
    signa = get_signa(XFYUN_CONFIG["appid"], XFYUN_CONFIG["secret_key"], ts)
    param_dict = {
        'appId': XFYUN_CONFIG["appid"],
        'signa': signa,
        'ts': ts,
        'orderId': orderId,
        'resultType': "transfer,predict"
    }
    url = XFYUN_CONFIG["lfasr_host"] + XFYUN_CONFIG["api_get_result"] + "?" + urllib.parse.urlencode(param_dict)
    status = 3
    async with aiohttp.ClientSession() as session:
        while status == 3:
            async with session.post(url, headers={"Content-type": "application/json"}) as response:
                result = await response.json()
            status = result['content']['orderInfo']['status']
            logging.debug(f"转写API调用返回状态: {status} (orderId: {orderId})")
            if status == 4:
                break
            await asyncio.sleep(5)
    return result

def merge_result_for_one_vad(result_vad: Dict) -> List[str]:
    """
    规范化JSON文件为可读文本
    
    Args:
        result_vad: 单个VAD结果
        
    Returns:
        List[str]: 处理后的文本列表
    """
    content = []
    for rt_dic in result_vad['st']['rt']:
        spk_str = 'spk' + str(3 - int(result_vad['st']['rl'])) + '##'
        for st_dic in rt_dic['ws']:
            for cw_dic in st_dic['cw']:
                for w in cw_dic['w']:
                    spk_str += w
        spk_str += '\n'
        content.append(spk_str)
    return content

async def process_file(upload_result: Dict) -> Dict:
    """
    异步处理单个文件：调用转写API、解析结果、保存转写文本并启动LLM工作流
    
    Args:
        upload_result: 上传结果
        
    Returns:
        Dict: 处理结果，包含转写文本和分析结果
    """
    file_path = upload_result["file_path"]
    logging.debug(f"开始处理文件 {file_path}")
    result = upload_result["result"]
    if 'content' in result and 'orderId' in result['content']:
        orderId = result['content']['orderId']
        logging.debug(f"调用转写 API 前，文件 {file_path}，orderId: {orderId}")
        transcription_result = await get_transcription_result_async(orderId)
        logging.debug(f"转写 API 返回，文件 {file_path}")
        if 'content' in transcription_result:
            try:
                js_xunfei_result = json.loads(transcription_result['content']['orderResult'])
            except Exception as e:
                return {"file_path": file_path, "status": "error", "message": f"解析转写结果失败: {e}"}
            content = []
            for result_one_vad_str in js_xunfei_result['lattice']:
                try:
                    js_result_one_vad = json.loads(result_one_vad_str['json_1best'])
                    content.extend(merge_result_for_one_vad(js_result_one_vad))
                except Exception as e:
                    logging.error(f"解析单个vad结果错误: {e}")
            file_name = os.path.basename(file_path)
            output_file_path = f"{file_name}_output.txt"
            with open(output_file_path, 'w', encoding='utf-8') as f:
                for line in content:
                    f.write(line)
            
            with open(output_file_path, 'r', encoding='utf-8') as f:
                conversation_text = f.read()
            
            # 调用LLM工作流进行分析
            logging.debug(f"开始调用LLM工作流分析，文件 {file_path}")
            analysis_result = await llm_workflow(conversation_text)
            logging.debug(f"LLM工作流分析完成，文件 {file_path}")
            
            return {
                "file_path": file_path,
                "status": "success",
                "analysis_result": analysis_result,
                "conversation_text": conversation_text,
                "output_file_path": output_file_path
            }
        else:
            return {"file_path": file_path, "status": "error", "message": "转写结果格式错误"}
    else:
        return {"file_path": file_path, "status": "error", "message": "上传失败或返回格式错误"}

async def process_all_files(temp_files: List[str], progress_placeholder) -> List[Dict]:
    """
    异步处理所有文件：先并发上传，再并发处理转写和分析，每完成一个文件更新进度
    进度条划分：
      上传阶段：0 ~ 0.2
      文件处理阶段：0.2 ~ 0.8
      
    Args:
        temp_files: 临时文件路径列表
        progress_placeholder: Streamlit进度显示容器
        
    Returns:
        List[Dict]: 处理结果列表
    """
    progress_bar = progress_placeholder.progress(0)
    status_text = progress_placeholder.empty()
    phase_text = progress_placeholder.empty()

    # 上传文件阶段
    phase_text.markdown("**📤 正在上传文件...**")
    logging.debug("开始并发上传文件")
    upload_results = await upload_files_async(temp_files)
    logging.debug("完成文件上传")
    phase_text.markdown("**📤 上传完成！**")
    progress_bar.progress(0.2)

    # 处理文件阶段
    phase_text.markdown("**🔄 正在转写文件...**")
    tasks = [process_file(upload_result) for upload_result in upload_results]
    results = []
    total = len(tasks)
    count = 0
    for task in asyncio.as_completed(tasks):
        result = await task
        count += 1
        progress = 0.2 + 0.6 * (count / total)
        progress_bar.progress(progress)
        status_text.markdown(f"⏳ 已完成 {count}/{total} 个文件转写")
        results.append(result)

    phase_text.markdown("**✅ 文件转写完成！**")
    progress_bar.progress(0.8)
    return results 