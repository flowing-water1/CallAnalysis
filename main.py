import streamlit as st
import os
import json
import time
import requests
import base64
import hashlib
import hmac
import urllib

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


# Streamlit界面
st.set_page_config(
    page_title="分析通话记录Demo📞",
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

                    st.success(f"分析完成，结果已保存为: {output_file_path}")
                else:
                    st.error("未能成功获取转写结果！")
            else:
                st.error("上传文件失败，无法获取订单ID！")
