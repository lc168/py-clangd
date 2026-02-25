import sqlite3
import sys
import os

def inspect_db(db_path):
    if not os.path.exists(db_path):
        print(f"Error: {db_path} not found")
        return

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    print("\n=== Table: symbols ===")
    cursor.execute("SELECT * FROM symbols LIMIT 20")
    for row in cursor.fetchall():
        print(row)

    print("\n=== Table: refs (Definitions) ===")
    cursor.execute("SELECT r.usr, s.name, r.file_path, r.s_line, r.role FROM refs r JOIN symbols s ON r.usr = s.usr WHERE r.role = 'def' LIMIT 20")
    for row in cursor.fetchall():
        print(row)

    print("\n=== Table: refs (Calls/Refs) ===")
    cursor.execute("SELECT r.usr, s.name, r.file_path, r.s_line, r.role FROM refs r JOIN symbols s ON r.usr = s.usr WHERE r.role != 'def' LIMIT 20")
    for row in cursor.fetchall():
        print(row)

    conn.close()

if __name__ == "__main__":
    db_path = sys.argv[1] if len(sys.argv) > 1 else "server/test/cases/pyclangd_index.db"
    inspect_db(db_path)
