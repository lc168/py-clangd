// ---------------------------------------------------------
// Super Complex Macro Level 2: Real Kernel Header Patterns
// ---------------------------------------------------------

// 39. TRACE_EVENT - The most notoriously complex macro in Linux
// Defines structs, function prototypes, and callbacks all at once
#define DECLARE_TRACE(name, proto, args) \
    extern void trace_##name(proto) // @def: DECLARE_TRACE

#define DEFINE_TRACE(name) \
    void trace_##name(void) {} // @def: DEFINE_TRACE

#define TRACE_EVENT(name, proto, args, struct, assign, print) /* @def: TRACE_EVENT */ \
    DECLARE_TRACE(name, PARAMS(proto), PARAMS(args)); \
    static inline void trace_##name##_rcuidle(proto) {}

#define PARAMS(args...) args

// 40. list_for_each_entry - Control flow macros wrapping container_of
#define list_first_entry(ptr, type, member) \
    list_entry((ptr)->next, type, member) // @def: list_first_entry

#define list_next_entry(pos, member) \
    list_entry((pos)->member.next, typeof(*(pos)), member) // @def: list_next_entry

#define list_for_each_entry(pos, head, member) /* @def: list_for_each_entry */ \
    for (pos = list_first_entry(head, typeof(*pos), member);    \
         &pos->member != (head);                    \
         pos = list_next_entry(pos, member))

// 41. BUILD_BUG_ON - Compile time assertions
#define BUILD_BUG_ON_ZERO(e) (sizeof(struct { int:-!!(e); }))
#define __must_be_array(a)  BUILD_BUG_ON_ZERO(__same_type((a), &(a)[0]))
#define BUILD_BUG_ON(condition) ((void)sizeof(char[1 - 2*!!(condition)])) // @def: BUILD_BUG_ON

#define __same_type(a, b) __builtin_types_compatible_p(typeof(a), typeof(b))

// 42. WRITE_ONCE / READ_ONCE - Volatile casting macros
#define __READ_ONCE(x)  (*(const volatile typeof(x) *)&(x))
#define READ_ONCE(x)    __READ_ONCE(x) // @def: READ_ONCE

#define __WRITE_ONCE(x, val) do { *(volatile typeof(x) *)&(x) = (val); } while (0)
#define WRITE_ONCE(x, val) __WRITE_ONCE(x, val) // @def: WRITE_ONCE

// 43. Page alignment macros
#define PAGE_SHIFT  12 // @def: PAGE_SHIFT
#define PAGE_SIZE   (_AC(1,UL) << PAGE_SHIFT)

#define __AC(X,Y)   (X##Y)
#define _AC(X,Y)    __AC(X,Y)

#define PAGE_MASK   (~(PAGE_SIZE-1)) // @def: PAGE_MASK
#define PAGE_ALIGN(addr) ALIGN(addr, PAGE_SIZE) // @def: PAGE_ALIGN

// 44. smp_processor_id / per_cpu
#define raw_smp_processor_id()  (1) // @def: raw_smp_processor_id
#define smp_processor_id()  raw_smp_processor_id() // @def: smp_processor_id

#define __my_cpu_offset 0
#define this_cpu_ptr(ptr)   ((typeof(ptr))((unsigned long)(ptr) + __my_cpu_offset))
#define per_cpu_ptr(ptr, cpu)   this_cpu_ptr(ptr) // @def: per_cpu_ptr

// 45. kthread_run - Macro calling a function with varargs
struct task_struct *kthread_create_on_node(int (*threadfn)(void *data),
                       void *data, int node,
                       const char namefmt[], ...); // @def: kthread_create_on_node

#define kthread_create(threadfn, data, namefmt, arg...) \
    kthread_create_on_node(threadfn, data, -1, namefmt, ##arg) // @def: kthread_create

#define kthread_run(threadfn, data, namefmt, ...) /* @def: kthread_run */ \
({                                         \
    struct task_struct *__k                        \
        = kthread_create(threadfn, data, namefmt, ## __VA_ARGS__); \
    if (!IS_ERR(__k))                          \
        (void)0; /* wake up thread */ \
    __k;                                       \
})

// 46. dev_dbg / pr_debug - Format string macros
#define pr_fmt(fmt) fmt // @def: pr_fmt

#define no_printk(fmt, ...)             \
({                          \
    if (0)                      \
        printk(fmt, ##__VA_ARGS__);     \
    0;                      \
}) // @def: no_printk

extern int printk(const char *fmt, ...); // @def: printk

#define pr_debug(fmt, ...) \
    no_printk(pr_fmt(fmt), ##__VA_ARGS__) // @def: pr_debug
#define dev_dbg(dev, fmt, ...) \
    printk(fmt, ##__VA_ARGS__) // @def: dev_dbg

// 47. setup_param - Boot parameters
struct kernel_param {
    const char *str;
    int (*setup_func)(char *); // @def: param_setup_func:setup_func
};

#define __setup_param(str, unique_id, fn)   \
    static const char __setup_str_##unique_id[] __init = str; \
    static struct kernel_param __setup_##unique_id  \
        __attribute__((__used__))       \
        __attribute__((__section__(".init.setup"))) \
        = { __setup_str_##unique_id, fn } // @def: __setup_param

#define __setup(str, fn)    __setup_param(str, fn, fn) // @def: __setup
#define early_param(str, fn)    __setup_param(str, fn, fn) // @def: early_param

// 48. RCU locking mechanisms
static inline void rcu_read_lock(void) {} // @def: rcu_read_lock
static inline void rcu_read_unlock(void) {} // @def: rcu_read_unlock

// 49. do_div - Complex 64bit math macro
#define do_div(n, base) ({ /* @def: do_div */ \
    uint32_t __base = (base);           \
    uint32_t __rem;                 \
    __rem = ((uint64_t)(n)) % __base;       \
    (n) = ((uint64_t)(n)) / __base;         \
    __rem;                      \
})

// 50. typeof_member - GCC extension heavy macro
#define typeof_member(T, m) typeof(((T*)0)->m) // @def: typeof_member

// 51. clamp - Range bounds checking
#define clamp(val, lo, hi) min((typeof(val))max(val, lo), hi) // @def: clamp
#define max(x, y) ({                \
    typeof(x) _max1 = (x);          \
    typeof(y) _max2 = (y);          \
    (void) (&_max1 == &_max2);      \
    _max1 > _max2 ? _max1 : _max2; }) // @def: max

// 52. ftrace macros
#define CALLER_ADDR0 ((unsigned long)__builtin_return_address(0)) // @def: CALLER_ADDR0

// 53. lockdep mapping
struct lockdep_map {
    const char *name; // @def: lockdep_name:name
};
#define STATIC_LOCKDEP_MAP_INIT(_name, _key) \
    { .name = (_name) } // @def: STATIC_LOCKDEP_MAP_INIT

// 54. rbtree nodes
struct rb_node {
    unsigned long  __rb_parent_color; // @def: __rb_parent_color:__rb_parent_color
    struct rb_node *rb_right;
    struct rb_node *rb_left;
} __attribute__((aligned(sizeof(long)))); // @def: rb_node

// 55. EXPORT_PER_CPU_SYMBOL
#define EXPORT_PER_CPU_SYMBOL(var) EXPORT_SYMBOL(var) // @def: EXPORT_PER_CPU_SYMBOL

// 56. seq_file operations
struct seq_file;
struct seq_operations {
    void * (*start) (struct seq_file *m, int *pos); // @def: seq_start:start
    void (*stop) (struct seq_file *m, void *v); // @def: seq_stop:stop
    void * (*next) (struct seq_file *m, void *v, int *pos);
    int (*show) (struct seq_file *m, void *v);
}; // @def: seq_operations

// 57. preempt counting
#define preempt_disable() do { } while (0) // @def: preempt_disable
#define preempt_enable() do { } while (0) // @def: preempt_enable

// 58. BUG() - Arch specific crash
#define BUG() do { \
    printk("BUG: failure at %s:%d/%s()!\n", __FILE__, __LINE__, __func__); \
    while(1); \
} while (0) // @def: BUG
