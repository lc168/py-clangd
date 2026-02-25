import sqlite3
import os

class Database:
    # 增加 is_main 参数，默认 False（工人模式）
    def __init__(self, db_path, is_main=False):
        self.db_path = db_path
        # 核心优化 1：isolation_level="IMMEDIATE" 
        # 这会强制 Python 的 sqlite3 驱动在获取写锁时更聪明，彻底杜绝死锁假象！
        self.conn = sqlite3.connect(db_path, timeout=60.0, check_same_thread=False, isolation_level="IMMEDIATE")
        self.cursor = self.conn.cursor()

        # 核心逻辑：只有主进程（包工头）才允许去建表！
        if is_main:
            # 只有主进程负责开启 WAL，一旦开启，永久生效，子进程无需再设
            self.conn.execute('PRAGMA journal_mode=WAL;')
            self.conn.execute('PRAGMA synchronous=NORMAL;')
            self._setup()

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
    def update_file_status(self, file_path, mtime, status):
        """更新文件状态：indexing, completed, failed"""
        self.cursor.execute('INSERT OR REPLACE INTO files VALUES (?, ?, ?)', (file_path, mtime, status))
        self.conn.commit()

    def prepare_file_reindex(self, file_path):
        """增量第一步：抹除该文件旧的物理位置记录"""
        self.cursor.execute('DELETE FROM refs WHERE file_path = ?', (file_path,))
        self.conn.commit()

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

    def close(self):
        self.conn.close()