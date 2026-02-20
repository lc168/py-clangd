import sqlite3

class IndexDatabase:
    def __init__(self, db_path="pyclangd_index.db"):
        self.conn = sqlite3.connect(db_path)
        self.cursor = self.conn.cursor()
        self._setup()

    def _setup(self):
        # USR 是 libclang 提供的唯一标识符，用于匹配跨文件的相同函数
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

    def record_definition(self, usr, name, file, line, col):
        self.cursor.execute('''
            REPLACE INTO symbols (usr, name, file_path, line, column)
            VALUES (?, ?, ?, ?, ?)
        ''', (usr, name, file, line, col))
        self.conn.commit()

    def find_definition(self, usr):
        self.cursor.execute('SELECT file_path, line, column FROM symbols WHERE usr = ?', (usr,))
        return self.cursor.fetchone()