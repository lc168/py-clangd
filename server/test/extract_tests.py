import re
import os

def extract_cases():
    # 指向你拷贝过来的原矿文件
    source_file = "llvm_raw_unittests/XRefsTests.cpp"
    output_dir = "generated_cases"
    
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    with open(source_file, 'r', encoding='utf-8') as f:
        content = f.read()

    # 正则提取 R"cpp( ... )cpp" 或者 R"c( ... )c"
    pattern = re.compile(r'R"(?:cpp|c)\((.*?)\)(?:cpp|c)"', re.DOTALL)
    matches = pattern.findall(content)

    count = 0
    for match in matches:
        # 我们只提取带有 ^ (点击位置) 的测试用例
        if '^' in match:
            # 清理头尾的空白
            code = match.strip()
            case_path = os.path.join(output_dir, f"case_{count:03d}.c")
            with open(case_path, "w", encoding='utf-8') as out_f:
                out_f.write(code)
            count += 1
            
    print(f"✅ 提炼完成！从 C++ 源码中成功提取了 {count} 个纯粹的跳转测试用例。")
    print(f"📂 用例已保存在: {output_dir}/")

if __name__ == "__main__":
    extract_cases()