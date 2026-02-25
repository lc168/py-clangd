#define FEATURE_ENABLED

#ifdef FEATURE_ENABLED
void active_func() {} // @def: enabled_func
#else
void active_func() {}
#endif

int main() {
    active_func(); // @jump: enabled_func
    return 0;
}
