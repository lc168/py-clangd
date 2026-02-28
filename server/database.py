#!/usr/bin/env python3
import sqlite3
import os
import time
import random
import functools

def with_retry(base_delay=0.05):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            retry_count = 0
            while True:
                try:
                    return func(*args, **kwargs)
                except sqlite3.OperationalError as e:
                    if "locked" in str(e).lower() or "busy" in str(e).lower():
                        # 退避 + 随机抖动，最大延迟控制在 1 秒左右，无限重试
                        logger.warning(f"数据库被锁，等待重试 {retry_count} 次: {e}")
                        delay = min(1.0, base_delay * (1.5 ** retry_count)) + random.uniform(0, 0.1)
                        time.sleep(delay)
                        retry_count += 1
                        continue
                    raise
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
        
        # 核心优化 2：并发 SQLite 的性能地基
        # WAL (Write-Ahead Logging) 允许多个读操作和一个写操作并发进行
        self.conn.execute('PRAGMA journal_mode=WAL;')
        self.conn.execute('PRAGMA synchronous=NORMAL;')
        self.conn.execute('PRAGMA busy_timeout=60000;') # 当数据库被锁定时，内部自动等待最多 60 秒再报错

        # 让所有进程都能按需自动建表（安全起见）
        self._setup()

    @with_retry()
    def _setup(self):
        # 表 A：全局符号字典 (极致瘦身，只存 USR、名字、类型)
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS symbols (
                usr TEXT PRIMARY KEY,
                name TEXT,
                kind TEXT
            )''')
        
        # 表 B：位置与引用关系 (使用 UNIQUE 防爆发)
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
                role TEXT,
                UNIQUE(usr, role, file_path, s_line, s_col)
            )''')
        
        # 表 C：增量与状态追踪
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS files (
                file_path TEXT PRIMARY KEY,
                mtime REAL,
                status TEXT
            )''')
        
        # 表 D：源码与头文件的包含关系
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS includes (
                source_file TEXT,
                included_file TEXT,
                exact_path TEXT,
                UNIQUE(source_file, included_file)
            )''')
        
        # 建立高频查询索引
        self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_sym_name ON symbols(name);')
        self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_ref_usr ON refs(usr);')
        self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_ref_caller ON refs(caller_usr);')
        self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_ref_file_role ON refs(file_path, role);')
        self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_included_file ON includes(included_file);')
        self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_includes_exact ON includes(exact_path);')
        self.conn.commit()

    # --- 增量更新的三大核心原子操作 ---
    @with_retry()
    def update_file_status(self, file_path, mtime, status, commit=True):
        """更新文件状态：indexing, completed, failed"""
        self.cursor.execute('INSERT OR REPLACE INTO files VALUES (?, ?, ?)', (file_path, mtime, status))
        if commit:
            self.conn.commit()

    @with_retry()
    def prepare_file_reindex(self, file_path):
        """增量第一步：抹除该文件旧的物理位置记录"""
        self.cursor.execute('DELETE FROM refs WHERE file_path = ?', (file_path,))
        self.cursor.execute('DELETE FROM includes WHERE source_file = ?', (file_path,))
        self.conn.commit()

    @with_retry()
    def batch_insert_v2(self, symbols, refs):
        """毫秒级批量写入：先更新字典，再插入引用拓扑"""
        if symbols:
            # 字典去重
            self.cursor.executemany('INSERT OR IGNORE INTO symbols VALUES (?, ?, ?)', symbols)
        if refs:
            # 引用直接使用 IGNORE 插入，由于有了 UNIQUE 约束，重复的头文件引用将被直接屏蔽！
            self.cursor.executemany('''
                INSERT OR IGNORE INTO refs (usr, caller_usr, file_path, s_line, s_col, e_line, e_col, role) 
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', refs)
        self.conn.commit()

    @with_retry()
    def save_parse_result(self, file_path, mtime, symbols, refs, included_files=None, commit=True):
        """【性能核心】：单次事务完成状态更新、清理与写入"""
        # 1. 更新状态与清理
        self.cursor.execute('INSERT OR REPLACE INTO files VALUES (?, ?, ?)', (file_path, mtime, 'completed'))
        #删除掉file_path对应的所有记录
        self.cursor.execute('DELETE FROM refs WHERE file_path = ?', (file_path,))
        self.cursor.execute('DELETE FROM includes WHERE source_file = ?', (file_path,))

        # 2. 写入数据
        if symbols:
            self.cursor.executemany('INSERT OR IGNORE INTO symbols VALUES (?, ?, ?)', symbols)
        if refs:
            self.cursor.executemany('''
                INSERT OR IGNORE INTO refs (usr, caller_usr, file_path, s_line, s_col, e_line, e_col, role) 
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', refs)
        if included_files:
            # included_files: [(absolute_path, exact_path_string), ...]
            includes_data = [(file_path, inc_file, exact) for inc_file, exact in included_files]
            self.cursor.executemany('INSERT OR IGNORE INTO includes VALUES (?, ?, ?)', includes_data)
            
        if commit:
            self.conn.commit()

    # --- LSP 查询接口 (全部升级为 JOIN 联表查询) ---
    def get_sources_including(self, included_file):
        """查询依赖了指定头文件的所有源文件"""
        self.cursor.execute('SELECT source_file FROM includes WHERE included_file = ?', (included_file,))
        return [row[0] for row in self.cursor.fetchall()]

    def get_include_by_exact_path(self, source_file, exact_path):
        """查找指定包含路径字面量对应的绝对路径，优先从当前所在文件查找"""
        self.cursor.execute('SELECT included_file FROM includes WHERE source_file = ? AND exact_path = ? LIMIT 1', (source_file, exact_path))
        res = self.cursor.fetchone()
        if res:
            return res[0]
            
        self.cursor.execute('SELECT included_file FROM includes WHERE exact_path = ? LIMIT 1', (exact_path,))
        res = self.cursor.fetchone()
        return res[0] if res else None

    # --- 从底层拆解上来的高层查询逻辑 (对应 LSP 请求) ---
    def lsp_did_save_db(self, file_path):
        """处理增量更新的查询，返回它自己以及依赖它的目标"""
        return self.get_sources_including(file_path)

    def lsp_document_symbols_db(self, file_path):
        self.cursor.execute('''
            SELECT s.name, s.kind, r.s_line, r.s_col, r.e_line, r.e_col 
            FROM refs r JOIN symbols s ON r.usr = s.usr
            WHERE r.file_path = ? AND r.role = 'def' ORDER BY r.s_line ASC
        ''', (file_path,))
        return self.cursor.fetchall()

    def lsp_workspace_symbols_db(self, query):
        self.cursor.execute('''
            SELECT s.name, r.file_path, r.s_line, r.s_col, s.usr 
            FROM refs r JOIN symbols s ON r.usr = s.usr
            WHERE s.name LIKE ? AND r.role = 'def' LIMIT 100
        ''', (f"%{query}%",))
        return self.cursor.fetchall()

    def lsp_definition_db(self, file_path, line, col, line_text=""):
        """查定义核心逻辑：优先头文件跳转，后查 USR 跳跃"""
        import re, os
        if "#include" in line_text:
            match = re.search(r'#include\s*[<"]([^>"]+)[>"]', line_text)
            if match:
                exact_path_clicked = match.group(1)
                inc_path = self.get_include_by_exact_path(file_path, exact_path_clicked)
                if inc_path and os.path.exists(inc_path):
                    return [(inc_path, 1, 1, 1, 1)]
                
        usr = self.get_usr_at_location(file_path, line, col)
        if usr:
            return self.get_definitions_by_usr(usr)
        return []

    def lsp_references_db(self, file_path, line, col):
        """查引用核心逻辑"""
        usr = self.get_usr_at_location(file_path, line, col)
        if usr:
            return self.get_references_by_usr(usr)
        return []

    def lsp_did_save_db(self, file_path, commands_map):
        """处理文件保存时的增量更新逻辑，返回需要重新索引的文件列表及其编译命令"""
        dependent_sources = self.get_sources_including(file_path)
        
        cmd_info = commands_map.get(file_path)
        files_to_index = []

        if cmd_info:
            files_to_index.append((file_path, cmd_info))
        
        for dep_src in dependent_sources:
            if dep_src == file_path:
                continue
            dep_cmd = commands_map.get(dep_src)
            if dep_cmd and not any(f[0] == dep_src for f in files_to_index):
                files_to_index.append((dep_src, dep_cmd))
                
        return files_to_index

    def lsp_code_action_db(self, file_path, line, col):
        """查支持的 Code Action 操作 (目前只看是不是宏)"""
        usr = self.get_usr_at_location(file_path, line, col)
        if usr and self.is_macro(usr):
            return "expand_macro"
        return None

    def lsp_execute_command_db(self, command, args, commands_map):
        """执行后台复杂指令，比如宏展开"""
        if command == "pyclangd.expandMacro":
            import os, shlex, tempfile, re, subprocess
            from cindex import Index, CursorKind
            uri, line_0, col_0 = args
            file_path = os.path.normpath(uri.replace("file://", ""))
            
            cmd_info = commands_map.get(file_path)
            if not cmd_info:
                return {"error": f"Cannot expand macro: missing compile_commands mapping for {file_path}"}
            
            idx = Index.create()
            raw_args = cmd_info.get('arguments', [])
            if not raw_args:
                command_str = cmd_info.get('command', '')
                if command_str: raw_args = shlex.split(command_str)
            
            compiler_args = []
            skip_next = False
            for arg in raw_args[1:]:
                if skip_next:
                    skip_next = False
                    continue
                if arg == '-o':
                    skip_next = True
                    continue
                if arg in ('-c', '-S'): continue
                if arg in ('-MD', '-MMD', '-MP', '-MT') or arg.startswith(('-Wp,-MD', '-Wp,-MMD')): continue
                if arg == '-MF':
                    skip_next = True
                    continue
                compiler_args.append(arg)
            
            compiler_args.append('-fsyntax-only')
            compiler_args.extend([
                '-ferror-limit=0', '-Wno-error', '-Wno-strict-prototypes',
                '-Wno-implicit-int', '-Wno-unknown-warning-option',
                '-Wno-unknown-attributes', '-Qunused-arguments'
            ])
            
            directory = cmd_info.get('directory', '')
            if directory:
                compiler_args.extend(['-working-directory', directory])
                
            compiler_path = raw_args[0] if raw_args else ''
            if 'aarch64' in compiler_path or 'arm64' in compiler_path:
                compiler_args.append('--target=aarch64-linux-gnu')
            elif 'arm' in compiler_path:
                compiler_args.append('--target=arm-linux-gnueabihf')
                
            builtin_includes = '/home/lc/llvm22/lib/clang/22/include' 
            compiler_args.extend(['-isystem', builtin_includes])

            tu = idx.parse(file_path, args=compiler_args, options=0x01)
            
            target_node = None
            line_1 = line_0 + 1
            col_1 = col_0 + 1
            for node in tu.cursor.walk_preorder():
                if node.kind == CursorKind.MACRO_INSTANTIATION:
                    loc = node.extent
                    if loc.start.line == line_1 and loc.start.column <= col_1 <= loc.end.column:
                        target_node = node
                        break
                        
            if not target_node:
                return {"error": f"Cannot find MACRO_INSTANTIATION at {line_1}:{col_1}"}
                
            with open(file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
                
            s_line = target_node.extent.start.line - 1
            s_col = target_node.extent.start.column - 1
            e_line = target_node.extent.end.line - 1
            e_col = target_node.extent.end.column - 1
            
            tmp_fd, tmp_path = tempfile.mkstemp(suffix=".c", dir=os.path.dirname(file_path))
            os.close(tmp_fd)
            
            try:
                mod_lines = lines.copy()
                mod_lines[e_line] = mod_lines[e_line][:e_col] + "/*PYCLANGD_END*/" + mod_lines[e_line][e_col:]
                mod_lines[s_line] = mod_lines[s_line][:s_col] + "/*PYCLANGD_START*/" + mod_lines[s_line][s_col:]
                
                with open(tmp_path, 'w', encoding='utf-8') as f:
                    f.writelines(mod_lines)
                
                clang_e_args = compiler_args.copy()
                if '-fsyntax-only' in clang_e_args:
                    clang_e_args.remove('-fsyntax-only')
                
                cmd = ["clang", "-E", "-C"] + clang_e_args + [tmp_path]
                result = subprocess.run(cmd, capture_output=True, text=True, check=True)
                output = result.stdout
                
                match = re.search(r'/\*PYCLANGD_START\*/(.*?)/\*PYCLANGD_END\*/', output, re.DOTALL)
                if match:
                    expanded_text = match.group(1).strip()
                    return {
                        "success": True,
                        "text": expanded_text,
                        "s_line": s_line,
                        "s_col": s_col,
                        "e_line": e_line,
                        "e_col": e_col
                    }
                else:
                    return {"error": "Failed to extract expanded text"}
            except Exception as e:
                return {"error": f"Subprocess error: {e}"}
            finally:
                os.remove(tmp_path)
                
        return {"error": "Unknown command"}

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
            SELECT r.usr FROM refs r
            LEFT JOIN symbols s ON r.usr = s.usr
            WHERE r.file_path = ? AND r.s_line = ? AND r.s_col <= ? AND r.e_col >= ?
            ORDER BY 
                (CASE WHEN s.kind = 'MACRO_DEFINITION' THEN 0 ELSE 1 END),
                (CASE WHEN r.role = 'def' THEN 1 ELSE 0 END), 
                (r.e_col - r.s_col) ASC
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

    def is_macro(self, usr):
        """判断一个符号是否为宏"""
        self.cursor.execute('SELECT kind FROM symbols WHERE usr = ?', (usr,))
        res = self.cursor.fetchone()
        return res and res[0] == 'MACRO_DEFINITION'

    def close(self):
        self.conn.close()