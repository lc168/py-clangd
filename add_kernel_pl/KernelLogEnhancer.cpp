#include "llvm/IR/PassManager.h"
#include "llvm/IR/Function.h"
#include "llvm/IR/Instructions.h"
#include "llvm/IR/IRBuilder.h"
#include "llvm/IR/Constants.h"
#include "llvm/IR/DebugInfoMetadata.h"
#include "llvm/IR/Module.h"
#include "llvm/Plugins/PassPlugin.h"
#include "llvm/Passes/PassBuilder.h"
#include "llvm/Support/raw_ostream.h" // 必须包含这个头文件用于 errs()

using namespace llvm;

struct KernelLogEnhancer : public PassInfoMixin<KernelLogEnhancer> {
    PreservedAnalyses run(Function &F, FunctionAnalysisManager &AM) {
        bool Changed = false;

        // 1. 扩大范围：包含内核最常用的底层打印函数
        static const std::vector<std::string> Sinks = {
            "printk", "_printk", "_dev_info", "_dev_err", "_dev_warn", "vprintk"
        };

        for (auto &BB : F) {//F 是什么？
            for (auto &I : BB) {
                auto *Call = dyn_cast<CallInst>(&I);
                if (!Call) continue;

                Function *Callee = Call->getCalledFunction();
                if (!Callee) continue;

                std::string Name = Callee->getName().str();
                bool foundSink = false;
                for (auto &S : Sinks) { if (Name.find(S) != std::string::npos) { foundSink = true; break; } }
                if (!foundSink) continue;

                // 2. 深度寻找 GlobalVariable (处理 GEP 指令)
                unsigned FmtIdx = (Name.find("dev_") != std::string::npos) ? 1 : 0;
                if (Call->arg_size() <= FmtIdx) continue;

                Value *V = Call->getArgOperand(FmtIdx)->stripPointerCasts();
                GlobalVariable *GV = nullptr;

                // 如果是直接引用
                if (auto *tmpGV = dyn_cast<GlobalVariable>(V)) {
                    GV = tmpGV;
                } 
                // 如果是通过 GEP 引用（这是最常见的情况）
                else if (auto *CE = dyn_cast<ConstantExpr>(V)) {
                    if (CE->getOpcode() == Instruction::GetElementPtr) {
                        GV = dyn_cast<GlobalVariable>(CE->getOperand(0));
                    }
                }

                if (!GV || !GV->hasInitializer()) continue;

                auto *CDA = dyn_cast<ConstantDataSequential>(GV->getInitializer());
                if (!CDA) continue;

                // 3. 提取位置信息
                const DebugLoc &Loc = I.getDebugLoc();
                if (!Loc) continue;
                DILocation *DIL = Loc.get();
                while (DIL->getInlinedAt()) DIL = DIL->getInlinedAt();

                std::string FileName = DIL->getFilename().str();
                // size_t LastSlash = FileName.find_last_of("/");
                // if (LastSlash != std::string::npos) FileName = FileName.substr(LastSlash + 1);
                
                // 4. 执行替换并打印调试信息到终端
                std::string RawStr = CDA->getAsString().str();
                std::string Prefix = (RawStr.size() > 2 && RawStr[0] == '\001') ? RawStr.substr(0, 2) : "";
                if (!Prefix.empty()) RawStr = RawStr.substr(2);

                std::string NewStr = Prefix + "[" + FileName + ":" + std::to_string(DIL->getLine()) + "] " + RawStr;
                
                IRBuilder<> Builder(&I);
                Call->setArgOperand(FmtIdx, Builder.CreateGlobalString(NewStr, "kl_str"));

                // 关键：在编译时输出，让你看到它在干活！
                errs() << "[LogPass] Hooked: " << Name << " in " << FileName << ":" << DIL->getLine() << "\n";
                
                Changed = true;
            }
        }
        return Changed ? PreservedAnalyses::none() : PreservedAnalyses::all();
    }
};

extern "C" LLVM_ATTRIBUTE_WEAK ::llvm::PassPluginLibraryInfo llvmGetPassPluginInfo() {
    return {LLVM_PLUGIN_API_VERSION, "LogEnhancer", "1.0",
            [](PassBuilder &PB) {
                // 1. 注册解析回调 (用于 opt 工具手动调用)
                PB.registerPipelineParsingCallback(
                    [](StringRef Name, FunctionPassManager &FPM, ...) {
                        if (Name == "log-enhancer") {
                            FPM.addPass(KernelLogEnhancer());
                            return true;
                        }
                        return false;
                    });

                // 2. 注册流水线起点回调 (用于 clang 自动调用)
                // 注意：这里参数必须是 ModulePassManager
                PB.registerPipelineStartEPCallback(
                    [](ModulePassManager &MPM, OptimizationLevel Level) {
                        // 使用适配器将 Function Pass 嵌入到 Module 流水线中
                        MPM.addPass(createModuleToFunctionPassAdaptor(KernelLogEnhancer()));
                    });
            }};
}