"""
数据库操作工具模块
提供通话分析系统的所有数据库操作接口
"""
import asyncio
import json
from datetime import datetime, date
from typing import List, Dict, Optional, Tuple, Any, Callable, Awaitable
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
            server_settings = {
                'timezone': 'Asia/Shanghai',  # 设置服务器时区
                'jit': 'off',
                'application_name': 'call_analysis_app'
            }
            server_settings.update(self.config.get('connect_args', {}).get('server_settings', {}))

            # 连接参数，添加时区设置
            connect_kwargs = {
                'host': self.config['host'],
                'port': self.config['port'],
                'database': self.config['database'],
                'user': self.config['username'],
                'password': self.config['password'],
                'server_settings': server_settings,
                **self.config.get('pool_config', {})
            }

            ssl_config = self.config.get('ssl_config', {})
            if 'ssl' in ssl_config:
                connect_kwargs['ssl'] = ssl_config['ssl']
            
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
        
        # 类型断言：确保 _pool 不为 None
        assert self._pool is not None, "Database pool should be initialized"
        
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
        创建新的日常记录（安全创建，防止重复）
        
        Args:
            salesperson_id: 销售人员ID
            upload_date: 上传日期
            
        Returns:
            新创建的记录ID或现有记录ID
        """
        async with self.acquire() as conn:
            # 先尝试获取现有记录，避免违反UNIQUE约束
            existing_record = await conn.fetchrow(
                """
                SELECT id FROM daily_call_records 
                WHERE salesperson_id = $1 AND upload_date = $2
                """,
                salesperson_id, upload_date
            )
            
            if existing_record:
                logger.warning(f"⚠️ 日常记录已存在: 销售人员ID {salesperson_id}, 日期 {upload_date}, 记录ID {existing_record['id']}")
                return existing_record['id']
            
            # 直接插入新记录（销售人员可以一天上传多次）
            row = await conn.fetchrow(
                """
                INSERT INTO daily_call_records 
                (salesperson_id, upload_date, total_calls, effective_calls, created_at)
                VALUES ($1, $2, 0, 0, NOW() AT TIME ZONE 'Asia/Shanghai')
                RETURNING id
                """,
                salesperson_id, upload_date
            )
            
            logger.info(f"📝 安全创建/获取日常记录: 销售人员ID {salesperson_id}, 日期 {upload_date}, 记录ID {row['id']}")
            return row['id']
    
    async def update_daily_record_stats(
        self, 
        daily_record_id: int,
        total_calls: int,
        effective_calls: int,
        average_score: Optional[float],
        summary_analysis: Optional[str],
        improvement_suggestions: Optional[str],
        merge_analysis: bool = False,
        audio_calls: Optional[int] = None,
        audio_effective_calls: Optional[int] = None,
        image_calls: Optional[int] = None,
        image_effective_calls: Optional[int] = None
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
            audio_calls: 音频通话数（可选，如果提供则更新）
            audio_effective_calls: 音频有效通话数（可选，如果提供则更新）
            image_calls: 图片通话数（可选，如果提供则更新）
            image_effective_calls: 图片有效通话数（可选，如果提供则更新）
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
            
            # 构建动态更新SQL，包含分类统计字段
            update_fields = [
                "total_calls = $2",
                "effective_calls = $3", 
                "average_score = $4",
                "summary_analysis = $5",
                "improvement_suggestions = $6",
                "updated_at = CURRENT_TIMESTAMP"
            ]
            update_values = [daily_record_id, total_calls, effective_calls, 
                           average_score, summary_analysis, improvement_suggestions]
            
            param_count = 6
            
            # 如果提供了分类统计数据，也更新这些字段
            if audio_calls is not None:
                param_count += 1
                update_fields.append(f"audio_calls = ${param_count}")
                update_values.append(audio_calls)
                
            if audio_effective_calls is not None:
                param_count += 1
                update_fields.append(f"audio_effective_calls = ${param_count}")
                update_values.append(audio_effective_calls)
                
            if image_calls is not None:
                param_count += 1
                update_fields.append(f"image_calls = ${param_count}")
                update_values.append(image_calls)
                
            if image_effective_calls is not None:
                param_count += 1
                update_fields.append(f"image_effective_calls = ${param_count}")
                update_values.append(image_effective_calls)
            
            # 构建最终SQL
            sql = f"""
                UPDATE daily_call_records 
                SET {', '.join(update_fields)}
                WHERE id = $1
            """
            
            logger.info(f"📊 更新统计数据: 总通话={total_calls}, 有效={effective_calls}, "
                       f"音频={audio_calls}, 音频有效={audio_effective_calls}, "
                       f"图片={image_calls}, 图片有效={image_effective_calls}")
            
            # 执行更新
            await conn.execute(sql, *update_values)
            
            # 验证数据一致性（CHECK约束检查）
            if (audio_calls is not None and image_calls is not None and 
                total_calls != (audio_calls + image_calls)):
                logger.error(f"❌ 数据一致性错误: total_calls({total_calls}) != audio_calls({audio_calls}) + image_calls({image_calls})")
                raise ValueError(f"总通话数不等于分类通话数之和: {total_calls} != {audio_calls} + {image_calls}")
            
            if (audio_effective_calls is not None and image_effective_calls is not None and 
                effective_calls != (audio_effective_calls + image_effective_calls)):
                logger.error(f"❌ 数据一致性错误: effective_calls({effective_calls}) != audio_effective_calls({audio_effective_calls}) + image_effective_calls({image_effective_calls})")
                raise ValueError(f"有效通话数不等于分类有效通话数之和: {effective_calls} != {audio_effective_calls} + {image_effective_calls}")
            
            logger.info("✅ 统计数据更新成功，数据一致性验证通过")
    
    async def update_image_call_statistics(
        self,
        daily_record_id: int,
        image_calls: int,
        image_effective_calls: int,
        reset_image_data: bool = False
    ):
        """
        更新日常记录中的图片通话统计数据
        
        Args:
            daily_record_id: 日常记录ID
            image_calls: 新增图片通话数
            image_effective_calls: 新增图片有效通话数
            reset_image_data: 是否重置图片数据（覆盖模式）
        """
        async with self.acquire() as conn:
            # 🔧 临时修复：检查image_calls字段是否存在
            image_fields_exist = await conn.fetchval("""
                SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name = 'daily_call_records' 
                AND column_name = 'image_calls'
                AND table_schema = 'public'
            """)
            
            if image_fields_exist > 0:
                # 原始逻辑：使用专门的图片字段
                if reset_image_data:
                    # 覆盖模式：直接设置为新值
                    await conn.execute(
                        """
                        UPDATE daily_call_records 
                        SET image_calls = $2,
                            image_effective_calls = $3,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE id = $1
                        """,
                        daily_record_id, image_calls, image_effective_calls
                    )
                    logger.info(f"📊 重置图片统计: 记录ID {daily_record_id}, 图片通话 {image_calls}, 有效 {image_effective_calls}")
                else:
                    # 追加模式：累加现有值
                    await conn.execute(
                        """
                        UPDATE daily_call_records 
                        SET image_calls = COALESCE(image_calls, 0) + $2,
                            image_effective_calls = COALESCE(image_effective_calls, 0) + $3,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE id = $1
                        """,
                        daily_record_id, image_calls, image_effective_calls
                    )
                    logger.info(f"📊 累加图片统计: 记录ID {daily_record_id}, 新增图片通话 {image_calls}, 新增有效 {image_effective_calls}")
                
                # 手动更新总计字段（以防触发器不工作）
                await conn.execute(
                    """
                    UPDATE daily_call_records 
                    SET total_calls = COALESCE(audio_calls, 0) + COALESCE(image_calls, 0),
                        effective_calls = COALESCE(audio_effective_calls, 0) + COALESCE(image_effective_calls, 0),
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = $1
                    """,
                    daily_record_id
                )
                logger.info(f"📊 手动更新总计字段完成")
            else:
                # 🚨 回退逻辑：图片字段不存在，直接更新总字段
                logger.warning(f"⚠️ 图片统计字段不存在，使用回退逻辑更新总计字段")
                
                if reset_image_data:
                    # 覆盖模式：直接设置为新值（这在回退模式下不安全，改为追加）
                    logger.warning(f"⚠️ 回退模式下不支持覆盖，改为追加模式")
                    await conn.execute(
                        """
                        UPDATE daily_call_records 
                        SET total_calls = COALESCE(total_calls, 0) + $2,
                            effective_calls = COALESCE(effective_calls, 0) + $3,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE id = $1
                        """,
                        daily_record_id, image_calls, image_effective_calls
                    )
                else:
                    # 追加模式：直接累加到总字段
                    await conn.execute(
                        """
                        UPDATE daily_call_records 
                        SET total_calls = COALESCE(total_calls, 0) + $2,
                            effective_calls = COALESCE(effective_calls, 0) + $3,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE id = $1
                        """,
                        daily_record_id, image_calls, image_effective_calls
                    )
                
                logger.info(f"📊 回退模式：累加到总计: 记录ID {daily_record_id}, 新增通话 {image_calls}, 新增有效 {image_effective_calls}")
    
    async def insert_call_detail(
        self,
        daily_record_id: int,
        salesperson_id: int,
        call_data: Dict[str, Any],
        record_type: str = 'audio'
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
            record_type: 记录类型，'audio' 或 'image'，默认 'audio'
        """
        async with self.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO call_details (
                    daily_record_id, salesperson_id, original_filename,
                    company_name, contact_person, phone_number,
                    conversation_text, analysis_text, 
                    score, is_effective, suggestions, record_type,
                    created_at
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, NOW() AT TIME ZONE 'Asia/Shanghai')
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
                call_data.get('suggestions'),
                record_type
            )
    
    async def batch_insert_call_details(
        self,
        daily_record_id: int,
        salesperson_id: int,
        call_data_list: List[Dict[str, Any]],
        record_type: str = 'audio'
    ):
        """
        批量插入通话详情记录
        
        Args:
            daily_record_id: 日常记录ID
            salesperson_id: 销售人员ID
            call_data_list: 通话数据列表
            record_type: 记录类型，'audio' 或 'image'，默认 'audio'
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
                    call_data.get('suggestions'),
                    record_type
                ))
            
            # 执行批量插入
            await conn.executemany(
                """
                INSERT INTO call_details (
                    daily_record_id, salesperson_id, original_filename,
                    company_name, contact_person, phone_number,
                    conversation_text, analysis_text, 
                    score, is_effective, suggestions, record_type,
                    created_at
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, NOW() AT TIME ZONE 'Asia/Shanghai')
                """,
                values
            )
            logger.info(f"批量插入了 {len(values)} 条 {record_type} 类型的通话详情记录")
    
    async def check_duplicate_filenames(
        self, 
        salesperson_id: int, 
        filenames: List[str],
        days_back: int = 30
    ) -> Dict[str, Any]:
        """
        检测重复文件名（完全匹配）
        
        Args:
            salesperson_id: 销售人员ID
            filenames: 要检测的文件名列表
            days_back: 检测最近多少天的记录，默认30天
            
        Returns:
            检测结果字典：
            {
                "duplicates": [
                    {
                        "filename": "文件名.mp3",
                        "last_upload_date": "2024-01-15",
                        "days_ago": 3
                    }
                ],
                "new_files": ["新文件1.mp3", "新文件2.aac"]
            }
        """
        async with self.acquire() as conn:
            if not filenames:
                return {"duplicates": [], "new_files": []}
            
            # 查询该销售员最近指定天数内的所有文件名
            existing_files = await conn.fetch(
                """
                SELECT original_filename, created_at::date as upload_date
                FROM call_details 
                WHERE salesperson_id = $1 
                AND original_filename = ANY($2)
                AND created_at >= NOW() - INTERVAL '%s days'
                ORDER BY created_at DESC
                """ % days_back,
                salesperson_id, filenames
            )
            
            # 构建现有文件名的字典，键为文件名，值为上传日期
            existing_files_dict = {}
            for existing_file in existing_files:
                filename = existing_file['original_filename']
                upload_date = existing_file['upload_date']
                # 如果同一文件名有多次上传，保留最近的一次
                if filename not in existing_files_dict or upload_date > existing_files_dict[filename]:
                    existing_files_dict[filename] = upload_date
            
            # 分类文件：重复 vs 新文件
            duplicates = []
            new_files = []
            
            today = date.today()
            
            for filename in filenames:
                if filename in existing_files_dict:
                    last_upload_date = existing_files_dict[filename]
                    days_ago = (today - last_upload_date).days
                    duplicates.append({
                        "filename": filename,
                        "last_upload_date": last_upload_date.strftime("%Y-%m-%d"),
                        "days_ago": days_ago
                    })
                else:
                    new_files.append(filename)
            
            logger.info(f"🔍 文件重复检测完成 - 销售员ID: {salesperson_id}")
            logger.info(f"   检测范围: 最近 {days_back} 天")
            logger.info(f"   总文件数: {len(filenames)}")
            logger.info(f"   重复文件: {len(duplicates)} 个")
            logger.info(f"   新文件: {len(new_files)} 个")
            
            return {
                "duplicates": duplicates,
                "new_files": new_files
            }

    async def get_recent_call_records(
        self, 
        salesperson_id: int, 
        days_back: int = 30,
        record_type: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        获取最近的通话记录（用于智能去重比较）
        
        Args:
            salesperson_id: 销售人员ID
            days_back: 获取最近多少天的记录，默认30天
            record_type: 记录类型筛选 ('audio', 'image', None表示全部)
            
        Returns:
            通话记录列表，包含以下字段：
            - id: 记录ID
            - original_filename: 文件名
            - company_name: 公司名称
            - contact_person: 联系人
            - phone_number: 电话号码
            - conversation_text: 通话时间信息
            - analysis_text: 通话统计信息
            - is_effective: 是否有效通话
            - created_at: 创建时间
        """
        async with self.acquire() as conn:
            # 构建查询条件
            query_conditions = [
                "salesperson_id = $1",
                "created_at >= NOW() - INTERVAL '%s days'" % days_back
            ]
            
            # 添加记录类型筛选
            if record_type:
                query_conditions.append("record_type = $2")
            
            # 构建查询SQL
            query = f"""
                SELECT 
                    id,
                    original_filename,
                    company_name,
                    contact_person,
                    phone_number,
                    conversation_text,
                    analysis_text,
                    is_effective,
                    created_at,
                    record_type
                FROM call_details 
                WHERE {' AND '.join(query_conditions)}
                ORDER BY created_at DESC
            """
            
            # 执行查询
            if record_type:
                records = await conn.fetch(query, salesperson_id, record_type)
            else:
                records = await conn.fetch(query, salesperson_id)
            
            # 转换为字典列表
            call_records = []
            for record in records:
                call_records.append({
                    'id': record['id'],
                    'original_filename': record['original_filename'],
                    'company_name': record['company_name'],
                    'contact_person': record['contact_person'], 
                    'phone_number': record['phone_number'],
                    'conversation_text': record['conversation_text'],
                    'analysis_text': record['analysis_text'],
                    'is_effective': record['is_effective'],
                    'created_at': record['created_at'],
                    'record_type': record['record_type']
                })
            
            logger.info(f"🔍 获取最近通话记录 - 销售员ID: {salesperson_id}")
            logger.info(f"   查询范围: 最近 {days_back} 天")
            logger.info(f"   记录类型: {record_type or '全部'}")
            logger.info(f"   获取记录数: {len(call_records)}")
            
            return call_records


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
        
    def _run_async(self, coro_factory: Callable[[], Awaitable[Any]]):
        """在新的事件循环中运行异步代码（带重试机制）"""
        import asyncio
        import time
        
        # 重试配置
        max_retries = 3
        retry_delay = 2  # 秒
        
        for attempt in range(max_retries):
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    return loop.run_until_complete(coro_factory())
                finally:
                    loop.close()
                    asyncio.set_event_loop(None)
            except Exception as e:
                if attempt < max_retries - 1:
                    logger.warning(f"连接失败 (尝试 {attempt + 1}/{max_retries}): {e}")
                    logger.info(f"等待 {retry_delay} 秒后重试...")
                    time.sleep(retry_delay)
                else:
                    logger.error(f"连接失败，已达最大重试次数: {e}")
                    raise
    
    def get_salespersons(self) -> List[Dict[str, Any]]:
        """同步获取销售人员列表"""
        async def _get():
            db = DatabaseManager(self.config)
            await db.initialize()
            try:
                return await db.get_salespersons()
            finally:
                await db.close()
        
        return self._run_async(_get)
    
    def check_daily_record_exists(self, salesperson_id: int, upload_date: date) -> bool:
        """同步检查记录是否存在"""
        async def _check():
            db = DatabaseManager(self.config)
            await db.initialize()
            try:
                return await db.check_daily_record_exists(salesperson_id, upload_date)
            finally:
                await db.close()
        
        return self._run_async(_check)
    
    def check_duplicate_filenames(
        self, 
        salesperson_id: int, 
        filenames: List[str],
        days_back: int = 30
    ) -> Dict[str, Any]:
        """同步检测重复文件名"""
        async def _check():
            db = DatabaseManager(self.config)
            await db.initialize()
            try:
                return await db.check_duplicate_filenames(salesperson_id, filenames, days_back)
            finally:
                await db.close()
        
        return self._run_async(_check)
    
    def get_recent_call_records(
        self, 
        salesperson_id: int, 
        days_back: int = 30,
        record_type: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """同步获取最近的通话记录"""
        async def _get():
            db = DatabaseManager(self.config)
            await db.initialize()
            try:
                return await db.get_recent_call_records(salesperson_id, days_back, record_type)
            finally:
                await db.close()
        
        return self._run_async(_get)
    
    def save_analysis_data(
        self,
        salesperson_id: int,
        call_details_list: List[Dict[str, Any]],
        summary_analysis: str,
        upload_choice: Optional[str] = None
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
                
                # 更新日常记录统计信息（音频处理）
                if current_upload_choice == "append" and existing_record:
                    # 追加模式：只传递总计数据，让方法自己处理分类统计的增量
                    await db.update_daily_record_stats(
                        daily_record_id,
                        total_calls,
                        effective_calls,
                        average_score,
                        summary_analysis,
                        improvement_suggestions,
                        merge_analysis=should_merge_analysis
                    )
                    # 追加模式下单独更新音频统计字段
                    async with db.acquire() as conn:
                        await conn.execute(
                            """
                            UPDATE daily_call_records 
                            SET audio_calls = COALESCE(audio_calls, 0) + $2,
                                audio_effective_calls = COALESCE(audio_effective_calls, 0) + $3,
                                updated_at = CURRENT_TIMESTAMP
                            WHERE id = $1
                            """,
                            daily_record_id, len(call_details_list), effective_calls - old_effective
                        )
                        logger.info(f"📊 追加模式：更新音频统计 +{len(call_details_list)} 通话, +{effective_calls - old_effective} 有效")
                else:
                    # 新记录或覆盖模式：直接设置分类统计字段
                    await db.update_daily_record_stats(
                        daily_record_id,
                        total_calls,
                        effective_calls,
                        average_score,
                        summary_analysis,
                        improvement_suggestions,
                        merge_analysis=should_merge_analysis,
                        audio_calls=len(call_details_list),  # 音频通话数等于详情列表长度
                        audio_effective_calls=effective_calls,  # 音频有效通话数
                        image_calls=0,  # 音频处理时图片通话为0
                        image_effective_calls=0  # 音频处理时图片有效通话为0
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
        
        return self._run_async(_save)
    
    def save_image_analysis_data(
        self,
        salesperson_id: int,
        processing_results: Dict[str, Any],
        upload_choice: Optional[str] = None
    ) -> bool:
        """
        同步保存图片识别分析数据到call_details表
        
        Args:
            salesperson_id: 销售人员ID
            processing_results: 图片处理结果，包含：
                - call_details_list: call_details格式的通话数据列表
                - total_images_processed: 处理的图片数量
                - total_calls_found: 发现的总通话数
                - total_effective_calls: 发现的有效通话数
                - processing_errors: 处理错误列表
            upload_choice: 上传选择 ('overwrite', 'append', None)
            
        Returns:
            bool: 保存是否成功
        """
        async def _save():
            db = DatabaseManager(self.config)
            await db.initialize()
            try:
                today = date.today()
                
                logger.info(f"🖼️ 开始保存图片识别数据:")
                logger.info(f"   销售人员ID: {salesperson_id}")
                logger.info(f"   上传日期: {today}")
                logger.info(f"   处理图片数: {processing_results.get('total_images_processed', 0)}")
                logger.info(f"   发现通话数: {processing_results.get('total_calls_found', 0)}")
                logger.info(f"   有效通话数: {processing_results.get('total_effective_calls', 0)}")
                logger.info(f"   操作模式: {upload_choice}")
                
                # 使用局部变量来避免重新赋值问题
                current_upload_choice = upload_choice
                
                # 获取 call_details 格式的数据
                call_details_list = processing_results.get("call_details_list", [])
                
                if not call_details_list:
                    logger.info("📊 没有发现有效的通话记录")
                    return True
                
                # 📌 参考录音板块逻辑：处理现有记录
                existing_record = await db.get_daily_record(salesperson_id, today)
                
                # 处理覆盖模式
                if current_upload_choice == "overwrite" and existing_record:
                    logger.warning(f"⚠️ 覆盖模式：准备删除销售人员 {salesperson_id} 在 {today} 的现有记录")
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
                    existing_record = None  # 重置现有记录状态
                
                # 获取或创建日常记录
                if existing_record and current_upload_choice == "append":
                    daily_record_id = existing_record['id']
                    logger.info(f"📝 使用现有记录 (追加模式): ID {daily_record_id}")
                elif existing_record and current_upload_choice is None:
                    # 如果存在记录但没有指定操作模式，默认使用追加模式
                    daily_record_id = existing_record['id']
                    logger.info(f"📝 使用现有记录 (默认追加模式): ID {daily_record_id}")
                    current_upload_choice = "append"  # 设置为追加模式
                else:
                    # 创建新记录（没有现有记录或覆盖模式删除后）
                    daily_record_id = await db.create_daily_record(salesperson_id, today)
                    logger.info(f"📝 创建新记录: ID {daily_record_id}")
                
                # 准备统计数据
                total_calls = len(call_details_list)
                effective_calls = sum(1 for detail in call_details_list if detail.get('is_effective', False))
                
                logger.info(f"📈 图片识别统计信息:")
                logger.info(f"   总通话数: {total_calls}")
                logger.info(f"   有效通话数: {effective_calls}")
                logger.info(f"   图片识别不使用评分字段")
                
                # 批量插入通话详情到call_details表
                if call_details_list:
                    await db.batch_insert_call_details(
                        daily_record_id,
                        salesperson_id,
                        call_details_list,
                        record_type='image'  # 标记为图片类型
                    )
                    logger.info(f"✅ 成功插入 {len(call_details_list)} 条图片通话详情")
                
                # 图片识别不计算平均分
                average_score = None
                logger.info(f"📊 图片识别模式：不使用评分字段")
                
                # 生成简单的汇总分析
                summary_analysis = generate_image_summary_analysis(call_details_list, processing_results)
                improvement_suggestions = None  # 图片识别暂不生成改进建议
                
                # 如果是追加模式，需要合并统计数据
                old_effective = 0  # 初始化变量（用于后续计算增量）
                if existing_record and current_upload_choice == "append":
                    logger.info(f"🔄 追加模式：合并统计数据")
                    
                    old_total = existing_record.get('total_calls', 0)
                    old_effective = existing_record.get('effective_calls', 0)
                    old_avg = existing_record.get('average_score')
                    
                    logger.info(f"   原有数据: {old_total} 通话, {old_effective} 有效, 平均分 {old_avg}")
                    logger.info(f"   新增数据: {total_calls} 通话, {effective_calls} 有效")
                    
                    # 合并统计数据
                    total_calls += old_total
                    effective_calls += old_effective
                    
                    logger.info(f"   合并后: {total_calls} 通话, {effective_calls} 有效")
                    
                    # 图片识别不重新计算平均分（保持原有的平均分）
                    if old_avg:
                        logger.info(f"   保持原有平均分: {old_avg} (图片识别不影响平均分计算)")
                        average_score = old_avg
                    else:
                        logger.info(f"   图片识别模式：不计算平均分")
                        average_score = None
                
                # 确定是否需要合并分析结果
                should_merge_analysis = (current_upload_choice == "append" and existing_record is not None)
                logger.info(f"📊 分析结果合并设置: {should_merge_analysis}")
                
                # 更新日常记录统计信息（图片处理）
                if current_upload_choice == "append" and existing_record:
                    # 追加模式：只传递总计数据，让方法自己处理分类统计的增量
                    await db.update_daily_record_stats(
                        daily_record_id,
                        total_calls,
                        effective_calls,
                        average_score,
                        summary_analysis,
                        improvement_suggestions,
                        merge_analysis=should_merge_analysis
                    )
                    # 追加模式下单独更新图片统计字段
                    async with db.acquire() as conn:
                        await conn.execute(
                            """
                            UPDATE daily_call_records 
                            SET image_calls = COALESCE(image_calls, 0) + $2,
                                image_effective_calls = COALESCE(image_effective_calls, 0) + $3,
                                updated_at = CURRENT_TIMESTAMP
                            WHERE id = $1
                            """,
                            daily_record_id, len(call_details_list), effective_calls - old_effective
                        )
                        logger.info(f"📊 追加模式：更新图片统计 +{len(call_details_list)} 通话, +{effective_calls - old_effective} 有效")
                else:
                    # 新记录或覆盖模式：直接设置分类统计字段
                    await db.update_daily_record_stats(
                        daily_record_id,
                        total_calls,
                        effective_calls,
                        average_score,
                        summary_analysis,
                        improvement_suggestions,
                        merge_analysis=should_merge_analysis,
                        audio_calls=0,  # 图片处理时音频通话为0
                        audio_effective_calls=0,  # 图片处理时音频有效通话为0
                        image_calls=len(call_details_list),  # 图片通话数等于详情列表长度
                        image_effective_calls=effective_calls  # 图片有效通话数
                    )
                
                # 处理错误信息记录
                errors = processing_results.get("processing_errors", [])
                if errors:
                    logger.warning(f"⚠️ 有 {len(errors)} 张图片处理失败:")
                    for error in errors:
                        logger.warning(f"   - {error.get('filename', 'Unknown')}: {error.get('error', 'Unknown error')}")
                
                logger.info(f"✅ 图片识别数据保存完成：{total_calls} 个通话，{effective_calls} 个有效通话")
                return True
                
            except Exception as e:
                logger.error(f"❌ 保存图片识别数据时出错: {str(e)}")
                import traceback
                traceback.print_exc()
                return False
            finally:
                await db.close()
        
        return self._run_async(_save)

def generate_image_summary_analysis(call_details_list: List[Dict[str, Any]], processing_results: Dict[str, Any]) -> str:
    """
    生成图片识别的汇总分析报告
    
    Args:
        call_details_list: 通话详情列表
        processing_results: 处理结果
        
    Returns:
        汇总分析文本
    """
    total_calls = len(call_details_list)
    effective_calls = sum(1 for detail in call_details_list if detail.get('is_effective', False))
    total_images = processing_results.get('total_images_processed', 0)
    
    # 统计公司信息
    companies = set()
    contacts = set()
    
    for detail in call_details_list:
        if detail.get('company_name'):
            companies.add(detail['company_name'])
        if detail.get('contact_person'):
            contacts.add(detail['contact_person'])
    
    # 图片识别不使用score字段，从analysis_text中提取时长信息
    avg_duration = 0  # 图片识别模式暂不计算平均时长
    
    summary = f"""### 📸 图片识别汇总分析报告

**基本统计：**
- 处理图片数量：{total_images} 张
- 识别通话记录：{total_calls} 个
- 有效通话（≥60秒）：{effective_calls} 个
- 有效通话率：{(effective_calls/total_calls*100):.1f}%" if total_calls > 0 else "无通话记录"

**业务范围：**
- 涉及公司数量：{len(companies)} 家
- 联系人数量：{len(contacts)} 人
- 通话时长统计：详见通话详情中的analysis_text字段

**识别的公司列表：**
{chr(10).join(f"- {company}" for company in sorted(companies)) if companies else "- 无明确公司信息"}

**备注：** 本分析基于微信通话截图识别，数据可能存在识别误差，建议核实重要信息。
"""
    
    return summary 
