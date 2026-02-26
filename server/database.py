import sqlite3
import os
import time
import random
import functools

def with_retry(max_retries=10, base_delay=0.05):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            for i in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except sqlite3.OperationalError as e:
                    if "locked" in str(e).lower() and i < max_retries - 1:
                        # 指数退避 + 随机抖动
                        delay = base_delay * (2 ** i) + random.uniform(0, 0.1)
                        time.sleep(delay)
                        continue
                    raise
            return func(*args, **kwargs)
        return wrapper
    return decorator

class Database:
    # 增加 is_main 参数，默认 False（工人模式）
    def __init__(self, db_path, is_main=False):
        self.db_path = db_path
        # 核心优化 1：isolation_level="IMMEDIATE" 
        # 这会强制 Python 的 sqlite3 驱动在获取写锁时更聪明，彻底杜绝死锁假象！
        self.conn = sqlite3.connect(db_path, timeout=60.0, check_same_thread=False, isolation_level="IMMEDIATE")
        self.cursor = self.conn.cursor()
        
        # 核心优化 2：无论主次进程，都应使用 NORMAL 同步模式
        self.conn.execute('PRAGMA journal_mode=WAL;')
        self.conn.execute('PRAGMA synchronous=NORMAL;')
        self.conn.execute(f'PRAGMA busy_timeout=60000;')

        # 核心逻辑：只有主进程（包工头）才允许去建表！
        if is_main:
            self.conn.execute('PRAGMA journal_mode=WAL;')
            self.conn.execute('PRAGMA synchronous=NORMAL;')
            self._setup()

    def enable_speed_mode(self):
        """开启极速索引模式：彻底牺牲断电安全性换取极致写入速度"""
        self.conn.execute('PRAGMA synchronous=OFF;')
        self.conn.execute('PRAGMA journal_mode=MEMORY;')
        self.conn.execute('PRAGMA cache_size=100000;') # 指数级增加缓存

    def _setup(self):
        # 表 A：全局符号字典 (极致瘦身，只存 USR、名字、类型)
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS symbols (
                usr TEXT PRIMARY KEY,
                name TEXT,
                kind TEXT
            )''')
        
        # 表 B：位置与引用关系 (保留了起始和结束坐标，兼容现有的 LSP 逻辑)
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS refs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                usr TEXT,
                caller_usr TEXT,
                file_path TEXT,
                s_line INTEGER,
                s_col INTEGER,
                e_line INTEGER,
                e_col INTEGER,
                role TEXT
            )''')
        
        # 表 C：增量与状态追踪
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS files (
                file_path TEXT PRIMARY KEY,
                mtime REAL,
                status TEXT
            )''')
        
        # 建立高频查询索引
        self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_sym_name ON symbols(name);')
        self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_ref_usr ON refs(usr);')
        self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_ref_caller ON refs(caller_usr);')
        self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_ref_file_role ON refs(file_path, role);')
        self.conn.commit()

    # --- 增量更新的三大核心原子操作 ---
    def update_file_status(self, file_path, mtime, status, commit=True):
        """更新文件状态：indexing, completed, failed"""
        self.cursor.execute('INSERT OR REPLACE INTO files VALUES (?, ?, ?)', (file_path, mtime, status))
        if commit:
            self.conn.commit()

    @with_retry()
    def prepare_file_reindex(self, file_path):
        """增量第一步：抹除该文件旧的物理位置记录"""
        self.cursor.execute('DELETE FROM refs WHERE file_path = ?', (file_path,))
        self.conn.commit()

    @with_retry()
    def batch_insert_v2(self, symbols, refs):
        """毫秒级批量写入：先更新字典，再插入引用拓扑"""
        if symbols:
            # 字典去重
            self.cursor.executemany('INSERT OR IGNORE INTO symbols VALUES (?, ?, ?)', symbols)
        if refs:
            # 引用直接插入
            self.cursor.executemany('''
                INSERT INTO refs (usr, caller_usr, file_path, s_line, s_col, e_line, e_col, role) 
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', refs)
        self.conn.commit()

    def save_index_result(self, file_path, mtime, symbols, refs, commit=True):
        """【性能核心】：单次事务完成状态更新、清理与写入"""
        # 1. 更新状态与清理
        self.cursor.execute('INSERT OR REPLACE INTO files VALUES (?, ?, ?)', (file_path, mtime, 'completed'))
        self.cursor.execute('DELETE FROM refs WHERE file_path = ?', (file_path,))
        
        # 2. 写入数据
        if symbols:
            self.cursor.executemany('INSERT OR IGNORE INTO symbols VALUES (?, ?, ?)', symbols)
        if refs:
            self.cursor.executemany('''
                INSERT INTO refs (usr, caller_usr, file_path, s_line, s_col, e_line, e_col, role) 
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', refs)
            
        if commit:
            self.conn.commit()

    # --- LSP 查询接口 (全部升级为 JOIN 联表查询) ---
    def search_symbols(self, query):
        """模糊搜索符号（Ctrl+T）- 只搜定义"""
        self.cursor.execute('''
            SELECT s.name, r.file_path, r.s_line, r.s_col, s.usr 
            FROM refs r JOIN symbols s ON r.usr = s.usr
            WHERE s.name LIKE ? AND r.role = 'def' LIMIT 100
        ''', (f"%{query}%",))
        return self.cursor.fetchall()

    def get_symbols_by_file(self, file_path):
        """大纲视图：查本文件的所有定义"""
        self.cursor.execute('''
            SELECT s.name, s.kind, r.s_line, r.s_col, r.e_line, r.e_col 
            FROM refs r JOIN symbols s ON r.usr = s.usr
            WHERE r.file_path = ? AND r.role = 'def' ORDER BY r.s_line ASC
        ''', (file_path,))
        return self.cursor.fetchall()
    
    # def get_definitions_by_name(self, name):
    #     """跳转定义 (F12)：查名字对应的所有定义位置"""
    #     self.cursor.execute('''
    #         SELECT r.file_path, r.s_line, r.s_col, r.e_line, r.e_col 
    #         FROM refs r JOIN symbols s ON r.usr = s.usr
    #         WHERE s.name = ? AND r.role = 'def'
    #     ''', (name,))
    #     return self.cursor.fetchall()
    def get_definitions_by_name(self, name):
        """跳转定义 (F12)：查名字对应的所有定义位置"""
        self.cursor.execute('''
            -- ⭐ 【修改核心】：加上 DISTINCT，强制合并物理坐标完全相同的重复结果
            SELECT DISTINCT r.file_path, r.s_line, r.s_col, r.e_line, r.e_col 
            FROM refs r JOIN symbols s ON r.usr = s.usr
            WHERE s.name = ? AND r.role = 'def'
        ''', (name,))
        return self.cursor.fetchall()

    def get_usr_at_location(self, file_path, line, col):
        """核心：查询特定坐标下的符号 USR (精准跳转的基础)"""
        # 匹配逻辑：s_line == line 且 s_col <= col <= e_col
        # ⭐ 优化：优先匹配 role != 'def' (引用处)，并按宽度升序排列 (最精准的优先)
        self.cursor.execute('''
            SELECT usr FROM refs 
            WHERE file_path = ? AND s_line = ? AND s_col <= ? AND e_col >= ?
            ORDER BY (CASE WHEN role = 'def' THEN 1 ELSE 0 END), (e_col - s_col) ASC
            LIMIT 1
        ''', (file_path, line, col, col))
        res = self.cursor.fetchone()
        return res[0] if res else None

    def get_definitions_by_usr(self, usr):
        """通过 USR 精确查找定义位置"""
        self.cursor.execute('''
            SELECT DISTINCT file_path, s_line, s_col, e_line, e_col 
            FROM refs WHERE usr = ? AND role = 'def'
        ''', (usr,))
        return self.cursor.fetchall()

    def get_references_by_usr(self, usr):
        """查 USR 对应的所有引用位置（包含声明/定义、调用、读取等）"""
        self.cursor.execute('''
            SELECT DISTINCT file_path, s_line, s_col, e_line, e_col 
            FROM refs WHERE usr = ? AND role IN ('ref', 'call', 'def')
        ''', (usr,))
        return self.cursor.fetchall()

    def get_references_by_name(self, name):
        """查名字对应的所有引用位置 (作为兜底)"""
        self.cursor.execute('''
            SELECT DISTINCT r.file_path, r.s_line, r.s_col, r.e_line, r.e_col 
            FROM refs r JOIN symbols s ON r.usr = s.usr
            WHERE s.name = ? AND r.role IN ('ref', 'call', 'def')
        ''', (name,))
        return self.cursor.fetchall()

    def close(self):
        self.conn.close()