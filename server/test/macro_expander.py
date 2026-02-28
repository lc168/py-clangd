#!/usr/bin/env python3
import subprocess
import re
import os

def get_macro_expansion(filepath: str, target_line: int, clang_bin="clang") -> str:
    """
    通用函数：获取 C/C++ 源文件中特定行的宏展开后代码。
    利用 clang -E 输出的 Line Marker (# 1 "filename") 进行精准定位。
    """
    # 确保文件存在
    if not os.path.isfile(filepath):
        return f"Error: File '{filepath}' not found."

    cmd = [clang_bin, "-E", filepath]
    
    try:
        # 执行预处理
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
    except subprocess.CalledProcessError as e:
        return f"Error running clang -E:\n{e.stderr}"

    expanded_lines = result.stdout.splitlines()
    
    # 匹配 clang 的 line marker，例如: 
    # # 1 "test_macro.c"
    # # 1 "test_macro.c" 2
    line_marker_regex = re.compile(r'^#\s+(\d+)\s+"([^"]+)"')
    
    target_filename = os.path.basename(filepath)
    
    # 这个变量用来追踪当前输出行对应原文件的第几行
    current_mapped_line = 0
    # 这个变量用来追踪当前输出行属于哪个文件（有可能是被 include 的头文件）
    current_mapped_file = ""
    
    extracted_text = []

    for line in expanded_lines:
        match = line_marker_regex.match(line)
        if match:
            # 遇到 Line Marker，重置行号和文件名锚点
            current_mapped_line = int(match.group(1))
            current_mapped_file = os.path.basename(match.group(2))
            continue
        
        # 对于不是 Line Marker 的普通代码行
        if current_mapped_file == target_filename:
            # 命中了我们要找的那一行！
            if current_mapped_line == target_line:
                extracted_text.append(line)
            
            # 重要：每输出/扫描一行普通代码，对应的原始物理行号就要 +1
            current_mapped_line += 1

    # 如果抓取到了内容，用换行符拼起来；如果没抓到，返回空
    if extracted_text:
        return "\n".join(extracted_text).strip()
    return ""


if __name__ == "__main__":
    # 解析你给的 clang -E 例子中的第 6 行和第 7 行
    print("----- 测试提取 z -----")
    # 注意：在原始的 test_macro.c 里，"int z = MAX..." 这行在第 6 行
    res1 = get_macro_expansion("test_macro.c", 19, clang_bin="/home/lc/llvm22/bin/clang-22")
    print(res1)
    
    print("\n----- 测试提取 z1 -----")
    # "int z1 = MAX..." 这行在第 7 行
    res2 = get_macro_expansion("test_macro.c", 26, clang_bin="/home/lc/llvm22/bin/clang-22")
    print(res2)

