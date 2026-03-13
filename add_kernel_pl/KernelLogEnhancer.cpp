#include "llvm/IR/PassManager.h"
#include "llvm/IR/Function.h"
#include "llvm/IR/Instructions.h"
#include "llvm/IR/IRBuilder.h"
#include "llvm/IR/Constants.h"
#include "llvm/IR/DebugInfoMetadata.h"
#include "llvm/IR/Module.h"
#include "llvm/Plugins/PassPlugin.h"
#include "llvm/Passes/PassBuilder.h"
#include <string>
#include <vector>

using namespace llvm;

struct KernelLogEnhancer : public PassInfoMixin<KernelLogEnhancer> {
    // 预定义需要处理的日志函数及其参数索引 (Format String Index)
    struct LogFunc { StringRef Name; unsigned FmtIdx; };
    const std::vector<LogFunc> TargetFuncs = {
        {"printk", 0}, {"_printk", 0}, {"printa", 0}, 
        {"_dev_info", 1}, {"_dev_err", 1}, {"dev_printk", 1}
    };

    PreservedAnalyses run(Function &F, FunctionAnalysisManager &AM) {
        // 核心优化：如果当前函数本身就在名单中（如 printa 的实现），直接跳过
        // 防止在包装器内部插桩导致死循环或 Log 冗余
        for (const auto &Target : TargetFuncs) {
            if (F.getName() == Target.Name) return PreservedAnalyses::all();
        }

        bool Changed = false;
        Module *M = F.getParent();

        for (auto &BB : F) {
            for (auto &I : BB) {
                auto *Call = dyn_cast<CallInst>(&I);
                if (!Call) continue;

                Function *Callee = Call->getCalledFunction();
                if (!Callee) continue;

                // 1. 识别目标函数
                int FmtIdx = -1;
                for (const auto &Target : TargetFuncs) {
                    if (Callee->getName().contains(Target.Name)) {
                        FmtIdx = Target.FmtIdx;
                        break;
                    }
                }
                if (FmtIdx == -1) continue;

                // 2. 获取源码坐标 (LLVM 23 推荐方式)
                const DebugLoc &Loc = I.getDebugLoc();
                if (!Loc) continue;

                // 自动追溯内联位置，确保拿到的是真实的调用点
                DILocation *DIL = Loc.get();
                while (DIL->getInlinedAt()) {
                    DIL = DIL->getInlinedAt();
                }

                std::string FileName = DIL->getFilename().str();
                size_t LastSlash = FileName.find_last_of("/");
                if (LastSlash != std::string::npos) FileName = FileName.substr(LastSlash + 1);
                int Line = DIL->getLine();

                // 3. 提取并增强格式化字符串
                if (Call->arg_size() <= (unsigned)FmtIdx) continue;
                Value *ArgFmt = Call->getArgOperand(FmtIdx)->stripPointerCasts();
                
                auto *GlobalVar = dyn_cast<GlobalVariable>(ArgFmt);
                if (!GlobalVar || !GlobalVar->hasInitializer()) continue;
                auto *Data = dyn_cast<ConstantDataSequential>(GlobalVar->getInitializer());
                if (!Data) continue;

                std::string OriginalStr = Data->getAsString().str();

                // 4. 处理内核前缀与拼接
                std::string Prefix = "";
                if (!OriginalStr.empty() && OriginalStr[0] == '\001') {
                    Prefix = OriginalStr.substr(0, 2);
                    OriginalStr = OriginalStr.substr(2);
                }

                std::string EnhancedStr = Prefix + "[" + FileName + ":" + std::to_string(Line) + "] " + OriginalStr;

                // 5. 替换操作 (LLVM 23 全局常量安全创建)
                IRBuilder<> Builder(&I);
                // Value *NewGlobalStr = Builder.CreateGlobalStringPtr(EnhancedStr, "kl_enhanced_log");
                Value *NewGlobalStr = Builder.CreateGlobalString(EnhancedStr, "kl_enhanced_log");
                Call->setArgOperand(FmtIdx, NewGlobalStr);

                Changed = true;
            }
        }
        return Changed ? PreservedAnalyses::none() : PreservedAnalyses::all();
    }
};

// 注册插件
extern "C" LLVM_ATTRIBUTE_WEAK ::llvm::PassPluginLibraryInfo llvmGetPassPluginInfo() {
    return {LLVM_PLUGIN_API_VERSION, "KernelLogEnhancer", "v1.0-llvm23",
            [](PassBuilder &PB) {
                PB.registerPipelineParsingCallback(
                    [](StringRef Name, FunctionPassManager &FPM, ...) {
                        if (Name == "log-enhancer") {
                            FPM.addPass(KernelLogEnhancer());
                            return true;
                        }
                        return false;
                    });
            }};
}