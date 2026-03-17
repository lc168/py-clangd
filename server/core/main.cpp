#include "clang/AST/RecursiveASTVisitor.h"
#include "clang/Frontend/CompilerInstance.h"
#include "clang/Frontend/FrontendActions.h"
#include "clang/Lex/PPCallbacks.h"
#include "clang/Tooling/CommonOptionsParser.h"
#include "clang/Tooling/Tooling.h"
#include <iostream>

using namespace clang;
using namespace clang::tooling;

// 1. 宏探针：专门处理预处理阶段
class IndexerPPCallbacks : public PPCallbacks {
    SourceManager &SM;
public:
    explicit IndexerPPCallbacks(SourceManager &SM) : SM(SM) {}

    void MacroDefined(const Token &MacroNameTok, const MacroDirective *MD) override {
        if (SM.isInSystemHeader(MacroNameTok.getLocation())) return;
        
        std::string Name = MacroNameTok.getIdentifierInfo()->getName().str();
        SourceLocation Loc = MacroNameTok.getLocation();
        PresumedLoc PLoc = SM.getPresumedLoc(Loc);

        // 输出格式可以自定义，方便 Python 解析
        std::cout << "SYMBOL|MACRO|" << Name << "|" 
                  << PLoc.getFilename() << "|" << PLoc.getLine() << "\n";
    }
};

// 2. AST 探针：处理变量和函数声明
class IndexerVisitor : public RecursiveASTVisitor<IndexerVisitor> {
    ASTContext &Context;
public:
    explicit IndexerVisitor(ASTContext &Context) : Context(Context) {}

    bool VisitVarDecl(VarDecl *D) {
        if (Context.getSourceManager().isInSystemHeader(D->getLocation())) return true;

        std::string Name = D->getNameAsString();
        std::string Type = D->getType().getAsString();
        // LLVM 23 获取 USR 的标准方式
        // 这里可以调用生成 USR 的辅助函数
        
        std::cout << "SYMBOL|VAR|" << Name << "|" << Type << "\n";
        return true;
    }
};

// 3. 逻辑封装
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
        // 在此处挂载 PPCallbacks
        getCompilerInstance().getPreprocessor().addPPCallbacks(
            std::make_unique<IndexerPPCallbacks>(getCompilerInstance().getSourceManager()));
        
        ASTFrontendAction::ExecuteAction();
    }

    std::unique_ptr<ASTConsumer> CreateASTConsumer(CompilerInstance &CI, StringRef InFile) override {
        return std::make_unique<IndexerConsumer>(CI.getASTContext());
    }
};

// 4. 入口函数
static llvm::cl::OptionCategory MyToolCategory("clang-indexer options");

int main(int argc, const char **argv) {
    auto ExpectedParser = CommonOptionsParser::create(argc, argv, MyToolCategory);
    if (!ExpectedParser) return 1;

    ClangTool Tool(ExpectedParser->getCompilations(), ExpectedParser->getSourcePathList());
    return Tool.run(newFrontendActionFactory<IndexerAction>().get());
}