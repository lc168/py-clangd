/**
 * 测试 lsp_references 对【函数调用】的引用查找
 *
 * 场景：
 *  1. 一个函数 helper() 被多处调用，确保所有调用点都能被找到
 *  2. 两个同名但不同签名的辅助函数互不干扰（如 compute_a / compute_b）
 */

int helper() { // @ref_target: helper
    return 42;
}

void caller_one() {
    int x = helper(); // @ref_expect: helper
}

void caller_two() {
    int y = helper() + 1; // @ref_expect: helper
}

int caller_three() {
    return helper(); // @ref_expect: helper
}

// 两个名字不同的函数，确保引用不交叉污染
int compute_a() { // @ref_target: compute_a
    return 1;
}

int compute_b() { // @ref_target: compute_b
    return 2;
}

int main() {
    compute_a(); // @ref_expect: compute_a
    compute_b(); // @ref_expect: compute_b
    compute_a(); // @ref_expect: compute_a
    return 0;
}
