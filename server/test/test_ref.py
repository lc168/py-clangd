import sys
import os

sys.path.append('/home/lc/py-clangd/server')
import clang_init
from cindex import Index, CursorKind

source = """
void *initial_boot_params;
void test() {
    initial_boot_params = 0;
}
"""
with open("test_snippet_ref.c", "w") as f:
    f.write(source)

idx = Index.create()
tu = idx.parse("test_snippet_ref.c", args=["-fsyntax-only"])

for node in tu.cursor.walk_preorder():
    if "initial_boot_params" in (node.spelling or "") and node.kind != CursorKind.VAR_DECL:
        print(f"Node: {node.kind} {node.spelling}")
        print(f"  is_declaration(): {node.kind.is_declaration()}")
        print(f"  is_reference(): {node.kind.is_reference()}")
        print(f"  is DECL_REF_EXPR: {node.kind == CursorKind.DECL_REF_EXPR}")
