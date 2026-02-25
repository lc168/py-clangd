import re
import os
import json

def extract_cases():
    source_file = "llvm_raw_unittests/XRefsTests.cpp"
    output_dir = "generated_cases"
    
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    with open(source_file, 'r', encoding='utf-8') as f:
        content = f.read()

    pattern = re.compile(r'R"(cpp|c)\((.*?)\)\1"', re.DOTALL)
    matches = pattern.findall(content)

    meta_data = []
    count = 0

    for lang, raw_code in matches:
        if '^' not in raw_code:
            continue

        lines = raw_code.split('\n')
        cursor_line, cursor_col = -1, -1
        target_line = -1

        # 1. 找光标起点 (题目)
        for i, line in enumerate(lines):
            if '^' in line:
                cursor_line = i
                cursor_col = line.find('^')
                break

        # 2. 找跳转终点 (标准答案)
        # 优先寻找 $def[[ (定义处)，如果没找到，再找普通的 [[
        for i, line in enumerate(lines):
            if '$def[[' in line or '$overridedef[[' in line:
                target_line = i
                break
        if target_line == -1:
            for i, line in enumerate(lines):
                if '[[' in line:
                    target_line = i
                    break
                    
        # 如果连答案都没有，说明这个测试可能是专门测试“不该发生跳转”的，暂且把答案设为光标处
        if target_line == -1:
            target_line = cursor_line

        # 3. 等宽隐身术清洗代码
        clean = raw_code
        def repl(m): return ' ' * len(m.group(0))
        
        clean = re.sub(r'\$[a-zA-Z0-9_]+\(', repl, clean)
        clean = re.sub(r'\)[a-zA-Z0-9_]*\[\[', repl, clean)
        clean = re.sub(r'\$[a-zA-Z0-9_]*\[\[', repl, clean)
        clean = re.sub(r'\$[a-zA-Z0-9_]*\^', repl, clean)
        clean = clean.replace('[[', '  ').replace(']]', '  ')
        clean = clean.replace('^', ' ')

        filename = f"case_{count:03d}.cpp"
        filepath = os.path.join(output_dir, filename)
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(clean)
        
        # ⭐ 把题目和答案一起存入答题卡
        meta_data.append({
            "file": filename,
            "line": cursor_line,
            "col": cursor_col,
            "target_line": target_line
        })
        count += 1
            
    with open(os.path.join(output_dir, "meta.json"), "w", encoding='utf-8') as f:
        json.dump(meta_data, f, indent=4)

    print(f"✅ 提炼 3.0 完成！成功提取了 {count} 个纯净 C/C++ 测试题，已生成包含标准答案的 meta.json。")

if __name__ == "__main__":
    extract_cases()
    