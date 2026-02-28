
# 写单个的文件分析的例子

# 2 仔细研究和分析清楚，目前的代码
# 3   主要是pares解析出来的数据是什么，通过简单的例子好好分析一下 
# 4   好好考虑一下，数据库的表结构，

# 宏代码的展开和分析

# 新功能
 # 无效宏区域暗淡，
 # 宏展开后的代码高亮
 # 函数调用关系图的绘制
 # 结构体成员的跳转？？

      with ProcessPoolExecutor(max_workers=max_workers) as executor:
            future_to_file = {executor.submit(Database.parse_to_sqlite, task): task for task in tasks}
            for future in as_completed(future_to_file):
                task = future_to_file[future]
                completed += 1
写的有问题，之前不是这样写的！




