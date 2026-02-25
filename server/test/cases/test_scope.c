// test_scope.c
// @def: g_val
int val = 10;

void func() {
    // @def: l_val
    int val = 20;
    // @jump: l_val
    val = 30;
}

int main() {
    // @jump: g_val
    val = 40;
    return 0;
}
