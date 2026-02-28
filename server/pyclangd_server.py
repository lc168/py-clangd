#!/usr/bin/env python3
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
        # LSP Features & Commands
        TEXT_DOCUMENT_CODE_ACTION,
        TEXT_DOCUMENT_DEFINITION,
        TEXT_DOCUMENT_DID_SAVE,
        TEXT_DOCUMENT_DOCUMENT_SYMBOL,
        TEXT_DOCUMENT_REFERENCES,
        WORKSPACE_EXECUTE_COMMAND,
        WORKSPACE_SYMBOL,

        # LSP Types & Classes
        ApplyWorkspaceEditParams,
        CodeAction,
        CodeActionKind,
        CodeActionParams,
        Command,
        DocumentSymbol,
        ExecuteCommandParams,
        Location,
        MessageType,
        OptionalVersionedTextDocumentIdentifier,
        Position,
        Range,
        SymbolInformation,
        SymbolKind,
        TextDocumentEdit,
        TextEdit,
        WorkspaceEdit,
    )
except ImportError as e:
    print(f"Error: 缺少基础库 {e}, 请执行 pip install pygls lsprotocol", file=sys.stderr)
    sys.exit(1)

from database import Database
from cindex import Index, Cursor, CursorKind, Config
import clang_init

# 日志定向到 stderr，VS Code 才能在输出窗口显示
logging.basicConfig(level=logging.WARNING,
                    stream=sys.stderr,
                    format='%(levelname)s [%(name)s]: %(message)s'
                    )

#创建PyClangd标记的打印
logger = logging.getLogger("PyClangd")
# # 单独把我们自己的 PyClangd 设置为 INFO 级别，这样只有我们的进度条会显示
logger.setLevel(logging.INFO)

# === 辅助函数：清洗编译参数 ===
def _clean_compiler_args(raw_args, directory, source_file=None):
    """清洗并组装传递给 libclang 的编译参数"""
    compiler_args = []
    skip_next = False
    source_basename = os.path.basename(source_file) if source_file else ""

    for arg in raw_args[1:]:
        if skip_next:
            skip_next = False
            continue
            
        # 1. 干掉输出指令 -o 及其后面的文件名
        if arg == '-o':
            skip_next = True
            continue
            
        # 2. 干掉编译动作指令 -c 和 -S
        if arg in ('-c', '-S'):
            continue
            
        # 3. 干掉重复的源文件
        if source_basename and os.path.basename(arg) == source_basename:
            continue
            
        # 4. 干掉 Clang 不认识的 GCC 专属参数
        if arg in ('-fconserve-stack', '-fno-var-tracking-assignments', '-fmerge-all-constants', '-fno-allow-store-data-races') or arg.startswith(('-mabi=', '-falign-kernels', '-mpreferred-stack-boundary=')):
            continue

        # 5. 干掉可能会导致 libclang 报错的参数：仅针对依赖生成与强制报错
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
    
    # 对付老旧内核代码的杀手锏
    compiler_args.extend([
        '-Wno-error',
        '-Wno-strict-prototypes',
        '-Wno-implicit-int',
        '-Wno-unknown-warning-option',
        '-Wno-unknown-attributes',
        '-Qunused-arguments'
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

# --- 独立 Worker 函数 (必须定义在顶层以支持序列化) ---
def parse_to_sqlite(args):
    cmd_info, db_path = args
    # --- 1. 路径预处理：使用 realpath 消除软链接影响 ---
    directory = cmd_info.get('directory', '')
    file_rel = cmd_info.get('file', '')
    source_file = os.path.realpath(os.path.join(directory, file_rel)) 
    
    # ⭐ 核心修复：必须切换到该文件所属的编译目录，否则 realpath(header) 会基于 py-clangd 目录解析！
    if directory:
        os.chdir(directory)
    
    # 暂时跳过汇编文件
    if source_file.endswith(('.S', '.s')):
        return "SKIP"

    if not os.path.exists(source_file):
        logger.warning(f"跳过不存在的文件: {source_file}")
        return "FAILED"

    idx = Index.create()
    
    # 获取原始参数
    raw_args = cmd_info.get('arguments')
    if not raw_args:
        # ⭐ 核心兼容：有些 compile_commands.json 使用 "command" 字符串而不是 "arguments" 列表
        command_str = cmd_info.get('command', '')
        if command_str:
            raw_args = shlex.split(command_str)
        else:
            raw_args = []
            
    # 使用新抽出的函数清洗并生成最终参数
    compiler_args = _clean_compiler_args(raw_args, directory, source_file)

    mtime = 0
    try:
        mtime = os.path.getmtime(source_file)
        #logger.info(f"正在编译 [{source_file}]:args={compiler_args}")
        tu = idx.parse(source_file, args=compiler_args, options=0x01)

        # # ⭐ 临时加的，用于调试test
        # return "test", source_file, mtime, [], []

        included_files = []
        for inc in tu.get_includes():
            if inc.include and inc.include.name:
                inc_path = os.path.realpath(inc.include.name)
                # 留空 exact_path_string，之后在 walk_preorder 里补齐
                included_files.append((inc_path, ""))

        # 用于快速查找并更新 exact_path
        inc_path_to_exact = {}

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
            CursorKind.OVERLOADED_DECL_REF,
            CursorKind.MACRO_INSTANTIATION,
            CursorKind.INCLUSION_DIRECTIVE
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
                if kind == CursorKind.INCLUSION_DIRECTIVE:
                    exact_path = node.spelling
                    if exact_path:
                        inc_file = node.get_included_file()
                        if inc_file and inc_file.name:
                            inc_path = os.path.realpath(inc_file.name)
                            inc_path_to_exact[inc_path] = exact_path
                    continue
                    
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

        # 更新 included_files 的 exact_path
        included_files = [(path, inc_path_to_exact.get(path, "")) for path, _ in included_files]

        db = Database(db_path, is_main=False)
        db.save_parse_result(source_file, mtime, symbols_to_upsert, refs_to_insert, included_files)
        db.close()
        
        return "SUCCESS"
    except Exception as e:

        logger.error(f"❌ 索引单文件崩溃 [{source_file}]: {repr(e)}")
        
        try:
            db = Database(db_path, is_main=False)
            db.update_file_status(source_file, mtime, 'failed')
            db.close()
        except Exception:
            pass
            
        return "FAILED"

# --- LSP 服务端类 ---
import threading

import typing

# 在 PyClangdServer 初始化时，存一下命令字典，方便单文件查询
class PyClangdServer(LanguageServer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.db: typing.Optional[Database] = None
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
    
    # 获取这个文件被哪些源文件包含，或者它本身就是源文件
    dependent_sources = []
    if server.db:
        dependent_sources = server.db.lsp_did_save_db(file_path)

    cmd_info = server.commands_map.get(file_path)
    files_to_index = []

    if cmd_info:
        # 该文件在 compile_commands 中（一般是.c文件），将它本身加入
        files_to_index.append((file_path, cmd_info))
    
    # 把受影响的源文件也加入重新索引的队列
    for dep_src in dependent_sources:
        if dep_src == file_path:
            continue
        dep_cmd = server.commands_map.get(dep_src)
        if dep_cmd and not any(f[0] == dep_src for f in files_to_index):
            files_to_index.append((dep_src, dep_cmd))

    if not files_to_index:
        logger.warning(f"增量跳过: {file_path} 不在 compile_commands 中，且无关联源文件包含它")
        return

    logger.info(f"触发增量索引: {os.path.basename(file_path)}, 连带 {len(files_to_index)-1 if cmd_info else len(files_to_index)} 个依赖文件")

    # 启动后台线程跑解析，坚决不阻塞 LSP 主线程的 UI 响应
    def reindex_task():
        for src, cmd in files_to_index:
            # logger.info(f"[开始解析] {src}")
            status = parse_to_sqlite((cmd, server.db.db_path))
            if status == "SUCCESS":
                logger.info(f"✅ 更新成功: {os.path.basename(src)}")
            else:
                logger.info(f"❌ 更新失败: {os.path.basename(src)}")

    threading.Thread(target=reindex_task, daemon=True).start()

@ls.feature(TEXT_DOCUMENT_DOCUMENT_SYMBOL)
def lsp_document_symbols(server: PyClangdServer, params):
    """大纲视图：从数据库秒级查询"""
    file_path = os.path.normpath(params.text_document.uri.replace("file://", ""))
    symbols = []
    if server.db:
        for name, kind_id, sl, sc, el, ec in server.db.lsp_document_symbols_db(file_path):
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
    if not server.db:
        return []
    
    return [SymbolInformation(
        name=n, kind=SymbolKind.Function,
        location=Location(uri=f"file://{fp}", range=Range(start=Position(line=sl-1, character=sc-1), 
                                                          end=Position(line=sl-1, character=sc-1+len(n))))
    ) for n, fp, sl, sc, usr in server.db.lsp_workspace_symbols_db(params.query)]


import re

# 在 PyClangdServer 类中修改或添加定义跳转函数
@ls.feature(TEXT_DOCUMENT_DEFINITION)
def lsp_definition(server: PyClangdServer, params):
    """跳转到定义：执行坐标精准匹配 (USR 级)"""
    uri = params.text_document.uri
    file_path = os.path.normpath(uri.replace("file://", ""))
    # LSP Position 是 0-indexed
    line_0 = params.position.line
    col_0 = params.position.character
    
    # 转换为 Clang/DB 使用的 1-indexed
    line_1 = line_0 + 1
    col_1 = col_0 + 1
    
    logger.info(f"👉 发起跳转: {file_path} 行{line_1} 列{col_1}")
    
    if not server.db:
        return None
        
    try:
        # 获取光标所在行文本
        line_text = ""
        doc = server.workspace.get_text_document(uri)
        if doc and line_0 < len(doc.lines):
            line_text = doc.lines[line_0]
            
        results = server.db.lsp_definition_db(file_path, line_1, col_1, line_text)
        
        if results:
            logger.info(f"   ↳ ✅ 查找成功: 找到 {len(results)} 个定义")
            return [Location(
                uri=f"file://{fp}",
                range=Range(
                    start=Position(line=sl-1, character=sc-1),
                    end=Position(line=el-1, character=ec-1)
                )
            ) for fp, sl, sc, el, ec in results]

        logger.info("   ↳ ❌ 跳转失败: 坐标未命或未找到定义")
        return None

    except Exception as e:
        logger.error(f"lsp_definition 崩溃: {e}")
        return None


@ls.feature(TEXT_DOCUMENT_REFERENCES)
def lsp_references(server: PyClangdServer, params):
    """查找引用：执行坐标精准匹配 (USR 级)"""
    uri = params.text_document.uri
    file_path = os.path.normpath(uri.replace("file://", ""))
    line_0 = params.position.line
    col_0 = params.position.character
    
    line_1 = line_0 + 1
    col_1 = col_0 + 1
    
    logger.info(f"👉 查找引用: {file_path} 行{line_1} 列{col_1}")
    
    if not server.db:
        return []
        
    try:
        results = server.db.lsp_references_db(file_path, line_1, col_1)
        if results:
            logger.info(f"   ↳ ✅ 引用查找成功: 找到 {len(results)} 处引用")
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


@ls.feature(TEXT_DOCUMENT_CODE_ACTION)
def lsp_code_action(server: PyClangdServer, params: CodeActionParams):
    """当光标停留在一行上，请求代码操作"""
    uri = params.text_document.uri
    file_path = os.path.normpath(uri.replace("file://", ""))
    
    line_1 = params.range.start.line + 1
    col_1 = params.range.start.character + 1
    
    if not server.db:
        return None
        
    action_type = server.db.lsp_code_action_db(file_path, line_1, col_1)
    if action_type == "expand_macro":
        return [
            CodeAction(
                title="🔬 完全展开宏 (py-clangd)",
                kind=CodeActionKind.RefactorRewrite,
                command=Command(
                    title="完全展开宏",
                    command="pyclangd.expandMacro",
                    arguments=[uri, params.range.start.line, params.range.start.character]
                )
            )
        ]
    return None

import tempfile
import re

@ls.feature(WORKSPACE_EXECUTE_COMMAND)
def lsp_execute_command(server: PyClangdServer, params: ExecuteCommandParams):
    if params.command == "pyclangd.expandMacro":
        if not server.db:
            return
            
        res = server.db.lsp_execute_command_db(params.command, params.arguments, server.commands_map)
        
        if res and res.get("success"):
            uri = params.arguments[0] # The URI
            expanded_text = res["text"]
            edit = WorkspaceEdit(
                changes={
                    uri: [
                        TextEdit(
                            range=Range(
                                start=Position(line=res["s_line"], character=res["s_col"]),
                                end=Position(line=res["e_line"], character=res["e_col"])
                            ),
                            new_text=expanded_text
                        )
                    ]
                }
            )
            server.lsp.send_request("workspace/applyEdit", ApplyWorkspaceEditParams(edit=edit, label="展开宏"))
            logger.info(f"成功展开宏: {expanded_text}")
        elif res and "error" in res:
            logger.error(f"Expand macro error: {res['error']}")

# --- 索引产生数据库---
def run_index_mode(workspace_dir, jobs):
    """主动索引模式（带增量更新与断点续传）"""
    workspace_dir = os.path.abspath(workspace_dir)
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
        
        # 暂时跳过汇编和不存在的文件
        if full_path.endswith(('.S', '.s')) or not os.path.exists(full_path):
            continue
        
        curr_mtime = os.path.getmtime(full_path)
        # 只要没记录过，或者时间戳变了，就加入重刷队列
        if full_path not in indexed_files or indexed_files[full_path] != curr_mtime:
            commands_to_run.append(cmd)

    if not commands_to_run:
        logger.info("🎉 所有文件均已是最新状态，无需重新索引！")
        return

    logger.info(f"🚀 开始索引: 共 {len(commands)} 个文件，增量需要处理 {len(commands_to_run)} 个, 进程数: {max_workers}")

    db = Database(db_path, is_main=True)
    
    from multiprocessing import Pool
    with Pool(processes=max_workers, maxtasksperchild=10) as pool:
        done = 0
        batch_count = 0
        
        import time
        start_time = time.time()
        
        try:
            tasks = [(cmd, db_path) for cmd in commands_to_run]
            for status in pool.imap_unordered(parse_to_sqlite, tasks, chunksize=10):
                if not status:
                    continue
                
                done += 1
                elapsed = time.time() - start_time
                logger.info(f"进度: [{done}/{len(commands_to_run)}] {done/len(commands_to_run)*100:.1f}% | 耗时: {elapsed:.2f}s")
                

        except KeyboardInterrupt:
            logger.warning("\n⚠️ 检测到 Ctrl+C 中断！正在强制终止所有后台解析进程...")
            pool.terminate() # 一键杀掉池子里所有的进程！
            pool.join()
            db.conn.commit()
            db.close()
            sys.exit(1)

        # 最后兜底提交
        db.conn.commit()
    db.close()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-d", "--directory")
    parser.add_argument("-s", "--server", action="store_true")
    parser.add_argument("-j", "--jobs", type=int, default=0)
    args = parser.parse_args()

    if args.server:
        ls.load_commands_map(args.directory)

        db_path = os.path.join(args.directory, "pyclangd_index.db")
        if os.path.exists(db_path):
            ls.db = Database(db_path)
            logger.info("LSP Server 加载数据库成功")
        ls.start_io()
    else:
        run_index_mode(args.directory, args.jobs)

if __name__ == "__main__":
    main()