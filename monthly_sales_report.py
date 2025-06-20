#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
月度销售人员有效通话统计推送脚本
定时任务：每月1号执行，推送上月各销售人员有效通话统计到企业微信群
"""

import requests
import json
import logging
import psycopg2
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any
import os
from dataclasses import dataclass

# 导入配置文件
try:
    from config import DATABASE_CONFIG, WECHAT_WORK_CONFIG, MONTHLY_REPORT_CONFIG
except ImportError:
    print("❌ 无法导入 config.py，请确保 config.py 文件存在")
    exit(1)

# 尝试加载环境变量文件
try:
    from dotenv import load_dotenv
    load_dotenv()  # 加载.env文件中的环境变量
except ImportError:
    pass  # 如果没有安装python-dotenv，跳过


# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('monthly_sales_report.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


@dataclass
class SalesRecord:
    """销售人员记录数据类"""
    salesperson: str
    effective_calls: int
    total_calls: int  # 总通话数
    effective_rate: float  # 有效通话率


class DatabaseManager:
    """数据库管理类"""
    
    def __init__(self, host: str = None, port: int = None, 
                 database: str = None, user: str = None, 
                 password: str = None):
        """
        初始化数据库连接参数
        
        Args:
            host: 数据库主机地址
            port: 数据库端口
            database: 数据库名称
            user: 用户名
            password: 密码
        """
        # 使用config.py中的配置作为默认值，环境变量可以覆盖
        self.connection_params = {
            'host': host or os.getenv('DB_HOST', DATABASE_CONFIG['host']),
            'port': port or int(os.getenv('DB_PORT', DATABASE_CONFIG['port'])),
            'database': database or os.getenv('DB_NAME', DATABASE_CONFIG['database']),
            'user': user or os.getenv('DB_USER', DATABASE_CONFIG['username']),
            'password': password or os.getenv('DB_PASSWORD', DATABASE_CONFIG['password'])
        }
    
    def get_connection(self):
        """获取数据库连接"""
        try:
            conn = psycopg2.connect(**self.connection_params)
            return conn
        except Exception as e:
            logger.error(f"数据库连接失败: {e}")
            raise
    
    def get_monthly_sales_data(self, year: int, month: int) -> List[SalesRecord]:
        """
        获取指定月份的销售人员有效通话统计数据
        
        Args:
            year: 年份
            month: 月份
            
        Returns:
            销售人员记录列表
        """
        conn = None
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            # 构建查询SQL - 统计指定月份每个销售人员的通话数据
            # 需要JOIN salespersons表获取销售人员姓名
            query = """
            SELECT 
                s.name as salesperson_name,
                SUM(dcr.effective_calls) as total_effective_calls,
                SUM(dcr.total_calls) as total_all_calls
            FROM daily_call_records dcr
            JOIN salespersons s ON dcr.salesperson_id = s.id
            WHERE EXTRACT(YEAR FROM dcr.upload_date) = %s 
                AND EXTRACT(MONTH FROM dcr.upload_date) = %s
            GROUP BY s.id, s.name
            ORDER BY s.name
            """
            
            cursor.execute(query, (year, month))
            results = cursor.fetchall()
            
            # 转换为SalesRecord对象列表
            sales_records = []
            for row in results:
                salesperson_name, effective_calls, total_calls = row
                
                # 计算有效率，处理除零情况
                effective_rate = (float(effective_calls) / float(total_calls) * 100) if total_calls and total_calls > 0 else 0.0
                
                sales_records.append(SalesRecord(
                    salesperson=salesperson_name,
                    effective_calls=int(effective_calls) if effective_calls else 0,
                    total_calls=int(total_calls) if total_calls else 0,
                    effective_rate=effective_rate
                ))
            
            logger.info(f"成功获取 {year}年{month}月 销售数据，共 {len(sales_records)} 人")
            return sales_records
            
        except Exception as e:
            logger.error(f"查询销售数据失败: {e}")
            raise
        finally:
            if conn:
                conn.close()


class WeChatWorkBot:
    """企业微信机器人类"""
    
    def __init__(self, webhook_key: str):
        """
        初始化企业微信机器人
        
        Args:
            webhook_key: 企业微信群机器人的webhook key
        """
        self.webhook_key = webhook_key
        self.base_url = f"https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key={webhook_key}"
    
    def send_markdown(self, content: str) -> bool:
        """
        发送Markdown格式消息到企业微信群
        
        Args:
            content: Markdown格式的消息内容
            
        Returns:
            发送是否成功
        """
        headers = {"content-type": "application/json"}
        
        msg = {
            "msgtype": "markdown",
            "markdown": {
                "content": content
            }
        }
        
        try:
            response = requests.post(self.base_url, headers=headers, json=msg, timeout=10)
            response.raise_for_status()
            
            result = response.json()
            if result.get('errcode') == 0:
                logger.info("企业微信消息发送成功")
                return True
            else:
                logger.error(f"企业微信消息发送失败: {result}")
                return False
                
        except Exception as e:
            logger.error(f"发送企业微信消息异常: {e}")
            return False


class SalesReportGenerator:
    """销售报告生成器"""
    
    @staticmethod
    def format_monthly_report(sales_records: List[SalesRecord], year: int, month: int) -> str:
        """
        格式化月度销售报告
        
        Args:
            sales_records: 销售记录列表
            year: 年份
            month: 月份
            
        Returns:
            格式化后的Markdown报告内容
        """
        mode_text = "（测试模式 - 当月数据）" if MONTHLY_REPORT_CONFIG.get('test_mode', False) else ""
        
        if not sales_records:
            return f"## 📊 {year}年{month}月销售人员通话统计{mode_text}\n\n❌ 暂无数据"
        
        # 按有效率排序（降序）
        sales_records_sorted = sorted(sales_records, key=lambda x: x.effective_rate, reverse=True)
        
        # 计算统计数据
        total_effective_calls = sum(record.effective_calls for record in sales_records_sorted)
        total_all_calls = sum(record.total_calls for record in sales_records_sorted)
        effective_rate = (total_effective_calls / total_all_calls * 100) if total_all_calls > 0 else 0
        
        # 构建报告内容
        report = f"## 📊 {year}年{month}月销售人员通话统计{mode_text}\n\n"
        report += f"**📈 总体概况：**\n"
        report += f"- 📞 总通话数：**{total_all_calls:,}** 次\n"
        report += f"- 🎯 有效通话数：**{total_effective_calls:,}** 次\n"
        report += f"- 📊 有效通话率：**{effective_rate:.1f}%**\n\n"
        
        report += f"**销售人员统计：**\n"
        
        # 销售人员列表（前10名，按有效率排序）
        top_performers = sales_records_sorted[:10]
        for i, record in enumerate(top_performers, 1):
            report += f"{i}. **{record.salesperson}**\n"
            report += f"   - 📊 有效率：**{record.effective_rate:.1f}%**\n"
            report += f"   - 📞 总通话：**{record.total_calls:,}** 次\n"
            report += f"   - 🎯 有效通话：**{record.effective_calls:,}** 次\n\n"
        
        # 如果人数超过10人，显示其余人员统计
        if len(sales_records_sorted) > 10:
            remaining_records = sales_records_sorted[10:]
            remaining_total_calls = sum(record.total_calls for record in remaining_records)
            remaining_effective_calls = sum(record.effective_calls for record in remaining_records)
            report += f"**其他 {len(remaining_records)} 位销售人员：**\n"
            report += f"- 📞 合计总通话：**{remaining_total_calls:,}** 次\n"
            report += f"- 🎯 合计有效通话：**{remaining_effective_calls:,}** 次\n\n"
        
        # 添加统计时间
        report += f"---\n"
        report += f"📅 统计时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        
        if MONTHLY_REPORT_CONFIG.get('test_mode', False):
            report += f"\n **当前为测试模式，查询当月数据。生产环境将自动查询上月数据。**"
        
        return report


def main():
    """主函数"""
    try:
        # 根据配置决定查询时间范围
        today = datetime.now()
        
        if MONTHLY_REPORT_CONFIG.get('test_mode', False):
            # 测试模式：查询当月数据
            target_year = today.year
            target_month = today.month
            logger.info(f"🧪 测试模式 - 开始生成 {target_year}年{target_month}月 销售人员通话统计报告")
        else:
            # 生产模式：查询上月数据
            if today.month == 1:
                target_year = today.year - 1
                target_month = 12
            else:
                target_year = today.year
                target_month = today.month - 1
            logger.info(f"📊 生产模式 - 开始生成 {target_year}年{target_month}月 销售人员通话统计报告")
        
        # 使用配置文件中的数据库参数创建数据库管理器
        db_manager = DatabaseManager()
        
        # 获取销售数据
        sales_records = db_manager.get_monthly_sales_data(target_year, target_month)
        
        # 生成报告
        report_content = SalesReportGenerator.format_monthly_report(
            sales_records, target_year, target_month
        )
        
        # 发送到企业微信 - 使用配置文件中的webhook key
        webhook_key = WECHAT_WORK_CONFIG['monthly_report_webhook']
        wechat_bot = WeChatWorkBot(webhook_key)
        
        success = wechat_bot.send_markdown(report_content)
        
        if success:
            logger.info("月度销售报告推送成功")
        else:
            logger.error("月度销售报告推送失败")
            
    except Exception as e:
        logger.error(f"执行月度销售报告推送任务失败: {e}")
        
        # 发送错误通知到企业微信 - 使用配置文件中的webhook key
        error_msg = f"## ❌ 月度销售报告生成失败\n\n"
        error_msg += f"**错误时间：** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        error_msg += f"**错误信息：** {str(e)}\n"
        error_msg += f"**建议：** 请检查数据库连接和数据完整性"
        
        try:
            webhook_key = WECHAT_WORK_CONFIG['monthly_report_webhook']
            error_bot = WeChatWorkBot(webhook_key)
            error_bot.send_markdown(error_msg)
        except:
            pass  # 如果连错误通知都发送失败，就不再处理


if __name__ == '__main__':
    main() 