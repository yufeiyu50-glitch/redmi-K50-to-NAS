#!/usr/bin/env python3
# 红米 K50 NAS 改造 - 软件包下载器（免 Root 重构版）
# 仅下载重构方案所需的工具，不含 Mi Unlock / Magisk / AccA（那些是旧 Root 方案用的）
import os, sys, json, ssl, zipfile, urllib.request

BASE = r"D:\红米K50-NAS改造"
SOFT = os.path.join(BASE, "software")
os.makedirs(SOFT, exist_ok=True)
CTX = ssl.create_default_context()


def download(url, dest, label=None):
    label = label or os.path.basename(dest)
    print(f"[DL] {label}\n  {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, context=CTX, timeout=180) as r:
        total = int(r.headers.get("Content-Length", 0) or 0)
        with open(dest, "wb") as f:
            got = 0
            while True:
                buf = r.read(65536)
                if not buf:
                    break
                f.write(buf)
                got += len(buf)
                if total:
                    sys.stderr.write(f"\r    {got/1e6:.1f}/{total/1e6:.1f} MB")
            sys.stderr.write("\n")
    print(f"  -> {dest}  ({os.path.getsize(dest)/1e6:.1f} MB)")


def get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, context=CTX, timeout=60) as r:
        return json.loads(r.read().decode())


# 1. Alpine aarch64 ISO
download(
    "https://dl-cdn.alpinelinux.org/alpine/v3.20/releases/aarch64/alpine-virt-3.20.3-aarch64.iso",
    os.path.join(SOFT, "alpine-virt-3.20.3-aarch64.iso"),
    "Alpine aarch64 ISO",
)

# 2. Android platform-tools (Windows, 含 adb)
download(
    "https://dl.google.com/android/repository/platform-tools-latest-windows.zip",
    os.path.join(SOFT, "platform-tools-latest-windows.zip"),
    "Android platform-tools (Windows)",
)

# 3. scrcpy (GitHub 最新 release, win64)
rel = get_json("https://api.github.com/repos/Genymobile/scrcpy/releases/latest")
asset = next((a for a in rel["assets"] if "win64" in a["name"] and a["name"].endswith(".zip")), None)
if asset is None:
    raise SystemExit("[错误] scrcpy 未找到 win64 发布包，请手动下载放到 software/")
scrcpy_zip = os.path.join(SOFT, asset["name"])
download(asset["browser_download_url"], scrcpy_zip, f"scrcpy ({rel['tag_name']})")

# 4. F-Droid 安装器
download("https://f-droid.org/F-Droid.apk", os.path.join(SOFT, "F-Droid.apk"), "F-Droid")

# 5. Termux / Termux:Boot (F-Droid 仓库直链，取最新版本)
#    注：F-Droid v1 API 现仅返回 versionCode，apk 命名规律为 <pkg>_<versionCode>.apk
for pkg, name in [("com.termux", "Termux"), ("com.termux.boot", "Termux-Boot")]:
    data = get_json(f"https://f-droid.org/api/v1/packages/{pkg}")
    pkgs = data.get("packages", [])
    latest = max(pkgs, key=lambda p: p.get("versionCode", 0))
    ver = latest.get("versionName", "?")
    vercode = latest["versionCode"]
    apk_name = f"{pkg}_{vercode}.apk"
    download(
        f"https://f-droid.org/repo/{apk_name}",
        os.path.join(SOFT, f"{name}.apk"),
        f"{name} ({ver})",
    )

# 解压 zip
print("[EXTRACT] platform-tools ...")
with zipfile.ZipFile(os.path.join(SOFT, "platform-tools-latest-windows.zip")) as z:
    z.extractall(SOFT)
print("[EXTRACT] scrcpy ...")
with zipfile.ZipFile(scrcpy_zip) as z:
    z.extractall(SOFT)

print("\n全部下载完成，目录:", SOFT)
for f in sorted(os.listdir(SOFT)):
    p = os.path.join(SOFT, f)
    if os.path.isfile(p):
        print(f"  {f}  ({os.path.getsize(p)/1e6:.1f} MB)")
    else:
        print(f"  [{f}/]")
