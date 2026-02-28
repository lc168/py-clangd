#!/usr/bin/env python3
import os
import sys
sys.path.append("/home/lc/sda/work/py-clangd/server")
import clang_init
from cindex import Index, CursorKind

test_c = """
#define MAX(a,b) ((a) > (b) ? (a) : (b))
int main() {
    int x = 1;
    int y = 2;
    int z = MAX(x+1, y);
    return 0;
}
"""
with open("test_macro.c", "w") as f:
    f.write(test_c)

idx = Index.create()
tu = idx.parse("test_macro.c", options=0x01)

# for node in tu.cursor.walk_preorder():
#     print(dir(node))
#     # print(
#     #     f"{node.kind:<32}spelling[{node.spelling:<20}],"
#     #     f"extent=({node.extent.start.line}:{node.extent.start.column} - {node.extent.end.line}:{node.extent.end.column})"
#     # )
#     break

def print_cursor_details(node):
    print(f"--- Details for Cursor: {node.spelling} ---")
    for attr in dir(node):
        if not attr.startswith('_'): # 忽略内置函数和私有变量
            try:
                value = getattr(node, attr)
                # 如果是方法，我们可以选择不调用它（或者你可以过滤掉 callable）
                if not callable(value):
                   print(f"  {attr}: {value}")
            except Exception as e:
                print(f"  {attr}: <Error fetching: {e}>")

for node in tu.cursor.walk_preorder():
    print_cursor_details(node)
    #break
