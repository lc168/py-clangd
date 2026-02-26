/**
 * 测试 lsp_references 对【枚举值】的引用查找
 *
 * 场景：
 *  1. 枚举值 STATE_IDLE 被用于 switch-case、if 判断、赋值
 *  2. 两个枚举里同名变体（如 OK）互不干扰
 */

typedef enum {
    STATE_IDLE = 0, // @ref_target: STATE_IDLE
    STATE_RUNNING,
    STATE_DONE
} State;

typedef enum {
    NET_OK = 0, // @ref_target: NET_OK
    NET_ERR
} NetStatus;

typedef enum {
    DISK_OK = 0, // @ref_target: DISK_OK
    DISK_ERR
} DiskStatus;

State get_initial_state() {
    return STATE_IDLE; // @ref_expect: STATE_IDLE
}

void process_state(State s) {
    switch (s) {
        case STATE_IDLE: // @ref_expect: STATE_IDLE
            break;
        default:
            break;
    }
}

int check_net() {
    return NET_OK; // @ref_expect: NET_OK
}

int check_disk() {
    return DISK_OK; // @ref_expect: DISK_OK
}

int main() {
    State s = STATE_IDLE; // @ref_expect: STATE_IDLE
    process_state(s);
    return 0;
}
