# 1 "test_macro.c"
# 1 "<built-in>" 1
# 1 "<built-in>" 3
# 412 "<built-in>" 3
# 1 "<command line>" 1
# 1 "<built-in>" 2
# 1 "test_macro.c" 2


int main() {
    int x = 1;
    int y = 2;
    int z = ((x+1) > (y) ? (x+1) : (y));
    return 0;
}
