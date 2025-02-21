import streamlit as st
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
from langchain_community.chat_models import ChatOpenAI
from langchain.prompts import ChatPromptTemplate
from langchain.schema import HumanMessage, SystemMessage
# 配置日志输出
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s %(levelname)s: %(message)s')

# 讯飞API配置
lfasr_host = 'https://raasr.xfyun.cn/v2/api'
api_upload = '/upload'
api_get_result = '/getResult'
appid = "7fd8fde4"
secret_key = "ce4e08d9f1870b5a45dcedc60e99780f"


# 请求签名生成
def get_signa(appid, secret_key, ts):
    m2 = hashlib.md5()
    m2.update((appid + ts).encode('utf-8'))
    md5 = m2.hexdigest()
    md5 = bytes(md5, encoding='utf-8')
    signa = hmac.new(secret_key.encode('utf-8'), md5, hashlib.sha1).digest()
    signa = base64.b64encode(signa)
    signa = str(signa, 'utf-8')
    return signa


async def upload_file_async(session: aiohttp.ClientSession, file_path: str) -> Dict:
    """异步上传单个文件"""
    ts = str(int(time.time()))
    signa = get_signa(appid, secret_key, ts)
    file_len = os.path.getsize(file_path)
    file_name = os.path.basename(file_path)
    param_dict = {
        'appId': appid,
        'signa': signa,
        'ts': ts,
        'fileSize': file_len,
        'fileName': file_name,
        'duration': "200",
        'roleNum': 2,
        'roleType': 1
    }
    url = lfasr_host + api_upload + "?" + urllib.parse.urlencode(param_dict)
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
    """
    ts = str(int(time.time()))
    signa = get_signa(appid, secret_key, ts)
    param_dict = {
        'appId': appid,
        'signa': signa,
        'ts': ts,
        'orderId': orderId,
        'resultType': "transfer,predict"
    }
    url = lfasr_host + api_get_result + "?" + urllib.parse.urlencode(param_dict)
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


def merge_result_for_one_vad(result_vad):
    """规范化JSON文件为可读文本"""
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


def identify_roles(raw_text: str) -> dict:
    """
    使用LLM识别对话中的角色
    """
    lines = raw_text.strip().split('\n')
    sample_dialogue = '\n'.join(lines[:10])
    llm = ChatOpenAI(
        openai_api_key="sk-gXeRXhgYsLFziprS93D5F6D31eE249D59235739b37Bd20B1",
        openai_api_base="https://openai.weavex.tech/v1",
        model_name="gpt-4o",
        temperature=0.2
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


def format_conversation(raw_text: str) -> tuple:
    """
    将原始的spk标记文本转换为更规范的对话格式
    """
    roles = identify_roles(raw_text)
    lines = raw_text.strip().split('\n')
    formatted_lines = []
    current_speaker = None
    current_content = []
    for line in lines:
        if not line.strip() or '##' not in line:
            continue
        speaker, content = line.split('##')
        content = content.strip()
        if not content or content.strip().replace('、', '').isdigit():
            continue
        speaker_role = roles.get(speaker, f"未知角色{speaker[-1]}")
        if speaker == current_speaker:
            current_content.append(content)
        else:
            if current_speaker and current_content:
                formatted_lines.append(
                    f"{roles.get(current_speaker, f'未知角色{current_speaker[-1]}')}：{''.join(current_content)}")
            current_speaker = speaker
            current_content = [content]
    if current_speaker and current_content:
        formatted_lines.append(
            f"{roles.get(current_speaker, f'未知角色{current_speaker[-1]}')}：{''.join(current_content)}")
    formatted_text = '\n\n'.join(formatted_lines)
    return formatted_text, roles


def analyze_conversation(conversation_text: str):
    """
    分析通话记录并提供改进建议
    """
    formatted_text, roles = format_conversation(conversation_text)
    confidence_warning = ""
    if roles.get("confidence", "low") == "low":
        confidence_warning = "\n\n 注意：系统对说话者角色的识别可信度较低，请人工核实。"
    system_prompt = f"""
    你是一位专业的销售通话分析专家。这是一段对话记录，其中：
    - {roles['spk1']} 的发言以"{roles['spk1']}："开头
    - {roles['spk2']} 的发言以"{roles['spk2']}："开头

    请从以下几个维度进行深入分析：
    1. 整体评分（满分100分）：
       - 开场白表现（20分）
       - 需求挖掘（20分）
       - 产品介绍（20分）
       - 异议处理（20分）
       - 成交技巧（20分）

    2. 详细分析：
       a) 对话节奏与互动
          - 销售节奏控制
          - 倾听与回应质量
          - 话语权把控

       b) 销售技巧应用
          - SPIN技巧运用
          - 价值展示能力
          - 促成交技巧

       c) 客户意向识别
          - 客户兴趣点
          - 购买意愿强度
          - 决策影响因素

    3. 具体改进建议：
       - 至少3个可立即执行的改进点
       - 建议的话术示例
       - 后续跟进建议

    请用简洁专业的语言进行分析，并突出关键发现。
    """
    llm = ChatOpenAI(
        openai_api_key="sk-gXeRXhgYsLFziprS93D5F6D31eE249D59235739b37Bd20B1",
        openai_api_base="https://openai.weavex.tech/v1",
        model_name="deepseek-r1",
        temperature=0.7
    )
    prompt = ChatPromptTemplate.from_messages([
        SystemMessage(content=system_prompt),
        HumanMessage(content=f"以下是需要分析的通话记录：\n\n{formatted_text}")
    ])
    try:
        response = llm(prompt.format_messages())
        return {
            "status": "success",
            "analysis": response.content,
            "formatted_text": formatted_text,
            "roles": roles
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"分析过程中出现错误: {str(e)}"
        }


async def process_file(upload_result: Dict) -> Dict:
    """
    异步处理单个文件：调用转写API、解析结果、保存转写文本并调用LLM进行分析
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
            logging.debug(f"开始调用LLM分析，文件 {file_path}")
            analysis_result = await asyncio.to_thread(analyze_conversation, conversation_text)
            logging.debug(f"LLM分析完成，文件 {file_path}")
            return {
                "file_path": file_path,
                "status": "success",
                "analysis_result": analysis_result,
                "output_file_path": output_file_path
            }
        else:
            return {"file_path": file_path, "status": "error", "message": "转写结果格式错误"}
    else:
        return {"file_path": file_path, "status": "error", "message": "上传失败或返回格式错误"}


async def process_all_files(temp_files: List[str], progress_placeholder) -> List[Dict]:
    """
    异步处理所有文件：先并发上传，再并发处理转写和分析，每完成一个文件更新进度
    """
    progress_bar = progress_placeholder.progress(0)
    status_text = progress_placeholder.empty()
    phase_text = progress_placeholder.empty()
    
    # 上传文件阶段
    phase_text.markdown("**📤 正在上传文件...**")
    logging.debug("开始并发上传文件")
    upload_results = await upload_files_async(temp_files)
    logging.debug("完成文件上传")
    
    # 处理文件阶段
    phase_text.markdown("**🔄 正在转写并分析文件...**")
    tasks = [process_file(upload_result) for upload_result in upload_results]
    results = []
    total = len(tasks)
    count = 0
    
    for task in asyncio.as_completed(tasks):
        result = await task
        count += 1
        progress_bar.progress(count / total)
        status_text.markdown(f"⏳ 已完成 {count}/{total} 个文件")
        results.append(result)
    
    phase_text.markdown("**✅ 所有文件处理完成！**")
    return results


def analyze_summary(all_analysis_results: List[Dict]) -> str:
    """
    对所有对话的分析结果进行汇总分析
    """
    system_prompt = """
    你是一位专业的销售培训专家。请对多个销售对话的分析结果进行汇总分析。
    
    请从以下几个方面进行总结：
    
    1. 整体表现评估
       - 团队整体得分情况
       - 共同的优势领域
       - 普遍存在的问题
    
    2. 典型案例分析
       - 最佳实践案例及其可借鉴之处
       - 典型问题案例及改进建议
    
    3. 系统性改进建议
       - 团队层面的培训重点
       - 具体的改进行动计划
       - 话术和技巧的标准化建议
    
    4. 数据分析
       - 各维度得分的统计分析
       - 成功率和关键影响因素
       - 绩效改进的量化目标
    
    请用清晰的结构和专业的语言进行分析，突出关键发现和可执行的建议。
    """
    
    llm = ChatOpenAI(
        openai_api_key="sk-gXeRXhgYsLFziprS93D5F6D31eE249D59235739b37Bd20B1",
        openai_api_base="https://openai.weavex.tech/v1",
        model_name="gpt-4o",
        temperature=0.7
    )
    
    # 准备所有分析结果的文本
    all_analyses = []
    for idx, result in enumerate(all_analysis_results, 1):
        if result["status"] == "success" and result["analysis_result"].get("status") == "success":
            all_analyses.append(f"对话 {idx} 的分析结果：\n{result['analysis_result']['analysis']}")
    
    combined_analyses = "\n\n".join(all_analyses)
    
    prompt = ChatPromptTemplate.from_messages([
        SystemMessage(content=system_prompt),
        HumanMessage(content=f"以下是{len(all_analyses)}个销售对话的分析结果，请进行汇总分析：\n\n{combined_analyses}")
    ])
    
    try:
        response = llm(prompt.format_messages())
        return response.content
    except Exception as e:
        return f"汇总分析过程中出现错误: {str(e)}"


# Streamlit界面
st.set_page_config(page_title="分析通话记录Demo", page_icon="📞")
st.title("分析通话记录（Demo）📞")

uploaded_files = st.file_uploader(
    "请上传通话录音文件",
    type=['wav', 'mp3', 'm4a', 'ogg'],
    accept_multiple_files=True
)

if uploaded_files:
    st.write("已上传的文件:")
    for file in uploaded_files:
        st.write(f"- {file.name}")

    if st.button("开始分析"):
        progress_placeholder = st.container()

        # 保存上传的文件到本地临时文件夹
        temp_files = []
        for uploaded_file in uploaded_files:
            temp_path = f"./temp_{uploaded_file.name}"
            with open(temp_path, "wb") as f:
                f.write(uploaded_file.getbuffer())
            temp_files.append(temp_path)

        try:
            results = asyncio.run(process_all_files(temp_files, progress_placeholder))
            
            # 创建三个主要标签页
            tab1, tab2, tab3 = st.tabs(["📝 所有对话记录", "📊 所有分析结果", "📈 汇总分析"])
            
            with tab1:
                for idx, res in enumerate(results, 1):
                    if res["status"] == "success":
                        analysis_result = res["analysis_result"]
                        if analysis_result.get("status") == "success":
                            st.markdown(f"### 📝 对话记录 {idx}")
                            if analysis_result["roles"].get("confidence", "low") != "high":
                                st.warning("⚠️ 该对话的角色识别可信度不高，请核实。")
                            st.markdown(f"**角色说明：**")
                            st.markdown(f"- 说话者1 ({analysis_result['roles']['spk1']})")
                            st.markdown(f"- 说话者2 ({analysis_result['roles']['spk2']})")
                            st.markdown("**详细对话：**")
                            st.markdown(analysis_result["formatted_text"])
                            st.markdown("---")
            
            with tab2:
                for idx, res in enumerate(results, 1):
                    if res["status"] == "success":
                        analysis_result = res["analysis_result"]
                        if analysis_result.get("status") == "success":
                            st.markdown(f"### 📊 分析结果 {idx}")
                            st.markdown(analysis_result["analysis"])
                            st.markdown("---")
            
            # 添加新的汇总分析标签页
            with tab3:
                st.markdown("### 📈 汇总分析报告")
                
                # 显示处理中的提示
                with st.spinner('正在生成汇总分析报告...'):
                    summary_analysis = analyze_summary([res for res in results if res["status"] == "success"])
                
                # 显示汇总分析结果
                st.markdown(summary_analysis)
            
            # 修改下载按钮，加入汇总分析
            combined_report = ""
            for idx, res in enumerate(results, 1):
                if res["status"] == "success" and res["analysis_result"].get("status") == "success":
                    combined_report += f"\n\n{'='*50}\n对话记录 {idx}：\n{'='*50}\n\n"
                    combined_report += res["analysis_result"]["formatted_text"]
                    combined_report += f"\n\n{'='*50}\n分析结果 {idx}：\n{'='*50}\n\n"
                    combined_report += res["analysis_result"]["analysis"]
            
            combined_report += f"\n\n{'='*50}\n汇总分析报告：\n{'='*50}\n\n"
            combined_report += summary_analysis
            
            st.download_button(
                label="📥 下载完整分析报告",
                data=combined_report,
                file_name="complete_analysis_report.txt",
                mime="text/plain"
            )

        except Exception as e:
            st.error(f"处理过程中出现错误：{str(e)}")
        finally:
            # 清理临时文件
            for temp_file in temp_files:
                if os.path.exists(temp_file):
                    os.remove(temp_file)