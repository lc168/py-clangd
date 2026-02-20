from pygls.server import LanguageServer
from lsp_types import Location, Range, Position
from server.cindex import Index, Cursor
from server.database import IndexDatabase

server = LanguageServer("PyClangd", "v0.1")
db = IndexDatabase()

@server.feature("textDocument/definition")
def lsp_definition(ls, params):
    doc = ls.workspace.get_document(params.text_document.uri)
    pos = params.position

    index = Index.create()
    # 理想情况下此处应获取该文件的编译 args，暂以默认解析演示
    tu = index.parse(doc.path)
    location = tu.get_location(doc.path, (pos.line + 1, pos.character + 1))
    cursor = Cursor.from_location(tu, location)

    # 1. 优先尝试在当前解析树中找定义
    defn = cursor.get_definition()
    
    # 2. 如果当前文件找不到，或者只是个声明，则去数据库搜 USR
    if not defn or not defn.is_definition():
        usr = cursor.get_usr()
        if usr:
            res = db.find_definition(usr)
            if res:
                return Location(uri=f"file://{res[0]}", 
                                range=Range(start=Position(line=res[1]-1, character=res[2]-1),
                                            end=Position(line=res[1]-1, character=res[2]-1)))

    if defn and defn.location.file:
        return Location(
            uri=f"file://{defn.location.file.name}",
            range=Range(start=Position(line=defn.location.line-1, character=defn.location.column-1),
                        end=Position(line=defn.location.line-1, character=defn.location.column-1))
        )

if __name__ == "__main__":
    server.start_io()