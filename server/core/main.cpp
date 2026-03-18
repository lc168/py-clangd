#include "clang/AST/ASTConsumer.h"
#include "clang/AST/RecursiveASTVisitor.h"
#include "clang/Frontend/CompilerInstance.h"
#include "clang/Frontend/FrontendActions.h"
#include "clang/Lex/PPCallbacks.h"
#include "clang/Tooling/CommonOptionsParser.h"
#include "clang/Tooling/Tooling.h"
#include "clang/Index/USRGeneration.h"
#include "llvm/ADT/SmallString.h"
#include <iostream>

using namespace clang;
using namespace clang::tooling;

// --- 工具函数：统一输出格式 ---
void printSymbol(SourceManager &SM, NamedDecl *D, SourceLocation Loc, const std::string &Relation) {
    if (Loc.isInvalid() || SM.isInSystemHeader(Loc)) return;

    // 关键：无论嵌套多少层，getSpellingLoc 都能拿到你写代码的那一行
    SourceLocation SpLoc = SM.getSpellingLoc(Loc);
    PresumedLoc PLoc = SM.getPresumedLoc(SpLoc);
    if (PLoc.isInvalid()) return;

    llvm::SmallString<128> USR;
    index::generateUSRForDecl(D, USR);

    std::cout << "{"
              << "\"kind\":\"" << Relation << "_" << D->getDeclKindName() << "\", "
              << "\"name\":\"" << D->getNameAsString() << "\", "
              << "\"usr\":\"" << USR.c_str() << "\", "
              << "\"line\":" << PLoc.getLine() << ", \"col\":" << PLoc.getColumn()
              << "}" << std::endl;
}

// --- 1. 宏探针：处理宏定义和深层展开 ---
class IndexerPPCallbacks : public PPCallbacks {
    SourceManager &SM;
public:
    explicit IndexerPPCallbacks(SourceManager &SM) : SM(SM) {}

    void MacroDefined(const Token &MacroNameTok, const MacroDirective *MD) override {
        if (SM.isInSystemHeader(MacroNameTok.getLocation())) return;
        std::string Name = MacroNameTok.getIdentifierInfo()->getName().str();
        PresumedLoc PLoc = SM.getPresumedLoc(MacroNameTok.getLocation());
        std::cout << "{\"kind\":\"DEF_MACRO\", \"name\":\"" << Name 
                  << "\", \"line\":" << PLoc.getLine() << ", \"col\":" << PLoc.getColumn() << "}" << std::endl;
    }

    void MacroExpands(const Token &MacroNameTok, const MacroDefinition &MD,
                      SourceRange Range, const MacroArgs *Args) override {
        // 这里处理宏嵌套。Range.getBegin() 会指向宏被触发的位置
        SourceLocation Loc = Range.getBegin();
        if (SM.isInSystemHeader(Loc)) return;

        // 获取书写位置：即使在宏定义内部，也能拿到对应的行号
        SourceLocation SpLoc = SM.getSpellingLoc(Loc);
        PresumedLoc PLoc = SM.getPresumedLoc(SpLoc);

        std::cout << "{\"kind\":\"REF_MACRO\", \"name\":\"" << MacroNameTok.getIdentifierInfo()->getName().str()
                  << "\", \"line\":" << PLoc.getLine() << ", \"col\":" << PLoc.getColumn() << "}" << std::endl;
    }
};

// --- 2. AST 探针：处理函数/变量的引用 ---
class IndexerVisitor : public RecursiveASTVisitor<IndexerVisitor> {
    ASTContext &Context;
public:
    explicit IndexerVisitor(ASTContext &Context) : Context(Context) {}

    // 抓取符号定义（函数、变量、结构体名）
    bool VisitNamedDecl(NamedDecl *D) {
        printSymbol(Context.getSourceManager(), D, D->getLocation(), "DEF");
        return true;
    }

    // 关键：抓取符号引用（解决宏内调用函数的问题）
    bool VisitDeclRefExpr(DeclRefExpr *E) {
        printSymbol(Context.getSourceManager(), E->getFoundDecl(), E->getLocation(), "REF");
        return true;
    }
};

// --- 3. 框架封装 (保持不变) ---
class IndexerConsumer : public ASTConsumer {
    IndexerVisitor Visitor;
public:
    explicit IndexerConsumer(ASTContext &Context) : Visitor(Context) {}
    void HandleTranslationUnit(ASTContext &Context) override {
        Visitor.TraverseDecl(Context.getTranslationUnitDecl());
    }
};

class IndexerAction : public ASTFrontendAction {
protected:
    void ExecuteAction() override {
        getCompilerInstance().getPreprocessor().addPPCallbacks(
            std::make_unique<IndexerPPCallbacks>(getCompilerInstance().getSourceManager()));
        ASTFrontendAction::ExecuteAction();
    }
    std::unique_ptr<ASTConsumer> CreateASTConsumer(CompilerInstance &CI, StringRef InFile) override {
        return std::make_unique<IndexerConsumer>(CI.getASTContext());
    }
};

static llvm::cl::OptionCategory MyToolCategory("PyClangd-Core Options");
int main(int argc, const char **argv) {
    auto ExpectedParser = CommonOptionsParser::create(argc, argv, MyToolCategory);
    if (!ExpectedParser) return 1;
    ClangTool Tool(ExpectedParser->getCompilations(), ExpectedParser->getSourcePathList());
    return Tool.run(newFrontendActionFactory<IndexerAction>().get());
}



