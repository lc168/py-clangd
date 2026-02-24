import os
import sys
import logging
import multiprocessing
import json
import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed

try:
    from pygls.server import LanguageServer
    from lsprotocol.types import (
        TEXT_DOCUMENT_DEFINITION, TEXT_DOCUMENT_DOCUMENT_SYMBOL, WORKSPACE_SYMBOL,
        Location, Range, Position, SymbolInformation, SymbolKind, DocumentSymbol, MessageType
    )
    from lsprotocol.types import TEXT_DOCUMENT_DID_SAVE
except ImportError as e:
    print(f"Error: 缺少基础库 {e}, 请执行 pip install pygls lsprotocol", file=sys.stderr)
    sys.exit(1)

from database import Database
from cindex import Index, Cursor, CursorKind, Config

# 日志定向到 stderr，VS Code 才能在输出窗口显示
logging.basicConfig(level=logging.INFO, stream=sys.stderr, format='%(levelname)s: %(message)s')
logger = logging.getLogger("PyClangd")

# --- 独立 Worker 函数 (必须定义在顶层以支持序列化) ---
def index_worker(cmd_info, lib_path, db_path):
    """
    单文件索引任务：由子进程调用
    """
    # --- 1. 路径预处理：使用 realpath 消除软链接影响 ---
    directory = cmd_info.get('directory', '')
    file_rel = cmd_info.get('file', '')
    source_file = os.path.realpath(os.path.join(directory, file_rel)) #
    
    # 暂时跳过汇编文件
    if source_file.endswith(('.S', '.s')):
        logger.info(f"跳过汇编文件: {source_file}")
        return True

    if not os.path.exists(source_file):
        # 遇到错误，向父进程返回“毒药”字符串
        logger.critical(f"File not found: {source_file}")

    db = Database(db_path)
    idx = Index.create()

    # --- 2. 终极参数清洗：精准剔除毒药参数 ---
    raw_args = cmd_info.get('arguments', [])
    # 提取源文件的纯文件名，比如 "bin2c.c"
    source_basename = os.path.basename(source_file)

    compiler_args = []
    skip_next = False  # ⭐ 必须要有这个状态位！

    for arg in raw_args[1:]:
        if skip_next:
            skip_next = False
            continue
            
        # 1. 彻底干掉输出指令 -o 及其后面的文件名
        if arg == '-o':
            skip_next = True
            continue
            
        # 2. 干掉编译动作指令 -c 和 -S
        if arg in ('-c', '-S'):
            continue
            
        # 3. 干掉重复的源文件
        if os.path.basename(arg) == source_basename:
            continue
            
        # 4. 干掉 Clang 不认识的 GCC 专属参数
        if arg in ('-fconserve-stack', '-fno-var-tracking-assignments') or arg.startswith('-mabi='):
            continue
        
        compiler_args.append(arg)

    compiler_args.append('-fsyntax-only')
    # ⭐ 新增：解除错误数量限制！哪怕有 1000 个不认识的 GCC 参数，也要把 AST 树给我建完！
    compiler_args.append('-ferror-limit=0')

    # === 【新增】：对付老旧内核代码的杀手锏 ===
    compiler_args.append('-Wno-error')               # 绝不把警告升级为错误
    compiler_args.append('-Wno-strict-prototypes')   # 忽略没有原型的函数报错
    compiler_args.append('-Wno-implicit-int')        # 忽略老代码没写返回值类型的报错
    compiler_args.append('-Wno-unknown-warning-option') # <--- 【新增】：让 Clang 忽略它不认识的 GCC 参数

    # ⭐ 新增：动态识别交叉编译架构 (从 raw_args[0] 也就是编译器名称中提取)
    compiler_path = raw_args[0] if raw_args else ''
    if 'aarch64' in compiler_path or 'arm64' in compiler_path:
        compiler_args.append('--target=aarch64-linux-gnu')
    elif 'arm' in compiler_path:
        compiler_args.append('--target=arm-linux-gnueabihf')

    # ⭐ 核心修复：强行注入 LLVM 22 的内置头文件路径
    # 请把下面的路径替换成你用 ls 真实看到的路径
    builtin_includes = '/home/lc/llvm22/lib/clang/22/include' 
    compiler_args.append('-isystem')
    compiler_args.append(builtin_includes)

    try:
        # 1. 事务开始：标记正在索引并清理旧数据
        mtime = os.path.getmtime(source_file)
        db.update_file_status(source_file, mtime, 'indexing')
        db.prepare_file_reindex(source_file)
        
        #logger.info(f"正在编译 [{source_file}]:args={compiler_args}")
        tu = idx.parse(source_file, args=compiler_args, options=0x01)
        
        for diag in tu.diagnostics:
            if diag.severity >= 3:
                logger.warning(f"编译报错 [{source_file}]:args={compiler_args}")
                logger.warning(f"语法报错(已忽略) [{source_file}]: {diag.spelling}")


        symbols_to_upsert = []
        refs_to_insert = []

        for node in tu.cursor.walk_preorder():
            if not node.location.file: continue
            
            # 【核心修改点】：去掉 samefile 限制，允许抓取头文件里的内联函数！
            # 但我们只存入当前 source_file 能够“看到”的符号位置
            node_file = os.path.realpath(node.location.file.name)
            
            # 角色 A: 定义 (def)
            if node.is_definition() and node.kind in (
                CursorKind.FUNCTION_DECL, CursorKind.CXX_METHOD,
                CursorKind.STRUCT_DECL, CursorKind.CLASS_DECL,
                CursorKind.VAR_DECL, CursorKind.MACRO_DEFINITION
            ):
                usr = node.get_usr()
                if not usr: continue
                # 存入字典
                symbols_to_upsert.append((usr, node.spelling, node.kind.name))
                # 存入位置 (role = 'def')
                refs_to_insert.append((
                    usr, None, node_file, 
                    node.extent.start.line, node.extent.start.column,
                    node.extent.end.line, node.extent.end.column, 'def'
                ))

            # 角色 B: 调用关系 (call)
            elif node.kind == CursorKind.CALL_EXPR:
                callee = node.referenced
                if callee:
                    usr = callee.get_usr()
                    if not usr: continue
                    
                    # 向上找父亲，看看是谁在调用它 (Caller)
                    parent = node.semantic_parent
                    caller_usr = parent.get_usr() if (parent and parent.kind.is_declaration()) else None
                    
                    # 补充字典 (防止被调用的库函数不在字典里)
                    symbols_to_upsert.append((usr, callee.spelling, callee.kind.name))
                    # 存入位置 (role = 'call')
                    refs_to_insert.append((
                        usr, caller_usr, node_file,
                        node.extent.start.line, node.extent.start.column,
                        node.extent.end.line, node.extent.end.column, 'call'
                    ))

        # 2. 事务提交：批量写入并标记完成
        db.batch_insert_v2(symbols_to_upsert, refs_to_insert)
        db.update_file_status(source_file, mtime, 'completed')
        return True
    except Exception as e:
        # === 【修改】：遇到 Python 级别崩溃，只牺牲当前文件，保全大局 ===
        logger.error(f"❌ 索引单文件崩溃 [{source_file}]: {repr(e)}")
        db.update_file_status(source_file, mtime, 'failed')
        return False  # 返回 False 即可，不要返回 "FATAL_ERROR" 导致主进程自杀
    finally:
        db.close()

# --- LSP 服务端类 ---
import threading

# 在 PyClangdServer 初始化时，存一下命令字典，方便单文件查询
class PyClangdServer(LanguageServer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.db = None
        self.lib_path = None
        self.commands_map = {}

    def load_commands_map(self, workspace_dir):
        """启动服务端时调用，缓存编译命令字典"""
        cc_path = os.path.join(workspace_dir, "compile_commands.json")
        if os.path.exists(cc_path):
            with open(cc_path, 'r') as f:
                cmds = json.load(f)
                for c in cmds:
                    abs_path = os.path.realpath(os.path.join(c.get('directory', ''), c.get('file', '')))
                    self.commands_map[abs_path] = c

ls = PyClangdServer("pyclangd", "1.0.0")

@ls.feature(TEXT_DOCUMENT_DID_SAVE)
def lsp_did_save(server: PyClangdServer, params):
    """当 VS Code 里按下 Ctrl+S，触发单文件增量更新"""
    file_path = os.path.normpath(params.text_document.uri.replace("file://", ""))
    
    cmd_info = server.commands_map.get(file_path)
    if not cmd_info:
        logger.warning(f"增量跳过: {file_path} 不在 compile_commands 中")
        return

    server.show_message_log(f"触发增量索引: {os.path.basename(file_path)}")

    # 启动后台线程跑解析，坚决不阻塞 LSP 主线程的 UI 响应
    def reindex_task():
        success = index_worker(cmd_info, server.lib_path, server.db.db_path)
        if success is True:
            server.show_message_log(f"✅ 更新成功: {os.path.basename(file_path)}")
        else:
            server.show_message_log(f"❌ 更新失败: {os.path.basename(file_path)}")

    threading.Thread(target=reindex_task, daemon=True).start()

@ls.feature(TEXT_DOCUMENT_DOCUMENT_SYMBOL)
def lsp_document_symbols(server: PyClangdServer, params):
    """大纲视图：从数据库秒级查询"""
    file_path = os.path.normpath(params.text_document.uri.replace("file://", ""))
    results = server.db.get_symbols_by_file(file_path)
    
    symbols = []
    for name, kind_id, sl, sc, el, ec in results:
        kind_map = {CursorKind.FUNCTION_DECL.value: SymbolKind.Function, 
                    CursorKind.VAR_DECL.value: SymbolKind.Variable,
                    CursorKind.MACRO_DEFINITION.value: SymbolKind.Constant}
        kind = kind_map.get(kind_id, SymbolKind.Field)
        
        rng = Range(start=Position(line=sl-1, character=sc-1), end=Position(line=el-1, character=ec-1))
        symbols.append(DocumentSymbol(name=name, kind=kind, range=rng, selection_range=rng, children=[]))
    return symbols

@ls.feature(WORKSPACE_SYMBOL)
def lsp_workspace_symbols(server: PyClangdServer, params):
    """全局符号搜索：Ctrl+T"""
    results = server.db.search_symbols(params.query)
    return [SymbolInformation(
        name=n, kind=SymbolKind.Function,
        location=Location(uri=f"file://{fp}", range=Range(start=Position(line=sl-1, character=sc-1), 
                                                          end=Position(line=sl-1, character=sc-1+len(n))))
    ) for n, fp, sl, sc, usr in results]


import re

# 在 PyClangdServer 类中修改或添加定义跳转函数
@ls.feature(TEXT_DOCUMENT_DEFINITION)
def lsp_definition(server: PyClangdServer, params):
    """跳转到定义：纯数据库查表，0 毫秒解析延迟"""
    uri = params.text_document.uri
    file_path = os.path.normpath(uri.replace("file://", ""))
    line_idx = params.position.line
    col_idx = params.position.character
    logger.info(f"跳转到定义:点击{file_path}:{line_idx},{col_idx}:")
    try:
        # 1. 直接读取本地文件提取单词
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
            if line_idx >= len(lines): return None
            current_line = lines[line_idx]
            
            # 使用正则从光标位置向前后扩展，提取完整的标识符
            # 匹配字母、数字、下划线
            word_match = None
            for m in re.finditer(r'[a-zA-Z_][a-zA-Z0-9_]*', current_line):
                if m.start() <= col_idx <= m.end():
                    word_match = m.group()
                    break
            
            if not word_match:
                return None

        # 2. 拿着单词直接去数据库里“撞”
        # 这里的速度是索引级的，对于 Linux 内核这种量级也是瞬间完成
        logger.info(f"跳转到定义:查找{word_match}")
        results = server.db.get_definitions_by_name(word_match)
        
        if not results:
            return None

        # 3. 构造返回位置
        locations = []
        for fp, sl, sc, el, ec in results:
            locations.append(Location(
                uri=f"file://{fp}",
                range=Range(
                    start=Position(line=sl-1, character=sc-1),
                    end=Position(line=el-1, character=ec-1)
                )
            ))
        
        # 如果有多个重名定义（比如不同结构体里的同名成员），VS Code 会弹出一个列表供用户选择
        return locations

    except Exception as e:
        logger.error(f"跳转定义失败: {e}")
        return None


# --- 逻辑控制 ---
def run_index_mode(workspace_dir, lib_path, jobs):
    """主动索引模式（带增量更新与断点续传）"""
    db_path = os.path.join(workspace_dir, "pyclangd_index.db")
    cc_path = os.path.join(workspace_dir, "compile_commands.json")
    
    if not os.path.exists(cc_path):
        logger.error("未找到 compile_commands.json")
        return

    with open(cc_path, 'r') as f:
        commands = json.load(f)

    max_workers = 1 if jobs <= 0 else jobs

    logger.info("主进程正在初始化数据库表结构...")
    init_db = Database(db_path, is_main=True)
    
    # --- 【新增】：获取数据库中已完成的文件状态 ---
    init_db.cursor.execute("SELECT file_path, mtime FROM files WHERE status='completed'")
    indexed_files = {row[0]: row[1] for row in init_db.cursor.fetchall()}
    init_db.close()

    # --- 【新增】：过滤出真正需要跑的增量任务 ---
    commands_to_run = []
    for cmd in commands:
        full_path = os.path.realpath(os.path.join(cmd.get('directory', ''), cmd.get('file', '')))
        if not os.path.exists(full_path): continue
        
        curr_mtime = os.path.getmtime(full_path)
        # 只要没记录过，或者时间戳变了，就加入重刷队列
        if full_path not in indexed_files or indexed_files[full_path] != curr_mtime:
            commands_to_run.append(cmd)

    if not commands_to_run:
        logger.info("🎉 所有文件均已是最新状态，无需重新索引！")
        return

    logger.info(f"🚀 开始索引: 共 {len(commands)} 个文件，增量需要处理 {len(commands_to_run)} 个, 进程数: {max_workers}")

    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        # 注意这里传的是 commands_to_run
        futures = [executor.submit(index_worker, cmd, lib_path, db_path) for cmd in commands_to_run]
        done = 0
        for future in as_completed(futures):
            result = future.result() 
            if result == "FATAL_ERROR":
                logger.critical("🛑 主进程收到致命错误报告，立即退出！")

                logger.critical("🛑 主进程收到致命错误报告，正在清理子进程并退出...")
                # 1. 遍历当前存活的所有子进程，发送强制终止信号
                for p in multiprocessing.active_children():
                    p.terminate()
                # 2. 退出主进程
                os._exit(1)
                
            done += 1
            if done % 5 == 0 or done == len(commands_to_run):
                logger.info(f"进度: [{done}/{len(commands_to_run)}] {done/len(commands_to_run)*100:.1f}%")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-d", "--directory")
    parser.add_argument("-l", "--libpath")
    parser.add_argument("-s", "--server", action="store_true")
    parser.add_argument("-j", "--jobs", type=int, default=0)
    args = parser.parse_args()

    if args.libpath:
        # # 1. 先只导入 Config，不要碰 Index 或 Cursor
        # from cindex import Config
        try:
            Config.set_library_path(args.libpath)
            logger.info(f"设置 LLVM 22 库路径: {args.libpath}")
        except Exception as e:
            logger.critical(f"main 无法加载 LLVM 库: {e}")
            logger.critical("发现致命配置错误，直接退出")
            sys.exit(1) # 发现致命配置错误，直接退出

    if args.server:
        ls.lib_path = args.libpath
        ls.load_commands_map(args.directory)

        db_path = os.path.join(args.directory, "pyclangd_index.db")
        if os.path.exists(db_path):
            ls.db = Database(db_path)
            logger.info("LSP Server 加载数据库成功")
        ls.start_io()
    else:
        run_index_mode(args.directory, args.libpath, args.jobs)

if __name__ == "__main__":
    main()