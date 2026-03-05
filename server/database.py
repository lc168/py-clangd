#!/usr/bin/env python3
import sqlite3
import os
import time
import random
import functools
import logging
import clang_init

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(funcName)s %(message)s'
)

logger = logging.getLogger("PyClangd")
logger.setLevel(logging.INFO)

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
    def __init__(self, workspace_dir):
        self.workspace_dir = os.path.abspath(workspace_dir)
        self.db_path = os.path.join(self.workspace_dir, "pyclangd_index.db")
        self.commands_map = {}
        
        # 核心优化 1：isolation_level="IMMEDIATE" 
        self.conn = sqlite3.connect(self.db_path, timeout=60.0, check_same_thread=False, isolation_level="IMMEDIATE")
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
        # # 表 A：全局符号字典 (极致瘦身，只存 USR、名字、类型)
        # self.cursor.execute('''
        #     CREATE TABLE IF NOT EXISTS symbols (
        #         usr TEXT PRIMARY KEY,
        #         name TEXT,
        #         kind TEXT
        #     )''')
        
        # 表 B：位置与引用关系 (使用 UNIQUE 防爆发)
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS symbols (
                file_path TEXT,  -- 文件路径
                s_line INTEGER,  -- 开始行
                s_col INTEGER,  -- 开始列
                e_line INTEGER,  -- 结束行
                e_col INTEGER,  -- 结束列
                usr TEXT,  -- 如果是 inc，usr为头文件路径，如果是 def，usr为符号的USR
                role TEXT,  -- 角色, 例如: "inc", "def", "ref"
                name TEXT,  -- 符号或文件名字
                kind TEXT,  -- 节点类型
                UNIQUE(file_path, s_line, s_col, e_line, e_col, usr)
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
        
        # # 建立高频查询索引
        # self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_sym_name ON symbols(name);')
        # self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_ref_usr ON refs(usr);')
        # self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_ref_caller ON refs(caller_usr);')
        # self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_ref_file_role ON refs(file_path, role);')
        # self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_included_file ON includes(included_file);')
        # self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_includes_exact ON includes(exact_path);')
        self.conn.commit()

    def load_commands_map(self):
        """加载 compile_commands.json, 返回 dict: { absolute_file_path -> dict }"""
        cc_path = os.path.join(self.workspace_dir, "compile_commands.json")
        commands_map = {}
        if not os.path.exists(cc_path):
            return commands_map
            
        import json
        with open(cc_path, 'r', encoding='utf-8') as f:
            commands = json.load(f)
            
        for cmd in commands:
            directory = cmd.get('directory', '')
            file_rel = cmd.get('file', '')
            abs_path = os.path.realpath(os.path.join(directory, file_rel))
            commands_map[abs_path] = cmd
            
        self.commands_map = commands_map
        return commands_map

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
        self.cursor.execute('DELETE FROM symbols WHERE file_path = ?', (file_path,))
        self.conn.commit()

    @with_retry()
    def save_parse_result(self, file_path, mtime, symbols):
        """【性能核心】：单次事务完成状态更新、清理与写入"""
        # 1. 更新状态与清理
        self.cursor.execute('INSERT OR REPLACE INTO files VALUES (?, ?, ?)', (file_path, mtime, 'completed'))
        #删除掉file_path对应的所有记录
        self.cursor.execute('DELETE FROM symbols WHERE file_path = ?', (file_path,))

        # 2. 写入数据
        if symbols:
            self.cursor.executemany('INSERT OR IGNORE INTO symbols VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)', symbols)
        # 3. 落盘
        self.conn.commit()

    # --- LSP 查询接口 (全部升级为单表查询) ---
    def get_sources_including(self, included_file):
        """查询依赖了指定头文件的所有源文件"""
        self.cursor.execute('SELECT DISTINCT file_path FROM symbols WHERE role = "inc" AND usr = ?', (included_file,))
        return [row[0] for row in self.cursor.fetchall()]

    # --- 从底层拆解上来的高层查询逻辑 (对应 LSP 请求) ---
    def lsp_document_symbols_db(self, file_path):
        self.cursor.execute('''
            SELECT name, kind, s_line, s_col, e_line, e_col 
            FROM symbols
            WHERE file_path = ? AND role = 'def' ORDER BY s_line ASC
        ''', (file_path,))
        return self.cursor.fetchall()

    def lsp_workspace_symbols_db(self, query):
    # 全局搜索
        self.cursor.execute('''
            SELECT name, file_path, s_line, s_col, usr 
            FROM symbols
            WHERE name LIKE ? AND role = 'def' LIMIT 100
        ''', (f"%{query}%",))
        return self.cursor.fetchall()

    def lsp_definition_db(self, file_path, line, col):
        """查定义核心逻辑：优先头文件跳转，后查 USR 跳跃（适配 Symbols 单表融合版架构）"""
        sqlcmd = f'''
            SELECT role, usr FROM symbols
            WHERE file_path = '{file_path}' AND s_line = {line} AND s_col <= {col} AND e_col >= {col}
            ORDER BY
                (CASE WHEN kind = 'MACRO_DEFINITION' THEN 0 ELSE 1 END),
                (CASE WHEN role = 'def' THEN 0 ELSE 1 END),
                (e_col - s_col) ASC LIMIT 1'''
        logger.info(f"lsp_definition_db: {sqlcmd}")
        self.cursor.execute(sqlcmd)
        res = self.cursor.fetchone()
        logger.info(f"res1: {res}")
        if not res:
            return []
        role, target_str = res
        if role == 'inc':
            # 头文件路径直接就存在了 target_str 中
            import os
            if os.path.exists(target_str):
                return [(target_str, 1, 1, 1, 1)]
            return []

        elif role in ('ref', 'def'):
            # 无论是引用处按 F12，还是定义处自己按 F12，统统拿着 USR 去找它的 def 记录
            sqlcmd = '''
                SELECT DISTINCT file_path, s_line, s_col, e_line, e_col 
                FROM symbols 
                WHERE usr = ? AND role = 'def'
            '''
            logger.info(f"role: {role}, target_usr: {target_str}")
            self.cursor.execute(sqlcmd, (target_str,))
            res = self.cursor.fetchall()
            logger.info(f"res2: {res}")
            return res

        return []



    def lsp_references_db(self, file_path, line, col):
        """查引用核心逻辑"""
        usr = self.get_usr_at_location(file_path, line, col)
        if usr:
            return self.get_references_by_usr(usr)
        return []

    def lsp_did_save_db(self, file_path):
        logger.info(f"lsp_did_save_db更新数据: {file_path}")
        """处理文件保存时的增量更新逻辑，返回需要重新索引的文件列表及其编译命令"""
        dependent_sources = self.get_sources_including(file_path)
        
        cmd_info = self.commands_map.get(file_path)
        files_to_index = []

        if cmd_info:
            files_to_index.append((file_path, cmd_info))
        
        for dep_src in dependent_sources:
            if dep_src == file_path:
                continue
            dep_cmd = self.commands_map.get(dep_src)
            if dep_cmd and not any(f[0] == dep_src for f in files_to_index):
                files_to_index.append((dep_src, dep_cmd))
        
        if not files_to_index:
            logger.warning(f"增量跳过: {file_path} 不在 compile_commands 中，且无关联源文件包含它")
            return

        logger.info(f"触发增量索引: {os.path.basename(file_path)}, 连带 {len(files_to_index)} 个依赖文件")

        # 启动后台线程跑解析，坚决不阻塞 LSP 主线程的 UI 响应
        def reindex_task():
            for src, cmd in files_to_index:
                # logger.info(f"[开始解析] {src}")
                status = self.index_worker((cmd, self.workspace_dir))
                if status == "SUCCESS":
                    logger.info(f"✅ 更新成功: {os.path.basename(src)}")
                else:
                    logger.info(f"❌ 更新失败: {os.path.basename(src)}")

        reindex_task()
        #threading.Thread(target=reindex_task, daemon=True).start()

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


    def get_usr_at_location(self, file_path, line, col):
        """核心：查询特定坐标下的符号 USR (精准跳转的基础)"""
        # 匹配逻辑：s_line == line 且 s_col <= col <= e_col
        # ⭐ 优化：优先匹配 role != 'def' (引用处)，并按宽度升序排列 (最精准的优先)
        self.cursor.execute('''
            SELECT usr FROM symbols
            WHERE file_path = ? AND s_line = ? AND s_col <= ? AND (s_line != e_line OR e_col >= ?) AND role != 'inc'
            ORDER BY 
                (CASE WHEN kind = 'MACRO_DEFINITION' THEN 0 ELSE 1 END),
                (CASE WHEN role = 'def' THEN 1 ELSE 0 END), 
                (e_col - s_col) ASC
            LIMIT 1
        ''', (file_path, line, col, col))
        res = self.cursor.fetchone()
        return res[0] if res else None

    def get_definitions_by_usr(self, usr):
        """通过 USR 精确查找定义位置"""
        self.cursor.execute('''
            SELECT DISTINCT file_path, s_line, s_col, e_line, e_col 
            FROM symbols WHERE usr = ? AND role = 'def'
        ''', (usr,))
        return self.cursor.fetchall()

    def get_references_by_usr(self, usr):
        """查 USR 对应的所有引用位置（包含声明/定义、调用、读取等）"""
        self.cursor.execute('''
            SELECT DISTINCT file_path, s_line, s_col, e_line, e_col 
            FROM symbols WHERE usr = ? AND role IN ('ref', 'def')
        ''', (usr,))
        return self.cursor.fetchall()

    def get_references_by_name(self, name):
        """查名字对应的所有引用位置 (作为兜底)"""
        self.cursor.execute('''
            SELECT DISTINCT file_path, s_line, s_col, e_line, e_col 
            FROM symbols
            WHERE name = ? AND role IN ('ref', 'def')
        ''', (name,))
        return self.cursor.fetchall()

    def is_macro(self, usr):
        """判断一个符号是否为宏"""
        self.cursor.execute('SELECT kind FROM symbols WHERE usr = ?', (usr,))
        res = self.cursor.fetchone()
        return res and res[0] == 'MACRO_DEFINITION'

    # =========================================================================
    # --- 构建索引与解析体系 (从原来的 pyclangd_server 中抽取) ---
    # =========================================================================

    @staticmethod
    def _clean_compiler_args(raw_args, directory, source_file=None):
        """清洗并组装传递给 libclang 的编译参数"""
        import os
        compiler_args = []
        skip_next = False
        source_basename = os.path.basename(source_file) if source_file else ""

        for arg in raw_args[1:]:
            if skip_next:
                skip_next = False
                continue
                
            if arg == '-o':
                skip_next = True
                continue
            if arg in ('-c', '-S'):
                continue
            if source_basename and os.path.basename(arg) == source_basename:
                continue
            if arg in ('-fconserve-stack', '-fno-var-tracking-assignments', '-fmerge-all-constants', '-fno-allow-store-data-races') or arg.startswith(('-mabi=', '-falign-kernels', '-mpreferred-stack-boundary=')):
                continue
            if arg in ('-MD', '-MMD', '-MP', '-MT') or arg.startswith(('-Wp,-MD', '-Wp,-MMD')):
                continue
            if arg == '-MF':
                skip_next = True
                continue
            if arg.startswith('-Werror='):
                continue
            
            compiler_args.append(arg)

        compiler_args.append('-fsyntax-only')
        compiler_args.append('-ferror-limit=0')
        compiler_args.extend([
            '-Wno-error', '-Wno-strict-prototypes', '-Wno-implicit-int',
            '-Wno-unknown-warning-option', '-Wno-unknown-attributes', '-Qunused-arguments'
        ])

        if directory:
            compiler_args.extend(['-working-directory', directory])

        compiler_path = raw_args[0] if raw_args else ''
        if 'aarch64' in compiler_path or 'arm64' in compiler_path:
            compiler_args.append('--target=aarch64-linux-gnu')
        elif 'arm' in compiler_path:
            compiler_args.append('--target=arm-linux-gnueabihf')

        builtin_includes = '/home/lc/llvm22/lib/clang/22/include' 
        compiler_args.extend(['-isystem', builtin_includes])
        return compiler_args

    @staticmethod
    def index_worker(args):
        """核心解析工人进程：为了支持多进程，必须为静态方法"""
        import os, shlex
        from cindex import Index, CursorKind
        
        cmd_info, workspace_dir = args
        
        directory = cmd_info.get('directory', '')
        file_rel = cmd_info.get('file', '')
        source_file = os.path.realpath(os.path.join(directory, file_rel)) 
        
        raw_args = cmd_info.get('arguments')
        if not raw_args:
            command_str = cmd_info.get('command', '')
            if command_str: raw_args = shlex.split(command_str)
            else: raw_args = []

        compiler_args = Database._clean_compiler_args(raw_args, directory, source_file)

        idx = Index.create()
        mtime = 0
        try:
            # 获取文件最后修改时间
            mtime = os.path.getmtime(source_file)
            tu = idx.parse(source_file, args=compiler_args, options=0x01)

            for diag in tu.diagnostics:
                if diag.severity >= 3:
                    logger.warning(f"编译报错 [{source_file}]:args={compiler_args}")
                    logger.warning(f"  ↳ {diag.spelling}")
                    break
        except Exception as e:
            logger.error(f"libclang 解析崩溃 [{source_file}]: {e}")
            return "FAILED"

        symbols_to_upsert = []
        refs_to_insert = []
        
        # 优化：路径缓存，大幅减少 os.path.realpath 调用
        last_raw_file_name = None
        last_realpath_file_name = None

        kind_def = (CursorKind.MACRO_DEFINITION,
                    CursorKind.FUNCTION_DECL,
                    CursorKind.VAR_DECL)

        # 遍历 AST 节点
        for node in tu.cursor.walk_preorder():

            if not node.location.file:
                continue  #跳过没有文件的节点

            raw_file_name = node.location.file.name
            s_line = node.location.line
            s_col = node.location.column

            #e_line,e_col 暂时没有用到
            # e_line = node.extent.end.line
            # e_col = node.extent.end.column
            
            # --- 优化点 1：缓存文件路径解析 ---尽量减少高耗时的os.path.realpath调用
            if raw_file_name == last_raw_file_name:
                realpath_file_name = last_realpath_file_name
            else:
                realpath_file_name = os.path.realpath(raw_file_name)
                last_raw_file_name = raw_file_name
                last_realpath_file_name = realpath_file_name
            
            # --- 优化点 2：减少 node.kind 获取次数 ---
            kind = node.kind
            
            # --- 角色 A: 提取定义 (Definitions) ---
            if  node.is_definition() or kind == CursorKind.MACRO_DEFINITION:
                
                usr = node.get_usr()
                if usr:
                    name = node.spelling or ""
                    symbols_to_upsert.append((realpath_file_name,
                                             s_line, s_col, s_line, s_col+len(name),
                                             usr, "def", name, kind.name))
                    continue


            # --- 提取 include 引用 ---
            if kind == CursorKind.INCLUSION_DIRECTIVE:
                exact_path = node.spelling
                if exact_path:
                    inc_file = node.get_included_file()
                    if inc_file and inc_file.name:
                        inc_path = os.path.realpath(inc_file.name)
                        symbols_to_upsert.append((realpath_file_name, 
                                                 s_line, s_col, s_line, s_col+len(inc_path),
                                                 inc_path, "inc", os.path.basename(inc_path), "INCLUSION_DIRECTIVE"))
                        continue

            # --- 角色 B: 提取引用 (References) ---
            is_ref_node = (
                kind.is_declaration() or
                kind.is_reference() or
                kind in (
                    CursorKind.DECL_REF_EXPR, 
                    CursorKind.MEMBER_REF_EXPR, 
                    CursorKind.MACRO_INSTANTIATION,
                    CursorKind.CALL_EXPR
                )
            )

            if is_ref_node:
                callee = node.referenced
                if callee:
                    usr = callee.get_usr()
                    if usr:
                        target_name = callee.spelling or ""
                        name = node.spelling or target_name or ""
                        symbols_to_upsert.append((realpath_file_name, 
                                                 s_line, s_col, s_line, s_col+len(name),
                                                 usr, "ref", name, callee.kind.name))
                        continue
            
            # 调试专用
            name = node.spelling or ""
            usr = node.get_usr()
            ref_usr = node.referenced.get_usr() if node.referenced else 'None'
            # if usr == "" and (ref_usr == "None" or ref_usr == ""):
            #    continue
            # if kind == CursorKind.UNEXPOSED_EXPR:
            #    continue
            logger.info(f"{os.path.basename(realpath_file_name)}|{s_line}|{s_col}|{s_line}|{s_col+len(name)}|usr={usr}|xxx|sp={node.spelling}|{kind.name}|ref_usr=[{ref_usr}]")

        # 实例化专属进程的 DB 防止锁冲突
        db = Database(workspace_dir)
        # 保存解析结果到数据库
        db.save_parse_result(source_file, mtime, symbols_to_upsert)
        db.close()
        
        return "SUCCESS"

    def run_index_mode(self, jobs):
        """主动索引模式（带增量更新与断点续传）"""
        import os, json, multiprocessing
        from concurrent.futures import ProcessPoolExecutor, as_completed
        
        workspace_dir = self.workspace_dir
        cc_path = os.path.join(workspace_dir, "compile_commands.json")
        
        if not os.path.exists(cc_path):
            logger.error("未找到 compile_commands.json")
            return

        with open(cc_path, 'r', encoding='utf-8') as f:
            commands = json.load(f)

        max_workers = 1 if jobs <= 0 else jobs

        self.cursor.execute('SELECT file_path, mtime FROM files WHERE status = "completed"')
        indexed_files = {row[0]: row[1] for row in self.cursor.fetchall()}

        tasks = []
        for cmd in commands:
            directory = cmd.get('directory', '')
            file_rel = cmd.get('file', '')
            abs_path = os.path.realpath(os.path.join(directory, file_rel))

            if not os.path.exists(abs_path):
                continue
                
            mtime = os.path.getmtime(abs_path)
            if abs_path in indexed_files and indexed_files[abs_path] >= mtime:
                continue
                
            tasks.append((cmd, workspace_dir))
            # 标记为 indexing 中状态
            self.update_file_status(abs_path, mtime, 'indexing', commit=False)

        self.conn.commit()

        total = len(tasks)
        if total == 0:
            logger.info("🎉 所有文件均已是最新状态，无需合并解析！")
            return

        logger.info(f"🚀 开始索引: 共 {len(commands)} 个文件，增量需要处理 {total} 个, 进程数: {max_workers}")

        completed = 0
        from time import time
        start_time = time()
        
        # ctrl + c 时能够自动安全退出
        with multiprocessing.Pool(processes=max_workers) as pool:
            # 使用 imap_unordered 可以极大地节省内存，它不会一次性把所有任务结果憋在内存里
            # 而是像流水线一样，谁先完成就先吐出谁的结果
            for res in pool.imap_unordered(Database.index_worker, tasks):
                completed += 1
                
                if res == "FAILED":
                    logger.error(f"某个文件处理失败，请查看上方详细日志")

                elapsed = time() - start_time
                progress = (completed / total) * 100
                logger.info(f"进度: [{completed}/{total}] {progress:.1f}% | 耗时: {elapsed:.2f}s")

    def close(self):
        self.conn.close()

    

if __name__ == '__main__':
    # 删除 pyclangd_index.db
    import os
    file = "test_kernel_def.c"
    workspace_dir = "/home/lc/py-clangd/server/test/cases/kernel/"
    db_path = workspace_dir+"pyclangd_index.db"
    if os.path.exists(db_path):
        os.remove(db_path)
    db = Database(workspace_dir)

    cmd_info = {
        "directory": workspace_dir,  # 编译执行的工作目录
        "file": file,    # 源文件的相对路径或绝对路径
        
        # 编译器及编译参数（注意一定要有 -I 指定头文件搜索路径，否则 clang 解析会报错）
        "arguments": [
            "clang",
            "-E",           # 告诉 clang 按照 C 语言解析 (-xc++ 就是 C++)
        ]
    }
    logger.info(f"开始索引: {cmd_info}")
    db.index_worker((cmd_info, ""))