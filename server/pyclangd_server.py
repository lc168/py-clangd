#!/usr/bin/env python3
import os
import sys
import logging
import multiprocessing
import json
import argparse
import shlex

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

# --- LSP 服务端类 ---
import threading

import typing

# 在 PyClangdServer 初始化时，存一下命令字典，方便单文件查询
class PyClangdServer(LanguageServer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.db: typing.Optional[Database] = None

ls = PyClangdServer("pyclangd", "1.0.0")

@ls.feature(TEXT_DOCUMENT_DID_SAVE)
def lsp_did_save(server: PyClangdServer, params):
    """当 VS Code 里按下 Ctrl+S，触发单文件增量更新"""
    file_path = os.path.normpath(params.text_document.uri.replace("file://", ""))
    if not server.db:
        return

    files_to_index = server.db.lsp_did_save_db(file_path, server.db.commands_map)

    if not files_to_index:
        logger.warning(f"增量跳过: {file_path} 不在 compile_commands 中，且无关联源文件包含它")
        return

    logger.info(f"触发增量索引: {os.path.basename(file_path)}, 连带 {len(files_to_index)} 个依赖文件")

    # 启动后台线程跑解析，坚决不阻塞 LSP 主线程的 UI 响应
    def reindex_task():
        for src, cmd in files_to_index:
            # logger.info(f"[开始解析] {src}")
            status = server.db.index_worker((cmd, server.db.workspace_dir))
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
            kind_map = {
                "FUNCTION_DECL": SymbolKind.Function, 
                "VAR_DECL": SymbolKind.Variable,
                "MACRO_DEFINITION": SymbolKind.Constant,
                "STRUCT_DECL": SymbolKind.Struct,
                "FIELD_DECL": SymbolKind.Field,
                "TYPEDEF_DECL": SymbolKind.Class
            }
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
    # 关键：将从客户端获取到的可能带有软链接的路径，转换为底层的真实绝对路径！
    # 这样才能保证去数据库查 `file_path` 时，能和 [index_worker](cci:1://file:///home/lc/py-clangd/server/database.py:515:4-651:24) 写入时的真实路径严丝合缝对上。
    file_path = os.path.realpath(uri.replace("file://", ""))

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
        results = server.db.lsp_definition_db(file_path, line_1, col_1)
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

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-d", "--directory")
    parser.add_argument("-s", "--server", action="store_true")
    parser.add_argument("-j", "--jobs", type=int, default=0)
    args = parser.parse_args()

    if args.server:
        ls.db = Database(args.directory)
        ls.db.load_commands_map()

        import threading
        threading.Thread(target=ls.db.run_index_mode, args=(args.jobs,), daemon=True).start()

        logger.info(f"🌐 启动 PyClangd LSP Server (Workspace: {args.directory}) ...")
        ls.start_io()
    else:
        db = Database(args.directory)
        db.load_commands_map()
        db.run_index_mode(args.jobs)

if __name__ == '__main__':
    main()