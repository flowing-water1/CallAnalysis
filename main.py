import streamlit as st
import os
import asyncio
import logging
from io import BytesIO
import re
import openpyxl
from config import LOGGING_CONFIG, EXCEL_CONFIG
from Audio_Recognition import (
    upload_files_async,
    get_transcription_result_async,
    merge_result_for_one_vad,
    process_file,
    process_all_files
)
from Identify_Roles import (
    identify_roles,
    format_conversation_with_roles
)
from Analyze_Conversation import analyze_conversation_with_roles
from Analyze_Summary import analyze_summary
from LLM_Workflow import llm_workflow

# 配置日志输出
logging.basicConfig(
    level=getattr(logging, LOGGING_CONFIG["level"]), 
    format=LOGGING_CONFIG["format"]
)

@st.dialog(title="欢迎使用通话分析工具！", width="large")
def tutorial():
    st.markdown("## 📚 使用教程")
    st.markdown("### ⚠️ 重要格式要求")
    st.markdown(
        "上传文件的格式必须是 :red[**\"公司名称-联系人-电话号码\"**] 的形式。中间有无空格不影响，但必须使用 :red[**\"-\"**] 作为分隔符。（此格式要求将在后续版本中优化）",
        unsafe_allow_html=True)

    st.markdown("### 使用流程")

    st.markdown("#### 1️⃣ 上传文件")
    st.markdown("点击下方按钮上传您的通话录音文件：")
    st.image("tutorial/上传文件按钮.png")
    st.markdown(":green[✅] 支持批量上传多个文件")
    st.image("tutorial/上传文件.png")

    st.markdown("#### 2️⃣ 确认上传状态")
    st.markdown("成功上传后，您将看到如下界面：")
    st.image("tutorial/上传之后的样子.png")

    st.markdown("#### 3️⃣ 开始分析流程")
    st.markdown("点击 :blue[**\"开始分析\"**] 按钮启动处理：")
    st.image("tutorial/开始分析.png")

    st.markdown("#### 4️⃣ 等待处理完成")
    st.markdown("系统正在处理中，请保持页面打开。您可以暂时切换到其他工作，处理完成后回来查看结果。")

    st.markdown("#### 5️⃣ 查看分析结果")
    st.image("tutorial/最终结果.png")

    st.markdown("#### 6️⃣ 导出分析报告")
    st.markdown("您可以下载：")
    st.markdown("• :blue[完整分析报告] - 包含所有通话记录和详细分析")
    st.markdown("• :green[电话开拓分析表] - 自动填写好的分析数据表格")

    st.markdown("表格中已自动填写好对应数据项：")
    st.image("tutorial/分析结果表格.png")

    st.markdown("分析报告采用Markdown格式，建议使用Markdown编辑器打开以获得最佳阅读体验：")
    st.image("tutorial/分析结果文档.png")

    st.markdown("### ❓ 如何关闭本教程")
    st.markdown("点击对话框外任意位置，或滚动至顶部点击右上角的'❌'即可关闭本教程。")


# Streamlit界面
st.set_page_config(page_title="分析通话记录Demo", page_icon="📞")

# 使用列布局让标题和按钮在同一行
title_col, button_col = st.columns([5, 1.2])

# 在第一列放置标题
with title_col:
    st.title("分析通话记录📞")

# 在第二列放置帮助按钮
with button_col:
    if st.button("📚 查看教程", help="点击查看详细使用教程"):
        # 当按钮被点击时，触发教程对话框
        tutorial()

# 初始化session state
if 'analysis_results' not in st.session_state:
    st.session_state.analysis_results = None
if 'combined_report' not in st.session_state:
    st.session_state.combined_report = None
if 'summary_analysis' not in st.session_state:
    st.session_state.summary_analysis = None
if 'analysis_completed' not in st.session_state:
    st.session_state.analysis_completed = False  # 用来标记分析是否完成
if 'tutorial_shown' not in st.session_state:
    st.session_state.tutorial_shown = False


    


# 仅在第一次加载页面且教程未显示过时显示教程
if not st.session_state.tutorial_shown:
    tutorial()
    st.session_state.tutorial_shown = True

uploaded_files = st.file_uploader(
    "请上传通话录音文件",
    type=['wav', 'mp3', 'm4a', 'ogg'],
    accept_multiple_files=True
)

if uploaded_files and not st.session_state.analysis_completed:
    st.write("已上传的文件:")
    for file in uploaded_files:
        st.write(f"- {file.name}")

    if st.button("开始分析", key="start_analysis"):
        with st.spinner("正在处理文件..."):
            progress_placeholder = st.empty()
            # 保存上传的文件到临时文件夹
            temp_files = []
            for uploaded_file in uploaded_files:
                # 确保临时文件夹存在
                os.makedirs("temp", exist_ok=True)
                temp_path = os.path.join("temp", f"temp_{uploaded_file.name}")
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
                # 尝试删除临时文件夹
                try:
                    os.rmdir("temp")
                except OSError:
                    pass  # 如果文件夹不为空或不存在，忽略错误

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
                analysis_result = res.get("analysis_result", {})
                if analysis_result.get("status") == "success":
                    file_name = os.path.basename(res["file_path"])
                    file_name = re.sub(r'^temp_', '', file_name)
                    file_name = os.path.splitext(file_name)[0]
                    with st.expander(f"📊 {file_name} 通话分析"):
                        st.markdown(analysis_result["analysis"])
                        st.markdown("---")
                else:
                    st.error(f"文件 {idx} 分析失败: {analysis_result.get('message', '未知错误')}")

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
        excel_filename = "电话开拓分析表_未知联系人.xlsx"  # 默认文件名
        
        def generate_excel_report():
            try:
                workbook = openpyxl.load_workbook(EXCEL_CONFIG["template_file"])
                worksheet = workbook.active
                file_names = []
                contact_persons = []
                analysis_data = []
                for res in st.session_state.analysis_results:
                    if res["status"] == "success" and res["analysis_result"].get("status") == "success":
                        file_name = os.path.basename(res["file_path"])
                        file_name = re.sub(r'^temp_', '', file_name)
                        file_name = os.path.splitext(file_name)[0]
                        
                        # 提取公司名称、联系人、电话号码
                        # 尝试匹配新格式: "公司名-联系人-电话号码"
                        pattern = r'^(.*?)-(.*?)-(.*)$'
                        match = re.match(pattern, file_name)
                        
                        company_name = ""
                        contact_person = ""
                        phone_number = ""
                        
                        if match:
                            # 新格式
                            company_name = match.group(1).strip()
                            contact_person = match.group(2).strip()
                            raw_phone = match.group(3).strip()
                            
                            # 清理电话号码中的空格和连字符
                            phone_number = re.sub(r'[\s-]', '', raw_phone)
                        else:
                            # 旧格式兼容: "公司名-电话号码"
                            old_pattern = r'^(.*?)-(.*?)$'
                            old_match = re.match(old_pattern, file_name)
                            if old_match:
                                company_name = old_match.group(1).strip()
                                raw_phone = old_match.group(2).strip()
                                phone_number = re.sub(r'[\s-]', '', raw_phone)
                            else:
                                # 如果两种格式都不匹配，直接使用文件名作为公司名
                                company_name = file_name
                        
                        file_names.append(company_name)
                        contact_persons.append(contact_person)
                        
                        # 提取评分和建议
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
                            r'总分\s*\n\s*(\d+)',
                            r'总分：\s*(\d+)分',
                            r'总分\s*[:：]\s*(\d+)',
                            r'总分计算[：:]\s*(?:[\s\S]*?)总分[：:]\s*(\d+)分',
                            r'总分[：:]\s*(\d+)\/\d+',
                            r'总分计算[：:]\s*(?:[\s\S]*?)总分[：:]\s*(\d+)\/\d+',
                            r'[总总]分[：:]\s*(\d+)',
                            r'总分\s*\n\s*总分[:：]\s*(?:.*?)=\s*(\d+)\s*分',
                            r'总分[:：]\s*(?:.*?)=\s*(\d+)\s*分',
                            r'总分\s*\n\s*(?:.*?)=\s*(\d+)\s*分',
                            r'=\s*(\d+)\s*分',
                            r'总分[:：]\s*\n\s*(\d+)分',
                            r'总分[:：]\s*\n\s*(\d+)分/\d+分',
                            r'总分[:：]\s*\n\s*(\d+)/\d+',
                            r'总分[:：]\s*(\d+)分/\d+分'
                        ]
                        for pattern in score_patterns:
                            score_match = re.search(pattern, analysis_text)
                            if score_match:
                                score = score_match.group(1)
                                break
                        if not score:
                            try:
                                # 查找各项评分并求和
                                individual_scores = re.findall(r':\s*(\d+)分', analysis_text)
                                if individual_scores and len(individual_scores) >= 5:  # 至少有5个评分项
                                    total = sum(int(s) for s in individual_scores)
                                    score = str(total)
                                    logging.debug(f"通过各项分数求和得到总分: {score}")
                            except:
                                pass
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
                        analysis_data.append({
                            "score": score, 
                            "suggestion": suggestion, 
                            "phone_number": phone_number,
                            "contact_person": contact_person
                        })
                
                # 查找表格中的列
                column_indices = {}
                for col in range(1, worksheet.max_column + 1):
                    header = worksheet.cell(1, col).value
                    if header:
                        column_indices[header] = col
                
                # 填写数据到表格中
                for i, (name, data) in enumerate(zip(file_names, analysis_data)):
                    row = i + 2
                    if row <= worksheet.max_row:
                        if "客户名称" in column_indices:
                            worksheet.cell(row, column_indices["客户名称"]).value = name
                        if "联系人" in column_indices:
                            worksheet.cell(row, column_indices["联系人"]).value = data["contact_person"]
                        if "联系电话" in column_indices and data["phone_number"]:
                            worksheet.cell(row, column_indices["联系电话"]).value = data["phone_number"]
                        if "评分" in column_indices and data["score"]:
                            try:
                                worksheet.cell(row, column_indices["评分"]).value = int(data["score"])
                            except ValueError:
                                worksheet.cell(row, column_indices["评分"]).value = data["score"]
                        if "通话优化建议" in column_indices and data["suggestion"]:
                            worksheet.cell(row, column_indices["通话优化建议"]).value = data["suggestion"]
                
                # 填写该日电话数
                total_calls = len([res for res in st.session_state.analysis_results if res["status"] == "success"])
                # 寻找"该日电话数"单元格
                for row in range(1, worksheet.max_row + 1):
                    cell_value = worksheet.cell(row, 1).value
                    if cell_value and "该日电话数" in str(cell_value):
                        # 假设CDEF合并单元格在第3列开始
                        worksheet.cell(row, 3).value = total_calls
                        break
                
                # 处理总结部分
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
                    
                    # 找到总结行
                    summary_row = None
                    for row in range(1, worksheet.max_row + 1):
                        cell_value = worksheet.cell(row, 1).value
                        if cell_value and "总结" in str(cell_value):
                            summary_row = row
                            break
                    
                    if not summary_row:
                        # 如果没找到，默认使用第33行
                        summary_row = EXCEL_CONFIG["summary_row"]
                    
                    if formatted_suggestions:
                        worksheet.cell(summary_row, 2).value = formatted_suggestions
                    
                    # 查找总评分列
                    total_score_col = None
                    for col in range(1, worksheet.max_column + 1):
                        cell_value = worksheet.cell(summary_row, col).value
                        if cell_value and "总评分" in str(cell_value):
                            total_score_col = col
                            break
                    
                    if total_score_col and avg_score:
                        worksheet.cell(summary_row, total_score_col).value = f"总评分：\n{avg_score}"
                        worksheet.cell(summary_row, total_score_col).alignment = openpyxl.styles.Alignment(wrapText=True)
                
                # 获取第一个文件的联系人名称，如果没有则使用默认值
                first_contact = contact_persons[0] if contact_persons and contact_persons[0] else "未知联系人"
                
                # 获取当前日期
                from datetime import datetime
                today_date = datetime.now().strftime("%Y%m%d")
                
                # 生成文件名
                global excel_filename
                excel_filename = f"电话开拓分析表_{first_contact}_{today_date}.xlsx"
                
                # 保存到内存中
                excel_buffer = BytesIO()
                workbook.save(excel_buffer)
                excel_buffer.seek(0)
                return excel_buffer
            except Exception as e:
                logging.error(f"生成Excel报告时出错: {e}")
                st.error(f"生成Excel报告时出错: {e}")
                return None

        excel_data = generate_excel_report()
        if excel_data:
            st.download_button(
                label="📊 下载电话开拓分析表",
                data=excel_data,
                file_name=excel_filename,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
