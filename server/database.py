import sqlite3
import os

class Database:
# ⭐ 增加 is_main 参数，默认 False（工人模式）
    def __init__(self, db_path, is_main=False):
        self.db_path = db_path
        # ⭐ 核心优化 1：isolation_level="IMMEDIATE" 
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
        # 符号表：存储定义位置和类型
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS symbols (
                usr TEXT PRIMARY KEY,
                name TEXT,
                kind INTEGER,
                file_path TEXT,
                s_line INTEGER,
                s_col INTEGER,
                e_line INTEGER,
                e_col INTEGER
            )''')
        
        # 调用关系表：存储函数间的指向关系
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS calls (
                caller_usr TEXT,
                callee_usr TEXT,
                file_path TEXT,
                line INTEGER,
                PRIMARY KEY (caller_usr, callee_usr, line)
            )''')
        
        # 为文件路径创建索引，加速大纲视图查询
        self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_file_path ON symbols(file_path);')
        self.conn.commit()
    
    # ⭐ 核心优化 2：新增批量写入方法
    def batch_insert(self, defs, calls):
        """毫秒级批量插入，瞬间释放锁"""
        if defs:
            self.cursor.executemany('''
                INSERT OR REPLACE INTO symbols VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', defs)
        if calls:
            self.cursor.executemany('''
                INSERT OR IGNORE INTO calls VALUES (?, ?, ?, ?)
            ''', calls)
        self.conn.commit()

    def record_definition(self, usr, name, kind, file, sl, sc, el, ec):
        """插入或更新符号定义"""
        self.cursor.execute('''
            INSERT OR REPLACE INTO symbols VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (usr, name, kind, file, sl, sc, el, ec))

    def record_call(self, caller, callee, file, line):
        """记录函数调用关系"""
        self.cursor.execute('''
            INSERT OR IGNORE INTO calls VALUES (?, ?, ?, ?)
        ''', (caller, callee, file, line))

    def search_symbols(self, query):
        """模糊搜索符号（用于 Ctrl+T）"""
        self.cursor.execute('''
            SELECT name, file_path, s_line, s_col, usr 
            FROM symbols WHERE name LIKE ? LIMIT 100
        ''', (f"%{query}%",))
        return self.cursor.fetchall()

    def get_symbols_by_file(self, file_path):
        """获取单个文件的所有符号（用于大纲视图）"""
        self.cursor.execute('''
            SELECT name, kind, s_line, s_col, e_line, e_col 
            FROM symbols WHERE file_path = ? ORDER BY s_line ASC
        ''', (file_path,))
        return self.cursor.fetchall()
    
    def get_definitions_by_name(self, name):
        """核心查询：根据符号名称直接秒查定义位置（函数定义跳转）"""
        # 利用 symbols 表的索引实现 O(log N) 级别的极速查询
        self.cursor.execute('''
            SELECT file_path, s_line, s_col, e_line, e_col 
            FROM symbols WHERE name = ?
        ''', (name,))
        return self.cursor.fetchall()

    def close(self):
        self.conn.close()