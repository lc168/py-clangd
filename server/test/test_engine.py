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
    return "/home/lc/llvm22/lib"

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
                def_match = re.search(r'//\s*@def:\s*([\w:]+)', line)
                if def_match:
                    label = def_match.group(1)
                    defs[label] = (f_rel, line_idx)
                
                # 匹配 @jump: label
                jump_match = re.search(r'//\s*@jump:\s*([\w:]+)', line)
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
                
                # 特殊逻辑：标记格式为 // @jump: label
                # 我们寻找行中与 label 相关的单词。
                # 比如：a.id = 1; // @jump: id_a  -> 我们想找 id
                
                # 在标记 // 之前的代码部分搜索
                code_part = content.split('//')[0]

                # 支持 @jump: label:word 格式，显式指定要点击的单词
                # 如果没有冒号，则 search_word 就是 label
                parts = label.split(':')
                search_word = parts[-1] 
                
                # 寻找 search_word
                m = re.search(r'\b' + re.escape(search_word) + r'\b', code_part)
                if m:
                    col_idx = m.start()
                else:
                    # 兜底：寻找 code_part 中的最后一个单词（通常是我们要跳转的那个）
                    words = list(re.finditer(r'\b[a-zA-Z_][a-zA-Z0-9_]*\b', code_part))
                    if words:
                        col_idx = words[-1].start()
                    else:
                        # 最后的兜底：行首
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