#!/usr/bin/env python3
import argparse
import logging
import os
import sys
import json
from urllib.parse import urlparse, unquote
from pathlib import Path

# pygls 1.3.1 适配的导入
from pygls.server import LanguageServer
from lsprotocol.types import (
    TEXT_DOCUMENT_DEFINITION,
    Location,
    Range,
    Position,
    MessageType  # 必须导入 MessageType 枚举
)

# 导入 cindex，注意这里添加了 Cursor
from cindex import Index, Cursor, CursorKind, Config
from database import IndexDatabase

# 强制日志输出到 stderr
logging.basicConfig(
    level=logging.INFO, 
    stream=sys.stderr, 
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger("PyClangd")

class PyClangdServer(LanguageServer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.db = None
        self.file_args_map = {}
        self.lib_path = ""

ls = PyClangdServer("pyclangd", "0.0.1")

# ---------- 辅助工具 ----------

def _uri_to_path(uri):
    parsed = urlparse(uri)
    return os.path.normpath(unquote(parsed.path))

def _load_compile_commands(workspace_dir):
    path = os.path.join(workspace_dir, "compile_commands.json")
    if not os.path.exists(path):
        return None
    with open(path, "r") as f:
        return json.load(f)

def _build_file_args_map(commands):
    result = {}
    for cmd in commands:
        path = cmd.get("file")
        if not path: continue
        args = cmd.get("arguments")
        result[path] = list(args)[1:-1] if args else cmd.get("command", "").split()[1:-1]
    return result

# ---------- 模式 2: 索引模式 ----------

def run_index_mode(workspace_dir, lib_path):
    db_path = os.path.join(workspace_dir, "pyclangd_index.db")
    if os.path.exists(db_path):
        logger.error(f"删除pyclangd_index.db")
        os.remove(db_path)

    # 必须在 Index.create() 之前设置
    if lib_path:
        Config.set_library_path(lib_path)

    commands = _load_compile_commands(workspace_dir)
    if not commands:
        logger.error(f"未找到编译数据库")
        return 1

    index = Index.create()
    db = IndexDatabase(db_path)
    
    for i, cmd in enumerate(commands):
        source_file = cmd.get("file")
        if not source_file: continue
        compiler_args = list(cmd.get("arguments", []))[1:-1] or cmd.get("command", "").split()[1:-1]
        
        try:
            tu = index.parse(source_file, args=compiler_args)
            for node in tu.cursor.walk_preorder():
                if node.kind in (CursorKind.FUNCTION_DECL, CursorKind.CXX_METHOD):
                    if node.is_definition() and node.location.file:
                        db.record_definition(node.get_usr(), node.spelling, node.location.file.name, node.location.line, node.location.column)
        except Exception as e:
            logger.error(f"索引失败: {e}")
    return 0

# ---------- 模式 1: LSP 模式 ----------

@ls.feature(TEXT_DOCUMENT_DEFINITION)
def lsp_definition(server: PyClangdServer, params):
    uri = params.text_document.uri
    pos = params.position
    
    # 修正点：使用 MessageType 枚举而不是整数
    server.show_message_log("--- 接收到跳转请求 ---", MessageType.Log)
    
    file_path = _uri_to_path(uri)
    line_1 = pos.line + 1
    col_1 = pos.character + 1

    server.show_message_log(f"分析位置: {file_path} L{line_1}:C{col_1}", MessageType.Info)

    if not server.db:
        server.show_message_log("错误: 数据库连接未初始化", MessageType.Error)
        return None

    try:
        # 修正点：不再在 handler 内部调用 set_library_path
        args = server.file_args_map.get(file_path, [])
        index = Index.create() # 这里的 index 是安全的，因为 main 中已初始化 path
        tu = index.parse(file_path, args=args)
        loc = tu.get_location(file_path, (line_1, col_1))
        
        # 修正点：已在顶部导入 Cursor
        cursor = Cursor.from_location(tu, loc)
        
        if not cursor or cursor.is_null():
            server.show_message_log("未能识别符号", MessageType.Warning)
            return None

        target = cursor.referenced if cursor.referenced else cursor
        usr = target.get_usr()
        
        if not usr:
            return None

        result = server.db.find_definition(usr)
        if result:
            def_path, def_line, def_col = result
            return Location(
                uri=Path(def_path).as_uri(),
                range=Range(
                    start=Position(line=def_line - 1, character=def_col - 1),
                    end=Position(line=def_line - 1, character=def_col)
                )
            )
    except Exception as e:
        server.show_message_log(f"跳转异常: {str(e)}", MessageType.Error)
        
    return None

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-d", "--dir", required=True)
    parser.add_argument("-s", "--server", action="store_true")
    parser.add_argument("-l", "--lib", default="")
    args = parser.parse_args()

    workspace_dir = os.path.abspath(args.dir)
    lib_path = args.lib
    
    # ⭐ 核心修正：在所有逻辑开始前，全局只调用一次 set_library_path
    if lib_path and os.path.exists(lib_path):
        try:
            Config.set_library_path(lib_path)
            logger.info(f"成功设置 Clang 路径: {lib_path}")
        except Exception as e:
            logger.warning(f"设置 Clang 路径时发生警告 (可能已设置): {e}")

    db_path = _db_path(workspace_dir)

    if args.server:
        ls.db = IndexDatabase(db_path)
        ls.lib_path = lib_path
        commands = _load_compile_commands(workspace_dir)
        ls.file_args_map = _build_file_args_map(commands) if commands else {}
        ls.start_io()
    else:
        sys.exit(run_index_mode(workspace_dir, lib_path))

def _db_path(workspace_dir):
    return os.path.join(workspace_dir, "pyclangd_index.db")

if __name__ == "__main__":
    main()