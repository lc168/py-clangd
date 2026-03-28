#!/usr/bin/env python3
# mytodo 1. 增加对汇编文件的支持
# mytodo 2. 增加对宏展开的支持
# mytodo 3. 增加对c++分析的支持
# mytodo 4. 增加对函数调用关系的绘制
# mytodo 5. 增加对结构体变量的绘制
# mytodo 6. 修改index_worker(args) 和后面的参数清洗(ok)
# mytodo 7. lsp_did_save_db改成单文件更新(ok)
# mytodo 8. 继续梳理代码逻辑，考虑还有那些功能？？为什么宏函数好像还是漏掉了？
# mytodo 9, 引用读，写，执行？定义？分析？
# mytodo 10, 增加libclang的so库准备发布代码
# mytodo 11, 解决幽灵符号的问题

import sqlite3
import os
import time
import random
import functools
import logging
import subprocess
import clang_init
import shlex
from cindex import Index, CursorKind
import json
import multiprocessing
import threading
import hashlib

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
    _workspace_dir = None
    _core_bin_path = None
    _clang_include_path = None
    _clang_lib_path = None
    commands_map = {}  #文件名 -> 编译命令
    file_md5_map = {}  #文件名 -> md5 记录文件和md5的关系在编译之前，现在检查md5是否改变

    def __init__(self, workspace_dir = None, setup=False):
        # 如果传入了路径，就更新全局配置
        if workspace_dir:
            Database._workspace_dir = os.path.abspath(workspace_dir)
            # 自动推导核心二进制路径
            script_dir = os.path.dirname(os.path.abspath(__file__))
            Database._core_bin_path = os.path.join(script_dir, "core/build/PyClangd-Core")
            Database._clang_include_path = os.path.join(script_dir, "clang_include/include")
            Database._clang_lib_path = os.path.join(script_dir, "clang_libs/")

        if not Database._workspace_dir:
            raise ValueError("❌ 错误：Database 尚未初始化 workspace_dir！请在程序入口处先调用 Database(path)")

        self.workspace_dir = Database._workspace_dir
        self.db_path = os.path.join(self.workspace_dir, "pyclangd_index.db")
        
        self.conn = sqlite3.connect(self.db_path, timeout=60.0, check_same_thread=False, isolation_level="IMMEDIATE")
        self.cursor = self.conn.cursor()
        self.conn.execute('PRAGMA journal_mode=WAL;')
        self.conn.execute('PRAGMA synchronous=NORMAL;')
        # 3. 只有 setup 为 True 时才检查表结构
        if setup:
            self._setup()
            self.load_commands_map()

    def get_file_md5(self, file_path):
        with open(file_path, "rb") as f:
            # 直接使用 file_digest 自动处理分块逻辑
            digest = hashlib.file_digest(f, "md5")
        return digest.hexdigest()

    @with_retry()
    def _setup(self):
        # 表 B：位置与引用关系 (使用 UNIQUE 防爆发)
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS symbols (
                file_path TEXT,  -- 文件路径
                s_line INTEGER,  -- 开始行
                s_col INTEGER,  -- 开始列
                e_line INTEGER,  -- 结束行
                e_col INTEGER,  -- 结束列
                usr TEXT,  -- 如果role=inc，那么usr为头文件路径，如果role=def或者role=ref，usr为符号的USR
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
                md5 TEXT
            )''')
        
        # 表 D：源码与头文件的包含关系
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS includes (
                source_file TEXT,
                included_file TEXT,
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
    def show_res(self, res):
        for index, r in enumerate(res, start=1):
            logger.info(f"✅ {index:<8}:{r[0]}:{r[1]}:{r[2]}:{r[3]}:{r[4]}")

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
    def save_parse_result(self, source_file, source_md5, symbols, includes):
        # 1. 保存主文件 MD5
        mtime = os.path.getmtime(source_file)
        self.cursor.execute('INSERT OR REPLACE INTO files (file_path, md5, mtime) VALUES (?, ?, ?)', 
                            (source_file, source_md5, mtime))
        
        # 2. 刷新依赖并顺手算头文件的 MD5
        self.cursor.execute('DELETE FROM includes WHERE source_file = ?', (source_file,))
        if includes:
            self.cursor.executemany('INSERT OR IGNORE INTO includes (source_file, included_file) VALUES (?, ?)', includes)
            for _, included_file in includes:
                if os.path.exists(included_file):
                    inc_md5 = self.get_file_md5(included_file)
                    self.cursor.execute('INSERT OR REPLACE INTO files (file_path, md5) VALUES (?, ?)', 
                                        (included_file, inc_md5))

        # 3. 清除主文件旧符号，插入新符号
        self.cursor.execute('DELETE FROM symbols WHERE file_path = ?', (source_file,))
        if symbols:
            self.cursor.executemany('INSERT OR IGNORE INTO symbols VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)', symbols)

        self.conn.commit()

    # --- LSP 查询接口 (全部升级为单表查询) ---
    def get_sources_including(self, included_file):
        """查询依赖了指定头文件的所有源文件"""
        self.cursor.execute('SELECT DISTINCT file_path FROM symbols WHERE role = "inc" AND usr = ?', (included_file,))
        return [row[0] for row in self.cursor.fetchall()]

    def lsp_document_symbols_db(self, file_path):
        #mytodo bug需要修复，获取符号表
        logger.info(f"👉 获取符号表: {file_path}")
        self.cursor.execute('''
            SELECT name, kind, s_line, s_col, e_line, e_col 
            FROM symbols
            WHERE file_path = ? AND role = 'def' ORDER BY s_line ASC
        ''', (file_path,))
        ret = self.cursor.fetchall()
        return ret

    def lsp_workspace_symbols_db(self, query):
    # 全局搜索关键字
        logger.info(f"👉 全局搜索CTRL+T: {query}")
        self.cursor.execute('''
            SELECT name, file_path, s_line, s_col, usr 
            FROM symbols
            WHERE name LIKE ? AND role = 'def' LIMIT 100
        ''', (f"%{query}%",))
        ret = self.cursor.fetchall()
        self.show_res(ret)
        return ret


    def get_string_at_location(self, file_path, line, col):
        """
        获取文件中指定行列(坐标)处被包裹的字符串。
        带有完整的异常路径日志输出。
        """
        logger.info(f"🔍 尝试在源码提取字符串 -> {file_path}:{line}:{col}")
        try:
            if not os.path.exists(file_path):
                logger.warning(f"❌ 提取字符串失败: 物理文件不存在 [{file_path}]")
                return None
                
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                # 遍历找到目标行
                for i, current_line in enumerate(f):
                    if i + 1 == line:
                        target_line = current_line
                        break
                else:
                    logger.warning(f"❌ 提取字符串失败: 请求行号 [{line}] 超出了文件总行数")
                    return None
                    
            idx = col - 1
            if idx < 0 or idx >= len(target_line):
                logger.warning(f"❌ 提取字符串失败: 列号 [{col}] 越界 (当前行长度: {len(target_line)})")
                return None
                
            valid_chars = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-")
            
            if target_line[idx] not in valid_chars:
                # 尝试向左或向右偏移寻找有效字符
                if idx + 1 < len(target_line) and target_line[idx + 1] in valid_chars:
                    logger.info(f"⚠️ 坐标恰好落在边界/括号上，向右偏移 1 个字符")
                    idx += 1
                elif idx - 1 >= 0 and target_line[idx - 1] in valid_chars:
                    logger.info(f"⚠️ 坐标恰好落在边界/括号上，向左偏移 1 个字符")
                    idx -= 1
                else:
                    logger.warning(f"❌ 提取字符串失败: 坐标处的字符 '{target_line[idx]}' 不是合法的标识符组成部分")
                    return None

            # 双向扩展
            left = idx
            right = idx
            
            while left > 0 and target_line[left - 1] in valid_chars:
                left -= 1
            while right < len(target_line) - 1 and target_line[right + 1] in valid_chars:
                right += 1
                
            extracted_str = target_line[left:right+1].strip()
            
            if extracted_str:
                logger.info(f"✅ 成功从源码中提取到字符串: '{extracted_str}'")
                return extracted_str
                
            logger.warning("❌ 提取字符串失败: 提取结果为空字符串")
            return None
            
        except Exception as e:
            logger.error(f"❌ 提取字符串时发生崩溃级异常: {e}")
            return None

    def lsp_definition_db(self, file_path, line, col):
        # 获取定义
        """查定义核心逻辑：优先头文件跳转，后查 USR 跳跃（适配 Symbols 单表融合版架构）"""
        logger.info(f"👉 发起跳转: {file_path}:{line}:{col}")
        res = self.get_usr_at_location(file_path, line, col)
        logger.info(f"查询usr结果: {res}")

        if not res:
            logger.info(f"❌查找usr失败，添加字符串查找来兜底")
            # 添加字符串查找来兜底
            # 获取鼠标所在的字符串
            target_str = self.get_string_at_location(file_path, line, col)
            # 调用字符串查找函数
            ret = self.get_definitions_by_name(target_str)
            logger.info(f"查询字符串结果: {len(ret)}个")
            self.show_res(ret)
            return ret

        role, target_str = res
        if role == 'inc':
            logger.info(f"✅ 找到头文件: {target_str}")
            # 头文件路径直接就存在了 target_str 中
            return [(target_str, 1, 1, 1, 1)]
        elif role in ('ref', 'def'):
            # 无论是引用处按 F12，还是定义处自己按 F12，统统拿着 USR 去找它的 def 记录
            self.cursor.execute('''
                SELECT file_path, s_line, s_col, e_line, e_col 
                FROM symbols
                WHERE usr = ? AND role = 'def'
            ''', (target_str,))
            res = self.cursor.fetchall()
            if res:
                logger.info(f"✅ 查找定义结果: 找到 {len(res)} 个定义")
                self.show_res(res)
            else:
                logger.info(f"❌ 查找定义失败: 坐标未命或未找到定义")

            return res

        return []

    def lsp_references_db(self, file_path, line, col):
        # mymark 获取变量引用
        """查引用核心逻辑"""
        logger.info(f"👉 查找引用: {file_path}:{line}:{col}")
        usr = self.get_usr_at_location(file_path, line, col)
        if usr:
            logger.info(f"找到引用usr={usr}")
            res = self.get_references_by_usr(usr)
            if res:
                logger.info(f"✅ 查找引用结果: 找到 {len(res)} 个引用")
                self.show_res(res)
            else:
                logger.info(f"❌ 查找引用失败: 坐标未命或未找到引用")
            return res
        else:
            logger.info(f"没有找到:{file_path}:{line}:{col}的usr")
        return []

    def lsp_did_save_db(self, file_path):
        # 计算文件md5值
        current_md5 = self.get_file_md5(file_path)
        self.cursor.execute('SELECT md5 FROM files WHERE file_path = ?', (file_path,))
        res = self.cursor.fetchone()
        
        if res and res[0] == current_md5:
            logger.info(f"主文件未变，跳过编译: {file_path}")
            return

        logger.info(f"开始增量分析并更新: {file_path}")

        # 查出依赖库，检查变脏的头文件
        self.cursor.execute('SELECT included_file FROM includes WHERE source_file = ?', (file_path,))
        dependencies = [row[0] for row in self.cursor.fetchall()]

        dirty_headers = []
        for inc_file in dependencies:
            logger.info(f"发现依赖文件: {inc_file}")
            if not os.path.exists(inc_file): continue
            
            inc_current_md5 = self.get_file_md5(inc_file)
            self.cursor.execute('SELECT md5 FROM files WHERE file_path = ?', (inc_file,))
            inc_old_md5_res = self.cursor.fetchone()
            
            # 如果变脏了，立刻清理它曾经产生的所有符号！
            if not inc_old_md5_res or inc_old_md5_res[0] != inc_current_md5:
                dirty_headers.append(inc_file)
                logger.info(f"删除头文件变脏的符号: {inc_file}")
                self.cursor.execute('DELETE FROM symbols WHERE file_path = ?', (inc_file,))
        
        self.conn.commit()
        
        if dirty_headers:
            logger.info(f"检测到 {len(dirty_headers)} 个头文件发生变化，已清理旧幽灵符号。")
        logger.info(f"开始重新索引: {file_path}")
        def reindex_task():
            cmd_info = self.commands_map.get(file_path)
            if not cmd_info: 
                logger.info(f"没有找到编译命令: {file_path}")
                return
            status, source_file = self.index_worker(cmd_info)
            if status == "SUCCESS":
                logger.info(f"✅ 更新成功: {source_file}")
                # 缺少保存会数据库和文件状态更新的动作？
            else:
                logger.info(f"❌ 更新失败: {source_file}")

        reindex_task()
        #threading.Thread(target=reindex_task, daemon=True).start()

    def is_macro(self, usr):
        """判断一个符号是否为宏"""
        self.cursor.execute('SELECT kind FROM symbols WHERE usr = ?', (usr,))
        res = self.cursor.fetchone()
        return res and res[0] == 'MACRO_DEFINITION'

    def lsp_code_action_db(self, file_path, line, col):
        # mymark lsp_code_action_db 目前只看是不是宏，这个功能基本是正常的！
        """查支持的 Code Action 操作 (目前只看是不是宏)"""
        ret = self.get_usr_at_location(file_path, line, col)
        if ret and ret[1] and self.is_macro(ret[1]):
            return "expand_macro"
        return None

    def lsp_execute_command_db(self, command, args, commands_map):
        #mymark 以后处理宏展开功能
        """执行后台复杂指令，比如宏展开"""
        if command == "pyclangd.expand_macro":
            return {"error": "Unknown command"}

    def get_usr_at_location(self, file_path, line, col):
        """核心：查询特定坐标下的符号 USR (精准跳转的基础)"""
        # 匹配逻辑：s_line == line 且 s_col <= col <= e_col
        # ⭐ 优化：优先匹配 role != 'def' (引用处)，并按宽度升序排列 (最精准的优先)
        self.cursor.execute('''
            SELECT role, usr FROM symbols
            WHERE file_path = ? AND s_line = ? AND s_col <= ? AND e_col >= ?
            ''', (file_path, line, col, col))
        res = self.cursor.fetchone()
        return res

    def get_definitions_by_usr(self, usr):
        # myark 这个函数在项目中没有使用，但是在其他测试验证文件中使用了
        """通过 USR 精确查找定义位置"""
        self.cursor.execute('''
            SELECT DISTINCT file_path, s_line, s_col, e_line, e_col 
            FROM symbols WHERE usr = ? AND role = 'def'
        ''', (usr,))
        return self.cursor.fetchall()

    def get_references_by_usr(self, usr):
        """查 USR 对应的所有引用位置（包含声明/定义、调用、读取等）"""
        # 这个是查询所有引的的关键函数
        self.cursor.execute('''
            SELECT DISTINCT file_path, s_line, s_col, e_line, e_col 
            FROM symbols WHERE usr = ? AND role = 'ref'
        ''', (usr,))
        return self.cursor.fetchall()

    def get_references_by_name(self, name):
        # mymark 这个函数在项目中没有使用，可以删除
        """查名字对应的所有引用位置 (作为兜底)"""
        self.cursor.execute('''
            SELECT DISTINCT file_path, s_line, s_col, e_line, e_col 
            FROM symbols
            WHERE name = ? AND role = 'ref'
        ''', (name,))
        return self.cursor.fetchall()

    def get_definitions_by_name(self, name):
        # mymark 这个函数在项目中没有使用，可以删除
        """查名字对应的所有定义位置 (作为兜底)"""
        self.cursor.execute('''
            SELECT DISTINCT file_path, s_line, s_col, e_line, e_col 
            FROM symbols
            WHERE name = ? AND role = 'def'
        ''', (name,))
        return self.cursor.fetchall()

    # =========================================================================
    # --- 构建索引与解析体系 (从原来的 pyclangd_server 中抽取) ---
    # =========================================================================

    @staticmethod
    def clean_compiler_args(cmd_info):#mymark 这里参数需要裁剪一下
        """清洗并组装传递给 libclang 的编译参数"""
        #print("清洗并组装传递给 libclang 的编译参数:", cmd_info)

        directory = cmd_info.get('directory', '')
        file_rel = cmd_info.get('file', '')
        source_file = os.path.realpath(os.path.join(directory, file_rel))

        raw_args = cmd_info.get('arguments')
        if not raw_args:
            command_str = cmd_info.get('command', '')
            if command_str: raw_args = shlex.split(command_str)
            else: raw_args = []

        """清洗并组装传递给 libclang 的编译参数"""
        compiler_args = []
        skip_next = False

        # 这些前缀的参数在 LibTooling 中极易引起报错
        forbidden_prefixes = (
           'ssss', #测试参数
           "sssss" #测试参数
        )
        
        # 必须剔除的精确匹配参数 (会导致 -dependency-file 报错)
        forbidden_exact = (
           'ssss', #测试参数
           "sssss" #测试参数
        )

        # 跳过当前和下一个参数
        forbidden_skip_next = (
            'sssssss', #测试参数
        )

        for arg in raw_args[1:]:
            if skip_next:
                skip_next = False
                continue
            if arg in forbidden_skip_next:
                skip_next = True
                continue
            if arg in forbidden_exact or arg.startswith(forbidden_prefixes):
                continue
            # 过滤掉源码文件路径本身（LibTooling 会在命令行第一项处理它）
            if os.path.basename(arg) == os.path.basename(source_file):
                continue
            compiler_args.append(arg)

        # mymark 先手动添加参数，以后优化
        compiler_args.extend(['-I', Database._clang_include_path])
        # compiler_args.append('--target=aarch64-linux-gnu')

        #print("清洗并组装传递给 libclang 的编译参数:", compiler_args)
        return source_file, compiler_args

    # 需求2：调用 C++ 核心进行解析
    @staticmethod
    def index_parse_cpp(source_file, compiler_args):
        """调用 PyClangd-Core 替代 libclang python 绑定"""
        if not Database._core_bin_path or not os.path.exists(Database._core_bin_path):
            logger.error(f"找不到核心程序: {Database._core_bin_path}")
            return "FAILED", []

        # 构造命令: ./PyClangd-Core source.c -- args...
        cmd = [Database._core_bin_path, source_file, "--"] + compiler_args
        
        # 动态编译版需要设置动态库搜索路径 #mymark 待修改
        env = os.environ.copy()
        env["LD_LIBRARY_PATH"] = Database._clang_lib_path + ":" + env.get("LD_LIBRARY_PATH", "")

        symbols_to_upsert = []
        includes_to_upsert = []
        try:
            # 执行并获取输出
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
            # 读取输出
            stdout_data, stderr_data = process.communicate()
            
            if process.returncode != 0:
                # 打印出具体的错误原因，方便我们定位是少了头文件还是参数不对
                logger.error(f"❌ C++ 核心解析失败 [{cmd}]\n{stderr_data}")
                return "FAILED", stderr_data

            for line in stdout_data.splitlines():
                line = line.strip()
                if not line.startswith('{'): continue
                
                try:
                    data = json.loads(line)
                    kind_raw = data.get("kind", "")
                    
                    if kind_raw == "inc":
                        role = "inc"
                    elif "DEF" in kind_raw or "MACRO_DEF" in kind_raw:
                        role = "def" 
                    else:
                        role = "ref"
                    
                    f_path = data.get("file", source_file)
                    name = data.get("name", "")
                    s_line = data.get("line", 0)
                    s_col = data.get("col", 0)
                    usr = data.get("usr", "")

                    # 收集依赖：源文件包含的头文件
                    if role == "inc" and f_path and usr:
                        includes_to_upsert.append((f_path, usr))
                    
                    # 组合成存储格式
                    symbols_to_upsert.append((
                        f_path, s_line, s_col, s_line, s_col + len(name),
                        usr,
                        role, name, kind_raw
                    ))
                except Exception as e:
                    logger.warning(f"解析 JSON 行失败: {line} \n error: {e}")

            process.wait()
            if process.returncode != 0:
                logger.error(f"PyClangd-Core 返回异常状态码: {process.returncode}")
                return "FAILED", [], []

            return "SUCCESS", symbols_to_upsert, includes_to_upsert

        except Exception as e:
            logger.exception(f"执行 PyClangd-Core 崩溃: {e}")
            return "FAILED", [], []

    @staticmethod
    def index_worker(cmd_info):
        """核心解析工人进程"""
        # 注意：这里需要确保 Database._core_bin_path 已在主进程设置
        source_file, compiler_args = Database.clean_compiler_args(cmd_info)
        # 使用 C++ 核心进行解析
        # 接收三个返回值
        status, symbols, includes = Database.index_parse_cpp(source_file, compiler_args)

        if status == "FAILED":
            return "FAILED", source_file
        else:
            # 需求1：使用无参初始化（前提是主进程已初始化过）
            db = Database()
            source_md5 = db.get_file_md5(source_file)
            # 传入 md5 和 includes
            db.save_parse_result(source_file, source_md5, symbols, includes)
            db.close()
            return "SUCCESS", source_file

    def run_index_mode(self, jobs):
        """主动索引模式（带增量更新与断点续传）"""

        from concurrent.futures import ProcessPoolExecutor, as_completed
        
        workspace_dir = self.workspace_dir
        cc_path = os.path.join(workspace_dir, "compile_commands.json")
        
        if not os.path.exists(cc_path):
            logger.error("未找到 compile_commands.json")
            return

        with open(cc_path, 'r', encoding='utf-8') as f:
            commands = json.load(f)

        # 扫描整个commands 一旦发现文件重复，报错
        # 重复文件标记数量
        repeat_count = 0
        file_set = set()
        for cmd in commands:
            file_rel = cmd.get('file', '')
            abs_path = os.path.realpath(os.path.join(cmd.get('directory', ''), file_rel))
            if abs_path in file_set:
                logger.error(f"文件 {abs_path} 重复出现！！！")
                repeat_count += 1
            file_set.add(abs_path)

        if repeat_count > 0:
            logger.error(f"发现 {repeat_count} 个重复文件，请注意！！！")

        max_workers = 1 if jobs <= 0 else jobs

        self.cursor.execute('SELECT file_path, mtime FROM files')
        indexed_files = {row[0]: row[1] for row in self.cursor.fetchall()}

        tasks = []
        for cmd in commands:
            directory = cmd.get('directory', '')
            file_rel = cmd.get('file', '')
            abs_path = os.path.realpath(os.path.join(directory, file_rel))

            if abs_path.endswith(('.s', '.S')):
                logger.info(f"文件 {abs_path} 是汇编文件，跳过解析")
                continue

            if not os.path.exists(abs_path):
                logger.error(f"文件 {abs_path} 不存在")
                continue
            
            mtime = os.path.getmtime(abs_path)
            # 如果文件存在且mtime相同，说明文件没有被修改，跳过解析
            if abs_path in indexed_files and indexed_files[abs_path] == mtime:
                logger.info(f"文件 {abs_path} 已是最新状态，无需合并解析！")
                continue

            tasks.append(cmd)

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
            for res, finished_file in pool.imap_unordered(Database.index_worker, tasks):
                completed += 1
                
                if res == "FAILED":
                    logger.error(f"某个文件处理失败，请查看上方详细日志 {finished_file}")

                elapsed = time() - start_time
                progress = (completed / total) * 100
                logger.info(f"进度: [{completed}/{total}] {progress:.1f}% | 耗时: {elapsed:.2f}s {finished_file}")

    def close(self):
        self.conn.close()

