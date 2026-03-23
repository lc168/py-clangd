
int func100(int arg) {
    //printf("hello world=%d\n", arg);
    return 1;
}


int func120(int arg) {
    //printf("hello world=%d\n", arg);
    return 1;
}

struct A100 {
    int (*fun_struct_c100)(int);
};



struct A {
    struct A100 a100;
    int aav1;
    int aav2;
};

struct B {
    struct A structa;
    int bbv1;
};

int main() {
    struct A a1;
    struct B b1 = {
        .structa = {
            .a100 = {
                .fun_struct_c100 = func120,
            },
            .aav1 = 1,
            .aav2 = 2,
        },
        .bbv1 = 1,
    };

    struct B b2;
    b2.structa.a100.fun_struct_c100 = func100;

    int x = b1.structa.aav2;
    b1.structa.a100.fun_struct_c100 = func100;

    b1.structa.a100.fun_struct_c100(88);

    return 0;
}