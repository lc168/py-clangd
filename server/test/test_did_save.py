import os
import sys
import time
import shutil

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.abspath(os.path.join(current_dir, ".."))
sys.path.append(parent_dir)

from pyclangd_server import PyClangdServer, lsp_did_save, index_worker
from database import Database

class MockTextDocument:
    def __init__(self, uri):
        self.uri = uri

class MockParams:
    def __init__(self, uri):
        self.text_document = MockTextDocument(uri)

class MockServer:
    def __init__(self, db_instance, c_file):
        self.db = db_instance
        self.commands_map = {
            os.path.realpath(c_file): {
                "directory": os.path.dirname(c_file),
                "file": os.path.basename(c_file),
                "arguments": ["clang", "-xc", "-I" + os.path.dirname(c_file), c_file]
            }
        }
        
    def show_message_log(self, msg):
        print(f"[MockServer Log]: {msg}")

def run_test():
    cases_dir = os.path.join(current_dir, "cases")
    db_path = os.path.join(cases_dir, "test_did_save.db")
    c_file = os.path.join(cases_dir, "test_did_save_target.c")
    
    if os.path.exists(db_path):
        os.remove(db_path)

    # Initialize basic DB
    db = Database(db_path, is_main=True)
    server = MockServer(db, c_file)
    
    print("="*60)
    print("🧪 测试 lsp_did_save 接口开始")
    print("="*60)

    # 阶段 1：初始状态
    print("\n▶ 阶段 1：创建初始文件 (包含函数 foo)")
    with open(c_file, "w") as f:
        f.write("void foo() {}\n")
    
    # 模拟按下 Ctrl+S
    params = MockParams(f"file://{c_file}")
    lsp_did_save(server, params)
    
    print("等待后台线程解析...")
    time.sleep(2) # 给线程一点时间跑完写库
    
    symbols_v1 = db.get_symbols_by_file(os.path.realpath(c_file))
    sym_names_v1 = [s[0] for s in symbols_v1]
    
    if "foo" in sym_names_v1:
        print("✅ 初始索引成功! 发现了 'foo'")
    else:
        print("❌ 错误：未在数据库中找到初始函数 'foo'")
        sys.exit(1)

    # 阶段 2：修改文件并再次触发保存
    print("\n▶ 阶段 2：修改文件 (删除 foo，改为 bar)")
    with open(c_file, "w") as f:
        f.write("void bar() {}\n")
        
    # 再次模拟按下 Ctrl+S
    lsp_did_save(server, params)
    
    print("等待后台线程增量更新...")
    time.sleep(2)
    
    symbols_v2 = db.get_symbols_by_file(os.path.realpath(c_file))
    sym_names_v2 = [s[0] for s in symbols_v2]
    
    success = True
    if "bar" in sym_names_v2:
        print("✅ 增量更新成功! 发现了新增加的 'bar'")
    else:
        print("❌ 错误：未能找到修改后的 'bar'")
        success = False
        
    if "foo" in sym_names_v2:
        print("❌ 错误：旧的 'foo' 未被清除。这是一个 BUG！")
        success = False
    else:
        print("✅ 增量更新成功! 旧的 'foo' 已被正确清除")

    print("\n" + ("="*60))
    if success:
        print("🎉 测试通过: lsp_did_save 能够正确触发后台增量更新！")
    else:
        print("💥 测试失败: 增量更新未达预期效果！")
    print("="*60)
    
    db.close()
    if os.path.exists(c_file):
        os.remove(c_file)
    if os.path.exists(db_path):
        os.remove(db_path)
        
    # sqlite-wal and shm cleanup
    if os.path.exists(db_path + "-wal"):
        os.remove(db_path + "-wal")
    if os.path.exists(db_path + "-shm"):
        os.remove(db_path + "-shm")

if __name__ == "__main__":
    run_test()
