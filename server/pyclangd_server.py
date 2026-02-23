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
        return "FATAL_ERROR"

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
        # 解析时传入清洗后的参数
        logger.info(f"正在编译1[{source_file}]: args={compiler_args}")
        # 开启 0x01 (DetailedPreprocessingRecord) 以支持宏分析
        tu = idx.parse(source_file, args=compiler_args, options=0x01)
        logger.info(f"正在编译2")
        # 调试：检查解析是否有致命错误
        for diag in tu.diagnostics:
            if diag.severity >= 3: # 严重错误或致命错误
                logger.error(f"解析警告/错误 [{source_file}]: {diag}")
                # 遇到错误，向父进程返回“毒药”字符串
                return "FATAL_ERROR"

# ⭐ 新增：准备两个内存列表来装数据，绝不提前写库！
        defs_to_insert = []
        calls_to_insert = []
        current_func_usr = None

        for node in tu.cursor.walk_preorder():
            if node.location.file:
                node_file = os.path.realpath(node.location.file.name) 
                if not os.path.samefile(node.location.file.name, source_file):
                   continue
                
                # 收集符号定义
                if node.is_definition() and node.kind in (
                    CursorKind.FUNCTION_DECL, CursorKind.CXX_METHOD,
                    CursorKind.STRUCT_DECL, CursorKind.CLASS_DECL,
                    CursorKind.VAR_DECL, CursorKind.MACRO_DEFINITION
                ):
                    current_func_usr = node.get_usr()
                    # 存入列表，而不是直接调 db
                    defs_to_insert.append((
                        current_func_usr, node.spelling, node.kind.value, source_file,
                        node.extent.start.line, node.extent.start.column,
                        node.extent.end.line, node.extent.end.column
                    ))

                # 收集调用关系
                if node.kind == CursorKind.CALL_EXPR and current_func_usr:
                    callee = node.referenced
                    if callee:
                        # 存入列表
                        calls_to_insert.append((
                            current_func_usr, callee.get_usr(), source_file, node.location.line
                        ))

        # ⭐ 所有的纯计算都做完了，最后花 1 毫秒瞬间砸进数据库！
        db.batch_insert(defs_to_insert, calls_to_insert)
        return True
    except Exception as e:
        # ⭐ 强行打印真正的异常原因！
        logger.critical(f"[{source_file}] index_worker 抛出异常: {repr(e)}")
        # 遇到错误，向父进程返回“毒药”字符串
        return "FATAL_ERROR"
    finally:
        db.close()

# --- LSP 服务端类 ---
class PyClangdServer(LanguageServer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.db = None

ls = PyClangdServer("pyclangd", "1.0.0")

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
    """主动索引模式"""
    db_path = os.path.join(workspace_dir, "pyclangd_index.db")
    #删除之前的旧的pyclangd_index.db 文件
    if os.path.exists(db_path):
        os.remove(db_path)

    cc_path = os.path.join(workspace_dir, "compile_commands.json")
    if not os.path.exists(cc_path):
        logger.error("未找到 compile_commands.json")
        return

    with open(cc_path, 'r') as f:
        commands = json.load(f)

    # 按照你的要求：手动控制 jobs
    if jobs <= 0:
        logger.error("请注意 jobs <= 0 所以强制max_workers = 1")
        max_workers = 1
    else:
        max_workers = jobs

    # ⭐ 新增：主进程负责提前建表并开启 WAL 模式！
    logger.info("主进程正在初始化数据库表结构...")
    init_db = Database(db_path, is_main=True)
    init_db.close() # 建完表立刻释放锁

    logger.info(f"🚀 开始索引: {len(commands)} 个文件, 进程数: {max_workers}")

    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(index_worker, cmd, lib_path, db_path) for cmd in commands]
        done = 0
        for future in as_completed(futures):
            # 获取子进程的返回值
            result = future.result() 
            
            # 如果收到毒药，主进程立刻终止整个程序！
            if result == "FATAL_ERROR":
                logger.critical("🛑 主进程收到致命错误报告，立即退出！")
                os._exit(1) # 绝对不要用 sys.exit(1)
                
            done += 1
            if done % 20 == 0 or done == len(commands):
                logger.info(f"进度: {done/len(commands)*100:.1f}")

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
        db_path = os.path.join(args.directory, "pyclangd_index.db")
        if os.path.exists(db_path):
            ls.db = Database(db_path)
            logger.info("LSP Server 加载数据库成功")
        ls.start_io()
    else:
        run_index_mode(args.directory, args.libpath, args.jobs)

if __name__ == "__main__":
    main()