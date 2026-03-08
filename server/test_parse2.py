import sys
import os

sys.path.append('/home/lc/py-clangd/server')
import clang_init
from cindex import Index, CursorKind

source = """
void *initial_boot_params;
void *test_var_with_init = 0;
"""

with open("test_snippet2.c", "w") as f:
    f.write(source)

idx = Index.create()
tu = idx.parse("test_snippet2.c", args=["-fsyntax-only"])

for node in tu.cursor.walk_preorder():
    if node.kind == CursorKind.VAR_DECL:
        print(f"Found: {node.kind} {node.spelling} at line {node.location.line} col {node.location.column} extent {node.extent.start.line}:{node.extent.start.column}-{node.extent.end.line}:{node.extent.end.column}")
        print(f"USR: {node.get_usr()}")
        print(f"Is def: {node.is_definition()}")

