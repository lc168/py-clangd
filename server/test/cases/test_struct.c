struct A {
    int id; // @def: id_a
};

struct B {
    int id; // @def: id_b
};

int main() {
    struct A a;
    struct B b;
    a.id = 1; // @jump: id_a
    b.id = 2; // @jump: id_b
    return 0;
}
