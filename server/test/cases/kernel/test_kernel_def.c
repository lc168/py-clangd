#include "test_kernel_headers.h"

// Basic declarations testing old headers
int global_sys_status = 1; // @def: global_sys_status_def
DEFINE_PER_CPU(int, runqueues) = 0; // @def: runqueues_def
DECLARE_WAIT_QUEUE_HEAD(my_queue); // @def: my_queue_def
int my_device_init(struct nested_dev *dev) { dev->info.dev_id = 100; return 0; } // @def: my_device_init
device_init_fn default_init = my_device_init; // @def: default_init
int syscall_table_size __read_mostly = 256; // @def: syscall_table_size_def

DEFINE_SPINLOCK(my_global_lock); // @def: my_global_lock
atomic_t my_ref_count = ATOMIC_INIT(1); // @def: my_ref_count
DECLARE_COMPLETION(my_comp); // @def: my_comp
int my_driver_param = 5;
module_param(my_driver_param, int, 0644); // @def: my_driver_param_usage:my_driver_param

// ========================================================
// Complex Test Objects Instantiation
// ========================================================

// 1. SYSCALL_DEFINE instances
SYSCALL_DEFINE3(read, unsigned int, fd, char *, buf, size_t, count) { // @def: sym_sys_read:read
    return 0;
}
EXPORT_SYMBOL(sys_read); // @jump: EXPORT_SYMBOL

SYSCALL_DEFINE1(close, unsigned int, fd) { // @def: sym_sys_close:close
    return 0;
}
EXPORT_SYMBOL_GPL(sys_close); // @jump: EXPORT_SYMBOL_GPL

// 2. Initcalls
int my_module_init_func(void) { return 0; } // @def: my_module_init_func
module_init(my_module_init_func); // @jump: module_init
subsys_initcall(my_module_init_func); // @jump: subsys_initcall

// 3. Platform Driver Magic
int my_pdrv_probe(struct device *dev) { return 0; } // @def: my_pdrv_probe
struct platform_driver my_pdrv = {
    .probe = my_pdrv_probe,
    .driver_name = "my_drv"
};
module_platform_driver(my_pdrv); // @jump: module_platform_driver

// 4. sysfs Device Attributes
int test_attr_show(struct device *dev, char *buf) { return 0; } // @def: test_attr_show
int test_attr_store(struct device *dev, const char *buf, size_t count) { return count; } // @def: test_attr_store

// Nested macro generating a struct!
DEVICE_ATTR(test_attr, 0644, test_attr_show, test_attr_store); // @jump: DEVICE_ATTR

int ro_attr_show(struct device *dev, char *buf) { return 0; } // @def: ro_attr_show
DEVICE_ATTR_RO(ro_attr); // @jump: DEVICE_ATTR_RO

// 5. BITMAP and bitops
DECLARE_BITMAP(my_bit_map, 64); // @jump: DECLARE_BITMAP

// 6. Very Complex: TRACE_EVENT instantiation
TRACE_EVENT(sched_switch, // @jump: TRACE_EVENT
    PARAMS(int prev_pid, int next_pid),
    PARAMS(prev_pid, next_pid),
    struct { int unused; },
    {},
    {}
);

// 7. kthread_run instantiation
int my_thread_fn(void *data) { return 0; } // @def: my_thread_fn
struct task_struct *my_bg_thread;

void start_kthread(void) {
    my_bg_thread = kthread_run(my_thread_fn, NULL, "my_bg_thread"); // @jump: kthread_run
}

// 8. EXPORT_PER_CPU_SYMBOL
EXPORT_PER_CPU_SYMBOL(runqueues); // @jump: EXPORT_PER_CPU_SYMBOL

// 9. Early Setup Param
int my_early_setup(char *str) { return 1; } // @def: my_early_setup
early_param("my_boot_arg", my_early_setup); // @jump: early_param

// 10. Seq File operations
void *my_seq_start(struct seq_file *m, int *pos) { return NULL; } // @def: my_seq_start
struct seq_operations my_seq_ops;
void init_seq() {
    my_seq_ops.start = my_seq_start; // @jump: seq_start:start
}
