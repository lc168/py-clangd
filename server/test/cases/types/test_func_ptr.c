void target_func() {} // @def: target_func:target_func

int main() {
    void (*ptr)() = target_func; // @def: f_ptr:ptr
    ptr = target_func; // @jump: target_func:target_func
    ptr(); // @jump: f_ptr:ptr
    return 0;
}
