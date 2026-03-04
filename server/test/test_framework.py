#!/usr/bin/env python3
import os
import sys
import json
import subprocess
import shutil


# Add server directory to path to import modules
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.abspath(os.path.join(current_dir, ".."))
sys.path.append(parent_dir)

from database import Database
from database import Database

def run_bear_make(cases_dir):
    print("🐻 Running bear make to generate compile_commands.json...")
    # Clean first
    subprocess.run(["make", "clean"], cwd=cases_dir, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    # Run bear
    res = subprocess.run(["bear", "--", "make", "-B"], cwd=cases_dir, capture_output=True, text=True)
    if res.returncode != 0:
        print("❌ Error running bear make:")
        print(res.stderr)
        return False
        
    cc_path = os.path.join(cases_dir, "compile_commands.json")
    if not os.path.exists(cc_path):
        print("❌ compile_commands.json wasn't generated!")
        return False
        
    print(f"✅ compile_commands.json generated at {cc_path}")
    return True

def validate_definitions(db, def_tests_path):
    print("\n🔍 Validating Definitions...")
    if not os.path.exists(def_tests_path):
        print("❌ def_tests.json not found!")
        return 0, 1
        
    with open(def_tests_path, 'r', encoding='utf-8') as f:
        tests = json.load(f)
        
    passed = 0
    failed = 0
    
    for t in tests:
        label = t["label"]
        src_file = os.path.join(current_dir, "cases", t["source_file"])
        src_line = t["source_line"]
        
        expected_file = os.path.join(current_dir, "cases", t["target_file"])
        expected_line = t["target_line"]
        
        # Read the exact line to find where the token starts before the comment
        # e.g a.id = 1; // @jump: id_a:id -> we want the column of `id`
        # e.g active_func(); // @jump: enabled_func -> we want the column of `active_func`
        
        with open(src_file, 'r', encoding='utf-8') as src_f:
            lines = src_f.readlines()
            if src_line <= len(lines):
                line_content = lines[src_line - 1]
                
                # Split off the comment part
                code_part = line_content.split('//')[0]
                
                # Find all word tokens in the code part
                import re
                matches = list(re.finditer(r'[a-zA-Z_]\w*', code_part))
                
                if matches:
                    # Depending on if the label specified a token, we might want to match it
                    token = label.split(':')[-1]
                    matched_col = None
                    
                    # Try to find the specific token from the label
                    for m in matches:
                        if m.group() == token:
                            matched_col = m.start() + 1
                    
                    # If the label name didn't match any code token (e.g. `enabled_func`), just pick the last word in the line
                    if not matched_col:
                        matched_col = matches[-1].start() + 1
                        
                    col = matched_col
                else:
                    col = 5
            else:
                col = 5
                
        # Directly call the high-level DB interface simulating an LSP request
        defs = db.lsp_definition_db(src_file, src_line, col)
        
        if not defs:
            print(f"❌ FAIL [{label}]: Found no definition for token at {t['source_file']}:{src_line}:{col}")
            failed += 1
            continue
            
        # Match expected
        found = False
        actual_matches = []
        for df in defs:
            fp, sl, sc, el, ec = df
            actual_matches.append(f"{os.path.basename(fp)}:{sl}")
            if fp == expected_file and sl == expected_line:
                found = True
                break
                
        if found:
            print(f"✅ PASS [{label}]: {t['source_file']}:{src_line} -> {t['target_file']}:{expected_line}")
            passed += 1
        else:
            print(f"❌ FAIL [{label}]: Expected {t['target_file']}:{expected_line}, but got {actual_matches}")
            failed += 1
            
    return passed, failed

def validate_references(db, ref_tests_path):
    print("\n🔍 Validating References...")
    if not os.path.exists(ref_tests_path):
        print("❌ ref_tests.json not found!")
        return 0, 1
        
    with open(ref_tests_path, 'r', encoding='utf-8') as f:
        tests = json.load(f)
        
    passed = 0
    failed = 0
    
    for t in tests:
        label = t["label"]
        src_file = os.path.join(current_dir, "cases", t["source_file"])
        src_line = t["source_line"]
        expected_targets = t["expected_targets"]
        
        with open(src_file, 'r', encoding='utf-8') as src_f:
            lines = src_f.readlines()
            if src_line <= len(lines):
                line_content = lines[src_line - 1]
                
                code_part = line_content.split('//')[0]
                import re
                matches = list(re.finditer(r'[a-zA-Z_]\w*', code_part))
                
                if matches:
                    token = label.split(':')[-1]
                    matched_col = None
                    for m in matches:
                        if m.group() == token:
                            matched_col = m.start() + 1
                    
                    if not matched_col:
                        matched_col = matches[-1].start() + 1
                        
                    col = matched_col
                else:
                    col = 5
            else:
                col = 5
                
        # Directly call the high-level DB interface
        refs = db.lsp_references_db(src_file, src_line, col)
        
        if not refs:
            print(f"❌ FAIL [{label}]: No references found at {t['source_file']}:{src_line}:{col}")
            failed += 1
            continue
        
        actual_locations = set()
        for r in refs:
            fp, sl, sc, el, ec = r
            actual_locations.add(f"{os.path.basename(fp)}:{sl}")
            
        expected_locations = set([f"{et['file']}:{et['line']}" for et in expected_targets])
        
        # Compare sets
        missing = expected_locations - actual_locations
        
        if not missing:
            print(f"✅ PASS [{label}]: Found all {len(expected_targets)} expected references.")
            passed += 1
        else:
            print(f"❌ FAIL [{label}]: Missing {missing}. Found: {actual_locations}, Expected: {expected_locations}")
            failed += 1
            
    return passed, failed

def main():
    cases_dir = os.path.join(current_dir, "cases")
    db_path = os.path.join(cases_dir, "pyclangd_index.db")
    
    # 1. Clean DB & Compile commands
    if os.path.exists(db_path):
        os.remove(db_path)
        
    # 2. Generate generic compile_commands.json
    if not run_bear_make(cases_dir):
        return
        
    # 3. Index everything via the real server logic
    print("\n⚡ Running parallel indexing...")
    db = Database(cases_dir)
    print("load_commands_map......................")
    db.load_commands_map()
    print("run_index_mode.....................")
    db.run_index_mode(jobs=0)
    print("if not os.path.exists(db_path):.....................")
    if not os.path.exists(db_path):
        print("❌ Index database was not created!")
        return
        
    # 4. Validate
    
    def_pass, def_fail = validate_definitions(db, os.path.join(current_dir, "def_tests.json"))
    ref_pass, ref_fail = validate_references(db, os.path.join(current_dir, "ref_tests.json"))
    
    db.close()
    
    # Print Summary
    total_pass = def_pass + ref_pass
    total_fail = def_fail + ref_fail
    total = total_pass + total_fail
    
    print("\n" + "="*50)
    print(f"📊 Auto-Testing Framework Summary")
    print("="*50)
    print(f"🎯 Total Score: {total_pass} / {total} | Accuracy: {(total_pass/(total+0.0001))*100:.2f}%")
    if total_fail == 0:
        print("🎉 ALL TESTS PASSED PIECE OF CAKE!")
    else:
        print(f"☠️  {total_fail} TESTS FAILED. PLEASE FIX YOUR SHIT.")
    print("="*50)

if __name__ == "__main__":
    main()
