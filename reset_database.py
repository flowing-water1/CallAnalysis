#!/usr/bin/env python3
"""
数据库重置脚本
删除现有表并重新创建，确保与最新设计完全一致
同时支持添加新的销售人员
"""

import asyncio
import asyncpg
import logging
from typing import List, Optional
from config import DATABASE_CONFIG

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 真实销售人员名单
REAL_SALESPERSONS = [
    "陈健泉",
    "冯勃桦", 
    "黄威霖",
    "李立颖",
    "唐晓杰",
    "吴嘉嘉"
]


async def get_db_connection() -> asyncpg.Connection:
    """创建数据库连接"""
    conn = await asyncpg.connect(
        host=DATABASE_CONFIG['host'],
        port=DATABASE_CONFIG['port'],
        user=DATABASE_CONFIG['username'],
        password=DATABASE_CONFIG['password'],
        database=DATABASE_CONFIG['database']
    )
    # 设置时区
    await conn.execute("SET timezone = 'Asia/Shanghai'")
    return conn


async def insert_real_salespersons(conn: asyncpg.Connection) -> None:
    """插入真实的销售人员数据"""
    logger.info("正在插入真实销售人员数据...")
    
    for name in REAL_SALESPERSONS:
        try:
            await conn.execute(
                "INSERT INTO salespersons (name) VALUES ($1) ON CONFLICT (name) DO NOTHING",
                name
            )
            logger.info(f"  ✅ 添加销售人员：{name}")
        except Exception as e:
            logger.error(f"  ❌ 添加销售人员 {name} 失败：{str(e)}")
    
    # 验证插入结果
    count = await conn.fetchval("SELECT COUNT(*) FROM salespersons")
    logger.info(f"销售人员总数：{count}")
    
    # 显示所有销售人员
    salespersons = await conn.fetch("SELECT id, name, created_at FROM salespersons ORDER BY id")
    logger.info("当前销售人员列表：")
    for sp in salespersons:
        logger.info(f"  ID: {sp['id']}, 姓名: {sp['name']}, 创建时间: {sp['created_at']}")


async def reset_database():
    """重置数据库：删除所有表并重新创建"""
    try:
        # 连接数据库
        logger.info("正在连接数据库...")
        conn = await get_db_connection()
        logger.info("数据库连接成功")
        
        # 删除现有表（按依赖顺序）
        logger.info("正在删除现有表...")
        await conn.execute("DROP TABLE IF EXISTS call_details CASCADE")
        await conn.execute("DROP TABLE IF EXISTS daily_call_records CASCADE")
        await conn.execute("DROP TABLE IF EXISTS salespersons CASCADE")
        logger.info("现有表已删除")
        
        # 删除可能存在的触发器函数
        await conn.execute("DROP FUNCTION IF EXISTS update_updated_at_column() CASCADE")
        await conn.execute("DROP FUNCTION IF EXISTS update_salesperson_activity() CASCADE")
        logger.info("触发器函数已删除")
        
        # 读取初始化脚本
        logger.info("正在读取初始化脚本...")
        with open('init_database.sql', 'r', encoding='utf-8') as f:
            init_sql = f.read()
        
        # 移除初始化脚本中的测试数据插入语句
        # 我们将使用真实的销售人员数据
        lines = init_sql.split('\n')
        filtered_lines = []
        skip_insert = False
        
        for line in lines:
            if line.strip().startswith("INSERT INTO salespersons"):
                skip_insert = True
                continue
            elif skip_insert and line.strip().startswith("ON CONFLICT"):
                skip_insert = False
                continue
            elif not skip_insert:
                filtered_lines.append(line)
        
        filtered_sql = '\n'.join(filtered_lines)
        
        # 执行初始化（不包含测试数据）
        logger.info("开始重新创建数据库表...")
        await conn.execute(filtered_sql)
        logger.info("数据库表重新创建完成！")
        
        # 插入真实的销售人员数据
        await insert_real_salespersons(conn)
        
        # 验证表结构
        logger.info("正在验证表结构...")
        
        # 检查 daily_call_records 表结构
        daily_records_columns = await conn.fetch("""
            SELECT column_name, data_type, is_nullable 
            FROM information_schema.columns 
            WHERE table_name = 'daily_call_records' 
            ORDER BY ordinal_position
        """)
        
        logger.info("daily_call_records 表字段：")
        daily_field_names = []
        for col in daily_records_columns:
            daily_field_names.append(col['column_name'])
            logger.info(f"  - {col['column_name']}: {col['data_type']} ({'NULL' if col['is_nullable'] == 'YES' else 'NOT NULL'})")
        
        # 检查 call_details 表结构
        call_details_columns = await conn.fetch("""
            SELECT column_name, data_type, is_nullable 
            FROM information_schema.columns 
            WHERE table_name = 'call_details' 
            ORDER BY ordinal_position
        """)
        
        logger.info("call_details 表字段：")
        call_field_names = []
        for col in call_details_columns:
            call_field_names.append(col['column_name'])
            logger.info(f"  - {col['column_name']}: {col['data_type']} ({'NULL' if col['is_nullable'] == 'YES' else 'NOT NULL'})")
        
        # 验证必需字段是否存在
        required_daily_fields = [
            'id', 'salesperson_id', 'upload_date', 'total_calls', 'effective_calls', 
            'average_score', 'summary_analysis', 'improvement_suggestions', 
            'processed_files', 'created_at', 'updated_at'
        ]
        
        required_call_fields = [
            'id', 'daily_record_id', 'salesperson_id', 'original_filename', 
            'company_name', 'contact_person', 'phone_number', 'score', 
            'is_effective', 'conversation_text', 'analysis_text', 'suggestions', 'created_at'
        ]
        
        missing_daily = [field for field in required_daily_fields if field not in daily_field_names]
        missing_call = [field for field in required_call_fields if field not in call_field_names]
        
        if missing_daily:
            logger.error(f"❌ daily_call_records 表缺少字段：{missing_daily}")
        if missing_call:
            logger.error(f"❌ call_details 表缺少字段：{missing_call}")
        
        if not missing_daily and not missing_call:
            logger.info("✅ 表结构验证成功！所有必需字段都存在。")
        else:
            logger.error("❌ 表结构验证失败！存在缺失字段。")
            raise Exception("表结构验证失败")
        
        # 特别验证 updated_at 字段
        if 'updated_at' in daily_field_names:
            logger.info("✅ updated_at 字段存在，触发器应该能正常工作。")
        else:
            logger.error("❌ 关键字段 updated_at 缺失！")
            raise Exception("关键字段 updated_at 缺失")
        
        # 验证销售人员数据
        salesperson_count = await conn.fetchval("SELECT COUNT(*) FROM salespersons")
        logger.info(f"销售人员数据：{salesperson_count} 条记录")
        
        if salesperson_count == 0:
            logger.warning("⚠️  没有销售人员数据！")
        elif salesperson_count != len(REAL_SALESPERSONS):
            logger.warning(f"⚠️  销售人员数量不匹配，实际：{salesperson_count}，预期：{len(REAL_SALESPERSONS)}。")
        else:
            logger.info(f"✅ 销售人员数据正常：{salesperson_count} 条记录。")
        
        # 验证索引
        indexes = await conn.fetch("""
            SELECT indexname FROM pg_indexes 
            WHERE tablename IN ('salespersons', 'daily_call_records', 'call_details')
            ORDER BY indexname
        """)
        
        logger.info("已创建的索引：")
        for idx in indexes:
            logger.info(f"  - {idx['indexname']}")
        
        # 验证触发器
        triggers = await conn.fetch("""
            SELECT trigger_name, event_manipulation, event_object_table
            FROM information_schema.triggers 
            WHERE event_object_schema = 'public'
            ORDER BY trigger_name
        """)
        
        logger.info("已创建的触发器：")
        for trigger in triggers:
            logger.info(f"  - {trigger['trigger_name']} on {trigger['event_object_table']} ({trigger['event_manipulation']})")
        
        logger.info("✅ 数据库重置完成！表结构验证成功。")
        
    except Exception as e:
        logger.error(f"重置过程中出现错误：{str(e)}")
        raise
    finally:
        if 'conn' in locals():
            await conn.close()
            logger.info("数据库连接已关闭")


async def add_salesperson(name: str) -> bool:
    """添加新的销售人员"""
    try:
        conn = await get_db_connection()
        logger.info(f"正在添加销售人员：{name}")
        
        # 检查是否已存在
        existing = await conn.fetchval(
            "SELECT id FROM salespersons WHERE name = $1", name
        )
        
        if existing:
            logger.warning(f"⚠️  销售人员 '{name}' 已存在（ID: {existing}）")
            return False
        
        # 插入新销售人员
        result = await conn.fetchrow(
            "INSERT INTO salespersons (name) VALUES ($1) RETURNING id, created_at",
            name
        )
        
        logger.info(f"✅ 成功添加销售人员：{name} (ID: {result['id']}, 创建时间: {result['created_at']})")
        return True
        
    except Exception as e:
        logger.error(f"❌ 添加销售人员失败：{str(e)}")
        return False
    finally:
        if 'conn' in locals():
            await conn.close()


async def list_salespersons() -> List[dict]:
    """列出所有销售人员"""
    try:
        conn = await get_db_connection()
        
        salespersons = await conn.fetch("""
            SELECT id, name, created_at, updated_at 
            FROM salespersons 
            ORDER BY id
        """)
        
        return [dict(sp) for sp in salespersons]
        
    except Exception as e:
        logger.error(f"❌ 获取销售人员列表失败：{str(e)}")
        return []
    finally:
        if 'conn' in locals():
            await conn.close()


async def remove_salesperson(name: str) -> bool:
    """删除销售人员（谨慎操作）"""
    try:
        conn = await get_db_connection()
        logger.info(f"正在删除销售人员：{name}")
        
        # 检查是否存在相关数据
        daily_records_count = await conn.fetchval("""
            SELECT COUNT(*) FROM daily_call_records dr 
            JOIN salespersons s ON dr.salesperson_id = s.id 
            WHERE s.name = $1
        """, name)
        
        call_details_count = await conn.fetchval("""
            SELECT COUNT(*) FROM call_details cd 
            JOIN salespersons s ON cd.salesperson_id = s.id 
            WHERE s.name = $1
        """, name)
        
        if daily_records_count > 0 or call_details_count > 0:
            logger.warning(f"⚠️  无法删除销售人员 '{name}'：存在相关数据记录")
            logger.warning(f"     每日记录：{daily_records_count} 条，通话详情：{call_details_count} 条")
            return False
        
        # 删除销售人员
        result = await conn.execute(
            "DELETE FROM salespersons WHERE name = $1", name
        )
        
        if result == "DELETE 0":
            logger.warning(f"⚠️  销售人员 '{name}' 不存在")
            return False
        
        logger.info(f"✅ 成功删除销售人员：{name}")
        return True
        
    except Exception as e:
        logger.error(f"❌ 删除销售人员失败：{str(e)}")
        return False
    finally:
        if 'conn' in locals():
            await conn.close()


def main():
    """主函数"""
    while True:
        print("=" * 60)
        print("通话分析系统 - 数据库管理工具")
        print("=" * 60)
        print()
        print("请选择要执行的操作：")
        print("1. 重置数据库（删除所有数据并重新创建）")
        print("2. 添加新销售人员")
        print("3. 查看所有销售人员")
        print("4. 删除销售人员（谨慎操作）")
        print("0. 退出")
        print()
        
        choice = input("请输入选项 (0-4): ").strip()
        
        if choice == "0":
            print("已退出。")
            break
            
        elif choice == "1":
            print()
            print("⚠️  警告：此操作将删除所有现有数据！")
            print()
            print("此工具将：")
            print("1. 删除所有现有表和数据")
            print("2. 重新创建表结构")
            print("3. 插入真实销售人员数据：")
            for i, name in enumerate(REAL_SALESPERSONS, 1):
                print(f"   {i}. {name}")
            print("4. 创建所有必需的索引")
            print()
            
            # 确认是否继续
            response = input("⚠️  确定要删除所有数据并重置数据库吗？(y/N): ").strip().lower()
            if response not in ['y', 'yes', '是']:
                print("重置已取消。")
                continue
            
            # 二次确认
            response2 = input("🔴 最后确认：这将永久删除所有数据，无法恢复。继续吗？(y/N): ").strip().lower()
            if response2 not in ['y', 'yes', '是']:
                print("重置已取消。")
                continue
            
            try:
                # 运行重置
                asyncio.run(reset_database())
                print()
                print("🎉 数据库重置成功完成！")
                print("现在您可以重新使用通话分析系统了。")
                print()
                print("💡 建议：重启 Streamlit 应用以清除所有缓存。")
            except Exception as e:
                print(f"❌ 重置失败：{str(e)}")
                print("请检查数据库连接配置和权限。")
        
        elif choice == "2":
            print()
            name = input("请输入新销售人员姓名: ").strip()
            if not name:
                print("❌ 姓名不能为空！")
                continue
            
            try:
                success = asyncio.run(add_salesperson(name))
                if success:
                    print(f"✅ 成功添加销售人员：{name}")
                else:
                    print(f"⚠️  添加失败，销售人员 '{name}' 可能已存在")
            except Exception as e:
                print(f"❌ 添加失败：{str(e)}")
        
        elif choice == "3":
            print()
            print("正在获取销售人员列表...")
            try:
                salespersons = asyncio.run(list_salespersons())
                if salespersons:
                    print(f"\n当前共有 {len(salespersons)} 名销售人员：")
                    print("-" * 80)
                    print(f"{'ID':<5} {'姓名':<15} {'创建时间':<20} {'最后更新':<20}")
                    print("-" * 80)
                    for sp in salespersons:
                        print(f"{sp['id']:<5} {sp['name']:<15} {sp['created_at']!s:<20} {sp['updated_at']!s:<20}")
                else:
                    print("❌ 没有找到销售人员数据")
            except Exception as e:
                print(f"❌ 获取失败：{str(e)}")
        
        elif choice == "4":
            print()
            name = input("请输入要删除的销售人员姓名: ").strip()
            if not name:
                print("❌ 姓名不能为空！")
                continue
            
            print(f"⚠️  警告：即将删除销售人员 '{name}'")
            print("注意：如果该销售人员有相关通话记录，将无法删除。")
            
            confirm = input("确定要删除吗？(y/N): ").strip().lower()
            if confirm not in ['y', 'yes', '是']:
                print("删除已取消。")
                continue
            
            try:
                success = asyncio.run(remove_salesperson(name))
                if success:
                    print(f"✅ 成功删除销售人员：{name}")
                else:
                    print(f"⚠️  删除失败")
            except Exception as e:
                print(f"❌ 删除失败：{str(e)}")
        
        else:
            print("❌ 无效选项，请重新选择。")
        
        print()
        input("按回车键继续...")
        print()


if __name__ == "__main__":
    main() 