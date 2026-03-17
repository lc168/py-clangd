#include "clang/AST/ASTConsumer.h"
#include "clang/AST/RecursiveASTVisitor.h"
#include "clang/AST/RecordLayout.h"
#include "clang/Frontend/CompilerInstance.h"
#include "clang/Frontend/FrontendActions.h"
#include "clang/Lex/PPCallbacks.h"
#include "clang/Tooling/CommonOptionsParser.h"
#include "clang/Tooling/Tooling.h"
#include <iostream>
#include <string>

using namespace clang;
using namespace clang::tooling;

// --- 1. 宏探针：抓取预处理信息 ---
class IndexerPPCallbacks : public PPCallbacks {
    SourceManager &SM;
public:
    explicit IndexerPPCallbacks(SourceManager &SM) : SM(SM) {}

    void MacroDefined(const Token &MacroNameTok, const MacroDirective *MD) override {
        if (SM.isInSystemHeader(MacroNameTok.getLocation())) return;

        std::string Name = MacroNameTok.getIdentifierInfo()->getName().str();
        PresumedLoc PLoc = SM.getPresumedLoc(MacroNameTok.getLocation());

        // 输出 JSON 格式
        std::cout << "{\"kind\":\"MACRO\", \"name\":\"" << Name 
                  << "\", \"file\":\"" << PLoc.getFilename() 
                  << "\", \"line\":" << PLoc.getLine() << "}" << std::endl;
    }
};

// --- 2. AST 探针：抓取变量和结构体偏移量 ---
class IndexerVisitor : public RecursiveASTVisitor<IndexerVisitor> {
    ASTContext &Context;
public:
    explicit IndexerVisitor(ASTContext &Context) : Context(Context) {}

    // 处理结构体成员 (Field)
    bool VisitFieldDecl(FieldDecl *F) {
        if (Context.getSourceManager().isInSystemHeader(F->getLocation())) return true;

        const RecordDecl *Record = F->getParent();
        const ASTRecordLayout &Layout = Context.getASTRecordLayout(Record);
        
        // 计算字节偏移量
        uint64_t OffsetBytes = Layout.getFieldOffset(F->getFieldIndex()) / 8;
        PresumedLoc PLoc = Context.getSourceManager().getPresumedLoc(F->getLocation());

        std::cout << "{\"kind\":\"FIELD\", \"name\":\"" << F->getNameAsString() 
                  << "\", \"struct\":\"" << Record->getNameAsString()
                  << "\", \"type\":\"" << F->getType().getAsString()
                  << "\", \"offset\":" << OffsetBytes
                  << ", \"line\":" << PLoc.getLine() << "}" << std::endl;
        return true;
    }

    // 处理全局/局部变量
    bool VisitVarDecl(VarDecl *D) {
        if (Context.getSourceManager().isInSystemHeader(D->getLocation())) return true;
        if (isa<ParmVarDecl>(D)) return true; // 忽略函数参数

        PresumedLoc PLoc = Context.getSourceManager().getPresumedLoc(D->getLocation());
        std::cout << "{\"kind\":\"VAR\", \"name\":\"" << D->getNameAsString() 
                  << "\", \"type\":\"" << D->getType().getAsString()
                  << "\", \"line\":" << PLoc.getLine() << "}" << std::endl;
        return true;
    }
};

// --- 3. 逻辑封装 (插槽连接器) ---
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

// --- 4. 入口函数 ---
static llvm::cl::OptionCategory MyToolCategory("./PyClangd-Core xx.c -- -I./include");

int main(int argc, const char **argv) {
    auto ExpectedParser = CommonOptionsParser::create(argc, argv, MyToolCategory);
    if (!ExpectedParser) return 1;

    ClangTool Tool(ExpectedParser->getCompilations(), ExpectedParser->getSourcePathList());
    return Tool.run(newFrontendActionFactory<IndexerAction>().get());
}