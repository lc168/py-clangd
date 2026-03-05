struct Inner {
    int val; // @def: val_member:val
};

struct Outer {
    struct Inner inner; // @def: inner_member:inner
};

int main() {
    struct Outer out;
    out.inner.val = 5; // @jump: inner_member:inner
    out.inner.val = 10; // @jump: val_member:val
    return 0;
}
