import gdb
import json
import time
import os

class AutoDumper:
    def __init__(self):
        self.is_running = False
        self.output_prefix = ""
        self.max_depth = 3
        self.visited = {}

    def start(self, output_prefix, depth):
        self.output_prefix = output_prefix
        self.max_depth = depth
        
        output_dir = os.path.dirname(self.output_prefix)
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir, exist_ok=True)

        if not self.is_running:
            gdb.events.stop.connect(self.stop_handler)
            self.is_running = True
            print(f"[*] G6 全量无锁抓取已启动.")
            print(f"[*] 文件前缀: {self.output_prefix}")
            print(f"[*] 递归深度: {depth}")
            print("[*] 提示: 触发断点后将自动抓取并继续。输入 'dump_to_g6_stop' 可停止。")

    def stop(self):
        if self.is_running:
            gdb.events.stop.disconnect(self.stop_handler)
            self.is_running = False
            print("[*] G6 全量抓取已停止。")

    # 每次触发断点时，都会调用这个函数
    def stop_handler(self, event):
        self.visited = {}
        
        try:
            frame = gdb.selected_frame()
            thread = gdb.selected_thread()
            
            ptid = thread.ptid
            tid = ptid[1] if ptid[1] != 0 else ptid[0]
            cpu_id = thread.num
            ts_ns = time.time_ns()
            
            file_name = f"{self.output_prefix}{ts_ns}_cpu{cpu_id}.json"

            # -----------------------------------------
            # 新增：获取文件路径和代码行号 (Symtab and Line)
            # -----------------------------------------
            sal = frame.find_sal()
            source_file = sal.symtab.fullname() if sal.symtab else "unknown_file"
            source_line = sal.line if sal.line else 0

            ctx = {
                "cpu_id": cpu_id,
                "tid": tid,
                "pc": hex(frame.pc()),
                "function": frame.name() if frame.name() else "unknown",
                "file": source_file,   # 绝对路径
                "line": source_line    # 代码行号
            }

            block = frame.block()
            args_data = {}
            locals_data = {}

            while block:
                for symbol in block:
                    if symbol.is_argument or symbol.is_variable:
                        try:
                            val = frame.read_var(symbol, block)
                            captured = self._capture_recursive(val, depth=0)
                            if symbol.is_argument:
                                args_data[symbol.name] = captured
                            else:
                                locals_data[symbol.name] = captured
                        except Exception:
                            pass
                block = block.superblock

            frame_data = {
                "ts_ns": ts_ns,
                "context": ctx,
                "variables": {
                    "args": args_data,
                    "locals": locals_data
                }
            }

            with open(file_name, 'w', encoding='utf-8') as f:
                json.dump(frame_data, f)

        except Exception as e:
            print(f"\n[Dump Error] 抓取失败: {e}")

        gdb.post_event(self._do_continue)

    def _do_continue(self):
        try:
            # 抑制正在运行时的多余报错提示
            gdb.execute("continue", to_string=True)
        except gdb.error:
            pass

    def _capture_recursive(self, val, depth):
        if depth > self.max_depth:
            return {"kind": "truncated", "reason": "max_depth"}

        t = val.type.strip_typedefs()
        
        try:
            addr = str(val.address).split()[0] if val.address else None
        except:
            addr = None

        if addr and addr != "0x0" and addr in self.visited:
            return {"kind": "ref", "link": addr}

        if addr:
            self.visited[addr] = True

        # -----------------------------------------
        # 修复：处理根节点本身就是指针的情况
        # -----------------------------------------
        if t.code == gdb.TYPE_CODE_PTR:
            try:
                ptr_addr = str(val).split()[0]
                if ptr_addr == "0x0":
                    return {"kind": "ptr", "link": "NULL"}
                else:
                    return {
                        "kind": "ptr", 
                        "link": ptr_addr, 
                        "target": self._capture_recursive(val.dereference(), depth + 1)
                    }
            except Exception as e:
                return {"kind": "ptr", "error": str(e)}

        # 处理数组
        if t.code == gdb.TYPE_CODE_ARRAY:
            try:
                target_type = t.target().strip_typedefs()
                if target_type.code == gdb.TYPE_CODE_INT and target_type.sizeof == 1:
                    return {"kind": "char_array", "data": val.string(errors='ignore')}
                
                (low, high) = t.range()
                arr_data = []
                for i in range(low, high + 1):
                    arr_data.append(self._capture_recursive(val[i], depth))
                return {"kind": "array", "elements": arr_data}
            except Exception as e:
                return {"kind": "array", "error": str(e)}

        # 处理结构体
        if t.code == gdb.TYPE_CODE_STRUCT:
            fields = {}
            for field in t.fields():
                if not hasattr(field, 'bitpos'): continue
                f_name = field.name
                try:
                    f_val = val[f_name]
                    f_type = f_val.type.strip_typedefs()
                    
                    if f_type.code == gdb.TYPE_CODE_PTR:
                        ptr_addr = str(f_val).split()[0]
                        if ptr_addr == "0x0":
                            fields[f_name] = {"kind": "ptr", "link": "NULL"}
                        else:
                            fields[f_name] = {
                                "kind": "ptr", 
                                "link": ptr_addr, 
                                "target": self._capture_recursive(f_val.dereference(), depth + 1)
                            }
                    else:
                        fields[f_name] = self._capture_recursive(f_val, depth)
                except:
                    fields[f_name] = {"kind": "error", "data": "<unreadable>"}
            return {"kind": "struct", "addr": addr, "fields": fields}

        return {"kind": "val", "data": str(val)}

global_dumper = AutoDumper()

class CmdDumpToG6(gdb.Command):
    def __init__(self):
        super(CmdDumpToG6, self).__init__("dump_to_g6", gdb.COMMAND_USER)

    def invoke(self, arg, from_tty):
        args = gdb.string_to_argv(arg)
        if len(args) < 1:
            print("用法: dump_to_g6 <输出目录/文件前缀> [--depth=N]")
            return
            
        output_prefix = args[0]
        depth = 3
        if len(args) >= 2 and args[1].startswith("--depth="):
            try:
                depth = int(args[1].split("=")[1])
            except ValueError:
                pass

        global_dumper.start(output_prefix, depth)

class CmdDumpStop(gdb.Command):
    def __init__(self):
        super(CmdDumpStop, self).__init__("dump_to_g6_stop", gdb.COMMAND_USER)

    def invoke(self, arg, from_tty):
        global_dumper.stop()

CmdDumpToG6()
CmdDumpStop()