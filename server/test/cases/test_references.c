int global_ref_target = 100; // @ref_expect: g_var

void modify_global() {
    global_ref_target += 10; // @ref_expect: g_var
}

void use_local() {
    int local_var = 1; // @ref_expect: l_var
    local_var = local_var + 1; // @ref_expect: l_var
    
    // Jump requests
    global_ref_target = 0; // @ref_target: g_var
    local_var = 0; // @ref_target: l_var
}

#define MY_MACRO 1 // @def: my_macro
#ifdef MY_MACRO // @jump: my_macro
int a = 1;
#endif
