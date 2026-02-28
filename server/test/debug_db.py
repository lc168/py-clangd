import sqlite3
import os
conn = sqlite3.connect("cases/pyclangd_index.db")
c = conn.cursor()
c.execute("SELECT usr, role, s_line, s_col, e_col FROM refs WHERE file_path LIKE '%test_kernel_def.c' AND s_line = 34")
for row in c.fetchall():
    print("REF:", row)
c.execute("SELECT usr, name, kind FROM symbols")
syms = {r[0]: (r[1], r[2]) for r in c.fetchall()}
print("SYMS:")
c.execute("SELECT usr, role, s_line, s_col, e_col FROM refs WHERE file_path LIKE '%test_kernel_def.c' AND s_line = 34")
for row in c.fetchall():
    print("SYM:", syms.get(row[0]))
