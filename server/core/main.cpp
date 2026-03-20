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

#include "llvm/Support/FileSystem.h"
#include "llvm/Support/Path.h"

// --- 1. 辅助函数：获取规范化绝对路径 (带 Size-1 缓存) ---
std::string getAbsPath(SourceManager &SM, SourceLocation Loc) {
    static thread_local std::string lastRawPath = "";
    static thread_local std::string lastRealPath = "";

    FileID FID = SM.getFileID(Loc);
    auto FE = SM.getFileEntryRefForID(FID);
    if (!FE) return "";

    std::string currentPath = FE->getName().str();

    // --- 新增：放行 Clang 的内部虚拟文件 ---
    // 这些文件不需要（也无法）去硬盘上找绝对路径，直接原样返回即可
    if (currentPath == "<built-in>" || currentPath == "<command line>" || currentPath == "<scratch space>") {
        return currentPath;
    }

    // 1. 命中缓存，直接返回
    if (currentPath == lastRawPath) {
        return lastRealPath;
    }

    // 2. 未命中缓存，请求操作系统进行规范化
    llvm::SmallString<256> realPath;
    if (!llvm::sys::fs::real_path(currentPath, realPath)) {
        // 更新缓存
        lastRawPath = currentPath;
        lastRealPath = realPath.str().str();
        return lastRealPath;
    } else {
        // 3. 真正遇到了异常情况（如文件权限被拒、文件刚被删除等）
        // 遵循你的思路：Fail-Fast 坚决报错，拒绝返回脏路径
        std::cerr << "[Warning] Could not resolve real path for disk file: " << currentPath << std::endl;
        
        // 更新缓存为空，防止下次同样的错误文件反复触发系统调用和打印
        lastRawPath = currentPath;
        lastRealPath = ""; 
        return "";
    }
}

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

        //2. 过滤掉系统头文件，保护数据库体积
        if (SM.isInSystemHeader(HashLoc)) return;

        // 1. 核心修复：获取文件名在源码中的起始位置 (FilenameRange.getBegin())
        // 而不是使用 HashLoc (#号的位置)
        SourceLocation FileStartLoc = SM.getSpellingLoc(FilenameRange.getBegin());
        PresumedLoc PLoc = SM.getPresumedLoc(FileStartLoc);
        if (!PLoc.isValid())
            return;

        // 2. 获取主文件的绝对路径 (调用上面的工具函数)
        std::string mainFileAbs = getAbsPath(SM, FileStartLoc);

        // 3. 获取目标头文件的绝对路径 (存入 usr 字段供跳转使用)
        std::string targetAbs = File->getName().str();
        if (llvm::sys::path::is_relative(targetAbs)) {
            llvm::SmallString<256> tmp(targetAbs);
            SM.getFileManager().makeAbsolutePath(tmp);
            targetAbs = tmp.str().str();
        }

        // 4. 发射 JSON
        // name: "linux/platform_device.h"
        // usr: "/home/lc/kernel/include/linux/platform_device.h"
        // file: "/home/lc/kernel/drivers/base/platform.c"
        // line/col: 定位到文件名的起始点
        emitJson("inc", FileName.str(), targetAbs, mainFileAbs, 
                 PLoc.getLine(), PLoc.getColumn());
    }

    // 1. 处理 #define
    void MacroDefined(const Token &MacroNameTok, const MacroDirective *MD) override {
        if (SM.isInSystemHeader(MacroNameTok.getLocation())) return;
        PresumedLoc PLoc = SM.getPresumedLoc(MacroNameTok.getLocation());
        if (!PLoc.isValid()) return;

        // ✅ 获取真正的绝对路径
        std::string absPath = getAbsPath(SM, MacroNameTok.getLocation());
        std::string macroUsr = std::string("c:") + absPath + "@" + MacroNameTok.getIdentifierInfo()->getName().str();
        emitJson("MACRO_DEF", MacroNameTok.getIdentifierInfo()->getName().str(), macroUsr, absPath, PLoc.getLine(), PLoc.getColumn());
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

        // ✅ 1. 获取宏【调用处】的真正绝对路径
        std::string absUsePath = getAbsPath(SM, UseLoc);

        std::string defFile = "<builtin>";
        if (const MacroInfo *MI = MD.getMacroInfo()) {
            SourceLocation DefLoc = MI->getDefinitionLoc();
            if (DefLoc.isValid() && !SM.isWrittenInBuiltinFile(DefLoc) && !SM.isWrittenInCommandLineFile(DefLoc)) {
                // ✅ 2. 获取宏【定义处】的真正绝对路径 (关键修复：确保 USR 一致)
                // 之前这里用的是 PDefLoc.getFilename()，可能会导致 USR 里混入相对路径
                defFile = getAbsPath(SM, DefLoc); 
            }
        }

        // 组装 USR
        std::string macroUsr = std::string("c:") + defFile + "@" + MacroNameTok.getIdentifierInfo()->getName().str();
        
        // 发射 JSON，使用 absUsePath 替代原先的 PUseLoc.getFilename()
        emitJson("MACRO_USE", MacroNameTok.getIdentifierInfo()->getName().str(), macroUsr, 
                absUsePath, PUseLoc.getLine(), PUseLoc.getColumn());
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
        } else if (isa<FieldDecl>(D) || isa<EnumConstantDecl>(D) || isa<TypedefNameDecl>(D)) {
            // --- 核心修复：补全必定是定义的节点类型 ---
            // 1. FieldDecl: 结构体/联合体成员
            // 2. EnumConstantDecl: 枚举里的具体取值
            // 3. TypedefNameDecl: typedef 类型别名
            // 这些东西在代码里只要写出来，它本身就是定义，不存在“先声明后定义”的说法
            isDef = true;
        }

        // --- 核心修复 A：区分 声明(DECL) 与 定义(DEF) ---
        // 只有真正的函数体或变量初始化才标记为 DEF
        if (role == "DEF" && !isDef) {
            role = "REF"; 
        }

        // --- 核心修复 B：只索引主文件中的定义 (极其重要！) ---
        // 如果你在解析 platform.c，那么只存 platform.c 里的符号定义。
        // 这样可以彻底解决“一个定义在数据库里出现几百次”的问题。
        //if (role == "DEF" && !SM.isInMainFile(Loc)) return;

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
        emitJson(role + "_" + D->getDeclKindName(), D->getNameAsString(), USR.c_str(), absPath, PLoc.getLine(), PLoc.getColumn());
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