import sys
import os

sys.path.append('/home/lc/py-clangd/server')
import clang_init
from cindex import Index, CursorKind

source = """
#define __section(S) __attribute__((__section__(#S)))
#define __ro_after_init __section(".data..ro_after_init")

void *initial_boot_params __ro_after_init;
"""

with open("test_snippet.c", "w") as f:
    f.write(source)

idx = Index.create()
tu = idx.parse("test_snippet.c", args=["-fsyntax-only"])

for node in tu.cursor.walk_preorder():
    if "initial_boot_params" in (node.spelling or ""):
        print(f"Found: {node.kind} {node.spelling} at line {node.location.line} col {node.location.column} extent {node.extent.start.line}:{node.extent.start.column}-{node.extent.end.line}:{node.extent.end.column}")
        print(f"USR: {node.get_usr()}")
        print(f"Is def: {node.is_definition()}")

