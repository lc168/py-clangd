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

    // 1. 抓取宏定义 (#define)
    void MacroDefined(const Token &MacroNameTok, const MacroDirective *MD) override {
        if (SM.isInSystemHeader(MacroNameTok.getLocation())) return;

        std::string Name = MacroNameTok.getIdentifierInfo()->getName().str();
        PresumedLoc PLoc = SM.getPresumedLoc(MacroNameTok.getLocation());
      //<< "\", \"file\":\"" << PLoc.getFilename() 
        std::cout << "{\"kind\":\"MACRO_DEF\", \"name\":\"" << Name 
                  << "\", \"line\":" << PLoc.getLine() << "," << PLoc.getColumn() << "}" << std::endl;
    }

    // 2. 【新增】抓取宏展开 (使用宏的地方)
    void MacroExpands(const Token &MacroNameTok, const MacroDefinition &MD,
                      SourceRange Range, const MacroArgs *Args) override {
        // 过滤掉系统头文件里的宏展开
        if (SM.isInSystemHeader(Range.getBegin())) return;

        std::string Name = MacroNameTok.getIdentifierInfo()->getName().str();
        PresumedLoc PLoc = SM.getPresumedLoc(Range.getBegin());

        std::cout << "{\"kind\":\"MACRO_USE\", \"name\":\"" << Name 
                  << "\", \"file\":\"" << PLoc.getFilename() 
                  << "\", \"line\":" << PLoc.getLine() << "," << PLoc.getColumn() << "}" << std::endl;
    }
};

#include "clang/Index/USRGeneration.h" // 必须包含，用于生成 USR
#include "llvm/ADT/SmallString.h"

class IndexerVisitor : public RecursiveASTVisitor<IndexerVisitor> {
    ASTContext &Context;
public:
    explicit IndexerVisitor(ASTContext &Context) : Context(Context) {}

    // --- A. 抓取定义 (原有逻辑) ---
    bool VisitNamedDecl(NamedDecl *D) {
        if (Context.getSourceManager().isInSystemHeader(D->getLocation())) return true;
        outputSymbol(D, "DECL", D->getLocation());
        return true;
    }

    // --- B. 【新增】抓取引用 (解决 test_func 在宏里被调用的问题) ---
    bool VisitDeclRefExpr(DeclRefExpr *E) {
        NamedDecl *D = E->getFoundDecl();
        if (Context.getSourceManager().isInSystemHeader(D->getLocation())) return true;

        // 关键点：对于宏内部的引用，获取它在主文件中的“展开位置”
        SourceLocation Loc = E->getLocation();
        if (Loc.isMacroID()) {
            // 将位置“拉”回到宏被调用的那一行（比如第 12 行）
            Loc = Context.getSourceManager().getFileLoc(Loc);
        }

        outputSymbol(D, "REF", Loc);
        return true;
    }

private:
    void outputSymbol(NamedDecl *D, const std::string &kindPrefix, SourceLocation Loc) {
        SourceManager &SM = Context.getSourceManager();
        if (SM.isInSystemHeader(Loc)) return;

        std::string Name = D->getNameAsString();
        PresumedLoc PLoc = SM.getPresumedLoc(Loc);
        if (PLoc.isInvalid()) return;

        llvm::SmallString<128> USR;
        index::generateUSRForDecl(D, USR);

        std::string Type = "None";
        if (ValueDecl *VD = dyn_cast<ValueDecl>(D)) {
            Type = VD->getType().getAsString();
        }

        std::cout << "{"
                  << "\"kind\":\"" << kindPrefix << "_" << D->getDeclKindName() << "\", "
                  << "\"name\":\"" << Name << "\", "
                  << "\"usr\":\"" << USR.c_str() << "\", "
                  << "\"type\":\"" << Type << "\", "
                  << "\"line\":" << PLoc.getLine() << ", \"col\":" << PLoc.getColumn()
                  << "}" << std::endl;
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