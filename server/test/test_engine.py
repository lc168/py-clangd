#!/usr/bin/env python3
import os
import sys
import json
import re

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.abspath(os.path.join(current_dir, ".."))
sys.path.append(parent_dir)

from pyclangd_server import PyClangdServer, lsp_definition, lsp_references
import clang_init
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

class MockDocumentData:
    def __init__(self, filepath):
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            self.lines = f.readlines()

class MockWorkspace:
    def get_text_document(self, uri):
        filepath = uri.replace("file://", "")
        if os.path.exists(filepath):
            return MockDocumentData(filepath)
        return None

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

def direct_build_db(workspace_dir, files):
    print(f"🔨 [1/2] 正在构建索引库 (共 {len(files)} 个文件)...")
    
    db_path = os.path.join(workspace_dir, "pyclangd_index.db")
    if os.path.exists(db_path):
        os.remove(db_path)

    db = Database(workspace_dir)
    
    for f_rel in files:
        filepath = os.path.join(workspace_dir, f_rel)
        mock_cmd_info = {
            "directory": workspace_dir,
            "file": f_rel,
            "arguments": ["clang", "--target=aarch64-linux-gnu", "-xc", "-DBUILDING_PYCLANGD_TEST", "-I" + workspace_dir, filepath]
        }
        if f_rel.endswith('.cpp'):
            mock_cmd_info["arguments"] = ["clang++", "--target=aarch64-linux-gnu", "-xc++", "-std=c++17", "-DBUILDING_PYCLANGD_TEST", "-I" + workspace_dir, filepath]
            
        # ⭐ 使用独立函数解析文件，并直接存入对应数据库
        status = Database.index_worker((mock_cmd_info, workspace_dir))
    
    db.close()

def run_tests():
    cases_root = os.path.join(current_dir, "cases")
    if not os.path.exists(cases_root):
        os.makedirs(cases_root)
        print(f"📅 已创建用例根目录: {cases_root}, 请放入测试子文件夹。")
        return

    subdirs = [os.path.join(cases_root, d) for d in os.listdir(cases_root) 
               if os.path.isdir(os.path.join(cases_root, d))]
    
    if not subdirs:
        print("❓ cases 目录下未发现任何子文件夹。")
        return

    total_score = 0
    total_cases = 0
    all_results_log = []

    print("="*80)
    print("🚀 开始多目录隔离测试...")
    print("="*80)

    for cases_dir in sorted(subdirs):
        subdir_name = os.path.basename(cases_dir)
        print(f"\n📁 正在处理测试目录: [{subdir_name}]")
        
        db_path = os.path.join(cases_dir, "pyclangd_index.db")
        tasks = discover_tests(cases_dir)
        if not tasks:
            print(f"  └── ❓ 未发现任何带有测试标记的文件，跳过。")
            continue
        
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
        direct_build_db(cases_dir, list(all_files))

        print(f"  └── 启动探测引擎 (共 {len(tasks)} 个测试点)...")
        
        class MockServer:
            def __init__(self, db_instance):
                self.db = db_instance
                self.workspace = MockWorkspace()
                
        server = MockServer(Database(cases_dir))

        subdir_score = 0
        
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
                        subdir_score += 1
                        status = "✅ PASS"
                    else:
                        status = "❌ FAIL"
                    
                    all_results_log.append(f"[{subdir_name}] {status} | Label(jump): {task['label']} | {task['file']}:{task['line']} -> Expected {task['expected_file']}:{task['expected_line']} | Actual: {actual_info}")
                    
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
                        subdir_score += 1
                        status = "✅ PASS"
                    else:
                        status = "❌ FAIL"
                        
                    actual_info_str = ", ".join(actual_info) if actual_info else "None"
                    expected_info_str = ", ".join([f"{f}:{l}" for f, l in expected_set])
                    all_results_log.append(f"[{subdir_name}] {status} | Label(ref): {task['label']} | {task['file']}:{task['line']} -> Expected: [{expected_info_str}] | Actual: [{actual_info_str}]")
                    if missing:
                        all_results_log.append(f"          ↳ Missing: {missing}")

            except Exception as e:
                all_results_log.append(f"[{subdir_name}] 💥 CRASH | Label({task['type']}): {task['label']} | Error: {e}")

        total_score += subdir_score
        total_cases += len(tasks)

    print("\n" + "="*80)
    print("📊 PyClangd Bug 多目录隔离探测报告")
    print("="*80)
    for log in all_results_log:
        print(log)
    print("-" * 80)
    if total_cases > 0:
        print(f"🎯 最终得分: {total_score} / {total_cases} | 准确率: {(total_score/total_cases)*100:.2f}%")
    else:
        print("🎯 没有执行任何测试用例。")
    print("="*80)

if __name__ == "__main__":
    run_tests()