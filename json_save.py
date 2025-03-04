#将voice_api_demo.py的json文件导出为完整的文件。
import json
import os
import requests
import urllib.parse


def read_jsonfile(path, en='utf-8'):
    with open(path, "r", encoding=en) as f:
        return json.load(f)


def merge_result_for_one_vad(result_vad):
    content = []
    for rt_dic in result_vad['st']['rt']:
        spk_str = 'spk' + str(3 - int(result_vad['st']['rl'])) + '##'
        for st_dic in rt_dic['ws']:
            for cw_dic in st_dic['cw']:
                for w in cw_dic['w']:
                    spk_str += w

        spk_str += '\n'
        print(spk_str)

    return spk_str


def content_to_file(content, output_file_path):
    with open(output_file_path, 'w', encoding='utf-8') as f:
        for lines in content:
            f.write(lines)
        f.close()


class XunfeiASR:
    def __init__(self, appid, signa, ts, file_path):
        self.appid = appid
        self.signa = signa
        self.ts = ts
        self.file_path = file_path

    def process_audio(self):
        # 上传文件
        file_len = os.path.getsize(self.file_path)
        file_name = os.path.basename(self.file_path)

        param_dict = {
            'appId': self.appid,
            'signa': self.signa,
            'ts': self.ts,
            'fileSize': file_len,
            'fileName': file_name,
            'duration': "200",
            'roleNum': 2,
            'roleType': 1
        }

        # 修改这部分：直接读取二进制数据
        data = open(self.file_path, 'rb').read(file_len)

        upload_url = XFASR_HOST + '/upload'
        response = requests.post(
            url=upload_url + "?" + urllib.parse.urlencode(param_dict),
            headers={"Content-type": "application/x-www-form-urlencoded"},  # 修改请求头
            data=data
        )
        
        result = json.loads(response.text)
        if result.get('code') != 0:
            raise Exception(f"上传失败: {result}")  # 修改错误信息显示完整结果


if __name__ == '__main__':

    path_xunfei = "xxxxxxx.json"
    output_path_xunfei = "xunfei_output.txt"
    js_xunfei = read_jsonfile(path_xunfei)
    js_xunfei_result = json.loads(js_xunfei['content']['orderResult'])
    # lattice是做了顺滑功能的识别结果，lattice2是不做顺滑功能的识别结果
    # json_1best：单个VAD的json结果
    content = []
    for result_one_vad_str in js_xunfei_result['lattice']:
        js_result_one_vad = json.loads(result_one_vad_str['json_1best'])
        content.append(merge_result_for_one_vad(js_result_one_vad))
    content_to_file(content, output_path_xunfei)