"""
数据库操作工具模块
提供通话分析系统的所有数据库操作接口
"""
import asyncio
import json
from datetime import datetime, date
from typing import List, Dict, Optional, Tuple, Any
import asyncpg
from contextlib import asynccontextmanager
import pytz
import logging

logger = logging.getLogger(__name__)

# 设置中国时区
CHINA_TZ = pytz.timezone('Asia/Shanghai')


class DatabaseManager:
    """数据库管理器，处理所有数据库操作"""
    
    def __init__(self, config: Dict[str, Any]):
        """
        初始化数据库管理器
        
        Args:
            config: 数据库配置字典（来自config.py的DATABASE_CONFIG）
        """
        self.config = config
        self._pool: Optional[asyncpg.Pool] = None
        
    async def initialize(self):
        """初始化数据库连接池并确保数据库结构完整"""
        if self._pool is None:
            # 连接参数，添加时区设置
            connect_kwargs = {
                'host': self.config['host'],
                'port': self.config['port'],
                'database': self.config['database'],
                'user': self.config['username'],
                'password': self.config['password'],
                'server_settings': {
                    'timezone': 'Asia/Shanghai',  # 设置服务器时区
                    'jit': 'off',
                    'application_name': 'call_analysis_app'
                },
                **self.config.get('pool_config', {})
            }
            
            # 创建连接池
            self._pool = await asyncpg.create_pool(**connect_kwargs)
            logger.info("数据库连接池创建成功")
            
            # 确保数据库结构完整（包括触发器）
            await self._ensure_database_structure()
    
    async def _ensure_database_structure(self):
        """确保数据库结构完整，包括表、索引和触发器"""
        try:
            async with self.acquire() as conn:
                # 检查并创建触发器函数
                logger.info("🔧 检查数据库触发器...")
                
                # 检查 update_salesperson_activity 函数是否存在
                function_exists = await conn.fetchval("""
                    SELECT EXISTS (
                        SELECT 1 FROM pg_proc 
                        WHERE proname = 'update_salesperson_activity'
                    )
                """)
                
                if not function_exists:
                    logger.info("📝 创建销售人员活动更新触发器函数...")
                    await conn.execute("""
                        CREATE OR REPLACE FUNCTION update_salesperson_activity()
                        RETURNS TRIGGER AS $$
                        BEGIN
                            -- 当 daily_call_records 表有插入或更新操作时，
                            -- 自动更新对应销售人员的 updated_at 字段
                            UPDATE salespersons 
                            SET updated_at = CURRENT_TIMESTAMP 
                            WHERE id = NEW.salesperson_id;
                            
                            RETURN NEW;
                        END;
                        $$ LANGUAGE 'plpgsql';
                    """)
                    logger.info("✅ 触发器函数创建成功")
                else:
                    logger.info("✅ 触发器函数已存在")
                
                # 检查触发器是否存在
                trigger_exists = await conn.fetchval("""
                    SELECT EXISTS (
                        SELECT 1 FROM information_schema.triggers 
                        WHERE trigger_name = 'update_salesperson_activity_trigger'
                        AND event_object_table = 'daily_call_records'
                    )
                """)
                
                if not trigger_exists:
                    logger.info("📝 创建销售人员活动更新触发器...")
                    await conn.execute("""
                        CREATE TRIGGER update_salesperson_activity_trigger
                            AFTER INSERT OR UPDATE ON daily_call_records
                            FOR EACH ROW 
                            EXECUTE FUNCTION update_salesperson_activity();
                    """)
                    logger.info("✅ 触发器创建成功")
                else:
                    logger.info("✅ 触发器已存在")
                
                # 验证触发器是否工作
                await self._verify_trigger_functionality(conn)
                
        except Exception as e:
            logger.error(f"❌ 确保数据库结构时出错: {str(e)}")
            # 不抛出异常，允许系统继续运行
    
    async def _verify_trigger_functionality(self, conn):
        """验证触发器功能是否正常"""
        try:
            # 静默验证：检查触发器是否在信息架构中正确注册
            triggers = await conn.fetch("""
                SELECT trigger_name, event_manipulation, action_timing
                FROM information_schema.triggers
                WHERE trigger_name = 'update_salesperson_activity_trigger'
                AND event_object_table = 'daily_call_records'
            """)
            
            if triggers:
                events = [t['event_manipulation'] for t in triggers]
                if 'INSERT' in events and 'UPDATE' in events:
                    logger.info("✅ 触发器功能验证通过")
                else:
                    logger.warning("⚠️  触发器可能配置不完整")
            else:
                logger.warning("⚠️  触发器验证失败")
                
        except Exception as e:
            logger.warning(f"⚠️  触发器验证时出错: {str(e)}")
            # 不影响主流程
    
    async def close(self):
        """关闭数据库连接池"""
        if self._pool:
            await self._pool.close()
            self._pool = None
            logger.info("数据库连接池已关闭")
    
    @asynccontextmanager
    async def acquire(self):
        """获取数据库连接的上下文管理器"""
        if self._pool is None:
            await self.initialize()
        async with self._pool.acquire() as connection:
            # 确保每个连接都使用正确的时区
            await connection.execute("SET timezone = 'Asia/Shanghai'")
            yield connection
    
    async def get_salespersons(self) -> List[Dict[str, Any]]:
        """
        获取所有销售人员列表
        
        Returns:
            销售人员列表 [{"id": 1, "name": "张三"}, ...]
        """
        async with self.acquire() as conn:
            rows = await conn.fetch(
                "SELECT id, name FROM salespersons ORDER BY name"
            )
            return [dict(row) for row in rows]
    
    async def get_salesperson_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        """
        根据姓名获取销售人员信息
        
        Args:
            name: 销售人员姓名
            
        Returns:
            销售人员信息字典，如果不存在返回None
        """
        async with self.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT id, name FROM salespersons WHERE name = $1",
                name
            )
            return dict(row) if row else None
    
    async def check_daily_record_exists(self, salesperson_id: int, upload_date: date) -> bool:
        """
        检查指定销售人员在指定日期是否已有记录
        
        Args:
            salesperson_id: 销售人员ID
            upload_date: 上传日期
            
        Returns:
            如果存在记录返回True，否则False
        """
        async with self.acquire() as conn:
            result = await conn.fetchval(
                """
                SELECT EXISTS(
                    SELECT 1 FROM daily_call_records 
                    WHERE salesperson_id = $1 AND upload_date = $2
                )
                """,
                salesperson_id, upload_date
            )
            return result
    
    async def get_daily_record(self, salesperson_id: int, upload_date: date) -> Optional[Dict[str, Any]]:
        """
        获取指定销售人员在指定日期的记录
        
        Args:
            salesperson_id: 销售人员ID
            upload_date: 上传日期
            
        Returns:
            日常记录信息字典，如果不存在返回None
        """
        async with self.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, total_calls, effective_calls, average_score,
                       summary_analysis, improvement_suggestions, 
                       created_at
                FROM daily_call_records 
                WHERE salesperson_id = $1 AND upload_date = $2
                """,
                salesperson_id, upload_date
            )
            return dict(row) if row else None
    
    async def delete_daily_record_and_details(self, daily_record_id: int):
        """
        删除日常记录及其所有相关的通话详情（级联删除）
        
        Args:
            daily_record_id: 日常记录ID
        """
        async with self.acquire() as conn:
            # 由于设置了ON DELETE CASCADE，删除daily_record会自动删除相关的call_details
            await conn.execute(
                "DELETE FROM daily_call_records WHERE id = $1",
                daily_record_id
            )
            logger.info(f"已删除日常记录ID: {daily_record_id} 及其所有通话详情")
    
    async def create_daily_record(self, salesperson_id: int, upload_date: date) -> int:
        """
        创建新的日常记录
        
        Args:
            salesperson_id: 销售人员ID
            upload_date: 上传日期
            
        Returns:
            新创建的记录ID
        """
        async with self.acquire() as conn:
            # 使用明确的中国时区时间
            row = await conn.fetchrow(
                """
                INSERT INTO daily_call_records 
                (salesperson_id, upload_date, total_calls, effective_calls, created_at)
                VALUES ($1, $2, 0, 0, NOW() AT TIME ZONE 'Asia/Shanghai')
                RETURNING id
                """,
                salesperson_id, upload_date
            )
            return row['id']
    
    async def update_daily_record_stats(
        self, 
        daily_record_id: int,
        total_calls: int,
        effective_calls: int,
        average_score: Optional[float],
        summary_analysis: Optional[str],
        improvement_suggestions: Optional[str],
        merge_analysis: bool = False
    ):
        """
        更新日常记录的统计信息
        
        Args:
            daily_record_id: 日常记录ID
            total_calls: 总通话数
            effective_calls: 有效通话数
            average_score: 平均评分
            summary_analysis: 汇总分析
            improvement_suggestions: 改进建议
            merge_analysis: 是否合并分析结果（追加模式时使用）
        """
        async with self.acquire() as conn:
            if merge_analysis:
                # 获取现有的分析结果
                existing_record = await conn.fetchrow(
                    """
                    SELECT summary_analysis, improvement_suggestions, created_at,
                           total_calls, effective_calls, average_score
                    FROM daily_call_records 
                    WHERE id = $1
                    """,
                    daily_record_id
                )
                
                if existing_record:
                    # 生成时间戳
                    from datetime import datetime
                    current_time = datetime.now().strftime("%Y-%m-%d %H:%M")
                    
                    # 准备评分历史信息
                    score_history = ""
                    old_total = existing_record['total_calls'] or 0
                    old_effective = existing_record['effective_calls'] or 0
                    old_avg = existing_record['average_score']
                    
                    # 计算新增的通话数据
                    new_calls = total_calls - old_total
                    new_effective = effective_calls - old_effective
                    
                    if old_total > 0 and new_calls > 0:
                        # 类型转换和计算显示值
                        old_avg_float = float(old_avg) if old_avg else None
                        current_avg_float = float(average_score) if average_score else None
                        
                        old_avg_display = f"{old_avg_float:.1f}" if old_avg_float else "N/A"
                        current_avg_display = f"{current_avg_float:.1f}" if current_avg_float else "N/A"
                        
                        # 计算新增部分的平均分
                        new_avg_display = "N/A"
                        if current_avg_float and old_avg_float and new_calls > 0:
                            new_avg = (current_avg_float * total_calls - old_avg_float * old_total) / new_calls
                            new_avg_display = f"{new_avg:.1f}"
                        
                        score_history = f"""
📊 **评分历史追踪**
├─ 原有记录：{old_total}个通话，{old_effective}个有效，平均分 {old_avg_display}
├─ 本次新增：{new_calls}个通话，{new_effective}个有效，平均分 {new_avg_display}
└─ 合并后：{total_calls}个通话，{effective_calls}个有效，平均分 {current_avg_display}

"""
                    
                    # 合并汇总分析
                    existing_summary = existing_record['summary_analysis'] or ''
                    if existing_summary and summary_analysis:
                        merged_summary = f"""{score_history}{existing_summary}

==================== 追加分析 ({current_time}) ====================
本次新增通话的分析结果：

{summary_analysis}
==================== 追加分析结束 ===================="""
                    else:
                        merged_summary = f"{score_history}{summary_analysis or existing_summary}"
                    
                    # 合并改进建议
                    existing_suggestions = existing_record['improvement_suggestions'] or ''
                    if existing_suggestions and improvement_suggestions:
                        merged_suggestions = f"""{existing_suggestions}

--- 基于新增通话的补充建议 ({current_time}) ---
{improvement_suggestions}"""
                    else:
                        merged_suggestions = improvement_suggestions or existing_suggestions
                    
                    # 使用合并后的内容
                    summary_analysis = merged_summary
                    improvement_suggestions = merged_suggestions
            
            # 更新记录
            await conn.execute(
                """
                UPDATE daily_call_records 
                SET total_calls = $2,
                    effective_calls = $3,
                    average_score = $4,
                    summary_analysis = $5,
                    improvement_suggestions = $6,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = $1
                """,
                daily_record_id, total_calls, effective_calls, 
                average_score, summary_analysis, improvement_suggestions
            )
    
    async def insert_call_detail(
        self,
        daily_record_id: int,
        salesperson_id: int,
        call_data: Dict[str, Any]
    ):
        """
        插入单条通话详情记录
        
        Args:
            daily_record_id: 日常记录ID
            salesperson_id: 销售人员ID
            call_data: 通话数据字典，包含：
                - original_filename: 原始文件名
                - company_name: 公司名称
                - contact_person: 联系人
                - phone_number: 电话号码
                - conversation_text: 对话文本
                - analysis_text: 完整分析文本
                - score: 通话评分
                - is_effective: 是否有效
                - suggestions: 改进建议
        """
        async with self.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO call_details (
                    daily_record_id, salesperson_id, original_filename,
                    company_name, contact_person, phone_number,
                    conversation_text, analysis_text, 
                    score, is_effective, suggestions,
                    created_at
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, NOW() AT TIME ZONE 'Asia/Shanghai')
                """,
                daily_record_id, salesperson_id,
                call_data.get('original_filename'),
                call_data.get('company_name'),
                call_data.get('contact_person'),
                call_data.get('phone_number'),
                call_data.get('conversation_text'),
                call_data.get('analysis_text'),
                call_data.get('score'),
                call_data.get('is_effective', False),
                call_data.get('suggestions')
            )
    
    async def batch_insert_call_details(
        self,
        daily_record_id: int,
        salesperson_id: int,
        call_data_list: List[Dict[str, Any]]
    ):
        """
        批量插入通话详情记录
        
        Args:
            daily_record_id: 日常记录ID
            salesperson_id: 销售人员ID
            call_data_list: 通话数据列表
        """
        async with self.acquire() as conn:
            # 准备批量插入的数据
            values = []
            for call_data in call_data_list:
                values.append((
                    daily_record_id,
                    salesperson_id,
                    call_data.get('original_filename'),
                    call_data.get('company_name'),
                    call_data.get('contact_person'),
                    call_data.get('phone_number'),
                    call_data.get('conversation_text'),
                    call_data.get('analysis_text'),
                    call_data.get('score'),
                    call_data.get('is_effective', False),
                    call_data.get('suggestions')
                ))
            
            # 执行批量插入
            await conn.executemany(
                """
                INSERT INTO call_details (
                    daily_record_id, salesperson_id, original_filename,
                    company_name, contact_person, phone_number,
                    conversation_text, analysis_text, 
                    score, is_effective, suggestions,
                    created_at
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, NOW() AT TIME ZONE 'Asia/Shanghai')
                """,
                values
            )
            logger.info(f"批量插入了 {len(values)} 条通话详情记录")


# 创建全局数据库管理器实例（需要在使用前配置）
db_manager: Optional[DatabaseManager] = None


def setup_database(config: Dict[str, Any]) -> DatabaseManager:
    """
    设置数据库管理器
    
    Args:
        config: 数据库配置
        
    Returns:
        配置好的数据库管理器实例
    """
    global db_manager
    db_manager = DatabaseManager(config)
    return db_manager


# Streamlit专用的同步接口
class SyncDatabaseManager:
    """为Streamlit提供的同步数据库接口"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        
    def _run_async(self, coro):
        """在新的事件循环中运行异步代码"""
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()
            asyncio.set_event_loop(None)
    
    def get_salespersons(self) -> List[Dict[str, Any]]:
        """同步获取销售人员列表"""
        async def _get():
            db = DatabaseManager(self.config)
            await db.initialize()
            try:
                return await db.get_salespersons()
            finally:
                await db.close()
        
        return self._run_async(_get())
    
    def check_daily_record_exists(self, salesperson_id: int, upload_date: date) -> bool:
        """同步检查记录是否存在"""
        async def _check():
            db = DatabaseManager(self.config)
            await db.initialize()
            try:
                return await db.check_daily_record_exists(salesperson_id, upload_date)
            finally:
                await db.close()
        
        return self._run_async(_check())
    
    def save_analysis_data(
        self,
        salesperson_id: int,
        call_details_list: List[Dict[str, Any]],
        summary_analysis: str,
        upload_choice: str = None
    ) -> bool:
        """同步保存分析数据"""
        async def _save():
            db = DatabaseManager(self.config)
            await db.initialize()
            try:
                today = date.today()
                
                # 安全检查：记录当前操作信息
                logger.info(f"🔄 开始保存分析数据:")
                logger.info(f"   销售人员ID: {salesperson_id}")
                logger.info(f"   上传日期: {today}")
                logger.info(f"   通话数量: {len(call_details_list)}")
                logger.info(f"   操作模式: {upload_choice}")
                
                # 使用局部变量来避免重新赋值问题
                current_upload_choice = upload_choice
                
                # 查询当前数据库中的记录数量（用于对比）
                async with db.acquire() as conn:
                    total_records_before = await conn.fetchval("SELECT COUNT(*) FROM daily_call_records")
                    total_details_before = await conn.fetchval("SELECT COUNT(*) FROM call_details")
                    logger.info(f"📊 操作前数据库状态:")
                    logger.info(f"   每日记录总数: {total_records_before}")
                    logger.info(f"   通话详情总数: {total_details_before}")
                
                # 处理现有记录
                existing_record = await db.get_daily_record(salesperson_id, today)
                if current_upload_choice == "overwrite" and existing_record:
                    # 安全检查：确认只删除指定销售人员当天的记录
                    logger.warning(f"⚠️  准备删除销售人员 {salesperson_id} 在 {today} 的现有记录")
                    logger.warning(f"   即将删除的记录ID: {existing_record['id']}")
                    
                    # 查询将要删除的详情数量
                    async with db.acquire() as conn:
                        details_to_delete = await conn.fetchval(
                            "SELECT COUNT(*) FROM call_details WHERE daily_record_id = $1",
                            existing_record['id']
                        )
                    logger.warning(f"   将删除 {details_to_delete} 条通话详情")
                    
                    # 执行删除操作
                    await db.delete_daily_record_and_details(existing_record['id'])
                    
                    # 验证删除后的状态
                    async with db.acquire() as conn:
                        total_records_after_delete = await conn.fetchval("SELECT COUNT(*) FROM daily_call_records")
                        total_details_after_delete = await conn.fetchval("SELECT COUNT(*) FROM call_details")
                        logger.info(f"✅ 删除后数据库状态:")
                        logger.info(f"   每日记录总数: {total_records_after_delete} (减少: {total_records_before - total_records_after_delete})")
                        logger.info(f"   通话详情总数: {total_details_after_delete} (减少: {total_details_before - total_details_after_delete})")
                    
                    # 安全检查：确认删除的数量合理
                    if (total_records_before - total_records_after_delete) > 1:
                        logger.error(f"❌ 异常：删除了超过1条每日记录！")
                        raise Exception("删除操作异常：删除的记录数量超出预期")
                    
                    existing_record = None  # 重置现有记录状态
                
                # 获取或创建日常记录
                if existing_record and current_upload_choice == "append":
                    daily_record_id = existing_record['id']
                    logger.info(f"📝 使用现有记录 (追加模式): ID {daily_record_id}")
                elif existing_record and current_upload_choice is None:
                    # 如果存在记录但没有指定操作模式，默认使用追加模式
                    daily_record_id = existing_record['id']
                    logger.info(f"📝 使用现有记录 (默认追加模式): ID {daily_record_id}")
                    current_upload_choice = "append"  # 设置为追加模式以便后续逻辑处理
                else:
                    # 创建新记录（没有现有记录或覆盖模式删除后）
                    daily_record_id = await db.create_daily_record(salesperson_id, today)
                    logger.info(f"📝 创建新记录: ID {daily_record_id}")
                    # 如果是新创建的记录，重新获取完整信息以便后续使用
                    if current_upload_choice == "append":
                        # 追加模式但没有现有记录的情况不应该发生，记录警告
                        logger.warning("⚠️  追加模式但没有找到现有记录，创建了新记录")
                        existing_record = None
                
                # 准备批量插入的数据
                total_calls = len(call_details_list)
                effective_calls = sum(1 for detail in call_details_list if detail.get('is_effective', False))
                scores = [detail['score'] for detail in call_details_list if detail.get('score') is not None]
                
                logger.info(f"📈 统计信息:")
                logger.info(f"   总通话数: {total_calls}")
                logger.info(f"   有效通话数: {effective_calls}")
                logger.info(f"   有评分通话数: {len(scores)}")
                
                # 转换数据格式（JSON序列化）
                for detail in call_details_list:
                    # 移除错误的score字段序列化，score是数值字段
                    pass
                
                # 批量插入通话详情
                if call_details_list:
                    await db.batch_insert_call_details(
                        daily_record_id,
                        salesperson_id,
                        call_details_list
                    )
                    logger.info(f"✅ 成功插入 {len(call_details_list)} 条通话详情")
                
                # 计算平均分
                average_score = sum(scores) / len(scores) if scores else None
                logger.info(f"📊 平均评分: {average_score:.2f}" if average_score else "📊 平均评分: 无")
                
                # 从汇总分析中提取改进建议
                from extract_utils import extract_all_summary_data
                summary_data = extract_all_summary_data(summary_analysis)
                improvement_suggestions = "\n".join(summary_data["improvement_measures"]) if summary_data["improvement_measures"] else None
                
                # 如果是追加模式，需要合并统计数据
                if existing_record and current_upload_choice == "append":
                    logger.info(f"🔄 追加模式：合并统计数据")
                    logger.info(f"   existing_record ID: {existing_record.get('id')}")
                    logger.info(f"   daily_record_id: {daily_record_id}")
                    
                    old_total = existing_record.get('total_calls', 0)
                    old_effective = existing_record.get('effective_calls', 0)
                    old_avg = existing_record.get('average_score')
                    
                    logger.info(f"   原有数据: {old_total} 通话, {old_effective} 有效, 平均分 {old_avg}")
                    logger.info(f"   新增数据: {len(call_details_list)} 通话, {effective_calls} 有效")
                    
                    # 合并统计数据
                    total_calls += old_total
                    effective_calls += old_effective
                    
                    logger.info(f"   合并后: {total_calls} 通话, {effective_calls} 有效")
                    
                    # 重新计算平均分
                    if old_avg and average_score:
                        old_avg_float = float(old_avg)
                        old_count = old_total
                        new_count = len(call_details_list)
                        if old_count + new_count > 0:
                            # 计算加权平均分
                            weighted_avg = (old_avg_float * old_count + average_score * new_count) / (old_count + new_count)
                            logger.info(f"   原平均分: {old_avg_float:.2f} (基于 {old_count} 个通话)")
                            logger.info(f"   新平均分: {average_score:.2f} (基于 {new_count} 个通话)")
                            logger.info(f"   合并后平均分: {weighted_avg:.2f}")
                            average_score = weighted_avg
                else:
                    logger.info(f"📝 非追加模式或无现有记录:")
                    logger.info(f"   upload_choice: {current_upload_choice}")
                    logger.info(f"   existing_record: {'存在' if existing_record else '不存在'}")
                
                # 确定是否需要合并分析结果
                should_merge_analysis = (current_upload_choice == "append" and existing_record is not None)
                logger.info(f"📊 分析结果合并设置: {should_merge_analysis}")
                
                # 更新日常记录统计信息
                await db.update_daily_record_stats(
                    daily_record_id,
                    total_calls,
                    effective_calls,
                    average_score,
                    summary_analysis,
                    improvement_suggestions,
                    merge_analysis=should_merge_analysis
                )
                
                # 最终验证：检查保存后的状态
                async with db.acquire() as conn:
                    total_records_final = await conn.fetchval("SELECT COUNT(*) FROM daily_call_records")
                    total_details_final = await conn.fetchval("SELECT COUNT(*) FROM call_details")
                    logger.info(f"🎉 最终数据库状态:")
                    logger.info(f"   每日记录总数: {total_records_final}")
                    logger.info(f"   通话详情总数: {total_details_final}")
                
                logger.info(f"✅ 成功保存分析结果到数据库：{total_calls} 个通话，{effective_calls} 个有效通话")
                return True
                
            except Exception as e:
                logger.error(f"❌ 保存数据时出错: {str(e)}")
                import traceback
                traceback.print_exc()
                return False
            finally:
                await db.close()
        
        return self._run_async(_save()) 