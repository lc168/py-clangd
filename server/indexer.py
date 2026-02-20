import json
import os
from server.cindex import Config, Index, CursorKind
from server.database import IndexDatabase

class PyClangdIndexer:
    def __init__(self, lib_path, db: IndexDatabase):
        Config.set_library_path(lib_path)
        self.index = Index.create()
        self.db = db

    def index_project(self, json_path):
        if not os.path.exists(json_path):
            return
        
        with open(json_path, 'r') as f:
            commands = json.load(f)

        for cmd in commands:
            file_path = cmd['file']
            # 过滤掉编译器路径，只保留参数
            args = list(cmd['arguments'])[1:-1]
            self._process_file(file_path, args)

    def _process_file(self, file_path, args):
        tu = self.index.parse(file_path, args=args)
        for node in tu.cursor.walk_preorder():
            # 只记录函数或方法的具体定义
            if node.kind in [CursorKind.FUNCTION_DECLARATION, CursorKind.CXX_METHOD]:
                if node.is_definition():
                    self.db.record_definition(
                        node.get_usr(),
                        node.spelling,
                        node.location.file.name,
                        node.location.line,
                        node.location.column
                    )