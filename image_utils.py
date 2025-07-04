"""
图片处理工具模块
提供图片格式转换、优化、预览组件和错误处理等功能
"""

import streamlit as st
import base64
from PIL import Image
from io import BytesIO
import logging
from typing import List, Tuple, Dict, Any, Optional

logger = logging.getLogger(__name__)

def optimize_image_for_llm(image_content: bytes, max_size: Tuple[int, int] = (1024, 1024), 
                          quality: int = 85) -> bytes:
    """
    优化图片大小和格式，提高LLM识别效果
    
    Args:
        image_content: 原始图片字节数据
        max_size: 最大尺寸 (width, height)
        quality: JPEG质量 (1-100)
    
    Returns:
        优化后的图片字节数据
    """
    try:
        # 打开图片
        image = Image.open(BytesIO(image_content))
        
        # 转换为RGB模式（如果是RGBA或其他模式）
        if image.mode != 'RGB':
            image = image.convert('RGB')
        
        # 计算新的尺寸，保持长宽比
        original_size = image.size
        ratio = min(max_size[0] / original_size[0], max_size[1] / original_size[1])
        
        if ratio < 1:  # 只有当图片比最大尺寸大时才压缩
            new_size = (int(original_size[0] * ratio), int(original_size[1] * ratio))
            image = image.resize(new_size, Image.Resampling.LANCZOS)
        
        # 保存为JPEG格式
        output = BytesIO()
        image.save(output, format='JPEG', quality=quality, optimize=True)
        optimized_content = output.getvalue()
        
        logger.info(f"图片优化完成: {len(image_content)} bytes -> {len(optimized_content)} bytes")
        return optimized_content
        
    except Exception as e:
        logger.error(f"图片优化失败: {str(e)}")
        return image_content  # 如果优化失败，返回原始内容

def encode_image_to_base64(image_content: bytes) -> str:
    """
    将图片内容编码为base64字符串
    
    Args:
        image_content: 图片字节数据
    
    Returns:
        base64编码的字符串
    """
    return base64.b64encode(image_content).decode('utf-8')

def create_image_preview_grid(uploaded_images: List[Any], columns: int = 3) -> None:
    """
    创建图片预览网格布局
    
    Args:
        uploaded_images: Streamlit上传的图片文件列表
        columns: 每行显示的列数
    """
    if not uploaded_images:
        return
    
    st.markdown("### 📸 图片预览")
    
    # 创建网格布局
    for i in range(0, len(uploaded_images), columns):
        cols = st.columns(columns)
        batch = uploaded_images[i:i + columns]
        
        for j, img_file in enumerate(batch):
            with cols[j]:
                try:
                    # 显示图片
                    st.image(img_file, caption=f"{img_file.name}", use_container_width=True)
                    
                    # 显示文件信息
                    file_size = len(img_file.getvalue())
                    st.caption(f"大小: {format_file_size(file_size)}")
                    
                except Exception as e:
                    st.error(f"无法预览图片 {img_file.name}: {str(e)}")

def format_file_size(size_bytes: int) -> str:
    """
    格式化文件大小显示
    
    Args:
        size_bytes: 文件大小（字节）
    
    Returns:
        格式化的文件大小字符串
    """
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    else:
        return f"{size_bytes / (1024 * 1024):.1f} MB"

def validate_image_format(image_file: Any) -> Tuple[bool, str]:
    """
    验证图片格式是否支持
    
    Args:
        image_file: Streamlit上传的图片文件
    
    Returns:
        (是否有效, 错误信息)
    """
    try:
        # 检查文件扩展名
        valid_extensions = ['.jpg', '.jpeg', '.png', '.bmp', '.gif']
        file_extension = image_file.name.lower().split('.')[-1]
        if f".{file_extension}" not in valid_extensions:
            return False, f"不支持的文件格式: {file_extension}"
        
        # 尝试打开图片验证格式
        image_content = image_file.getvalue()
        image = Image.open(BytesIO(image_content))
        
        # 检查图片尺寸
        width, height = image.size
        if width < 100 or height < 100:
            return False, "图片尺寸过小，可能影响识别效果"
        
        # 检查文件大小
        if len(image_content) > 10 * 1024 * 1024:  # 10MB
            return False, "图片文件过大，请压缩后重新上传"
        
        return True, ""
        
    except Exception as e:
        return False, f"图片格式验证失败: {str(e)}"

def handle_image_processing_errors(errors: List[Dict[str, Any]]) -> None:
    """
    统一处理图片识别错误并显示给用户
    
    Args:
        errors: 错误信息列表，每个元素包含 {'filename': str, 'error': str}
    """
    if not errors:
        return
    
    st.warning(f"⚠️ 有 {len(errors)} 张图片处理失败")
    
    with st.expander("📋 查看失败详情", expanded=False):
        for error_info in errors:
            st.error(f"**{error_info['filename']}**: {error_info['error']}")
    
    st.info("💡 建议：")
    st.markdown("""
    - 确保图片清晰，包含完整的通话信息
    - 检查图片格式是否正确 (JPG, PNG等)
    - 如果图片过大，请适当压缩
    - 可以重新上传失败的图片再次尝试
    """)

def display_processing_summary(results: Dict[str, Any]) -> None:
    """
    显示图片处理结果摘要
    
    Args:
        results: 处理结果字典，包含 total, success, failed, calls_found 等信息
    """
    st.markdown("### 📊 处理结果摘要")
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric("总图片数", results.get('total', 0))
    
    with col2:
        success_count = results.get('success', 0)
        st.metric(
            "识别成功", 
            success_count, 
            delta=f"+{success_count}" if success_count > 0 else None
        )
    
    with col3:
        failed_count = results.get('failed', 0)
        st.metric(
            "识别失败", 
            failed_count, 
            delta=f"-{failed_count}" if failed_count > 0 else None
        )
    
    with col4:
        calls_found = results.get('calls_found', 0)
        st.metric("发现通话", calls_found)
    
    # 显示详细统计
    if results.get('effective_calls', 0) > 0:
        st.success(f"✅ 发现 {results['effective_calls']} 个有效通话")
    
    if results.get('total_calls', 0) > 0:
        st.info(f"📞 总计发现 {results['total_calls']} 个通话记录")

def display_duplicate_analysis(duplicate_result: Dict[str, Any]) -> Optional[str]:
    """
    显示图片文件名重复分析结果并获取用户选择
    
    Args:
        duplicate_result: 去重检查结果
    
    Returns:
        用户选择 ('skip_duplicates', 'force_all', None)
    """
    if not duplicate_result.get("has_duplicates", False):
        # 没有重复文件，显示简单信息
        st.success(f"✅ 检查完成：所有 {duplicate_result.get('new_count', 0)} 张图片都是新文件")
        return "proceed"  # 可以直接处理
    
    # 有重复文件，显示详细信息
    st.warning(f"⚠️ 发现 {duplicate_result.get('duplicate_count', 0)} 个重复文件名")
    
    # 显示重复文件详情
    with st.expander("📋 查看重复文件详情", expanded=True):
        duplicates = duplicate_result.get("duplicates", [])
        
        for i, dup in enumerate(duplicates, 1):
            col1, col2, col3 = st.columns([2, 1, 1])
            
            with col1:
                st.write(f"**{i}. {dup['filename']}**")
            
            with col2:
                st.write(f"上次上传: {dup['last_upload_date']}")
            
            with col3:
                st.write(f"{dup['days_ago']} 天前")
    
    # 显示统计信息
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.metric("总图片数", duplicate_result.get('total_images', 0))
    
    with col2:
        st.metric("重复文件", duplicate_result.get('duplicate_count', 0), delta=f"-{duplicate_result.get('duplicate_count', 0)}")
    
    with col3:
        st.metric("新文件", duplicate_result.get('new_count', 0), delta=f"+{duplicate_result.get('new_count', 0)}")
    
    # 用户选择按钮
    st.markdown("### 🤔 请选择处理方式：")
    
    col1, col2, col3 = st.columns(3)
    
    user_choice = None
    
    with col1:
        if st.button("🚫 跳过重复项", type="primary", help="只处理新文件，跳过重复的图片"):
            user_choice = "skip_duplicates"
    
    with col2:
        if st.button("🔄 强制处理全部", help="处理所有图片，包括重复的文件"):
            user_choice = "force_all"
    
    with col3:
        if st.button("❌ 取消上传", type="secondary", help="取消本次图片上传"):
            user_choice = "cancel"
    
    # 显示选择结果的预览
    if user_choice == "skip_duplicates":
        st.info(f"📝 将处理 {duplicate_result.get('new_count', 0)} 张新图片，跳过 {duplicate_result.get('duplicate_count', 0)} 张重复图片")
    elif user_choice == "force_all":
        st.warning(f"⚠️ 将强制处理所有 {duplicate_result.get('total_images', 0)} 张图片（包括重复文件）")
    elif user_choice == "cancel":
        st.error("❌ 已取消图片上传")
    
    return user_choice

def display_duplicate_files_info(duplicate_result: Dict[str, Any]) -> None:
    """
    显示重复文件的详细信息（用于处理完成后的总结）
    
    Args:
        duplicate_result: 去重检查结果
    """
    if not duplicate_result.get("has_duplicates", False):
        return
    
    st.markdown("### 📝 文件名重复处理总结")
    
    duplicates = duplicate_result.get("duplicates", [])
    
    # 创建表格显示重复文件信息
    data = []
    for dup in duplicates:
        data.append({
            "文件名": dup["filename"],
            "上次上传日期": dup["last_upload_date"], 
            "距今天数": f"{dup['days_ago']} 天",
            "状态": "🔄 已重复处理" if duplicate_result.get("processed_duplicates", False) else "🚫 已跳过"
        })
    
    if data:
        import pandas as pd
        df = pd.DataFrame(data)
        st.dataframe(df, use_container_width=True, hide_index=True)
        
        # 显示处理建议
        st.info("""
        💡 **关于重复文件的建议：**
        - 重复文件名可能表示相同的通话截图
        - 建议检查文件内容是否确实相同
        - 如需重新处理，可修改文件名后重新上传
        """)

def create_confirmation_dialog(summary_data: Dict[str, Any]) -> bool:
    """
    创建确认对话框，让用户确认处理结果
    
    Args:
        summary_data: 汇总数据
    
    Returns:
        用户是否确认
    """
    st.markdown("### ⚠️ 请确认处理结果")
    
    # 显示即将更新的数据
    st.markdown("**即将更新到数据库的数据：**")
    col1, col2 = st.columns(2)
    
    with col1:
        st.metric("新增总通话数", summary_data.get('total_calls', 0))
    
    with col2:
        st.metric("新增有效通话数", summary_data.get('effective_calls', 0))
    
    # 确认按钮
    col1, col2 = st.columns(2)
    
    with col1:
        if st.button("✅ 确认并保存", type="primary"):
            return True
    
    with col2:
        if st.button("❌ 取消", type="secondary"):
            st.session_state.image_processing_cancelled = True
            return False
    
    return False

def display_smart_duplicate_result(detection_result: Dict[str, Any]) -> bool:
    """
    显示智能去重结果
    
    Args:
        detection_result: 智能去重检测结果
    
    Returns:
        是否继续处理（有新记录要处理返回True）
    """
    skip_count = detection_result["skip_count"]
    process_count = detection_result["process_count"]
    
    # 显示统计信息
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.metric("检测记录数", skip_count + process_count)
    
    with col2:
        st.metric("跳过重复", skip_count, delta=f"-{skip_count}" if skip_count > 0 else None)
    
    with col3:
        st.metric("新增记录", process_count, delta=f"+{process_count}" if process_count > 0 else None)
    
    if skip_count > 0:
        st.warning(f"🤖 智能去重：检测到 {skip_count} 个高相似度记录已自动跳过")
        
        # 显示跳过的记录详情
        with st.expander(f"📋 查看跳过的 {skip_count} 个重复记录", expanded=False):
            for i, skipped in enumerate(detection_result["skipped_calls"], 1):
                call = skipped["call"]
                similarity = skipped["similarity"]
                matched = skipped["matched_call"]
                
                # 显示相似度得分和标题
                st.markdown(f"### {i}. {call.get('contact_info', '未知联系人')} - 相似度: {similarity:.2%}")
                
                # 创建两列对比显示
                col1, col2 = st.columns(2)
                
                with col1:
                    st.markdown("**📸 新识别记录：**")
                    st.markdown(f"- 📞 联系人: {call.get('contact_info', '未知')}")
                    st.markdown(f"- 🏢 公司: {call.get('company_name', '未知')}")
                    st.markdown(f"- ⏰ 时间: {call.get('call_time', '未知')}")
                    st.markdown(f"- ⏱️ 时长: {call.get('duration_text', '未知')}")
                    if call.get('is_effective'):
                        st.success("✅ 有效通话")
                    else:
                        st.warning("⚠️ 无效通话")
                
                with col2:
                    st.markdown("**📊 已存在记录：**")
                    st.markdown(f"- 📞 联系人: {matched.get('contact_person', '未知')}")
                    st.markdown(f"- 🏢 公司: {matched.get('company_name', '未知')}")
                    st.markdown(f"- ⏰ 时间: {matched.get('conversation_text', '未知')}")
                    st.markdown(f"- 📋 统计: {matched.get('analysis_text', '未知')[:50]}...")
                    st.markdown(f"- 📁 文件: {matched.get('original_filename', '未知')}")
                
                # 显示相似度分析
                st.markdown("---")
                st.markdown("**🔍 相似度分析：**")
                st.markdown(f"- 总相似度得分: **{similarity:.2%}** (阈值: 70%)")
                st.info("💡 系统判定：相似度超过阈值，自动跳过处理")
                
                if i < skip_count:
                    st.markdown("---")
    
    if process_count > 0:
        st.success(f"✅ 将处理 {process_count} 个新记录")
    else:
        st.info("📝 所有记录都已存在，无需重复处理")
    
    return process_count > 0  # 返回是否需要继续处理

def display_smart_detection_progress(message: str, progress: float = None) -> None:
    """
    显示智能检测进度
    
    Args:
        message: 进度消息
        progress: 进度百分比 (0-1)
    """
    if progress is not None:
        st.progress(progress)
    st.markdown(f"**{message}**") 