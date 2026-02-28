#include "test_kernel_headers.h"

// Example struct that uses list_head
struct my_module {
    int id; // @def: my_module_id:id
    struct list_head list; // @def: my_module_list:list
};

void check_status() {
    // 1. Variable declared in struct via macro
    int ver = KERNEL_VERSION; // @jump: KERNEL_VERSION

    // 2. Global variable defined in another file, declared in header
    int a = global_sys_status; // @jump: global_sys_status_def

    // 3. Variable defined via DEFINE_PER_CPU macro, declared via DECLARE_PER_CPU macro
    int rq = runqueues; // @jump: runqueues_def

    // 4. Variable defined inside nested struct in header
    struct nested_dev nv;
    nv.info.dev_id = 42; // @jump: ns_dev_id:dev_id
    
    // 5. Member of a struct defined in header
    struct task_struct t;
    t.pid = 1; // @jump: task_pid:pid

    // 6. Inline function from header
    init_task(&t); // @jump: init_task
}

void check_macros() {
    struct my_module mod;
    struct list_head *pos = &mod.list; // @jump: my_module_list:list

    // 7. Using container_of macro
    struct my_module *m1 = container_of(pos, struct my_module, list); // @jump: container_of

    // 8. Using list_entry macro
    struct my_module *m2 = list_entry(pos, struct my_module, list); // @jump: list_entry
    
    m2->id = 5; // @jump: my_module_id:id
}

void check_complex_structs() {
    struct complex_dev cdev;
    
    // 9. Accessing unnamed union member
    cdev.dma_addr = 0x1000; // @jump: dma_addr:dma_addr
    cdev.flags = 1; // @jump: flags:flags
}

void check_function_pointers() {
    // 10. Using typedef from header
    device_init_fn init = 0; // @jump: device_init_fn:device_init_fn
    
    struct nested_dev d;
    if (init) {
        init(&d); // We don't jump on the call of func ptr usually, but testing the type is good
    }
}

// ========================================================
// Complex Usage testing (Part 2)
// ========================================================

void check_macro_math() {
    unsigned long a = 10;
    // 11. ALIGN macro
    unsigned long b = ALIGN(a, 8); // @jump: ALIGN
    // 12. IS_ERR pointer encoding
    void *ptr = (void *)((unsigned long)-10);
    if (IS_ERR(ptr)) { // @jump: IS_ERR
        long code = PTR_ERR(ptr); // @jump: PTR_ERR
    }
}

void check_locking_rcu() {
    // 13. preempt
    preempt_disable(); // @jump: preempt_disable
    // 14. RCU functions from headers
    rcu_read_lock(); // @jump: rcu_read_lock
    void *p = 0;
    void *v = rcu_dereference(p); // @jump: rcu_dereference
    rcu_read_unlock(); // @jump: rcu_read_unlock
    preempt_enable(); // @jump: preempt_enable
}

void check_list_iterators() {
    // 15. The infamous list_for_each_entry macro
    struct list_head *my_list_head = 0;
    struct my_module *curr;
    
    list_for_each_entry(curr, my_list_head, list) { // @jump: list_for_each_entry
        curr->id = 1; // @jump: my_module_id:id
    }
}

void check_complex_assertions() {
    int val = 5;
    // 16. Kernel asserts
    BUG_ON(val > 10); // @jump: BUG_ON
    WARN_ON(val < 0); // @jump: WARN_ON
    BUILD_BUG_ON(sizeof(int) != 4); // @jump: BUILD_BUG_ON
}

void check_memory_percpu() {
    // 17. per_cpu_ptr macro usage
    int *cpu_runq = per_cpu_ptr(&runqueues, 0); // @jump: per_cpu_ptr
    int local = *cpu_runq;
    
    // 18. smp macros
    int cpu_id = smp_processor_id(); // @jump: smp_processor_id
    int raw_cpu = raw_smp_processor_id(); // @jump: raw_smp_processor_id
}

void check_math_div() {
    uint64_t large_num = 10000;
    uint32_t base = 3;
    // 19. do_div macro returning remainder and modifying arg
    uint32_t rem = do_div(large_num, base); // @jump: do_div
}

void check_sysfs_device_usage() {
    // 20. Checking macros that instantiate multiple things internally
    struct device_node *node = 0;
    if (node) {
        const char *n = node->name; // @jump: dev_node_name:name
        struct device_node *p = node->parent; // @jump: dev_node_parent:parent
    }
    
    // Using atomic from header
    atomic_t ref = ATOMIC_INIT(0); // @jump: ATOMIC_INIT
    ref.counter = 1; // @jump: counter:counter
}
