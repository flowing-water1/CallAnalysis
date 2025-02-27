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
import pandas as pd
from io import BytesIO
import re
import openpyxl

# 配置日志输出
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s %(levelname)s: %(message)s')

# 讯飞API配置
lfasr_host = 'https://raasr.xfyun.cn/v2/api'
api_upload = '/upload'
api_get_result = '/getResult'
appid = "8d2e895b"
secret_key = "8d5c02bd69345f504761da6b818b423f"

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
        openai_api_key="sk-OdCoqKCvctCJaPHUF2Ea9eF9C01940D8Aa7cB82889EaE165",
        openai_api_base="https://api.pumpkinaigc.online/v1",
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

def format_conversation_with_roles(raw_text: str, roles: dict) -> str:
    """
    根据已有的角色信息，将原始的spk标记文本转换为更规范的对话格式
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

def analyze_conversation_with_roles(conversation_text: str, roles: dict) -> dict:
    """
    使用LLM对通话记录进行分析，并给出改进建议，此处不再调用identify_roles，而是使用传入的roles
    """
    formatted_text = format_conversation_with_roles(conversation_text, roles)
    confidence_warning = ""
    if roles.get("confidence", "low") == "low":
        confidence_warning = "\n\n 注意：系统对说话者角色的识别可信度较低，请人工核实。"
    system_prompt = f"""
    你是一位专业的销售通话分析专家，负责对销售对话进行分析评估。
    以下是对话记录，其中 {roles['spk1']} 的发言以 "{roles['spk1']}：" 开头，{roles['spk2']} 的发言以 "{roles['spk2']}：" 开头。

    <角色标识>
    {roles['spk1']}: {{ROLES_SPK1}}
    {roles['spk2']}: {{ROLES_SPK2}}
    </角色标识>

    请按照以下评分标准对销售对话进行评估：
    1. 30 秒自我介绍清晰度（30 分）
        - 是否包含公司/个人核心价值
        - 是否控制在 30 秒中
        - 是否建立专业可信形象
    2. 客户需求洞察（20 分）
        - 是否明确客户行业类型
        - 是否确认现有需求
        - 是否量化客户业务规模
    3. SPIN 痛点挖掘（15 分）
        - Situation：是否确认现状
        - Problem：是否发现问题
        - Implication：是否阐明问题影响
        - Need - Payoff：是否引导解决方案需求
    4. 价值展示能力（15 分）
        - 是否针对性匹配客户需求
        - 是否使用数据/案例支撑
        - 是否说明ROI或成本效益
    5. 决策流程掌握（10 分）
        - 是否确认采购决策阶段
        - 是否识别关键决策人
        - 是否了解预算周期
    6. 后续跟进铺垫（10 分）
        - 是否约定具体跟进时间
        - 是否设置价值锚点
        - 是否取得客户承诺

    请按以下流程执行分析：
    1. 针对每个评分标准，先在[分析内容]中：
        - 引用对话中的具体语句
        - 分析是否符合标准要求
        - 指出存在/缺失的要素
    2. 在【评分】中给出该标准得分（0 - 满分）

    完成所有标准评估后：
    1. 计算总分（满分 100 分）
    2. 在【总结】标签中：
        - 指出 1 个最关键改进点
        - 改进点包含：
            * 问题描述（20 字内）
            * 具体建议（30 字内）
            * 示范话术（可选）

    以MarkDown格式输出以下内容：

    ### 分析
    #### 标准 1 - 自我介绍
    - [分析内容]
    **评分：/30**
    #### 标准 2 - 客户需求洞察
    - [分析内容]
    **评分：/20**
    #### 标准 3 - SPIN 痛点挖掘
    - [分析内容]
    **评分：/15**
    #### 标准 4 - 价值展示能力
    - [分析内容]
    **评分：/15**
    #### 标准 5 - 决策流程掌握
    - [分析内容]
    **评分：/10**
    #### 标准 6 - 后续跟进铺垫
    - [分析内容]
    **评分：/10**
    #### 总分
    **/100**

    总结
    1. 改进点：[问题]
       建议：[方案] 
       示例：[引用对话记录的话术进行修改]

    现在开始逐项分析。
    """
    llm = ChatOpenAI(
        openai_api_key="sk-OdCoqKCvctCJaPHUF2Ea9eF9C01940D8Aa7cB82889EaE165",
        openai_api_base="https://api.pumpkinaigc.online/v1",
        model_name="gpt-4o",
        temperature=0.7
    )
    prompt = ChatPromptTemplate.from_messages([
        SystemMessage(content=system_prompt),
        HumanMessage(content=f"以下是需要分析的通话记录：\n\n{formatted_text}")
    ])
    try:
        response = llm(prompt.format_messages())
        analysis_text = response.content
        filtered_text = re.sub(r"(>?\s*Reasoning[\s\S]*?Reasoned for \d+\s*seconds\s*)", "", analysis_text, flags=re.IGNORECASE)
        return {
            "status": "success",
            "analysis": filtered_text,
            "formatted_text": formatted_text,
            "roles": roles
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"分析过程中出现错误: {str(e)}"
        }

async def llm_workflow(conversation_text: str) -> dict:
    """
    针对每个转写文件，先调用identify_roles，再调用analyze_conversation_with_roles，
    形成一个完整的LLM工作流
    """
    roles = await asyncio.to_thread(identify_roles, conversation_text)
    analysis_result = await asyncio.to_thread(analyze_conversation_with_roles, conversation_text, roles)
    return analysis_result

async def process_file(upload_result: Dict) -> Dict:
    """
    异步处理单个文件：调用转写API、解析结果、保存转写文本并启动LLM工作流（角色识别和通话记录分析）
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
            logging.debug(f"开始调用LLM工作流分析，文件 {file_path}")
            analysis_result = await llm_workflow(conversation_text)
            logging.debug(f"LLM工作流分析完成，文件 {file_path}")
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
    进度条划分：
      上传阶段：0 ~ 0.2
      文件处理阶段：0.2 ~ 0.8
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
    phase_text.markdown("**🔄 正在转写并分析文件...**")
    tasks = [process_file(upload_result) for upload_result in upload_results]
    results = []
    total = len(tasks)
    count = 0
    for task in asyncio.as_completed(tasks):
        result = await task
        count += 1
        progress = 0.2 + 0.6 * (count / total)
        progress_bar.progress(progress)
        status_text.markdown(f"⏳ 已完成 {count}/{total} 个文件")
        results.append(result)

    phase_text.markdown("**✅ 文件处理完成！**")
    progress_bar.progress(0.8)
    return results

def analyze_summary(all_analysis_results: List[Dict]) -> str:
    """
    对所有对话的分析结果进行汇总分析
    """
    system_prompt = f"""
    你是一位专业的销售培训专家，需要根据当日销售对话分析报告进行汇总分析，生成一份结构化的销售分析报告。

    请按照以下步骤处理数据：
    1. 数据解析阶段：
        - 仔细提取所有通话记录的评分数据，确保每个评分都有对话文本支撑。
        - 认真识别每份报告中的关键改进点，避免主观臆断，仅基于对话事实。
    2. 计算分析阶段：
        - 计算平均评分，结果保留两位小数。
        - 统计重复出现的改进建议频次。
    3. 建议筛选阶段：
        - 选择出现频率最高的前3个改进领域。
        - 确保每条建议满足以下条件：
          a) 基于至少3个通话记录的共同问题。
          b) 聚焦可量化的行为改进。
          c) 包含具体的提升方向。

    输出要求：
    请在[销售分析报告]标签下输出以下内容，以Markdown形式呈现：
    ### [销售分析报告]
    1. **平均评分**：数值结果
    2. **改进建议**：
        - 每条建议单独列出，问题描述简明（不超过25字），改进措施具体可执行，整体控制在50字左右。

    特别注意：
    - 优先处理影响客户转化率的要素。
    - 建议需包含可衡量的行为指标，避免使用模糊性表述。
    - 保持建议间的正交性，不重复覆盖相同维度。
    - 改进建议要可让销售可执行。

    ### [销售分析报告]
    1. **平均评分**：[在此填写平均评分]
    2. **改进建议**：
        - [建议1，按照要求格式编写]
        - [建议2，按照要求格式编写]
        - [建议3，按照要求格式编写]
    """
    llm = ChatOpenAI(
        openai_api_key="f465c1fc-481e-4668-bfa2-ec9187c2f1e4",
        openai_api_base="https://ark.cn-beijing.volces.com/api/v3",
        model_name="deepseek-r1-250120",
        temperature=0.7
    )

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

# 初始化session state
if 'analysis_results' not in st.session_state:
    st.session_state.analysis_results = None
if 'combined_report' not in st.session_state:
    st.session_state.combined_report = None
if 'summary_analysis' not in st.session_state:
    st.session_state.summary_analysis = None
if 'analysis_completed' not in st.session_state:
    st.session_state.analysis_completed = False  # 用来标记分析是否完成
if 'contact_person' not in st.session_state:
    st.session_state.contact_person = ""  # 用于存储联系人信息

# 添加联系人输入框
contact_person = st.text_input("请输入本次对接客户的联系人", value=st.session_state.contact_person)
if contact_person != st.session_state.contact_person:
    st.session_state.contact_person = contact_person

uploaded_files = st.file_uploader(
    "请上传通话录音文件",
    type=['wav', 'mp3', 'm4a', 'ogg'],
    accept_multiple_files=True
)

if uploaded_files and not st.session_state.analysis_completed:
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
            st.session_state.analysis_results = results

            # 生成汇总分析并保存，同时更新进度条（汇总分析占 20%）
            phase_text = progress_placeholder.empty()
            phase_text.markdown("**🔄 正在生成汇总分析...**")
            progress_bar = progress_placeholder.progress(0.9)
            st.session_state.summary_analysis = analyze_summary([res for res in results if res["status"] == "success"])
            progress_bar.progress(1.0)
            phase_text.markdown("**✅ 所有文件处理完成！**")

            # 生成完整报告并保存
            combined_report = ""
            for idx, res in enumerate(results, 1):
                if res["status"] == "success" and res["analysis_result"].get("status") == "success":
                    combined_report += f"\n\n{'=' * 50}\n对话记录 {idx}：\n{'=' * 50}\n\n"
                    combined_report += res["analysis_result"]["formatted_text"]
                    combined_report += f"\n\n{'=' * 50}\n分析结果 {idx}：\n{'=' * 50}\n\n"
                    combined_report += res["analysis_result"]["analysis"]

            combined_report += f"\n\n{'=' * 50}\n汇总分析报告：\n{'=' * 50}\n\n"
            combined_report += st.session_state.summary_analysis
            st.session_state.combined_report = combined_report

            st.session_state.analysis_completed = True  # 标记分析完成

        except Exception as e:
            st.error(f"处理过程中出现错误：{str(e)}")
        finally:
            # 清理临时文件
            for temp_file in temp_files:
                if os.path.exists(temp_file):
                    os.remove(temp_file)

if st.session_state.analysis_results:
    tab1, tab2, tab3 = st.tabs(["📝 所有对话记录", "📊 所有分析结果", "📈 汇总分析"])

    with tab1:
        for idx, res in enumerate(st.session_state.analysis_results, 1):
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
        for idx, res in enumerate(st.session_state.analysis_results, 1):
            if res["status"] == "success":
                analysis_result = res["analysis_result"]
                if analysis_result.get("status") == "success":
                    file_name = os.path.basename(res["file_path"])
                    file_name = re.sub(r'^temp_', '', file_name)
                    file_name = os.path.splitext(file_name)[0]
                    with st.expander(f"📊 {file_name} 通话分析"):
                        st.markdown(analysis_result["analysis"])
                        st.markdown("---")

    with tab3:
        st.markdown("### 📈 汇总分析报告")
        st.markdown(st.session_state.summary_analysis)

    col1, col2 = st.columns(2)
    with col1:
        st.download_button(
            label="📥 下载完整分析报告",
            data=st.session_state.combined_report,
            file_name="complete_analysis_report.md",
            mime="text/plain"
        )

    with col2:
        def generate_excel_report():
            try:
                workbook = openpyxl.load_workbook("电话开拓分析表.xlsx")
                worksheet = workbook.active
                file_names = []
                analysis_data = []
                for res in st.session_state.analysis_results:
                    if res["status"] == "success" and res["analysis_result"].get("status") == "success":
                        file_name = os.path.basename(res["file_path"])
                        file_name = re.sub(r'^temp_', '', file_name)
                        file_name = os.path.splitext(file_name)[0]
                        file_names.append(file_name)
                        analysis_text = res["analysis_result"]["analysis"]
                        score = ""
                        score_patterns = [
                            r'总分\s*\n\s*####\s*(\d+)/100',
                            r'总分\s*\n\s*总分：\s*(\d+)/100',
                            r'总分\s*\n\s*(\d+)/100',
                            r'总分：\s*(\d+)/100',
                            r'总分\s*(\d+)/100',
                            r'总分：?\s*(\d+)',
                            r'####\s*总分\s*\n\s*\*\*(\d+)/100\*\*',
                            r'总分\s*\n\s*\*\*(\d+)/100\*\*',
                            r'\*\*(\d+)/100\*\*',
                            r'总分\s*\n\s*(\d+)'
                        ]
                        for pattern in score_patterns:
                            score_match = re.search(pattern, analysis_text)
                            if score_match:
                                score = score_match.group(1)
                                break
                        if not score:
                            general_score_match = re.search(r'(\d+)/100', analysis_text)
                            if general_score_match:
                                score = general_score_match.group(1)
                        suggestion = ""
                        suggestion_patterns = [
                            r'建议：\s*(.+?)(?:\n|$)',
                            r'建议：\s*\*\*(.+?)\*\*',
                            r'建议：\s*(.+?)\*\*',
                            r'建议：\s*(.+)',
                            r'改进点：.+?\n\s*建议：\s*(.+?)(?:\n|$)',
                            r'\*\*建议\*\*：\s*(.+?)(?:\n|$)',
                            r'\*\*建议\*\*：\s*(.+)',
                            r'总结\s*\n\s*\d+\.\s*改进点.+?\n\s*建议：\s*(.+?)(?:\n|$)',
                            r'总结\s*\n\s*\d+\.\s*改进点.+?\n\s*\*\*建议\*\*：\s*(.+?)(?:\n|$)',
                            r'总结\s*\n\s*\d+\.\s*改进点：.+?\n\s*- \*\*建议\*\*：\s*(.+?)(?:\n|$)',
                            r'总结\s*\n\s*\d+\.\s*改进点：.+?\n\s*- 建议：\s*(.+?)(?:\n|$)',
                            r'建议\s*(.+?)(?:\n|$)'
                        ]
                        for pattern in suggestion_patterns:
                            suggestion_match = re.search(pattern, analysis_text)
                            if suggestion_match:
                                suggestion = suggestion_match.group(1).strip()
                                suggestion = re.sub(r'\*\*(.+?)\*\*', r'\1', suggestion)
                                suggestion = re.sub(r'\*(.+?)\*', r'\1', suggestion)
                                break
                        if not suggestion:
                            summary_section = re.search(r'总结.*?(?:\n|$)(.*?)(?=##|\Z)', analysis_text, re.DOTALL)
                            if summary_section:
                                summary_text = summary_section.group(1)
                                dash_content = re.search(r'-\s*(.+?)(?:\n|$)', summary_text)
                                if dash_content:
                                    suggestion = dash_content.group(1).strip()
                                    suggestion = re.sub(r'\*\*(.+?)\*\*', r'\1', suggestion)
                                    suggestion = re.sub(r'\*(.+?)\*', r'\1', suggestion)
                        if not suggestion:
                            summary_match = re.search(r'总结.*?(?:\n|$)(.*?)(?=\n\n|\Z)', analysis_text, re.DOTALL)
                            if summary_match:
                                first_sentence = re.search(r'[^.!?。！？]+[.!?。！？]', summary_match.group(1))
                                if first_sentence:
                                    suggestion = first_sentence.group(0).strip()
                                    suggestion = re.sub(r'\*\*(.+?)\*\*', r'\1', suggestion)
                                    suggestion = re.sub(r'\*(.+?)\*', r'\1', suggestion)
                        analysis_data.append({"score": score, "suggestion": suggestion})
                column_indices = {}
                for col in range(1, worksheet.max_column + 1):
                    header = worksheet.cell(1, col).value
                    if header:
                        column_indices[header] = col
                for i, (name, data) in enumerate(zip(file_names, analysis_data)):
                    row = i + 2
                    if row <= worksheet.max_row:
                        if "客户名称" in column_indices:
                            worksheet.cell(row, column_indices["客户名称"]).value = name
                        if "联系人" in column_indices:
                            worksheet.cell(row, column_indices["联系人"]).value = st.session_state.contact_person
                        if "评分" in column_indices and data["score"]:
                            try:
                                worksheet.cell(row, column_indices["评分"]).value = int(data["score"])
                            except ValueError:
                                worksheet.cell(row, column_indices["评分"]).value = data["score"]
                        if "通话优化建议" in column_indices and data["suggestion"]:
                            worksheet.cell(row, column_indices["通话优化建议"]).value = data["suggestion"]
                if st.session_state.summary_analysis:
                    avg_score = ""
                    avg_score_patterns = [
                        r'平均评分[^\d]*(\d+\.?\d*)',
                        r'平均评分：\s*(\d+\.?\d*)',
                        r'平均[^\d]*(\d+\.?\d*)',
                        r'平均分[^\d]*(\d+\.?\d*)'
                    ]
                    for pattern in avg_score_patterns:
                        avg_score_match = re.search(pattern, st.session_state.summary_analysis)
                        if avg_score_match:
                            avg_score = avg_score_match.group(1)
                            break
                    suggestions = []
                    list_items = re.findall(r'- (.+?)(?:\n|$)', st.session_state.summary_analysis)
                    if list_items:
                        suggestions.extend(list_items)
                    if not suggestions:
                        numbered_items = re.findall(r'\d+\.\s+(.+?)(?:\n|$)', st.session_state.summary_analysis)
                        if numbered_items:
                            suggestions.extend(numbered_items)
                    formatted_suggestions = "改进建议：\n"
                    for suggestion in suggestions:
                        clean_suggestion = re.sub(r'\*\*(.+?)\*\*', r'\1', suggestion)
                        clean_suggestion = re.sub(r'\*(.+?)\*', r'\1', clean_suggestion)
                        formatted_suggestions += f"- {clean_suggestion}\n"
                    summary_row = 32
                    for row in range(1, worksheet.max_row + 1):
                        cell_value = worksheet.cell(row, 1).value
                        if cell_value and "总结" in str(cell_value):
                            summary_row = row
                            break
                    if formatted_suggestions:
                        worksheet.cell(summary_row, 2).value = formatted_suggestions
                    total_score_col = None
                    for col in range(1, worksheet.max_column + 1):
                        cell_value = worksheet.cell(summary_row, col).value
                        if cell_value and "总评分" in str(cell_value):
                            total_score_col = col
                            break
                    if total_score_col and avg_score:
                        worksheet.cell(summary_row, total_score_col).value = f"总评分：\n{avg_score}"
                        worksheet.cell(summary_row, total_score_col).alignment = openpyxl.styles.Alignment(wrapText=True)
                output = BytesIO()
                workbook.save(output)
                output.seek(0)
                processed_data = output.getvalue()
                return processed_data
            except Exception as e:
                st.error(f"处理Excel文件时出错: {str(e)}")
                return None

        excel_data = generate_excel_report()
        if excel_data:
            st.download_button(
                label="📊 下载电话开拓分析表",
                data=excel_data,
                file_name="电话开拓分析表_已填写.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
