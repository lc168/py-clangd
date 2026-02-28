from cindex import Index, CursorKind
import os

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
tu = idx.parse("test_macro.c", args=["-DetailedPreprocessingRecord"])

for node in tu.cursor.walk_preorder():
    if node.kind == CursorKind.MACRO_INSTANTIATION:
        print(f"Inst: {node.spelling} at {node.location.line}:{node.location.column}")
        for token in node.get_tokens():
            print(f"  Token: {token.spelling}")
    elif node.kind == CursorKind.VAR_DECL and node.spelling == "z":
        print(f"Var: {node.spelling}")
        for child in node.get_children():
            print(f"  Child: {child.kind} {child.spelling}")
            for token in child.get_tokens():
                print(f"    Token: {token.spelling}")

