#!/usr/bin/env python3
import os
import re
import json

def extract_test_cases(cases_dir):
    def_tests = []
    ref_tests = []
    
    # Store all definitions and references as we read
    # defs: label -> {"file": filename, "line": line_num}
    defs = {}
    
    # jumps: list of {"label": label, "file": filename, "line": line_num}
    jumps = []
    
    # refs_expected: label -> list of {"file": filename, "line": line_num}
    refs_expected = {}
    
    # refs_target: label -> list of {"file": filename, "line": line_num}
    refs_target = []
    
    # regexes
    def_re = re.compile(r'@def:\s*([^ ]+)')
    jump_re = re.compile(r'@jump:\s*([^ ]+)')
    ref_expect_re = re.compile(r'@ref_expect:\s*([^ ]+)')
    ref_target_re = re.compile(r'@ref_target:\s*([^ ]+)')
    
    # Read files
    for filename in sorted(os.listdir(cases_dir)):
        if not (filename.endswith('.c') or filename.endswith('.cpp') or filename.endswith('.h')):
            continue
            
        filepath = os.path.join(cases_dir, filename)
        with open(filepath, 'r', encoding='utf-8') as f:
            for i, line in enumerate(f):
                line_num = i + 1
                
                # Check for @def
                def_match = def_re.search(line)
                if def_match:
                    label = def_match.group(1).strip()
                    defs[label] = {"file": filename, "line": line_num}
                    
                # Check for @jump
                jump_match = jump_re.search(line)
                if jump_match:
                    label = jump_match.group(1).strip()
                    jumps.append({
                        "label": label,
                        "source_file": filename,
                        "source_line": line_num
                    })
                    
                # Check for @ref_expect
                ref_expect_match = ref_expect_re.search(line)
                if ref_expect_match:
                    label = ref_expect_match.group(1).strip()
                    if label not in refs_expected:
                        refs_expected[label] = []
                    refs_expected[label].append({"file": filename, "line": line_num})
                    
                # Check for @ref_target
                ref_target_match = ref_target_re.search(line)
                if ref_target_match:
                    label = ref_target_match.group(1).strip()
                    refs_target.append({
                        "label": label,
                        "source_file": filename,
                        "source_line": line_num,
                    })
                    
    # Pair jumps with defs
    for j in jumps:
        label = j["label"]
        if label in defs:
            def_tests.append({
                "label": label,
                "source_file": j["source_file"],
                "source_line": j["source_line"],
                "target_file": defs[label]["file"],
                "target_line": defs[label]["line"]
            })
        else:
            print(f"Warning: Jump label '{label}' in {j['source_file']}:{j['source_line']} has no matching @def")
            
    # Pair ref targets with ref expects
    for rt in refs_target:
        label = rt["label"]
        if label in refs_expected:
            # Important: the target itself might also be a reference according to the tests
            all_expected = list(refs_expected[label]) 
            # some references are also expects in the original test script.
            # to mimic accurately we will rely strictly on the @ref_expect tags.
            
            ref_tests.append({
                "label": label,
                "source_file": rt["source_file"],
                "source_line": rt["source_line"],
                "expected_targets": all_expected
            })
        else:
            print(f"Warning: Ref target label '{label}' in {rt['source_file']}:{rt['source_line']} has no matching @ref_expect")
            
    return def_tests, ref_tests

def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    cases_dir = os.path.join(script_dir, "cases")
    
    if not os.path.exists(cases_dir):
        print(f"Error: Directory not found: {cases_dir}")
        return
        
    def_tests, ref_tests = extract_test_cases(cases_dir)
    
    def_path = os.path.join(script_dir, "def_tests.json")
    with open(def_path, 'w', encoding='utf-8') as f:
        json.dump(def_tests, f, indent=4, ensure_ascii=False)
    print(f"✅ 生成了 {len(def_tests)} 个 definitions 测试用例到 {os.path.basename(def_path)}")
    
    ref_path = os.path.join(script_dir, "ref_tests.json")
    with open(ref_path, 'w', encoding='utf-8') as f:
        json.dump(ref_tests, f, indent=4, ensure_ascii=False)
    print(f"✅ 生成了 {len(ref_tests)} 个 references 测试用例到 {os.path.basename(ref_path)}")

if __name__ == "__main__":
    main()
