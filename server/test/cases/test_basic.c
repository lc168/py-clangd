void foo() { // @def: foo
}

int main() {
    foo(); // @jump: foo
    return 0;
}
