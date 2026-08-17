#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
红米 K50 NAS 改造 · 可视化辅助向导（免 Root / 免解锁 BL 重构版）
版本：v0.1（未实测——按用户实机反馈迭代，见 README 顶部说明）
功能：
  1. 扫描 software/ 文件夹，识别已就位的工具包（✓/✗），缺哪个可一键补下
  2. 引导开启开发者选项 / USB 调试，实时检测手机连接状态
  3. 一键 adb install 安装 F-Droid / Termux / Termux:Boot
  4. 一键启动 scrcpy 投屏（绕开屏幕坏区）
  5. 可选：把 Alpine ISO 推到手机，省手机端下载流量
  6. Termux 初始化 / 自启动命令块，一键复制
  7. 报错诊断：粘贴报错即匹配已知解法
使用：把本程序与 software/ 放在同一目录，双击运行（或 python k50_nas_assistant.py）
"""
import os, sys, json, ssl, zipfile, threading, subprocess, urllib.request, tkinter as tk
from tkinter import ttk, scrolledtext, messagebox

# ------------------------- 路径 -------------------------
def app_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

SOFT = os.path.join(app_dir(), "software")
os.makedirs(SOFT, exist_ok=True)
GUIDE = os.path.join(app_dir(), "红米K50_NAS改造_重构方案.md")

# ------------------------- 工具扫描 -------------------------
def find_adb():
    p = os.path.join(SOFT, "platform-tools", "adb.exe")
    return p if os.path.exists(p) else None

def find_scrcpy():
    for root, _, files in os.walk(SOFT):
        if "scrcpy.exe" in files:
            return os.path.join(root, "scrcpy.exe")
    return None

def scan_software():
    """返回每项 (名称, 是否存在, 备注)"""
    items = []
    # Alpine ISO
    iso = next((f for f in os.listdir(SOFT) if f.startswith("alpine-virt") and f.endswith(".iso")), None)
    items.append(("Alpine aarch64 ISO", iso is not None, iso or "未找到 alpine-virt-*-aarch64.iso"))
    # platform-tools
    items.append(("Android platform-tools (adb)", find_adb() is not None, "software/platform-tools/adb.exe"))
    # scrcpy
    items.append(("scrcpy 投屏", find_scrcpy() is not None, "software/ 下 scrcpy.exe"))
    # apks
    for name in ["F-Droid.apk", "Termux.apk", "Termux-Boot.apk"]:
        items.append((name, os.path.exists(os.path.join(SOFT, name)), name))
    return items

# ------------------------- 内置下载器（exe 也能用） -------------------------
CTX = ssl.create_default_context()
DL_TASKS = [
    ("Alpine ISO", "https://dl-cdn.alpinelinux.org/alpine/v3.20/releases/aarch64/alpine-virt-3.20.3-aarch64.iso",
     "alpine-virt-3.20.3-aarch64.iso"),
    ("platform-tools", "https://dl.google.com/android/repository/platform-tools-latest-windows.zip",
     "platform-tools-latest-windows.zip"),
    ("F-Droid", "https://f-droid.org/F-Droid.apk", "F-Droid.apk"),
]

def _dl(url, dest):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, context=CTX, timeout=180) as r:
        with open(dest, "wb") as f:
            while True:
                b = r.read(65536)
                if not b:
                    break
                f.write(b)

def download_missing(log_fn):
    # 固定三项（zip 需解压）；Termux 两个 apk 用 F-Droid API 动态获取
    ok = True
    try:
        for label, url, fn in DL_TASKS:
            dest = os.path.join(SOFT, fn)
            if os.path.exists(dest):
                log_fn(f"[跳过] {label} 已存在")
                continue
            log_fn(f"[下载] {label} ...")
            _dl(url, dest)
            log_fn(f"  完成 {os.path.getsize(dest)/1e6:.1f} MB")
        # 解压 platform-tools
        zp = os.path.join(SOFT, "platform-tools-latest-windows.zip")
        if os.path.exists(zp) and not os.path.exists(os.path.join(SOFT, "platform-tools", "adb.exe")):
            log_fn("[解压] platform-tools ...")
            with zipfile.ZipFile(zp) as z:
                z.extractall(SOFT)
        # scrcpy 最新
        rel = json.loads(urllib.request.urlopen(
            urllib.request.Request("https://api.github.com/repos/Genymobile/scrcpy/releases/latest",
                                   headers={"User-Agent": "Mozilla/5.0"}), timeout=60).read())
        asset = next((a for a in rel["assets"] if "win64" in a["name"] and a["name"].endswith(".zip")), None)
        if not asset:
            raise RuntimeError("scrcpy 未找到 win64 发布包")
        sz = os.path.join(SOFT, asset["name"])
        if not os.path.exists(sz):
            log_fn(f"[下载] scrcpy {rel['tag_name']} ...")
            _dl(asset["browser_download_url"], sz)
        if not find_scrcpy():
            log_fn("[解压] scrcpy ...")
            with zipfile.ZipFile(sz) as z:
                z.extractall(SOFT)
        # Termux / Termux-Boot
        for pkg, name in [("com.termux", "Termux"), ("com.termux.boot", "Termux-Boot")]:
            apk = os.path.join(SOFT, f"{name}.apk")
            if os.path.exists(apk):
                continue
            data = json.loads(urllib.request.urlopen(
                urllib.request.Request(f"https://f-droid.org/api/v1/packages/{pkg}",
                                       headers={"User-Agent": "Mozilla/5.0"}), timeout=60).read())
            latest = max(data.get("packages", []), key=lambda p: p.get("versionCode", 0))
            apk_name = f"{pkg}_{latest['versionCode']}.apk"
            log_fn(f"[下载] {name} {latest.get('versionName','?')} ...")
            _dl(f"https://f-droid.org/repo/{apk_name}", apk)
    except Exception as e:
        ok = False
        log_fn(f"[下载失败] {e}")
    log_fn("下载完成，请点「重新扫描」刷新状态。" if ok else "部分下载失败，可重试或手动放入 software/。")
    return ok

# ------------------------- ADB 运行器（线程安全） -------------------------
class Adb:
    def __init__(self, log_widget, root):
        self.adb = find_adb()
        self.log = log_widget
        self.root = root

    def available(self):
        return self.adb is not None

    def run(self, args, done=None):
        if not self.adb:
            self._append("[错误] 未找到 adb.exe，请先在第 1 步准备好 platform-tools。")
            if done:
                done("")
            return
        def worker():
            try:
                p = subprocess.run([self.adb] + args, capture_output=True, text=True,
                                   encoding="utf-8", errors="replace", timeout=600)
                out = (p.stdout + p.stderr).strip()
            except Exception as e:
                out = f"[执行异常] {e}"
            self.root.after(0, lambda: self._append(out or "(无输出)"))
            if done:
                self.root.after(0, lambda: done(out))
        threading.Thread(target=worker, daemon=True).start()

    def _append(self, text):
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n" + "-" * 40 + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

# ------------------------- 报错诊断库 -------------------------
DIAG = [
    ("virtio-9p-pci is not a valid device",
     "Termux 的 QEMU 未编译 9p/virtfs。不要使用 -virtfs 参数。改用文件镜像方案：\n"
     "在外接盘上 qemu-img create -f qcow2 数据盘，再用 -drive file=... 挂给 VM。"),
    ("unauthorized",
     "手机端弹出了「是否允许 USB 调试」——在手机上点「始终允许」再点确定，然后重新点「检测手机」。"),
    ("offline",
     "设备 offline：重插 USB 线、换原装线/接口，或在手机开发者选项里撤消授权后重连。"),
    ("device not found", "未识别到手机：检查 USB 线、确认已开启「USB 调试」、手机是否选了「传输文件(MTP)」模式。"),
    ("no devices/emulators found", "没有已连接设备：先连 USB，开启 USB 调试，再点「检测手机」。"),
    ("more than one device", "多台设备：命令后加 -s <序列号> 指定，或在手机只连一台。"),
    ("console=ttyS0", "-nographic 黑屏：安装/启动内核参数加 console=ttyS0；或先去掉 -nographic 用默认显示确认能进系统再切回。"),
    ("cortex-a78", "-cpu cortex-a78 报错：改成 -cpu max。"),
    ("entropy", "Docker 卡在生成密钥/启动慢：QEMU 启动命令加 -device virtio-rng-pci 补熵。"),
    ("could not open tunnel", "Tailscale 建不起隧道：QEMU 用户态网络无 /dev/net/tun。用 tailscaled --tun=userspace-networking 启动。"),
    ("INSTALL_FAILED_VERSION_DOWNGRADE", "安装被拒（版本降级）：用 adb install -r -d 允许降级重装。"),
    ("INSTALL_FAILED_ALREADY_EXISTS", "已存在：用 adb install -r 覆盖安装。"),
    ("INSTALL_FAILED", "安装失败：查看完整报错；常见为空间不足或签名冲突，先 adb install -r 重试。"),
]

def diagnose(text):
    text = text.lower()
    hits = [fix for kw, fix in DIAG if kw.lower() in text]
    if hits:
        return "\n\n".join(f"● {h}" for h in hits)
    return ("未匹配到已知解法。通用排查：\n"
            "1) 复制完整报错到此处再试；\n"
            "2) 确认上一步是否成功（adb devices 有 device 状态）；\n"
            "3) 参考《重构方案》末尾「故障排查」章节；\n"
            "4) 把报错发我，我帮你定位。")

# ------------------------- 主界面 -------------------------
STEPS = ["1. 准备软件", "2. 开调试/连手机", "3. 安装 APK", "4. 投屏辅助",
         "5. 推送资源", "6. Termux 初始化", "7. 自启动/远程", "8. 报错诊断"]

class App:
    def __init__(self, root):
        self.root = root
        root.title("红米 K50 NAS 改造助手（免 Root 版）")
        root.geometry("980x680")

        # 顶部状态条
        top = ttk.Frame(root)
        top.pack(fill="x", padx=8, pady=6)
        ttk.Label(top, text="手机状态：", font=("Microsoft YaHei", 10, "bold")).pack(side="left")
        self.status = ttk.Label(top, text="未检测", foreground="red")
        self.status.pack(side="left")
        self.serial = ""
        ttk.Button(top, text="检测手机", command=self.check_phone).pack(side="right")
        ttk.Button(top, text="打开重构方案", command=self.open_guide).pack(side="right", padx=4)

        # 主体：左步骤树 + 右内容
        body = ttk.Frame(root)
        body.pack(fill="both", expand=True, padx=8)
        self.lb = tk.Listbox(body, width=18, font=("Microsoft YaHei", 10))
        for s in STEPS:
            self.lb.insert("end", s)
        self.lb.pack(side="left", fill="y")
        self.lb.bind("<<ListboxSelect>>", self.on_step)
        self.lb.selection_set(0)

        self.right = ttk.Frame(body)
        self.right.pack(side="left", fill="both", expand=True, padx=8)

        # 公共日志
        self.log = scrolledtext.ScrolledText(root, height=9, font=("Consolas", 9))
        self.log.configure(state="disabled")
        self.log.pack(fill="x", padx=8, pady=4)
        ttk.Button(root, text="清空日志", command=lambda: self.log.configure(state="normal") or self.log.delete("1.0", "end") or self.log.configure(state="disabled")).pack(anchor="e", padx=8)

        self.adb = Adb(self.log, root)
        self.frames = {}
        self.build_all()
        self.show_step(0)

    # ---------- 通用 ----------
    def L(self, w):
        self.log.configure(state="normal")
        self.log.insert("end", w + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def open_guide(self):
        if os.path.exists(GUIDE):
            os.startfile(GUIDE)
        else:
            messagebox.showinfo("提示", "未找到重构方案 md（应与本程序同目录）。")

    def check_phone(self):
        def done(out):
            for line in out.splitlines():
                line = line.strip()
                if line and not line.startswith("List of") and "\t" in line:
                    parts = line.split("\t")
                    self.serial = parts[0]
                    st = parts[1] if len(parts) > 1 else "?"
                    self.status.configure(text=f"{st} ({self.serial})",
                                          foreground="green" if st == "device" else "orange")
                    return
            self.status.configure(text="未连接", foreground="red")
        self.adb.run(["devices", "-l"], done)

    def on_step(self, ev):
        idx = self.lb.curselection()
        if idx:
            self.show_step(idx[0])

    def show_step(self, i):
        for f in self.frames.values():
            f.pack_forget()
        self.frames[i].pack(fill="both", expand=True)

    def copy(self, txt_widget):
        self.root.clipboard_clear()
        self.root.clipboard_append(txt_widget.get("1.0", "end").rstrip())
        messagebox.showinfo("已复制", "命令已复制到剪贴板，去 Termux 粘贴执行。")

    # ---------- 各步骤界面 ----------
    def build_all(self):
        for i in range(len(STEPS)):
            f = ttk.Frame(self.right)
            self.frames[i] = f
        self.build_step0()
        self.build_step1()
        self.build_step2()
        self.build_step3()
        self.build_step4()
        self.build_step5()
        self.build_step6()
        self.build_step7()

    def _title(self, parent, text):
        ttk.Label(parent, text=text, font=("Microsoft YaHei", 12, "bold")).pack(anchor="w", pady=4)

    def build_step0(self):
        f = self.frames[0]
        self._title(f, "第 1 步 · 准备软件")
        ttk.Label(f, text="把下载好的安装包放进 software/ 文件夹，或点「下载缺失项」自动补齐。").pack(anchor="w")
        self.soft_list = tk.StringVar()
        self.soft_lb = tk.Listbox(f, height=8, font=("Consolas", 10))
        self.soft_lb.pack(fill="x", pady=6)
        row = ttk.Frame(f)
        row.pack(fill="x")
        ttk.Button(row, text="重新扫描", command=self.rescan).pack(side="left")
        ttk.Button(row, text="下载缺失项", command=self.do_download).pack(side="left", padx=6)
        self.rescan()

    def rescan(self):
        self.soft_lb.delete(0, "end")
        for name, ok, note in scan_software():
            self.soft_lb.insert("end", f"{'✓' if ok else '✗'}  {name}  ({note})")
            self.soft_lb.itemconfig("end", foreground="green" if ok else "red")
        self.adb.adb = find_adb()

    def do_download(self):
        self.L("[下载] 开始补齐缺失软件包 ...")
        threading.Thread(target=download_missing, args=(self.L,), daemon=True).start()

    def build_step1(self):
        f = self.frames[1]
        self._title(f, "第 2 步 · 开启开发者选项 & USB 调试")
        txt = ("1) 设置 → 关于手机/我的设备 → 连点「OS 版本/MIUI 版本」7 次，开启开发者选项。\n"
               "2) 设置 → 更多设置 → 开发者选项 → 打开「USB 调试」（OEM 解锁可不开，因为本方案不解锁 BL）。\n"
               "3) 用原装线连电脑，手机选「传输文件(MTP)」模式。\n"
               "4) 点右上角「检测手机」，状态变绿(device)即可进入下一步。\n"
               "5) 若提示「允许 USB 调试」，在手机上勾选始终允许并确认。")
        ttk.Label(f, text=txt, justify="left", font=("Microsoft YaHei", 10), wraplength=760).pack(anchor="w", pady=6)
        ttk.Button(f, text="检测手机连接", command=self.check_phone).pack(anchor="w")

    def build_step2(self):
        f = self.frames[2]
        self._title(f, "第 3 步 · 安装 APK（adb install）")
        ttk.Label(f, text="手机保持连接，逐个安装。Termux 与 Termux:Boot 必须来自 F-Droid（Play 版已停更）。").pack(anchor="w", pady=4)
        for name in ["F-Droid.apk", "Termux.apk", "Termux-Boot.apk"]:
            row = ttk.Frame(f)
            row.pack(fill="x", pady=3)
            ttk.Label(row, text=name, width=18).pack(side="left")
            ttk.Button(row, text="安装", command=lambda n=name: self.install_apk(n)).pack(side="left")
        ttk.Label(f, text="提示：安装后打开 F-Droid 一次、Termux:Boot 一次（注册开机广播）。").pack(anchor="w", pady=8)

    def install_apk(self, name):
        path = os.path.join(SOFT, name)
        if not os.path.exists(path):
            messagebox.showerror("缺失", f"未找到 {name}，请回第 1 步下载/放入。")
            return
        self.L(f"[安装] {name} ...")
        self.adb.run(["install", "-r", path])

    def build_step3(self):
        f = self.frames[3]
        self._title(f, "第 4 步 · scrcpy 投屏（绕开屏幕坏区）")
        ttk.Label(f, text="手机连电脑并已授权调试后，点下面按钮启动投屏，用鼠标操作手机。").pack(anchor="w", pady=4)
        ttk.Button(f, text="启动 scrcpy", command=self.launch_scrcpy).pack(anchor="w")

    def launch_scrcpy(self):
        exe = find_scrcpy()
        if not exe:
            messagebox.showerror("缺失", "未找到 scrcpy.exe，请回第 1 步。")
            return
        try:
            subprocess.Popen([exe], cwd=os.path.dirname(exe))
            self.L("[scrcpy] 已启动，请在弹出的窗口操作手机。")
        except Exception as e:
            self.L(f"[scrcpy 失败] {e}")

    def build_step4(self):
        f = self.frames[4]
        self._title(f, "第 5 步 · 推送资源到手机（可选，省流量）")
        ttk.Label(f, text="若电脑已下载 Alpine ISO，可直接推到手机 /sdcard/Download，省去手机端下载 72MB。").pack(anchor="w", pady=4)
        ttk.Button(f, text="推送 Alpine ISO 到手机", command=self.push_iso).pack(anchor="w")

    def push_iso(self):
        iso = next((os.path.join(SOFT, x) for x in os.listdir(SOFT)
                    if x.startswith("alpine-virt") and x.endswith(".iso")), None)
        if not iso:
            messagebox.showerror("缺失", "未找到 Alpine ISO，请回第 1 步。")
            return
        self.L(f"[推送] {os.path.basename(iso)} -> /sdcard/Download/ （可能需 1-2 分钟）")
        self.adb.run(["push", iso, "/sdcard/Download/"])

    def _cmd_block(self, parent, title, code):
        ttk.Label(parent, text=title, font=("Microsoft YaHei", 10, "bold")).pack(anchor="w", pady=(6, 2))
        t = scrolledtext.ScrolledText(parent, height=max(4, code.count("\n") + 1), font=("Consolas", 9))
        t.insert("end", code)
        t.pack(fill="x")
        ttk.Button(parent, text="复制", command=lambda: self.copy(t)).pack(anchor="e", pady=2)

    def build_step5(self):
        f = self.frames[5]
        self._title(f, "第 6 步 · Termux 初始化（命令复制到 Termux 执行）")
        self._cmd_block(f, "① 开通存储 + 装基础包",
                        "termux-setup-storage\n"
                        "pkg update && pkg upgrade -y\n"
                        "pkg install openssh tsu wget curl git tmux qemu-system-aarch64 qemu-utils -y")
        self._cmd_block(f, "② 开 SSH 远程管理",
                        "passwd\n"
                        "sshd\n"
                        "ifconfig wlan0 | grep inet   # 记下列出的 IP")
        self._cmd_block(f, "③ 电脑 SSH 连入 Termux",
                        "ssh -p 8022 刚才记的IP\n"
                        "# 之后所有操作在电脑 SSH 里完成，手机屏幕不再需要")
        ttk.Label(f, text="详细步骤（下载 Alpine、建盘、QEMU 启动参数）见《重构方案》Phase 3。",
                  font=("Microsoft YaHei", 9)).pack(anchor="w", pady=6)

    def build_step6(self):
        f = self.frames[6]
        self._title(f, "第 7 步 · 自启动 & 远程访问")
        self._cmd_block(f, "Termux:Boot 自启脚本 ~/.termux/boot.sh（精简版）",
                        "mkdir -p ~/.termux\n"
                        "termux-wake-lock\n"
                        "# 在 tmux 里启动 QEMU（完整参数见重构方案 Phase 5）\n"
                        "tmux new-session -d -s nas \"qemu-system-aarch64 -machine virt -cpu cortex-a78 -smp 4 -m 4096 -accel tcg,thread=multi -bios $PREFIX/share/qemu/edk2-aarch64-code.fd -netdev user,id=n1,hostfwd=tcp::2222-:22 -device virtio-net,netdev=n1 -device virtio-rng-pci -drive file=alpine-docker.qcow2,if=virtio,format=qcow2 -nographic\"")
        self._cmd_block(f, "Tailscale 远程（userspace 模式，免 TUN）",
                        "apk add tailscale\n"
                        "rc-update add tailscale default\n"
                        "service tailscale start\n"
                        "tailscaled --tun=userspace-networking &\n"
                        "tailscale up")

    def build_step7(self):
        f = self.frames[7]
        self._title(f, "第 8 步 · 报错诊断")
        ttk.Label(f, text="把终端/QEMU/adb 的报错粘贴到下面，点「诊断」匹配已知解法。").pack(anchor="w", pady=4)
        self.err_in = scrolledtext.ScrolledText(f, height=6, font=("Consolas", 9))
        self.err_in.pack(fill="x")
        ttk.Button(f, text="诊断", command=self.run_diag).pack(anchor="e", pady=4)
        self.err_out = scrolledtext.ScrolledText(f, height=10, font=("Microsoft YaHei", 10))
        self.err_out.pack(fill="both", expand=True)

    def run_diag(self):
        txt = self.err_in.get("1.0", "end")
        self.err_out.delete("1.0", "end")
        self.err_out.insert("end", diagnose(txt))


def main():
    root = tk.Tk()
    try:
        root.iconbitmap()  # 无图标则忽略
    except Exception:
        pass
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
