import os
import json
import time
import uuid
import datetime
import copy
import asyncio
import aiohttp
import logging
from typing import List, Dict, Any, Optional
import tos
from LLM_Workflow import llm_workflow
from config import VOLCANO_CONFIG  # 从config导入火山引擎配置

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
    
    # 生成唯一的对象键名（使用文件原始名称+时间戳）
    file_name = os.path.basename(local_file_path)
    file_ext = os.path.splitext(file_name)[1]
    current_time = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    object_key = f"{os.path.splitext(file_name)[0]}-{current_time}{file_ext}"
    
    try:
        # 上传对象
        logging.debug(f"上传对象: {object_key}...")
        with open(local_file_path, 'rb') as f:
            resp = client.put_object(bucket_name, object_key, content=f)
        logging.debug(f"上传对象响应状态码: {resp.status_code}")
        
        # 使用正确的方法生成公共URL
        # 方法1：设置对象的ACL为public-read
        try:
            client.put_object_acl(bucket_name, object_key, acl="public-read")
            file_url = f"https://{bucket_name}.{endpoint}/{object_key}"
            logging.debug(f"公共URL: {file_url}")
            return file_url
        except Exception as acl_error:
            logging.error(f"设置对象ACL失败: {acl_error}")
            
            # 方法2：尝试使用签名URL
            try:
                # 使用签名URL工具类签名URL
                current_time = int(time.time())
                expiration = current_time + 24 * 60 * 60  # 24小时后过期
                
                # 这里针对不同版本的TOS SDK提供几种可能的调用方式
                try:
                    # 尝试使用签名URL
                    from tos.enum import HttpMethodEnum
                    signed_url = client.pre_signed_url(HttpMethodEnum.GET, bucket_name, object_key, expires=expiration)
                except ImportError:
                    try:
                        # 尝试使用其他可能的方法
                        signed_url = client.get_presigned_url(bucket_name, object_key, expires=expiration)
                    except:
                        # 最后的备选方案
                        signed_url = client.generate_presigned_url(bucket_name, object_key, expiration)
                
                logging.debug(f"签名URL: {signed_url}")
                return signed_url
            except Exception as sign_error:
                logging.error(f"生成签名URL失败: {sign_error}")
                
                # 方法3：如果以上方法都失败，使用临时公开URL
                temp_url = f"https://{bucket_name}.{endpoint}/{object_key}"
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
            "format": "mp3",  # 根据实际音频格式调整
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
        
        # 写入音频信息
        if 'audio_info' in result_json:
            f.write("\n【音频信息】\n")
            duration = result_json['audio_info'].get('duration', 0) / 1000  # 毫秒转秒
            f.write(f"总时长: {duration:.2f}秒\n")
        
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
        # 1. 上传文件到TOS
        file_url = await upload_to_tos_async(file_path)
        logging.debug(f"文件已上传到TOS: {file_url}")
        
        # 2. 提交转写任务
        async with aiohttp.ClientSession() as session:
            submit_result = await submit_task_async(session, file_url)
            task_id = submit_result["task_id"]
            x_tt_logid = submit_result["x_tt_logid"]
            
            # 3. 轮询查询任务结果
            while True:
                query_result = await query_task_async(session, task_id, x_tt_logid)
                status_code = query_result["status_code"]
                
                if status_code == "20000000":  # 任务完成
                    logging.debug("转写结果获取成功!")
                    result_json = query_result["data"]
                    break
                elif status_code != "20000001" and status_code != "20000002":  # 任务失败
                    error_msg = f"转写失败: {query_result['message']}"
                    logging.error(error_msg)
                    return {
                        "file_path": file_path,
                        "status": "error",
                        "message": error_msg
                    }
                else:  # 任务处理中
                    logging.debug(f"任务处理中，状态码: {status_code}，等待5秒后重试...")
                    await asyncio.sleep(5)
        
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
        
        # 8. 调用LLM工作流进行分析
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
    
    except Exception as e:
        logging.error(f"处理文件 {file_path} 时发生错误: {e}")
        return {
            "file_path": file_path,
            "status": "error", 
            "message": str(e)
        }

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