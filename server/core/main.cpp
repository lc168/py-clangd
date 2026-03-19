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

    // --- 新增：处理 #include 指令 ---
    void InclusionDirective(SourceLocation HashLoc, const Token &IncludeTok,
                          StringRef FileName, bool IsAngled,
                          CharSourceRange FilenameRange, OptionalFileEntryRef File,
                          StringRef SearchPath, StringRef RelativePath,
                          const Module *SuggestedModule, bool ModuleImported,
                          SrcMgr::CharacteristicKind FileType) override {
        
        // 1. 检查目标文件是否真的存在
        if (!File) return;

        // 2. 过滤掉系统头文件，保护数据库体积
        if (SM.isInSystemHeader(HashLoc)) return;

        // 3. 获取包含语句在主文件中的位置 (用于点击)
        SourceLocation Loc = SM.getSpellingLoc(HashLoc);
        PresumedLoc PLoc = SM.getPresumedLoc(Loc);
        if (!PLoc.isValid()) return;

        // 4. 获取被包含文件的真实绝对路径 (解决相对路径跳转失败)
        std::string absIncludedPath = File->getName().str();

        // 5. 发射 JSON
        // kind 设为 "inc", role 设为 "inc", usr 存放目标文件的绝对路径
        emitJson("inc", FileName.str(), absIncludedPath,
                 PLoc.getFilename(), PLoc.getLine(), PLoc.getColumn());
    }

    // 1. 处理 #define
    void MacroDefined(const Token &MacroNameTok, const MacroDirective *MD) override {
        if (SM.isInSystemHeader(MacroNameTok.getLocation())) return;
        PresumedLoc PLoc = SM.getPresumedLoc(MacroNameTok.getLocation());
        if (!PLoc.isValid()) return;
        std::string macroUsr = std::string("c:") + PLoc.getFilename() + "@" + MacroNameTok.getIdentifierInfo()->getName().str();
        emitJson("MACRO_DEF", MacroNameTok.getIdentifierInfo()->getName().str(), macroUsr, PLoc.getFilename(), PLoc.getLine(), PLoc.getColumn());
    }

    // 2. 处理普通的宏展开
    void MacroExpands(const Token &MacroNameTok, const MacroDefinition &MD, SourceRange Range, const MacroArgs *Args) override {
        handleMacroReference(MacroNameTok, MD);
    }

    // 3. --- 新增：处理 #ifdef ---
    void Ifdef(SourceLocation Loc, const Token &MacroNameTok, const MacroDefinition &MD) override {
        handleMacroReference(MacroNameTok, MD);
    }

    // 4. --- 新增：处理 #ifndef ---
    void Ifndef(SourceLocation Loc, const Token &MacroNameTok, const MacroDefinition &MD) override {
        handleMacroReference(MacroNameTok, MD);
    }

    // 5. --- 新增：处理 #if defined(MY_MACRO) ---
    void Defined(const Token &MacroNameTok, const MacroDefinition &MD, SourceRange Range) override {
        handleMacroReference(MacroNameTok, MD);
    }

private:
    // 统一处理宏引用的逻辑，确保 USR 逻辑与之前“锚定定义处”的策略一致
    void handleMacroReference(const Token &MacroNameTok, const MacroDefinition &MD) {
        SourceLocation UseLoc = SM.getSpellingLoc(MacroNameTok.getLocation());
        if (SM.isInSystemHeader(UseLoc)) return;
        PresumedLoc PUseLoc = SM.getPresumedLoc(UseLoc);
        if (!PUseLoc.isValid()) return;

        std::string defFile = "<builtin>";
        if (const MacroInfo *MI = MD.getMacroInfo()) {
            SourceLocation DefLoc = MI->getDefinitionLoc();
            if (DefLoc.isValid() && !SM.isWrittenInBuiltinFile(DefLoc) && !SM.isWrittenInCommandLineFile(DefLoc)) {
                PresumedLoc PDefLoc = SM.getPresumedLoc(DefLoc);
                if (PDefLoc.isValid()) defFile = PDefLoc.getFilename();
            }
        }

        std::string macroUsr = std::string("c:") + defFile + "@" + MacroNameTok.getIdentifierInfo()->getName().str();
        emitJson("MACRO_USE", MacroNameTok.getIdentifierInfo()->getName().str(), macroUsr, 
                PUseLoc.getFilename(), PUseLoc.getLine(), PUseLoc.getColumn());
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

    // --- 新增：处理结构体成员访问 (如 out.inner) ---
    bool VisitMemberExpr(MemberExpr *E) {
        // E->getMemberDecl() 获取该成员的定义 (ValueDecl)
        // E->getMemberLoc() 获取成员名字在源码中的位置 (极其重要，用于坐标匹配)
        processSymbol(E->getMemberDecl(), "REF", E->getMemberLoc());
        return true;
    }

    // --- 新增：处理类型名的引用 (如 device_init_fn, struct nested_dev) ---
    bool VisitTypeLoc(TypeLoc TL) {
        SourceManager &SM = Context.getSourceManager();
        if (SM.isInSystemHeader(TL.getBeginLoc())) return true;

        // 1. 处理 typedef 类型引用 (device_init_fn)
        if (auto TDTL = TL.getAs<TypedefTypeLoc>()) {
            // 直接通过 getTypePtr() 获取 TypedefType，再调用 getDecl()
            // 这种写法在 LLVM 各个版本中最为稳健
            processSymbol(TDTL.getTypePtr()->getDecl(), "REF", TDTL.getNameLoc());
        }
        // 2. 处理 结构体/联合体/枚举 类型引用 (struct nested_dev)
        else if (auto TTL = TL.getAs<TagTypeLoc>()) {
            processSymbol(TTL.getDecl(), "REF", TTL.getNameLoc());
        }
        return true;
    }

private:
    void processSymbol(NamedDecl *D, std::string role, SourceLocation Loc) {
        SourceManager &SM = Context.getSourceManager();
        Loc = SM.getSpellingLoc(Loc);
        if (SM.isInSystemHeader(Loc)) return;
    
        // 在 processSymbol 内部：
        bool isDef = false;
        if (auto *FD = dyn_cast<FunctionDecl>(D)) {
            isDef = FD->isThisDeclarationADefinition();
        } else if (auto *VD = dyn_cast<VarDecl>(D)) {
            isDef = VD->isThisDeclarationADefinition();
        } else if (auto *TD = dyn_cast<TagDecl>(D)) {
            isDef = TD->isThisDeclarationADefinition();
        }

        // --- 核心修复 A：区分 声明(DECL) 与 定义(DEF) ---
        // 只有真正的函数体或变量初始化才标记为 DEF
        if (role == "DEF" && !isDef) {
            role = "REF"; 
        }

        // --- 核心修复 B：只索引主文件中的定义 (极其重要！) ---
        // 如果你在解析 platform.c，那么只存 platform.c 里的符号定义。
        // 这样可以彻底解决“一个定义在数据库里出现几百次”的问题。
        if (role == "DEF" && !SM.isInMainFile(Loc)) return;

        // --- 核心修复 C：强制转换为绝对路径 ---
        FileID FID = SM.getFileID(Loc);
        const FileEntry *FE = SM.getFileEntryForID(FID);
        if (!FE) return;

        // tryGetRealPathName 会尝试获取该文件在磁盘上的真实绝对路径
        std::string absPath = FE->tryGetRealPathName().str();
        if (absPath.empty()) {
            absPath = SM.getFilename(Loc).str();
        } // 兜底方案

        // --- 核心修复逻辑：穿透匿名成员 ---
        // 在内核中，dma_addr 经常是 IndirectFieldDecl
        if (auto *IFD = dyn_cast<IndirectFieldDecl>(D)) {
            // 获取它在匿名容器里真正对应的 FieldDecl
            D = IFD->getAnonField(); 
        }
        // 如果经过穿透后发现 D 还是没有名字（比如匿名 union 本身），则跳过
        if (D->getNameAsString().empty()) return;

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