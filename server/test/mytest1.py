#!/usr/bin/env python3
from concurrent.futures import ProcessPoolExecutor

# commands_to_run 假设是个存了 100 个任务指令的列表
# max_workers = 4 表示同时请 4 个工人（子进程）干活
def index_worker(index):
    print(">>>>>>>开始执行任务", index)
    # 模拟耗时
    import time
    #随机耗时
    import random
    time.sleep(random.randint(1, 5))
    print("<<任务执行完毕", index)
    return ("ok",index)

commands_to_run = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]

with ProcessPoolExecutor(max_workers=2) as executor:
    # .map 本质就是把任务列表里的东西，一个个喂给 index_worker，并自动阻塞等待所有人干完
    results = executor.map(index_worker, commands_to_run)
    
    # 所有人干完后，收集结果
    for res in results:
        print("一个文件处理完了：", res)
