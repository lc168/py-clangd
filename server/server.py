import json
import os
import sys
import logging
from cindex import Index, CursorKind, Config

# 设置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("PyClangdIndexer")

# 引入你的数据库管理类
from database import IndexDatabase

class PyClangdIndexer:
    def __init__(self, lib_clang_path):
        if os.path.exists(lib_clang_path):
            Config.set_library_path(lib_clang_path)
        self.index = Index.create()
        self.db = IndexDatabase()

    def run(self, compile_commands_path):
        if not os.path.exists(compile_commands_path):
            logger.error(f"找不到编译数据库: {compile_commands_path}")
            return

        logger.info(f"开始解析编译数据库: {compile_commands_path}")
        with open(compile_commands_path, 'r') as f:
            commands = json.load(f)

        total = len(commands)
        for i, cmd in enumerate(commands):
            source_file = cmd['file']
            # 提取编译参数（去掉第一个编译器路径和最后一个源文件名）
            # 注意：某些 bear 生成的格式可能不同，这里取 arguments 字段
            args = cmd.get('arguments', [])
            if args:
                compiler_args = args[1:-1]
            else:
                # 兼容只有 command 字符串的情况
                command_str = cmd.get('command', '')
                compiler_args = command_str.split()[1:-1]

            logger.info(f"[{i+1}/{total}] 正在索引: {source_file}")
            self._index_file(source_file, compiler_args)
        
        logger.info("索引构建完成！")

    def _index_file(self, file_path, args):
        try:
            # 解析 Translation Unit
            tu = self.index.parse(file_path, args=args)
            
            # 递归遍历 AST 寻找定义
            for node in tu.cursor.walk_preorder():
                # 我们关注函数声明、C++ 类成员方法声明
                if node.kind in [CursorKind.FUNCTION_DECL, CursorKind.CXX_METHOD]:
                    # 关键：只有 node.is_definition() 为 True 才是我们要找的跳转目标
                    if node.is_definition():
                        usr = node.get_usr()
                        if usr and node.location.file:
                            self.db.record_definition(
                                usr,
                                node.spelling,
                                node.location.file.name,
                                node.location.line,
                                node.location.column
                            )
        except Exception as e:
            logger.error(f"解析文件 {file_path} 失败: {str(e)}")

if __name__ == "__main__":
    # 使用你之前的 LLVM 22 路径
    LIB_PATH = "/home/lc/llvm/llvm-project/build/lib"
    # 假设 compile_commands.json 在当前 PyClangd 根目录下
    compile_commands_path = "/home/lc/c_test1/compile_commands.json"
    #JSON_PATH = os.path.join(os.path.dirname(compile_commands_dir), "compile_commands.json")
    
    indexer = PyClangdIndexer(LIB_PATH)
    indexer.run(compile_commands_path)