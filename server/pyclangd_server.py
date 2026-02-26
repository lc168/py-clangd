import os
import sys
import logging
import multiprocessing
import json
import argparse
import shlex
from concurrent.futures import ProcessPoolExecutor, as_completed

try:
    from pygls.server import LanguageServer
    from lsprotocol.types import (
        TEXT_DOCUMENT_DEFINITION, TEXT_DOCUMENT_DOCUMENT_SYMBOL, WORKSPACE_SYMBOL,
        TEXT_DOCUMENT_REFERENCES,
        Location, Range, Position, SymbolInformation, SymbolKind, DocumentSymbol, MessageType
    )
    from lsprotocol.types import TEXT_DOCUMENT_DID_SAVE
except ImportError as e:
    print(f"Error: 缺少基础库 {e}, 请执行 pip install pygls lsprotocol", file=sys.stderr)
    sys.exit(1)

from database import Database
from cindex import Index, Cursor, CursorKind, Config

# 日志定向到 stderr，VS Code 才能在输出窗口显示
logging.basicConfig(level=logging.WARNING,
                    stream=sys.stderr,
                    format='%(levelname)s [%(name)s]: %(message)s'
                    )

#创建PyClangd标记的打印
logger = logging.getLogger("PyClangd")
# # 单独把我们自己的 PyClangd 设置为 INFO 级别，这样只有我们的进度条会显示
logger.setLevel(logging.INFO)

# --- 独立 Worker 函数 (必须定义在顶层以支持序列化) ---
def index_worker(cmd_info, lib_path):
    # --- 1. 路径预处理：使用 realpath 消除软链接影响 ---
    directory = cmd_info.get('directory', '')
    file_rel = cmd_info.get('file', '')
    source_file = os.path.realpath(os.path.join(directory, file_rel)) 
    
    # ⭐ 核心修复：必须切换到该文件所属的编译目录，否则 realpath(header) 会基于 py-clangd 目录解析！
    if directory:
        os.chdir(directory)
    
    # 暂时跳过汇编文件
    if source_file.endswith(('.S', '.s')):
        return "SKIP", source_file, 0, [], []

    if not os.path.exists(source_file):
        logger.warning(f"跳过不存在的文件: {source_file}")
        return "FAILED", source_file, 0, [], []

    if not Config.library_path:
        Config.set_library_path(lib_path)
    idx = Index.create()
    
    # 获取原始参数并进行清洗
    raw_args = cmd_info.get('arguments')
    if not raw_args:
        # ⭐ 核心兼容：有些 compile_commands.json 使用 "command" 字符串而不是 "arguments" 列表
        command_str = cmd_info.get('command', '')
        if command_str:
            raw_args = shlex.split(command_str)
        else:
            raw_args = []
            
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
        if arg in ('-fconserve-stack', '-fno-var-tracking-assignments', '-fmerge-all-constants') or arg.startswith(('-mabi=', '-falign-kernels')):
            continue

        # 5. 干掉可能会导致 libclang 报错的参数：仅针对依赖生成与强制报错
        # 注意：不要 arg.startswith('-Wp,-MMD')，这太宽泛了，可能干掉 -Wp,-D_FORTIFY_SOURCE
        if arg in ('-MD', '-MMD', '-MP', '-MT') or arg.startswith(('-Wp,-MD', '-Wp,-MMD')):
            continue
        if arg == '-MF':
            skip_next = True
            continue
        if arg.startswith('-Werror='):
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

    # === 【修复核心】：对付内核代码，必须注入 Working Directory ===
    if directory:
        compiler_args.append('-working-directory')
        compiler_args.append(directory)

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

    mtime = 0
    try:
        mtime = os.path.getmtime(source_file)
        #logger.info(f"正在编译 [{source_file}]:args={compiler_args}")
        tu = idx.parse(source_file, args=compiler_args, options=0x01)
        
        for diag in tu.diagnostics:
            if diag.severity >= 3:
                logger.warning(f"编译报错 [{source_file}]:args={compiler_args}")
                logger.warning(f"语法报错(已忽略文件) [{source_file}]: {diag.spelling}")


        symbols_to_upsert = []
        refs_to_insert = []
        
        # 优化：路径缓存，大幅减少 os.path.realpath 调用
        path_cache = {}
        last_file_obj = None
        last_node_file = None

        # 提前定义好 kind 常量，加速循环
        REF_KINDS = {
            CursorKind.CALL_EXPR,
            CursorKind.MEMBER_REF_EXPR,
            CursorKind.DECL_REF_EXPR,
            CursorKind.TYPE_REF,
            CursorKind.OVERLOADED_DECL_REF
        }
        
        DEF_KINDS = {
            CursorKind.FUNCTION_DECL, CursorKind.CXX_METHOD,
            CursorKind.STRUCT_DECL, CursorKind.CLASS_DECL,
            CursorKind.VAR_DECL, CursorKind.FIELD_DECL,
            CursorKind.TYPEDEF_DECL,
            CursorKind.ENUM_DECL, CursorKind.ENUM_CONSTANT_DECL,
            CursorKind.MACRO_DEFINITION
        }

        for node in tu.cursor.walk_preorder():
            loc = node.location
            file_obj = loc.file
            if not file_obj: continue
            
            # --- 优化点 1：缓存文件路径解析 ---
            if file_obj == last_file_obj:
                node_file = last_node_file
            else:
                raw_name = file_obj.name
                if raw_name in path_cache:
                    node_file = path_cache[raw_name]
                else:
                    node_file = os.path.realpath(raw_name)
                    path_cache[raw_name] = node_file
                last_file_obj = file_obj
                last_node_file = node_file
            
            # --- 优化点 2：减少 node.kind 获取次数 ---
            kind = node.kind
            
            # --- 角色 A: 定义 (def) ---
            if kind in DEF_KINDS:
                if kind == CursorKind.MACRO_DEFINITION or node.is_definition():
                    usr = node.get_usr()
                    if usr:
                        name = node.spelling or ""
                        symbols_to_upsert.append((usr, name, kind.name))
                        s_line, s_col = loc.line, loc.column
                        refs_to_insert.append((
                            usr, None, node_file, 
                            s_line, s_col, s_line, s_col + len(name), 'def'
                        ))

            # --- 角色 B: 引用与调用 (ref/call) ---
            if kind in REF_KINDS:
                target = node.referenced
                if target:
                    usr = target.get_usr()
                    if usr:
                        parent = node.semantic_parent
                        caller_usr = parent.get_usr() if (parent and parent.kind.is_declaration()) else None
                        
                        target_name = target.spelling or ""
                        symbols_to_upsert.append((usr, target_name, target.kind.name))
                        
                        role = 'call' if kind == CursorKind.CALL_EXPR else 'ref'
                        s_line, s_col = loc.line, loc.column
                        # 使用 pinpoint 坐标
                        name = node.spelling or target_name or ""
                        refs_to_insert.append((
                            usr, caller_usr, node_file,
                            s_line, s_col, s_line, s_col + len(name), role
                        ))

        # 调试：记录成功返回
        with open("/tmp/pyclangd_worker.log", "a") as f:
            f.write(f"SUCCESS: {source_file}, symbols={len(symbols_to_upsert)}, refs={len(refs_to_insert)}\n")
            
        return "SUCCESS", source_file, mtime, symbols_to_upsert, refs_to_insert
    except Exception as e:
        with open("/tmp/pyclangd_worker.log", "a") as f:
            f.write(f"FAILED: {source_file}, error={repr(e)}\n")
        logger.error(f"❌ 索引单文件崩溃 [{source_file}]: {repr(e)}")
        return "FAILED", source_file, mtime, [], []

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
    """跳转到定义：先尝试坐标精准匹配，再回退到单词模糊匹配"""
    uri = params.text_document.uri
    file_path = os.path.normpath(uri.replace("file://", ""))
    # LSP Position 是 0-indexed
    line_0 = params.position.line
    col_0 = params.position.character
    
    # 转换为 Clang/DB 使用的 1-indexed
    line_1 = line_0 + 1
    col_1 = col_0 + 1
    
    logger.info(f"👉 发起跳转: {os.path.basename(file_path)} 行{line_1} 列{col_1}")
    
    try:
        # --- 策略 1：坐标精准匹配 (USR 级别) ---
        usr = server.db.get_usr_at_location(file_path, line_1, col_1)
        if usr:
            logger.info(f"   ↳ 🎯 坐标命中了 USR: {usr} (line={line_1}, col={col_1})")
            results = server.db.get_definitions_by_usr(usr)
            if results:
                logger.info(f"   ↳ ✅ USR 查找成功: 找到 {len(results)} 个定义")
                return [Location(
                    uri=f"file://{fp}",
                    range=Range(
                        start=Position(line=sl-1, character=sc-1),
                        end=Position(line=el-1, character=ec-1)
                    )
                ) for fp, sl, sc, el, ec in results]

        # --- 策略 2：单词模糊匹配 (回退方案) ---
        # 如果坐标没命（比如索引还没更新，或者是一个没抓取到的引用类型）
        word_match = None
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
            if line_0 < len(lines):
                current_line = lines[line_0]
                for m in re.finditer(r'[a-zA-Z_][a-zA-Z0-9_]*', current_line):
                    if m.start() <= col_0 <= m.end():
                        word_match = m.group()
                        break
        
        if word_match:
            logger.info(f"   ↳ 🔍 坐标未命中，回退到单词搜索: '{word_match}' ...")
            results = server.db.get_definitions_by_name(word_match)
            if results:
                logger.info(f"   ↳ ✅ 单词查找成功: 找到 {len(results)} 个定义")
                return [Location(
                    uri=f"file://{fp}",
                    range=Range(
                        start=Position(line=sl-1, character=sc-1),
                        end=Position(line=el-1, character=ec-1)
                    )
                ) for fp, sl, sc, el, ec in results]

        logger.info("   ↳ ❌ 跳转失败: 坐标和单词均未找到定义")
        return None

    except Exception as e:
        logger.error(f"lsp_definition 崩溃: {e}")
        return None


@ls.feature(TEXT_DOCUMENT_REFERENCES)
def lsp_references(server: PyClangdServer, params):
    """查找引用：先精准查找 USR 的所有引用，失败则回退到同名匹配"""
    uri = params.text_document.uri
    file_path = os.path.normpath(uri.replace("file://", ""))
    line_0 = params.position.line
    col_0 = params.position.character
    
    line_1 = line_0 + 1
    col_1 = col_0 + 1
    
    logger.info(f"👉 查找引用: {os.path.basename(file_path)} 行{line_1} 列{col_1}")
    
    try:
        # --- 策略 1：坐标精准匹配 (USR 级别) ---
        usr = server.db.get_usr_at_location(file_path, line_1, col_1)
        if usr:
            logger.info(f"   ↳ 🎯 坐标命中了 USR: {usr} (line={line_1}, col={col_1})")
            results = server.db.get_references_by_usr(usr)
            if results:
                logger.info(f"   ↳ ✅ USR 引用查找成功: 找到 {len(results)} 处引用")
                return [Location(
                    uri=f"file://{fp}",
                    range=Range(
                        start=Position(line=sl-1, character=sc-1),
                        end=Position(line=el-1, character=ec-1)
                    )
                ) for fp, sl, sc, el, ec in results]

        # --- 策略 2：单词模糊匹配 (回退方案) ---
        word_match = None
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
            if line_0 < len(lines):
                current_line = lines[line_0]
                for m in re.finditer(r'[a-zA-Z_][a-zA-Z0-9_]*', current_line):
                    if m.start() <= col_0 <= m.end():
                        word_match = m.group()
                        break
        
        if word_match:
            logger.info(f"   ↳ 🔍 坐标未命中，回退到单词搜索引用: '{word_match}' ...")
            results = server.db.get_references_by_name(word_match)
            if results:
                logger.info(f"   ↳ ✅ 单词引用查找成功: 找到 {len(results)} 处引用")
                return [Location(
                    uri=f"file://{fp}",
                    range=Range(
                        start=Position(line=sl-1, character=sc-1),
                        end=Position(line=el-1, character=ec-1)
                    )
                ) for fp, sl, sc, el, ec in results]

        logger.info("   ↳ ❌ 查找引用失败: 未找到任何引用")
        # 返回空列表而不是 None 是查找引用的标准行为
        return []

    except Exception as e:
        logger.error(f"lsp_references 崩溃: {e}")
        return []


# --- 逻辑控制 ---
def run_index_mode(workspace_dir, lib_path, jobs):
    """主动索引模式（带增量更新与断点续传）"""
    workspace_dir = os.path.abspath(workspace_dir)
    db_path = os.path.join(workspace_dir, "pyclangd_index.db")
    cc_path = os.path.join(workspace_dir, "compile_commands.json")
    lib_path = os.path.abspath(lib_path)
    
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

    # --- 【优化核心】：主进程持有唯一写锁，Worker 只管解析 ---
    db = Database(db_path, is_main=True)
    db.enable_speed_mode()
    
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        # 注意：Worker 不再接收 db_path
        futures = [executor.submit(index_worker, cmd, lib_path) for cmd in commands_to_run]
        done = 0
        batch_count = 0
        
        for future in as_completed(futures):
            try:
                worker_res = future.result()
                if not worker_res: continue
                
                status, source_file, mtime, symbols, refs = worker_res
                
                if status == "SUCCESS":
                    batch_count += 1
                    # 每 50 个文件提交一次，平衡性能与事务开销
                    db.save_index_result(source_file, mtime, symbols, refs, commit=(batch_count >= 50))
                    if batch_count >= 50: batch_count = 0
                elif status == "FAILED":
                    db.update_file_status(source_file, mtime, 'failed')
                
                done += 1
                if done % 20 == 0 or done == len(commands_to_run):
                    logger.info(f"进度: [{done}/{len(commands_to_run)}] {done/len(commands_to_run)*100:.1f}%")
            except Exception as e:
                logger.error(f"❌ 主进程处理子任务异常: {repr(e)}")
                done += 1

        # 最后兜底提交
        db.conn.commit()
    db.close()

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