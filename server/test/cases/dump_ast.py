import os
import sys

current_dir = os.path.dirname(os.path.abspath(__file__))
server_dir = os.path.abspath(os.path.join(current_dir, "..", ".."))
sys.path.append(server_dir)

from cindex import Config, Index, CursorKind

def main():
    Config.set_library_path("/home/lc/llvm22/lib")
    idx = Index.create()
    
    test_file = "test_ifdef.c"
    with open(test_file, 'w') as f:
        f.write("#define MY_MACRO 1\n#ifdef MY_MACRO\nint a = 1;\n#endif\n")
        
    print(f"Parsing {test_file}...")
    # 0x01 is DetailedPreprocessingRecord
    tu = idx.parse(test_file, options=0x01)
    
    for node in tu.cursor.walk_preorder():
        if node.location.file and node.location.file.name == test_file:
            print(f"Found node: {node.kind} at line {node.location.line}, col {node.location.column}, spelling='{node.spelling}'")

if __name__ == "__main__":
    main()
