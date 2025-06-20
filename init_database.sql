-- ================================
-- Call Analysis 数据库初始化脚本 (通过Python代码执行)
-- ================================

-- 创建销售人员表
CREATE TABLE IF NOT EXISTS salespersons (
    id SERIAL PRIMARY KEY,
    name VARCHAR(50) NOT NULL UNIQUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 创建每日通话记录汇总表
CREATE TABLE IF NOT EXISTS daily_call_records (
    id SERIAL PRIMARY KEY,
    salesperson_id INTEGER NOT NULL REFERENCES salespersons(id),
    upload_date DATE NOT NULL,
    
    -- 通话统计数据
    total_calls INTEGER NOT NULL DEFAULT 0,
    effective_calls INTEGER NOT NULL DEFAULT 0,
    average_score DECIMAL(5,2), -- 支持0-100分，保留2位小数
    
    -- 分析结果
    summary_analysis TEXT,
    improvement_suggestions TEXT,
    
    -- 元数据
    processed_files INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    -- 确保每人每天只有一条记录
    UNIQUE(salesperson_id, upload_date)
);

-- 创建通话详情表
CREATE TABLE IF NOT EXISTS call_details (
    id SERIAL PRIMARY KEY,
    daily_record_id INTEGER NOT NULL REFERENCES daily_call_records(id) ON DELETE CASCADE,
    salesperson_id INTEGER NOT NULL REFERENCES salespersons(id), -- 直接关联销售人员，便于查询
    
    -- 文件信息
    original_filename VARCHAR(255),
    company_name VARCHAR(100),
    contact_person VARCHAR(50),
    phone_number VARCHAR(20),
    
    -- 通话分析
    score DECIMAL(5,2) CHECK (score >= 0 AND score <= 100), -- 支持0-100分评分
    is_effective BOOLEAN DEFAULT FALSE,
    conversation_text TEXT,
    analysis_text TEXT,
    suggestions TEXT,
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 创建索引以提高查询性能
CREATE INDEX IF NOT EXISTS idx_daily_records_salesperson ON daily_call_records(salesperson_id);
CREATE INDEX IF NOT EXISTS idx_daily_records_date ON daily_call_records(upload_date);
CREATE INDEX IF NOT EXISTS idx_daily_records_salesperson_date ON daily_call_records(salesperson_id, upload_date);

-- 复合索引（用于统计查询）
CREATE INDEX IF NOT EXISTS idx_daily_records_stats ON daily_call_records(salesperson_id, upload_date, effective_calls);

-- 通话详情索引
CREATE INDEX IF NOT EXISTS idx_call_details_daily_record ON call_details(daily_record_id);
CREATE INDEX IF NOT EXISTS idx_call_details_salesperson ON call_details(salesperson_id); -- 直接按销售查询
CREATE INDEX IF NOT EXISTS idx_call_details_effective ON call_details(is_effective);
CREATE INDEX IF NOT EXISTS idx_call_details_company ON call_details(company_name); -- 按公司查询

-- 创建更新时间的触发器函数
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';

-- 创建更新销售人员活动时间的触发器函数
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

-- 为表添加自动更新时间戳的触发器
CREATE TRIGGER update_salespersons_updated_at 
    BEFORE UPDATE ON salespersons 
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_daily_records_updated_at 
    BEFORE UPDATE ON daily_call_records 
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- 创建触发器：当在 daily_call_records 表插入或更新记录时，更新销售人员的活动时间
CREATE TRIGGER update_salesperson_activity_trigger
    AFTER INSERT OR UPDATE ON daily_call_records
    FOR EACH ROW 
    EXECUTE FUNCTION update_salesperson_activity();

-- 插入测试销售人员数据（与设计文档保持一致）
INSERT INTO salespersons (name) VALUES 
    ('张三'),
    ('李四'),
    ('王五'),
    ('赵六'),
    ('钱七'),
    ('孙八'),
    ('周九'),
    ('吴十'),
    ('郑十一'),
    ('陈十二')
ON CONFLICT (name) DO NOTHING; 