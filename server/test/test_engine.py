import os
import sys
import json
import re

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.abspath(os.path.join(current_dir, ".."))
sys.path.append(parent_dir)

from pyclangd_server import PyClangdServer, lsp_definition, index_worker
from database import Database

# --- Mock Classes for LSP ---
class MockPosition:
    def __init__(self, line, character):
        self.line = line
        self.character = character

class MockTextDocument:
    def __init__(self, uri):
        self.uri = uri

class MockParams:
    def __init__(self, uri, line, character):
        self.text_document = MockTextDocument(uri)
        self.position = MockPosition(line, character)

# --- Helper to find libclang ---
def find_lib_path():
    # 优先从环境变量读取
    env_path = os.environ.get("PYCLANGD_LIB_PATH")
    if env_path and os.path.exists(env_path):
        return env_path
    # 常见路径尝试
    common_paths = [
        "/home/lc/llvm22/lib",
    ]
    for p in common_paths:
        if os.path.exists(p):
            return p
    return None

# --- Marker Discovery Logic ---
def discover_tests(cases_dir):
    """
    扫描目录下的 .c/.cpp 文件，提取 @def 和 @jump 标记。
    标记现在必须与代码在同一行。
    格式: 
      void foo() { // @def: foo
      foo(); // @jump: foo
    """
    defs = {} # label -> (file_rel, line_idx)
    jumps_raw = [] # list of (file_rel, line_idx, label)
    
    files = [f for f in os.listdir(cases_dir) if f.endswith(('.c', '.cpp', '.h', '.hpp'))]
    
    for f_rel in files:
        f_abs = os.path.join(cases_dir, f_rel)
        with open(f_abs, 'r', encoding='utf-8', errors='ignore') as f:
            for line_idx, line in enumerate(f):
                # 匹配 @def: label
                def_match = re.search(r'//\s*@def:\s*(\w+)', line)
                if def_match:
                    label = def_match.group(1)
                    defs[label] = (f_rel, line_idx)
                
                # 匹配 @jump: label
                jump_match = re.search(r'//\s*@jump:\s*(\w+)', line)
                if jump_match:
                    label = jump_match.group(1)
                    jumps_raw.append({
                        "file": f_rel,
                        "line": line_idx,
                        "label": label
                    })
                    
    # 关联数据，生成测试任务
    test_tasks = []
    for j in jumps_raw:
        label = j['label']
        if label in defs:
            def_file, def_line = defs[label]
            
            # 在发起跳转的行找 label 对应的单词起始列
            f_abs = os.path.join(cases_dir, j['file'])
            col_idx = 0
            with open(f_abs, 'r') as f:
                lines = f.readlines()
                content = lines[j['line']]
                # 查找标识符，考虑多种可能性（可能是 label 本身，也可能是 label_a 这种）
                # 我们优先查找 label 本身。
                # 比如：// @jump: id_a 对应代码 a.id = 1; 这里的标识符是 id
                # 所以我们还是需要一种方式知道到底要跳哪个词。
                # 约定：标记格式改为 // @jump: label (word_to_click)
                # 暂且简单处理：如果在行内找到 label，就用它的位置。
                # 如果没找到（比如结构体成员），我们就搜 // @jump: label 之前的第一个标识符
                
                # 特殊处理：如果 label 包含下划线且没搜到，尝试搜后缀（如 id_a -> id）
                search_word = label
                if label not in content and '_' in label:
                    search_word = label.split('_')[0]
                
                m = re.search(r'\b' + re.escape(search_word) + r'\b', content)
                if m:
                    col_idx = m.start()
                else:
                    # 兜底：找行中第一个单词
                    m2 = re.search(r'[a-zA-Z_]', content)
                    if m2: col_idx = m2.start()
            
            test_tasks.append({
                "file": j['file'],
                "line": j['line'],
                "col": col_idx,
                "expected_file": def_file,
                "expected_line": def_line,
                "label": label
            })
    return test_tasks

def direct_build_db(cases_dir, db_path, lib_path, files):
    print(f"🔨 [1/2] 正在构建索引库 (共 {len(files)} 个文件)...")
    
    if os.path.exists(db_path):
        os.remove(db_path)
        
    db = Database(db_path, is_main=True)
    db.close()

    from cindex import Config
    try:
        Config.set_library_path(lib_path)
    except Exception: pass

    for f_rel in files:
        filepath = os.path.join(cases_dir, f_rel)
        mock_cmd_info = {
            "directory": cases_dir,
            "file": f_rel,
            "arguments": ["clang", "-xc", "-I" + cases_dir, filepath]
        }
        if f_rel.endswith('.cpp'):
            mock_cmd_info["arguments"] = ["clang++", "-xc++", "-std=c++17", "-I" + cases_dir, filepath]
            
        index_worker(mock_cmd_info, lib_path, db_path)

def run_tests():
    cases_dir = os.path.join(current_dir, "cases")
    if not os.path.exists(cases_dir):
        os.makedirs(cases_dir)
        print(f"📅 已创建用例目录: {cases_dir}, 请放入测试文件。")
        return

    lib_path = find_lib_path()
    if not lib_path:
        print("❌ 找不到 libclang 库路径，请设置 PYCLANGD_LIB_PATH 环境变量。")
        return
    print(f"🔍 使用 libclang 路径: {lib_path}")

    db_path = os.path.join(cases_dir, "pyclangd_index.db")
    
    tasks = discover_tests(cases_dir)
    if not tasks:
        print("❓ 未发现任何带有 @jump 标记的测试用例。")
        return
    
    # 找出所有涉及的文件进行索引
    all_files = set()
    for t in tasks:
        all_files.add(t['file'])
        all_files.add(t['expected_file'])

    # 1. 建库
    direct_build_db(cases_dir, db_path, lib_path, list(all_files))

    print(f"\n🚀 [2/2] 启动探测引擎 (共 {len(tasks)} 个测试点)...")
    server = PyClangdServer("pyclangd-tester", "v1.0") 
    server.db = Database(db_path, is_main=False)

    score = 0
    total_cases = len(tasks)
    results_log = []

    # 2. 逐个验证
    for task in tasks:
        uri = f"file://{os.path.join(cases_dir, task['file'])}"
        # LSP Position 是 0-indexed
        params = MockParams(uri, task['line'], task['col'])
        
        try:
            results = lsp_definition(server, params)
            success = False
            actual_info = "None"
            
            if results:
                # 检查是否命中了期望的文件和行
                for res in results:
                    actual_file = os.path.relpath(res.uri.replace("file://", ""), cases_dir)
                    actual_line = res.range.start.line
                    if actual_file == task['expected_file'] and actual_line == task['expected_line']:
                        success = True
                        break
                
                # 记录第一个结果用于显示
                first_res = results[0]
                first_file = os.path.relpath(first_res.uri.replace("file://", ""), cases_dir)
                actual_info = f"{first_file}:{first_res.range.start.line}"

            if success:
                score += 1
                status = "✅ PASS"
            else:
                status = "❌ FAIL"
            
            results_log.append(f"{status} | Label: {task['label']} | {task['file']}:{task['line']} -> Expected {task['expected_file']}:{task['expected_line']} | Actual: {actual_info}")
            
        except Exception as e:
            results_log.append(f"💥 CRASH | Label: {task['label']} | Error: {e}")

    print("="*80)
    print("📊 PyClangd Bug 探测报告")
    print("="*80)
    for log in results_log:
        print(log)
    print("-" * 80)
    print(f"🎯 最终得分: {score} / {total_cases} | 准确率: {(score/total_cases)*100:.2f}%")
    print("="*80)

if __name__ == "__main__":
    run_tests()