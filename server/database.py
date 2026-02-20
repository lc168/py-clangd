import sqlite3
import os

class IndexDatabase:
    def __init__(self):
        # 数据库存放在 server 目录下
        db_path = os.path.join(os.path.dirname(__file__), "pyclangd_index.db")
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.cursor = self.conn.cursor()
        self._setup()

    def _setup(self):
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS symbols (
                usr TEXT PRIMARY KEY,
                name TEXT,
                file_path TEXT,
                line INTEGER,
                column INTEGER
            )
        ''')
        self.conn.commit()

    def find_definition(self, usr):
        self.cursor.execute('SELECT file_path, line, column FROM symbols WHERE usr = ?', (usr,))
        return self.cursor.fetchone()

    def record_definition(self, usr, name, file, line, col):
        self.cursor.execute('''
            REPLACE INTO symbols (usr, name, file_path, line, column)
            VALUES (?, ?, ?, ?, ?)
        ''', (usr, name, file, line, col))
        self.conn.commit()