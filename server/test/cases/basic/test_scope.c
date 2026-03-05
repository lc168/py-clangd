int val = 10; // @def: g_val:val

void func() {
    int val = 20; // @def: l_val:val
    val = 30; // @jump: l_val:val
}

int main() {
    val = 40; // @jump: g_val:val
    return 0;
}
