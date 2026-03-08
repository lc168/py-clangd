
#define __section(S) __attribute__((__section__(#S)))
#define __ro_after_init __section(".data..ro_after_init")

void *initial_boot_params __ro_after_init;
