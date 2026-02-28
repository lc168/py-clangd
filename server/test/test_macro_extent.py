from cindex import Index, CursorKind
import os
import clang_init

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

for node in tu.cursor.walk_preorder():
    if "MAX" in (node.spelling or ""):
        print(f"Node: kind={node.kind}, spelling={node.spelling}, extent=({node.extent.start.line}:{node.extent.start.column} - {node.extent.end.line}:{node.extent.end.column})")
