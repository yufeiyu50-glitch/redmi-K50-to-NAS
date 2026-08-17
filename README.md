# 红米 K50 NAS 改造 · 工具包与辅助程序

> **⚠️ 当前版本：v0.1（未实际测试）**
> 本版本作者尚未在实际的红米 K50 手机上跑过完整流程。
> 程序可能在某些环境（例如特定的 HyperOS 版本、Termux 版本、ADB 驱动）下出现未覆盖的报错。
> **请按说明在实机操作，遇到任何错误、卡顿或步骤不合理的地方，把报错/截图发回给作者，按反馈迭代。**
> 反馈即版本演进动力，谢谢🙏

本目录配合《红米K50_NAS改造_重构方案.md》（免 Root / 免解锁 BL 版）使用。

## 目录结构
```
红米K50-NAS改造/
├─ software/                # 软件包存放处（也是程序的"拖放文件夹"）
│  ├─ alpine-virt-3.20.3-aarch64.iso
│  ├─ platform-tools/       # adb.exe（来自 Android platform-tools）
│  ├─ scrcpy-*/             # scrcpy 投屏
│  ├─ F-Droid.apk
│  ├─ Termux.apk
│  └─ Termux-Boot.apk
├─ k50_nas_assistant.py     # 辅助向导源码（需 Python 3）
├─ k50_nas_assistant.exe    # 辅助向导可执行文件（双击运行，免装 Python）
├─ download_tools.py        # 软件包下载器（可重跑补下）
├─ 红米K50_NAS改造实战指南(1).md   # 你原来的初版方案（参考）
└─ README.md
```

> 注：`miflash_unlock_7.6.727.43.zip` 是旧 Root 方案用的，**重构后的免 Root 方案不需要它**，保留未动。

## 使用方法
1. 手机用原装 USB 线连电脑，开启「USB 调试」（设置 → 关于手机 → 连点 OS 版本 7 次 → 开发者选项 → USB 调试）。
2. 双击 `k50_nas_assistant.exe`（或 `python k50_nas_assistant.py`）。
3. 按左侧 8 个步骤推进：
   - **第 1 步** 自动扫描 `software/` 是否齐全，缺哪个点「下载缺失项」自动补。
   - **第 2 步** 点「检测手机」，状态变绿(device)即连接正常。
   - **第 3 步** 逐个 `adb install` 安装 F-Droid / Termux / Termux:Boot。
   - **第 4 步** 启动 scrcpy 投屏，绕开屏幕坏区。
   - **第 5 步**（可选）把 Alpine ISO 推到手机，省手机端流量。
   - **第 6/7 步** 复制 Termux / 自启动 / Tailscale 命令到 Termux 执行。
   - **第 8 步** 把报错粘贴进来点「诊断」，匹配已知解法。

## 重新下载软件包
- 直接双击运行 `download_tools.py`（需 Python 3），或在该程序第 1 步点「下载缺失项」。
- 也可手动把安装包放进 `software/` 文件夹，程序会自动识别（✓）。

## 说明
- 本工具只负责「准备 + 引导 + 排错」，真正的 QEMU/Alpine/Docker 部署命令在 Termux 内执行，详细参数见重构方案文档。
- 所有操作均在 Android 用户态，无需 Root、无需解锁 BL、无需等待 168 小时。

## 克隆与使用

### 从 GitHub 克隆
```bash
git clone https://github.com/yufeiyu50-glitch/redmi-K50-to-NAS.git
cd redmi-K50-to-NAS
```

### 获取软件包（大二进制不入库）
本仓库的 `.gitignore` 已排除 `software/` 目录、`*.apk/*.iso/*.zip` 与 `*.exe`（体积大、均可从网络下载），因此 clone 后这些文件不存在。请二选一获取：
- 运行下载器：`python download_tools.py`（自动拉取 Alpine ISO / platform-tools / scrcpy / 各 APK 到 `software/`）
- 或双击运行 `k50_nas_assistant.exe`（若本地已存在），在第 1 步点「下载缺失项」

### 运行辅助向导
- 有 Python 3 + tkinter：直接 `python k50_nas_assistant.py`
- `k50_nas_assistant.exe` 不在仓库中。如需可执行文件，用 PyInstaller 自行打包：
  ```bash
  pyinstaller --onefile --windowed --name k50_nas_assistant k50_nas_assistant.py
  ```
  生成的 `dist/k50_nas_assistant.exe` 双击即可运行（**务必用自带 tkinter 的 Python 打包，否则运行会崩溃**）。
