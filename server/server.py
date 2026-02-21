#!/usr/bin/env python3
"""
PyClangd: C/C++ LSP backend.
两种运行模式:
  模式1 (LSP 常驻): python3 server.py -d <workspace_dir> -s
  模式2 (仅建索引): python3 server.py -d <workspace_dir>
"""
import argparse
import json
import logging
import os
import sys
from urllib.parse import urlparse, unquote

from cindex import Index, Cursor, CursorKind, Config
from database import IndexDatabase

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("PyClangd")

# 可选: 通过环境变量指定 libclang 路径 (LLVM 22)
LIB_CLANG_PATH = os.environ.get("PYCLANGD_LIB_PATH", "")


def _compile_commands_path(workspace_dir):
    return os.path.join(workspace_dir, "compile_commands.json")


def _db_path(workspace_dir):
    return os.path.join(workspace_dir, "pyclangd_index.db")


def _load_compile_commands(workspace_dir):
    path = _compile_commands_path(workspace_dir)
    if not os.path.exists(path):
        return None
    with open(path, "r") as f:
        return json.load(f)


def _build_file_args_map(commands):
    """从 compile_commands 构建 文件路径 -> 编译参数列表 的映射。"""
    result = {}
    for cmd in commands:
        path = cmd.get("file")
        if not path:
            continue
        args = cmd.get("arguments")
        if args:
            # 去掉第一个编译器路径和最后一个源文件名
            result[path] = list(args)[1:-1]
        else:
            command_str = cmd.get("command", "")
            parts = command_str.split()
            result[path] = parts[1:-1] if len(parts) > 2 else []
    return result


# ---------- 模式2: 仅索引 ----------
def run_index_mode(workspace_dir, lib_path):
    """解析 workspace_dir 下的 compile_commands.json，重建 SQLite 索引并退出。"""
    db_path = _db_path(workspace_dir)
    if os.path.exists(db_path):
        os.remove(db_path)
        logger.info("已删除旧数据库: %s", db_path)

    commands = _load_compile_commands(workspace_dir)
    if not commands:
        logger.error("未找到 compile_commands.json: %s", _compile_commands_path(workspace_dir))
        return 1

    if lib_path and os.path.exists(lib_path):
        Config.set_library_path(lib_path)
    index = Index.create()
    db = IndexDatabase(db_path)
    total = len(commands)
    for i, cmd in enumerate(commands):
        source_file = cmd.get("file")
        if not source_file:
            continue
        args = cmd.get("arguments")
        if args:
            compiler_args = list(args)[1:-1]
        else:
            command_str = cmd.get("command", "")
            compiler_args = command_str.split()[1:-1] if command_str else []
        logger.info("[%s/%s] 索引: %s", i + 1, total, source_file)
        try:
            tu = index.parse(source_file, args=compiler_args)
            for node in tu.cursor.walk_preorder():
                if node.kind in (CursorKind.FUNCTION_DECL, CursorKind.CXX_METHOD):
                    if node.is_definition():
                        usr = node.get_usr()
                        if usr and node.location.file:
                            db.record_definition(
                                usr,
                                node.spelling,
                                node.location.file.name,
                                node.location.line,
                                node.location.column,
                            )
        except Exception as e:
            logger.error("解析失败 %s: %s", source_file, e)
    logger.info("索引构建完成: %s", db_path)
    return 0


# ---------- 模式1: LSP 服务 (stdin/stdout JSON-RPC) ----------
def _read_lsp_message(stream):
    """读取一条 Content-Length 形式的 LSP 消息。stream 应为二进制模式以保证按字节读取。"""
    buf = getattr(stream, "buffer", stream)
    line = buf.readline()
    if not line:
        return None
    if not line.strip().lower().startswith(b"content-length:"):
        while line and line.strip():
            line = buf.readline()
        return _read_lsp_message(stream)
    length = int(line.split(b":", 1)[1].strip())
    buf.readline()  # 消费 \r\n 空行
    body = buf.read(length).decode("utf-8")
    return json.loads(body) if body else None


def _write_lsp_message(stream, obj):
    """写一条 LSP 消息。"""
    body = json.dumps(obj, ensure_ascii=False)
    data = body.encode("utf-8")
    buf = getattr(stream, "buffer", stream)
    buf.write(f"Content-Length: {len(data)}\r\n\r\n".encode("ascii"))
    buf.write(data)
    buf.flush()


def _uri_to_path(uri):
    if uri.startswith("file://"):
        return unquote(urlparse(uri).path)
    return uri


def _path_to_uri(path):
    return "file://" + path if not path.startswith("file://") else path


def _handle_definition(params, file_args_map, db, lib_path):
    """处理 textDocument/definition：根据位置解析出 USR，再查库。"""
    uri = params.get("textDocument", {}).get("uri")
    position = params.get("position")
    if not uri or position is None:
        return None
    file_path = _uri_to_path(uri)
    line_1based = position.get("line", 0) + 1
    col_1based = position.get("character", 0) + 1

    args = file_args_map.get(file_path) if file_args_map else None
    if args is None:
        # 尝试用绝对路径或规范化路径再查一次
        for k, v in (file_args_map or {}).items():
            if os.path.normpath(k) == os.path.normpath(file_path):
                args = v
                break
    if args is None:
        return None

    try:
        if lib_path and os.path.exists(lib_path):
            Config.set_library_path(lib_path)
        index = Index.create()
        tu = index.parse(file_path, args=args)
        loc = tu.get_location(file_path, (line_1based, col_1based))
        cursor = Cursor.from_location(tu, loc)
        if cursor is None or cursor.is_null():
            return None
        # 引用处取 referenced，再取 USR（与索引里存的定义 USR 一致）
        ref = cursor.referenced
        target = ref if ref and not ref.is_null() else cursor
        usr = target.get_usr() if target else None
        if not usr:
            return None
        row = db.find_definition(usr)
        if not row:
            return None
        def_path, def_line, def_col = row
        # 库中为 1-based，LSP 为 0-based
        return {
            "uri": _path_to_uri(def_path),
            "range": {
                "start": {"line": def_line - 1, "character": def_col - 1},
                "end": {"line": def_line - 1, "character": def_col - 1},
            },
        }
    except Exception as e:
        logger.debug("definition 失败: %s", e)
        return None


def run_lsp_mode(workspace_dir, lib_path):
    """从 stdin 读 JSON-RPC，处理 LSP 请求，常驻运行。"""
    db_path = _db_path(workspace_dir)
    if not os.path.exists(db_path):
        logger.warning("索引不存在，将先建索引: %s", db_path)
        run_index_mode(workspace_dir, lib_path)

    db = IndexDatabase(db_path)
    commands = _load_compile_commands(workspace_dir)
    file_args_map = _build_file_args_map(commands) if commands else {}

    if lib_path and os.path.exists(lib_path):
        Config.set_library_path(lib_path)

    stdin = sys.stdin
    while True:
        msg = _read_lsp_message(stdin)
        if msg is None:
            break
        msg_id = msg.get("id")
        method = msg.get("method")
        params = msg.get("params") or {}

        if method == "initialize":
            result = {
                "capabilities": {
                    "definitionProvider": True,
                },
                "serverInfo": {"name": "pyclangd", "version": "0.0.1"},
            }
            _write_lsp_message(sys.stdout, {"id": msg_id, "result": result})
        elif method == "initialized":
            # 无返回值
            pass
        elif method == "textDocument/definition":
            result = _handle_definition(params, file_args_map, db, lib_path)
            _write_lsp_message(sys.stdout, {"id": msg_id, "result": result})
        else:
            # 其他请求返回 null
            if msg_id is not None:
                _write_lsp_message(sys.stdout, {"id": msg_id, "result": None})
    return 0


def main():
    parser = argparse.ArgumentParser(description="PyClangd: C/C++ LSP 后端")
    parser.add_argument("-d", "--dir", required=True, help="需要分析的代码目录（其下应有 bear 生成的 compile_commands.json）")
    parser.add_argument("-s", "--server", action="store_true", help="以 LSP 模式常驻运行，与 VS Code 通讯")
    parser.add_argument("-l", "--lib", default="", help="libclang 库目录（可选，也可用环境变量 PYCLANGD_LIB_PATH）")
    args = parser.parse_args()
    workspace_dir = os.path.abspath(args.dir)
    lib_path = args.lib or LIB_CLANG_PATH

    if not os.path.isdir(workspace_dir):
        logger.error("目录不存在: %s", workspace_dir)
        return 1

    if args.server:
        return run_lsp_mode(workspace_dir, lib_path)
    return run_index_mode(workspace_dir, lib_path)


if __name__ == "__main__":
    sys.exit(main() or 0)
