void my_function(int a); // @def: func_decl

void my_function(int a) { // @def: func_def
}

int main() {
    my_function(10); // @jump: func_def
    return 0;
}
