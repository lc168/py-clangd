#!/usr/bin/env python3
import os
import sys
sys.path.append("/home/lc/sda/work/py-clangd/server")
import clang_init
from cindex import Index, CursorKind

# test_c = """
# #define MAX(a,b) ((a) > (b) ? (a) : (b))
# int main() {
#     int x = 1;
#     int y = 2;
#     int z = MAX(x+1, y);
#     return 0;
# }
# """
# with open("test_macro.c", "w") as f:
#     f.write(test_c)

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
                print(f"    Trying {attr}")
                #value = getattr(node, attr)
                # 如果是方法，我们可以选择不调用它（或者你可以过滤掉 callable）
                # if not callable(value):
                #    print(f"  {attr}: {value}")
            except Exception as e:
                print(f"  {attr}: <Error fetching: {e}>")


def print_node_tokens(node):
    print(f"Tokens for node '{node.spelling}' (kind: {node.kind}):")
    # 将生成器转为列表，或者直接用 for 遍历
    tokens = list(node.get_tokens())
    if not tokens:
        print("(No tokens found)")
        return
    for token in tokens:
        print(f"Token:'{token.spelling}'|Kind:{token.kind.name}")


# 通过函数传入参数是 node，获取extent.start.file, extent.start.offset, extent.end.offset, 来显示文件的内容
# 通过 extent.start.file 找到文件路径
# 通过 extent.start.offset 找到文件内容
# 通过 extent.end.offset 找到文件内容
def show_extent_location_data(node):
    file_path = node.extent.start.file
    start_offset = node.extent.start.offset
    end_offset = node.extent.end.offset

    len = end_offset - start_offset
    print(f"START !!!----------------usr={node.get_usr()}--")
    loc_file_name = node.location.file.name if node.location.file else "None"
    start_file_name = node.extent.start.file.name if node.extent.start.file else "None"
    end_file_name = node.extent.end.file.name if node.extent.end.file else "None"

    print(
        f"len={len}, spelling={node.spelling},\n"
        f"kind={node.kind},\n"
        f"location.file={loc_file_name},\n"
        f"start.file={start_file_name},\n"
        f"end.file={end_file_name}\n"
    )

    if node.location.file:
        with open(node.location.file.name, 'r') as f:
            print(f"file_extent={node.location.file.name}:{node.location.line}:{node.location.column}")
            content = f.read()
            print(content[node.location.offset:node.location.offset+len])


    if node.extent.start.file:
        with open(node.extent.start.file.name, "r") as f:
            print(f"file_local={node.extent.start.file.name}:{node.extent.start.line}:{node.extent.start.column}")
            content = f.read()
            print(content[start_offset:end_offset])

    print_node_tokens(node)
    print("END ----------------")

    return node.extent.start.file

def print_cursor_details_v2(node):
    print(
        f"{node.kind.name:<32}"
        f"spelling[{node.spelling:<20}]"
        f"extent=({node.extent.start.file}:{node.extent.start.offset}:{node.extent.end.offset})"
    )

for node in tu.cursor.walk_preorder():
    show_extent_location_data(node)
    #break
