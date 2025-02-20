#将voice_api_demo.py的json文件导出为完整的文件。
import json


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