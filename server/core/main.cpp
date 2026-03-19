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

// 统一 JSON 输出辅助函数
void emitJson(const std::string &kind, const std::string &name, const std::string &usr, 
              const std::string &file, int line, int col) {
    std::cout << "{"
              << "\"kind\":\"" << kind << "\", "
              << "\"name\":\"" << name << "\", "
              << "\"usr\":\"" << usr << "\", "
              << "\"file\":\"" << file << "\", "
              << "\"line\":" << line << ", \"col\":" << col
              << "}" << std::endl;
}

class IndexerPPCallbacks : public PPCallbacks {
    SourceManager &SM;
public:
    explicit IndexerPPCallbacks(SourceManager &SM) : SM(SM) {}
    void MacroDefined(const Token &MacroNameTok, const MacroDirective *MD) override {
        if (SM.isInSystemHeader(MacroNameTok.getLocation())) return;
        PresumedLoc PLoc = SM.getPresumedLoc(MacroNameTok.getLocation());
        std::string macroUsr = std::string("c:") + PLoc.getFilename() + "@" + MacroNameTok.getIdentifierInfo()->getName().str();
        emitJson("MACRO_DEF", MacroNameTok.getIdentifierInfo()->getName().str(), macroUsr, PLoc.getFilename(), PLoc.getLine(), PLoc.getColumn());
    }
    void MacroExpands(const Token &MacroNameTok, const MacroDefinition &MD, SourceRange Range, const MacroArgs *Args) override {
        SourceLocation Loc = SM.getSpellingLoc(Range.getBegin());
        if (SM.isInSystemHeader(Loc)) return;
        PresumedLoc PLoc = SM.getPresumedLoc(Loc);
        std::string macroUsr = std::string("c:") + PLoc.getFilename() + "@" + MacroNameTok.getIdentifierInfo()->getName().str();
        emitJson("MACRO_USE", MacroNameTok.getIdentifierInfo()->getName().str(), macroUsr, PLoc.getFilename(), PLoc.getLine(), PLoc.getColumn());
    }
};

class IndexerVisitor : public RecursiveASTVisitor<IndexerVisitor> {
    ASTContext &Context;
public:
    explicit IndexerVisitor(ASTContext &Context) : Context(Context) {}
    bool VisitNamedDecl(NamedDecl *D) {
        processSymbol(D, "DEF", D->getLocation());
        return true;
    }
    bool VisitDeclRefExpr(DeclRefExpr *E) {
        processSymbol(E->getFoundDecl(), "REF", E->getLocation());
        return true;
    }
private:
    void processSymbol(NamedDecl *D, const std::string &role, SourceLocation Loc) {
        SourceManager &SM = Context.getSourceManager();
        Loc = SM.getSpellingLoc(Loc);
        if (SM.isInSystemHeader(Loc)) return;
        
        llvm::SmallString<128> USR;
        index::generateUSRForDecl(D, USR);
        PresumedLoc PLoc = SM.getPresumedLoc(Loc);
        emitJson(role + "_" + D->getDeclKindName(), D->getNameAsString(), USR.c_str(), PLoc.getFilename(), PLoc.getLine(), PLoc.getColumn());
    }
};

class IndexerConsumer : public ASTConsumer {
    IndexerVisitor Visitor;
public:
    explicit IndexerConsumer(ASTContext &Context) : Visitor(Context) {}
    void HandleTranslationUnit(ASTContext &Context) override { Visitor.TraverseDecl(Context.getTranslationUnitDecl()); }
};

class IndexerAction : public ASTFrontendAction {
protected:
    void ExecuteAction() override {
        getCompilerInstance().getPreprocessor().addPPCallbacks(std::make_unique<IndexerPPCallbacks>(getCompilerInstance().getSourceManager()));
        ASTFrontendAction::ExecuteAction();
    }
    std::unique_ptr<ASTConsumer> CreateASTConsumer(CompilerInstance &CI, StringRef InFile) override { return std::make_unique<IndexerConsumer>(CI.getASTContext()); }
};

static llvm::cl::OptionCategory MyToolCategory("PyClangd-Core Options");
int main(int argc, const char **argv) {
    auto ExpectedParser = CommonOptionsParser::create(argc, argv, MyToolCategory);
    if (!ExpectedParser) return 1;
    ClangTool Tool(ExpectedParser->getCompilations(), ExpectedParser->getSourcePathList());
    return Tool.run(newFrontendActionFactory<IndexerAction>().get());
}