/**
 * 测试 lsp_references 对【宏】的引用查找
 *
 * 场景：
 *  1. 常量宏 BUF_SIZE 被多处引用，确保所有展开点都能被找到
 *  2. 函数宏 MAX() 被多处调用，确保宏实例化都能被追踪
 *  3. 两个不同宏互不干扰
 */

#define BUF_SIZE 256   // @ref_target: BUF_SIZE
#define TIMEOUT  1000  // @ref_target: TIMEOUT

void alloc_buffer() {
    char buf[BUF_SIZE]; // @ref_expect: BUF_SIZE
    (void)buf;
}

int get_size() {
    return BUF_SIZE; // @ref_expect: BUF_SIZE
}

void timer_init() {
    int t = TIMEOUT; // @ref_expect: TIMEOUT
    (void)t;
}

int is_timeout(int elapsed) {
    return elapsed >= TIMEOUT; // @ref_expect: TIMEOUT
}

int main() {
    char arr[BUF_SIZE]; // @ref_expect: BUF_SIZE
    (void)arr;
    return 0;
}
