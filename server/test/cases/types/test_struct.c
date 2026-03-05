struct A {
    int id; // @def: id_a:id
};

struct B {
    int id; // @def: id_b:id
};

int main() {
    struct A a;
    struct B b;
    a.id = 1; // @jump: id_a:id
    b.id = 2; // @jump: id_b:id
    return 0;
}
