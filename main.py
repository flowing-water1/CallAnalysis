import streamlit as st
import os
import json
import time
import requests
import base64
import hashlib
import hmac
import urllib
from langchain_community.chat_models  import ChatOpenAI
from langchain.prompts import ChatPromptTemplate
from langchain.schema import HumanMessage, SystemMessage

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


# 上传文件到讯飞API
def upload_file_to_xunfei(upload_file_path):
    ts = str(int(time.time()))
    signa = get_signa(appid, secret_key, ts)

    file_len = os.path.getsize(upload_file_path)
    file_name = os.path.basename(upload_file_path)

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

    data = open(upload_file_path, 'rb').read(file_len)

    response = requests.post(url=lfasr_host + api_upload + "?" + urllib.parse.urlencode(param_dict),
                             headers={"Content-type": "application/json"}, data=data)
    result = json.loads(response.text)
    return result


# 获取转写结果
def get_transcription_result(orderId):
    ts = str(int(time.time()))
    signa = get_signa(appid, secret_key, ts)

    param_dict = {
        'appId': appid,
        'signa': signa,
        'ts': ts,
        'orderId': orderId,
        'resultType': "transfer,predict"
    }

    status = 3
    while status == 3:
        response = requests.post(url=lfasr_host + api_get_result + "?" + urllib.parse.urlencode(param_dict),
                                 headers={"Content-type": "application/json"})
        result = json.loads(response.text)
        status = result['content']['orderInfo']['status']
        if status == 4:
            break
        time.sleep(5)
    return result


# 规范化JSON文件为可读文本
def merge_result_for_one_vad(result_vad):
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


def content_to_file(content, output_file_path):
    with open(output_file_path, 'w', encoding='utf-8') as f:
        for lines in content:
            f.write(lines)


def identify_roles(raw_text: str) -> dict:
    """
    使用LLM识别对话中的角色

    Args:
        raw_text (str): 原始的带spk标记的文本

    Returns:
        dict: 角色映射关系，如 {'spk1': '销售', 'spk2': '客户'}
    """
    # 提取前几轮对话用于角色判断
    lines = raw_text.strip().split('\n')
    sample_dialogue = '\n'.join(lines[:10])  # 取前10行进行分析

    llm = ChatOpenAI(
        openai_api_key="sk-gXeRXhgYsLFziprS93D5F6D31eE249D59235739b37Bd20B1",
        openai_api_base="https://openai.weavex.tech/v1",
        model_name="gpt-4o",
        temperature=0.2  # 降低温度以获得更确定的答案
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
        # 如果识别失败，返回默认映射
        return {
            "spk1": "未知角色1",
            "spk2": "未知角色2",
            "confidence": "low"
        }


def format_conversation(raw_text: str) -> tuple:
    """
    将原始的spk标记文本转换为更规范的对话格式

    Returns:
        tuple: (formatted_text, roles_info)
    """
    # 首先识别角色
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

        # 使用识别出的角色
        speaker_role = roles.get(speaker, f"未知角色{speaker[-1]}")

        if speaker == current_speaker:
            current_content.append(content)
        else:
            if current_speaker and current_content:
                formatted_lines.append(f"{roles.get(current_speaker, f'未知角色{current_speaker[-1]}')}：{''.join(current_content)}")
            current_speaker = speaker
            current_content = [content]

    # 处理最后一组对话
    if current_speaker and current_content:
        formatted_lines.append(f"{roles.get(current_speaker, f'未知角色{current_speaker[-1]}')}：{''.join(current_content)}")

    formatted_text = '\n\n'.join(formatted_lines)

    return formatted_text, roles


def analyze_conversation(conversation_text: str):
    """
    分析通话记录并提供改进建议
    """
    # 格式化对话文本并获取角色信息
    formatted_text, roles = format_conversation(conversation_text)

    # 如果角色识别可信度低，在分析结果中提醒
    confidence_warning = ""
    if roles.get("confidence", "low") == "low":
        confidence_warning = "\n\n 注意：系统对说话者角色的识别可信度较低，请人工核实。"

    # 调整system prompt，加入角色信息
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

    # 配置OpenAI API
    llm = ChatOpenAI(
        openai_api_key="sk-gXeRXhgYsLFziprS93D5F6D31eE249D59235739b37Bd20B1",
        openai_api_base="https://openai.weavex.tech/v1",
        model_name="deepseek-r1",
        temperature=0.7
    )

    # 创建提示模板
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


# Streamlit界面
st.set_page_config(
    page_title="分析通话记录Demo",
    page_icon="📞"
)

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
        st.info("文件分析中...")

        for uploaded_file in uploaded_files:
            with open(f"./temp_{uploaded_file.name}", "wb") as f:
                f.write(uploaded_file.getbuffer())

            result = upload_file_to_xunfei(f"./temp_{uploaded_file.name}")
            if 'content' in result and 'orderId' in result['content']:
                orderId = result['content']['orderId']
                transcription_result = get_transcription_result(orderId)

                # 处理转写结果
                if 'content' in transcription_result:
                    js_xunfei_result = json.loads(transcription_result['content']['orderResult'])
                    content = []
                    for result_one_vad_str in js_xunfei_result['lattice']:
                        js_result_one_vad = json.loads(result_one_vad_str['json_1best'])
                        content.extend(merge_result_for_one_vad(js_result_one_vad))

                    # 输出到文件
                    output_file_path = f"{uploaded_file.name}_output.txt"
                    content_to_file(content, output_file_path)

                    # 读取文件内容进行分析
                    with open(output_file_path, 'r', encoding='utf-8') as f:
                        conversation_text = f.read()

                    # 调用大模型进行分析
                    analysis_result = analyze_conversation(conversation_text)

                    if analysis_result["status"] == "success":
                        st.success(f"文件转写和分析已完成！")

                        # 使用tabs来组织内容
                        tab1, tab2 = st.tabs(["📝 对话记录", "📊 分析结果"])

                        with tab1:
                            # 显示角色识别信息
                            if analysis_result["roles"].get("confidence") != "high":
                                st.warning(" 系统对说话者角色的识别可信度不高，请核实。", icon="⚠️")

                            st.markdown("### 对话角色")
                            st.markdown(f"- 说话者1 ({analysis_result['roles']['spk1']})")
                            st.markdown(f"- 说话者2 ({analysis_result['roles']['spk2']})")

                            st.markdown("### 通话记录")
                            st.markdown(analysis_result["formatted_text"])

                        with tab2:
                            st.markdown("### 🔍 通话分析结果")
                            st.markdown(analysis_result["analysis"])

                        # 下载按钮
                        st.download_button(
                            label="📥 下载完整分析报告",
                            data=f"通话记录：\n\n{analysis_result['formatted_text']}\n\n分析结果：\n\n{analysis_result['analysis']}",
                            file_name=f"{uploaded_file.name}_analysis_report.txt",
                            mime="text/plain"
                        )
                    else:
                        st.error(f"分析过程出现错误：{analysis_result['message']}")
                        st.success(f"仅完成文件转写，结果已保存为: {output_file_path}")

                    # 删除临时文件
                    os.remove(f"./temp_{uploaded_file.name}")
                else:
                    st.error("未能成功获取转写结果！")
            else:
                st.error("上传文件失败，无法获取订单ID！")
