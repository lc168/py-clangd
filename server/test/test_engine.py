import os
import sys
import json
import re

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.abspath(os.path.join(current_dir, ".."))
sys.path.append(parent_dir)

from pyclangd_server import PyClangdServer, lsp_definition, lsp_references, index_worker
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
    扫描目录下的 .c/.cpp 文件，提取 @def 和 @jump 标记，以及 @ref_target 和 @ref_expect 标记。
    标记现在必须与代码在同一行。
    格式: 
      void foo() { // @def: foo
      foo(); // @jump: foo
      
      int abc; // @ref_target: abc
      abc = 1; // @ref_expect: abc
      abc = 2; // @ref_expect: abc
    """
    defs = {} # label -> (file_rel, line_idx)
    jumps_raw = [] # list of (file_rel, line_idx, label)
    
    # 引用测试数据
    ref_targets = {} # label -> (file_rel, line_idx)
    ref_expects = {} # label -> list of (file_rel, line_idx)
    
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

                # 匹配 @ref_target: label
                ref_target_match = re.search(r'//\s*@ref_target:\s*([\w:]+)', line)
                if ref_target_match:
                    label = ref_target_match.group(1)
                    ref_targets[label] = (f_rel, line_idx)

                # 匹配 @ref_expect: label
                ref_expect_match = re.search(r'//\s*@ref_expect:\s*([\w:]+)', line)
                if ref_expect_match:
                    label = ref_expect_match.group(1)
                    if label not in ref_expects:
                        ref_expects[label] = []
                    ref_expects[label].append((f_rel, line_idx))
                    
    # 辅助函数：计算标记所在行的列索引
    def calculate_col_idx(j_file, j_line, target_label):
        f_abs = os.path.join(cases_dir, j_file)
        with open(f_abs, 'r') as f:
            lines = f.readlines()
            content = lines[j_line]
            code_part = content.split('//')[0]
            parts = target_label.split(':')
            search_word = parts[-1] 
            
            m = re.search(r'\b' + re.escape(search_word) + r'\b', code_part)
            if m:
                return m.start()
            
            words = list(re.finditer(r'\b[a-zA-Z_][a-zA-Z0-9_]*\b', code_part))
            if words:
                return words[-1].start()
            
            m2 = re.search(r'[a-zA-Z_]', content)
            if m2: return m2.start()
        return 0

    # 关联数据，生成跳转测试任务
    test_tasks = []
    for j in jumps_raw:
        label = j['label']
        if label in defs:
            def_file, def_line = defs[label]
            col_idx = calculate_col_idx(j['file'], j['line'], label)
            
            test_tasks.append({
                "type": "jump",
                "file": j['file'],
                "line": j['line'],
                "col": col_idx,
                "expected_file": def_file,
                "expected_line": def_line,
                "label": label
            })
            
    # 关联数据，生成引用测试任务
    for label, (target_file, target_line) in ref_targets.items():
        if label in ref_expects:
            col_idx = calculate_col_idx(target_file, target_line, label)
            
            test_tasks.append({
                "type": "ref",
                "file": target_file,
                "line": target_line,
                "col": col_idx,
                "expected_refs": ref_expects[label],
                "label": label
            })
            
    return test_tasks

def direct_build_db(cases_dir, db_path, lib_path, files):
    print(f"🔨 [1/2] 正在构建索引库 (共 {len(files)} 个文件)...")
    
    if os.path.exists(db_path):
        os.remove(db_path)
        
    lib_path = find_lib_path()
    from cindex import Config
    try:
        Config.set_library_path(lib_path)
    except Exception: pass

    db = Database(db_path, is_main=True)
    
    for f_rel in files:
        filepath = os.path.join(cases_dir, f_rel)
        mock_cmd_info = {
            "directory": cases_dir,
            "file": f_rel,
            "arguments": ["clang", "-xc", "-I" + cases_dir, filepath]
        }
        if f_rel.endswith('.cpp'):
            mock_cmd_info["arguments"] = ["clang++", "-xc++", "-std=c++17", "-I" + cases_dir, filepath]
            
        res = index_worker(mock_cmd_info, lib_path)
        if res and res[0] == "SUCCESS":
            _, source_file, mtime, symbols, refs = res
            db.save_index_result(source_file, mtime, symbols, refs)
    
    db.close()

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
        if t['type'] == 'jump':
            all_files.add(t['expected_file'])
        elif t['type'] == 'ref':
            for ef, _ in t['expected_refs']:
                all_files.add(ef)

    # 1. 建库
    direct_build_db(cases_dir, db_path, lib_path, list(all_files))

    print(f"\n🚀 [2/2] 启动探测引擎 (共 {len(tasks)} 个测试点)...")
    
    class MockServer:
        def __init__(self, db_instance):
            self.db = db_instance
            
    server = MockServer(Database(db_path, is_main=False))

    score = 0
    total_cases = len(tasks)
    results_log = []

    # 2. 逐个验证
    for task in tasks:
        uri = f"file://{os.path.join(cases_dir, task['file'])}"
        # LSP Position 是 0-indexed
        params = MockParams(uri, task['line'], task['col'])
        
        try:
            if task['type'] == 'jump':
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
                
                results_log.append(f"{status} | Label(jump): {task['label']} | {task['file']}:{task['line']} -> Expected {task['expected_file']}:{task['expected_line']} | Actual: {actual_info}")
                
            elif task['type'] == 'ref':
                results = lsp_references(server, params)
                
                # Check if all expected refs are returned
                expected_set = set(task['expected_refs']) # set of (file, line)
                actual_set = set()
                actual_info = []
                
                if results:
                    for res in results:
                        actual_file = os.path.relpath(res.uri.replace("file://", ""), cases_dir)
                        actual_line = res.range.start.line
                        actual_set.add((actual_file, actual_line))
                        actual_info.append(f"{actual_file}:{actual_line}")
                
                missing = expected_set - actual_set
                
                if not missing:
                    score += 1
                    status = "✅ PASS"
                else:
                    status = "❌ FAIL"
                    
                actual_info_str = ", ".join(actual_info) if actual_info else "None"
                expected_info_str = ", ".join([f"{f}:{l}" for f, l in expected_set])
                results_log.append(f"{status} | Label(ref): {task['label']} | {task['file']}:{task['line']} -> Expected: [{expected_info_str}] | Actual: [{actual_info_str}]")
                if missing:
                    results_log.append(f"          ↳ Missing: {missing}")

        except Exception as e:
            results_log.append(f"💥 CRASH | Label({task['type']}): {task['label']} | Error: {e}")

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