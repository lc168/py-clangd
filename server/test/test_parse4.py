import sys
import os

sys.path.append('/home/lc/py-clangd/server')
import clang_init
from cindex import Index, CursorKind, StorageClass

source = """
extern void *extern_var;
void *tentative_var;
static void *tentative_static;
void *init_var = 0;
"""

with open("test_snippet4.c", "w") as f:
    f.write(source)

idx = Index.create()
tu = idx.parse("test_snippet4.c", args=["-fsyntax-only"])

for node in tu.cursor.walk_preorder():
    if node.kind == CursorKind.VAR_DECL:
        is_tentative = not node.is_definition() and node.storage_class != StorageClass.EXTERN
        print(f"--- {node.spelling} ---")
        print(f"Is def: {node.is_definition()}")
        print(f"Storage class: {node.storage_class}")
        print(f"is_tentative: {is_tentative}")
