# 红米 K50 NAS 改造实战指南（重构版 v2）

> 设备：红米 K50（代号 rubens）12GB+256GB · 屏幕有坏区但仍可触控操作
> 方案：**免 Root / 免解锁 BL** · Termux + QEMU(aarch64) + Alpine Linux + Docker
> 目标：离线下载 + 影视播放 + 网盘挂载，7×24 无人值守
> 重构日期：2026-08-17（基于 v1 实测社区反馈与改进分析重构）

---

## 0. 与初版相比的核心变更（先看这段）

| # | 初版做法 | 重构做法 | 原因 |
|---|---------|---------|------|
| 1 | **必须 Root + 解锁 BL**（168h 等待） | **完全免 Root、免解锁 BL** | QEMU/Alpine/Docker 都在 Android 用户态运行，不需要 Root；唯一用到 Root 的 USB 块直通本身在 Termux QEMU 下不可行（无 9p），改用文件镜像替代 |
| 2 | 9p/virtfs 共享外接 SSD | **在外接盘上建 QEMU 磁盘镜像文件**（`-drive file=`） | Termux 的 qemu 通常没编译 `--enable-virtfs`，`-virtfs` 直接报设备不存在；文件镜像无需 Root、无需 9p |
| 3 | 系统盘 8G | **系统盘 20G** | Alpine+Docker+4 镜像解压远超 8G，8G 会写爆 |
| 4 | QEMU 内存 6G | **QEMU 内存 4G** | HyperOS 空占 3–4G，给 6G 会触发 Android 内存紧张反杀 Termux（你最怕的后台被杀） |
| 5 | `-cpu cortex-a72` | **`-cpu cortex-a78`**（回退 `max`） | 天玑 8100 大核即 Cortex-A78，指令集更贴近、兼容性更好 |
| 6 | ACC（需 Root）限制充电 | **HyperOS 自带「电池保护/智能充电保护」**（设置→电池，限充 80%） | 免 Root 即可获得同等 UPS + 防鼓包能力 |
| 7 | Tailscale 默认 TUN | **`tailscaled --tun=userspace-networking`** | QEMU 用户态网络无 `/dev/net/tun`，默认模式建不起隧道 |
| 8 | UEFI 用 Linaro 旧包 | **Termux 自带 `$PREFIX/share/qemu/edk2-aarch64-code.fd`** | Linaro 旧包可能失效；Termux 已自带可用固件 |
| 9 | `-nographic` 黑屏风险 | 内核加 **`console=ttyS0`** | 串口控制台未配会装完黑屏进不去 |
| 10 | 外接盘按 NVMe 硬盘盒买 | **USB 2.0 现实下选自带供电的 SATA SSD 或高速 U 盘** | K50 OTG 实测为 USB 2.0（≈40MB/s），NVMe 纯浪费且 OTG 带不动 |
| 11 | compose 带 `version` 字段 | **删除 `version`** | 新版 docker compose 已弃用该字段，会报警告 |
| 12 | 无熵源 | 加 **`-device virtio-rng-pci`** | Docker/SSH 密钥生成缺熵会极慢甚至卡死 |

> **总工期变化**：初版约 8–9 天（主要是 168h 解锁等待）。重构版 **0 天等待**，实际操作约 3–4 小时即可跑通。

---

## 1. 方案选择理由（重构版）

1. **免 Root 是可行的**：7×24 供电用 HyperOS 自带电池保护（限充 80%）替代 ACC；后台保活用电池优化白名单 + Termux:Boot + wake-lock（均免 Root）；USB 存储用 QEMU 磁盘镜像文件替代块直通（免 Root）。
2. **选 QEMU(aarch64) 而非 x86_64**：K50 是 ARM，同架构 TCG 翻译效率远高于 x86_64 交叉模拟。
3. **选 QEMU 而非编译自定义内核**：MediaTek 内核编译坑多易砖；QEMU 可靠性高得多，天玑 8100 + 12G 完全扛得住虚拟化开销。（原生内核为可选进阶，见末章，仍需 Root。）
4. **选 Alpine 而非 Ubuntu/Debian**：Alpine 仅需 ~500MB 磁盘 + ~50MB 内存，把更多资源留给 Docker。
5. **保留电池 + 系统限充**：电池兼作 UPS，断电不丢数据；系统限充 80% 控制鼓包风险。

**软件架构（从底到顶）**：

```
Android 14 (HyperOS)  ← 底层系统，提供硬件驱动（免 Root）
  └─ Termux            ← 终端环境，运行 QEMU（F-Droid 版）
      └─ QEMU aarch64  ← 虚拟机，TCG 同架构翻译
          └─ Alpine Linux  ← 极轻量 Linux，原生支持 Docker
              └─ Docker Engine
                  ├─ qBittorrent  (离线下载 BT/PT)
                  ├─ Jellyfin     (影视播放/刮削)
                  ├─ Alist        (网盘聚合挂载)
                  └─ Aria2        (HTTP/磁力下载)
```

---

## 2. 关于「绕过小米账号绑定解锁 BL」——重要澄清

你测试后发现绑定解锁耗时太久（168 小时 / 7 天），想绕过。核实社区现状后结论如下，**请务必看清，避免被误导白等**：

### 2.1 本方案根本不需要解锁 BL
如上所述，QEMU/Alpine/Docker 全在 Android 用户态运行，**不需要 Root、不需要解锁 BL**。直接采用免 Root 架构，168 小时等待**彻底消失**，也省去 Magisk/线刷/强刷的所有砖机风险。这是最干净、最快的「绕法」。

### 2.2 如果你仍想要 Root（进阶需求），168 小时无法真正跳过
- **等待期是小米服务器端强制的**，不是本地能改的。社区所谓「bypass 脚本」（如 `Xiaomi-HyperOS-BootLoader-Bypass`）**只跳过「小米社区 5 级 + 答题」这道 HyperOS 新增门禁**，对已经绑定的设备**仍需老老实实等 168 小时**才能用官方工具解锁。它**省不掉时间**。
- 「调手机时间」「拔 SIM 卡解锁」等老教程是**无效的**——校验在服务端，本地改时间没用。
- 「MTK 强解 BL」仅对部分老联发科机型有效，K50（天玑 8100）是否在可用范围**不确定**，且多为第三方付费/高风险服务，有砖机、丢数据、账号风控风险，**不推荐**。
- 「9008 / EDL 模式」只能解锁**无账号锁（未绑定小米账号）的纯净机**；你的账号已绑，走不通。

> **结论**：不要用「绕过脚本」去赌省时间——它们省不掉 168 小时。要么**接受免 Root 架构（推荐，立即可开工）**，要么**接受等 168 小时**去拿 Root（仅当你确实需要 ACC 精细控电或原生 Docker 内核时）。

### 2.3 免 Root 下如何获得「UPS + 防鼓包」
- 设置 → 电池 → 开启 **电池保护 / 智能充电保护**（限制充电至 80%）。不同 HyperOS 版本名称略有差异，找到「限制充电」「电池保护」类开关即可。
- 若你的机型无此开关，则接受满充（UPS 收益仍在，仅鼓包风险略升，2–3 年通常无碍）。

---

## 3. 全流程准备清单

### 3.1 硬件清单（与初版相近，调整 USB 部分）

| 序号 | 硬件 | 用途 | 备注 |
|:---:|------|------|------|
| 1 | 红米 K50（12+256GB） | NAS 主机 | 屏幕有坏区但可触控 |
| 2 | Windows 电脑 | SSH 远程管理、下载镜像 | 仅辅助，不再需要线刷/解锁 |
| 3 | 原装/高质量 USB 数据线 | 连接手机与电脑 | 传文件、ADB 调试 |
| 4 | Type-C OTG 转接头 | 连接外接 SSD | **K50 OTG 为 USB 2.0（≈40MB/s），无需买 3.0/3.1 或 NVMe 硬盘盒** |
| 5 | 外接 SSD（1TB+） | NAS 存储 | **选自带供电的 SATA SSD 或高速 U 盘**；NVMe 硬盘盒纯浪费（速度被 USB2.0 卡死，且 OTG 500mA 带不动 NVMe） |
| 6 | 充电器（5V/3A） | 7×24 供电 | 原装即可 |
| 7 | 散热背夹（半导体） | 7×24 散热 | 约 30 元；天玑 8100 满载发热明显 |
| 8 | 路由器 | 网络连接 | 需支持 DHCP 地址保留 |

### 3.2 软件清单（移除所有 Root/解锁工具）

| 序号 | 软件 | 运行平台 | 用途 | 下载地址 |
|:---:|------|:---:|------|------|
| 1 | Android Platform Tools | Windows | ADB（无线调试可选优化） | <https://developer.android.com/tools/releases/platform-tools> |
| 2 | scrcpy | Windows | 投屏辅助操作坏区 | <https://github.com/Genymobile/scrcpy/releases> |
| 3 | F-Droid | 手机 | 装 Termux / Termux:Boot | <https://f-droid.org/F-Droid.apk> |
| 4 | Termux | 手机 | 终端环境，运行 QEMU | **F-Droid 安装（Play 版已停更）** |
| 5 | Termux:Boot | 手机 | 开机自启 QEMU（免 Root） | F-Droid |
| 6 | Alpine Virt ISO（aarch64） | QEMU 内 | 轻量 Linux | <https://dl-cdn.alpinelinux.org/alpine/v3.20/releases/aarch64/alpine-virt-3.20.3-aarch64.iso> |
| 7 | QEMU UEFI 固件 | QEMU 内 | aarch64 引导 | **Termux 自带** `$PREFIX/share/qemu/edk2-aarch64-code.fd`，无需下载 |

> 已删除：Mi Unlock、线刷包、MiFlash、Magisk、AccA。这些在免 Root 架构中全部不需要。

### 3.3 账号与网络

| 项目 | 说明 |
|------|------|
| 路由器管理密码 | 设 DHCP 地址保留（固定 IP） |
| 家庭 WiFi 密码 | 手机需连 WiFi |
| 网盘账号（可选） | 阿里云盘/夸克/115/百度等，Alist 挂载用 |
| 小米账号 | **不再需要**（免解锁） |

---

## 4. Phase 0：硬件改造与准备

### 4.1 屏幕坏区应对
同初版：能在手机上点的直接点；坏区挡按钮用 scrcpy（需先开 USB 调试）辅助。Root 后（本版改为装好 Termux SSH 后）基本不需要屏幕。

### 4.2 电池管理（免 Root）
设置 → 电池 → 开启 **电池保护 / 智能充电保护**（限充 80%）。电池兼作 UPS，断电自动切电池不丢数据。

### 4.3 散热方案
同初版：最低要求背面朝上自然散热；推荐半导体散热背夹（约 30 元）；进阶 3D 打印支架 + 5V 静音风扇。实测骁龙 865 同类 NAS 日常 41°C、拷机 58°C、功耗 ~4.8W；天玑 8100（5nm）更优。

### 4.4 外接存储（文件镜像方案，免 Root）
256GB 内置扣系统 + VM 后约剩 180–200GB，不够存影视。扩展方案：

| 方案 | 容量 | 实测速度 | 供电 | 推荐度 |
|------|------|---------|------|:---:|
| Type-C OTG + SATA SSD（自带供电） | 1TB+ | ≤40MB/s（被 USB2.0 卡） | 硬盘盒自供电 | **推荐** |
| Type-C OTG + 高速 U 盘 | 256GB+ | ≤40MB/s | 手机供电 | 够用 |
| Type-C OTG + NVMe 硬盘盒 | 1TB+ | ≤40MB/s（同样被卡） | 需独立供电 | **不推荐**（浪费钱） |

> **关键改动**：不在 Android 里挂载块设备、不用 9p。而是在电脑或手机上把 SSD 格式化为 **exFAT**（Android 原生可读写、支持大文件），插到 K50 后，在 Termux 里**直接在外接盘上创建一个 QEMU 磁盘镜像文件**，当成 VM 的数据盘交给 QEMU。全程免 Root。

插上 USB 后确认挂载点（Android 通常挂在 `/storage/<UUID>/`，Termux 执行 `termux-setup-storage` 后可通过 `/storage/` 访问）：

```bash
# 在 Termux 中
termux-setup-storage
ls /storage/            # 找到你的 USB 盘 UUID 目录
# 假设为 /storage/1234-5678/
```

在外接盘上建数据盘镜像（qcow2 按需增长，不会立刻占满）：

```bash
qemu-img create -f qcow2 /storage/1234-5678/k50-nas-data.qcow2 900G
```

> exFAT 不支持稀疏文件，qcow2 会随实际写入增长（不是立刻占 900G），足够用。若担心碎片，可改 `raw` 但会预占空间，按容量权衡。

---

## 5. Phase 1：开发者选项 + 投屏（免解锁）

### 5.1 开启开发者选项与 USB 调试
设置 → 关于手机 → 连点「MIUI/OS 版本」7 次 → 开发者选项 → 开启 **USB 调试**（OEM 解锁可不开，因为不解锁 BL）。

### 5.2 投屏辅助
电脑装 scrcpy，手机 USB 连电脑，`scrcpy` 投屏用鼠标操作，绕开坏区。

> 至此**所有解锁/刷机/Root 步骤全部不需要**。下一步直接进 Termux。

---

## 6. Phase 2：Termux 环境与系统优化（免 Root）

### 6.1 安装 Termux + Termux:Boot（F-Droid）
1. 装 F-Droid → 搜 Termux 安装；同时装 **Termux:Boot**。
2. 初始化：

```bash
pkg update && pkg upgrade -y
pkg install openssh tsu wget curl git tmux qemu-system-aarch64 qemu-utils -y
```

3. 开通存储访问：`termux-setup-storage`。

### 6.2 关闭 Termux 电池优化（关键，免 Root）
设置 → 应用管理 → Termux → 省电策略 → **无限制**；允许自启动、允许后台弹出。
> HyperOS 后台杀进程激进，这一步是 7×24 稳定的命门。

### 6.3 SSH 远程管理
```bash
passwd                 # 设密码
sshd                   # 启动 SSH（端口 8022）
ifconfig wlan0 | grep inet   # 记 IP，如 192.168.1.100
```
电脑测试：`ssh -p 8022 192.168.1.100`

### 6.4 路由器固定 IP
登录路由器 → DHCP 地址保留 → 绑定 K50 MAC 到固定 IP（如 192.168.1.100）。

### 6.5 可选：无线调试 ADB 后台保活增强（非必须）
若 HyperOS 仍杀后台，可在开发者选项开 **无线调试**，用 ADB 尝试：

```bash
adb connect 192.168.1.100:PORT   # 无线调试端口
adb shell settings put global settings_enable_monitor_phantom_procs false
adb shell settings put global max_phantom_processes 2147483647
```

> 注意：部分 HyperOS 版本该全局设置需 Root 才能写，若提示权限不足属正常——**不是必须**，前面的电池优化白名单 + Termux:Boot + wake-lock 已能覆盖大多数场景。多任务界面**锁定 Termux 卡片**也有效。

### 6.6 开机 wake-lock（免 Root）
在启动脚本里加 `termux-wake-lock` 防止系统休眠杀进程。

---

## 7. Phase 3：Docker 环境搭建（QEMU 修正版）

> 以下在电脑 `ssh -p 8022 192.168.1.100` 进 Termux 操作。

### 7.1 下载 Alpine（UEFI 用 Termux 自带）
```bash
cd ~
wget https://dl-cdn.alpinelinux.org/alpine/v3.20/releases/aarch64/alpine-virt-3.20.3-aarch64.iso
# UEFI 用自带固件，无需下载：
ls $PREFIX/share/qemu/edk2-aarch64-code.fd
```

### 7.2 创建系统盘（20G）
```bash
qemu-img create -f qcow2 alpine-docker.qcow2 20G
```

### 7.3 首次启动：安装 Alpine（修正参数）
```bash
qemu-system-aarch64 \
  -machine virt \
  -cpu cortex-a78 \
  -smp 4 \
  -m 4096 \
  -accel tcg,thread=multi \
  -bios $PREFIX/share/qemu/edk2-aarch64-code.fd \
  -netdev user,id=n1,hostfwd=tcp::2222-:22 \
  -device virtio-net,netdev=n1 \
  -device virtio-rng-pci \
  -drive file=alpine-docker.qcow2,if=virtio,format=qcow2 \
  -cdrom alpine-virt-3.20.3-aarch64.iso \
  -nographic
```

> 若 `-nographic` 下黑屏，安装 ISO 引导时在内核参数追加 `console=ttyS0`（EFI 启动项编辑里加）；多数情况默认即输出到串口。

进入安装：
```bash
setup-alpine
# Keyboard: us / us
# Hostname: nas
# Interface: eth0 / dhcp
# Root password: 设强密码（记好！）
# Timezone: Asia/Shanghai
# Mirror: mirrors.tuna.tsinghua.edu.cn
# Disk: vda / Mode: sys / Erase: y
poweroff
```

### 7.4 二次启动：正式运行（带全部端口转发 + 数据盘）
```bash
qemu-system-aarch64 \
  -machine virt \
  -cpu cortex-a78 \
  -smp 4 \
  -m 4096 \
  -accel tcg,thread=multi \
  -bios $PREFIX/share/qemu/edk2-aarch64-code.fd \
  -netdev user,id=n1,hostfwd=tcp::2222-:22,hostfwd=tcp::8080-:8080,hostfwd=tcp::8096-:8096,hostfwd=tcp::5244-:5244,hostfwd=tcp::6800-:6800,hostfwd=tcp::6881-:6881 \
  -device virtio-net,netdev=n1 \
  -device virtio-rng-pci \
  -drive file=alpine-docker.qcow2,if=virtio,format=qcow2 \
  -drive file=/storage/1234-5678/k50-nas-data.qcow2,if=virtio,format=qcow2 \
  -nographic
```

> 数据盘即外接 SSD 上的镜像文件，免 Root、免 9p。Alpine 内把它格式化为 ext4 挂到 `/mnt/downloads`（见 7.6）。
> 若 `-cpu cortex-a78` 报错，改为 `-cpu max`。

端口转发：

| 手机端口 | Alpine 内 | 服务 |
|:---:|:---:|------|
| 2222 | 22 | SSH（管理 Alpine） |
| 8080 | 8080 | qBittorrent |
| 8096 | 8096 | Jellyfin |
| 5244 | 5244 | Alist |
| 6800 | 6800 | Aria2 RPC |
| 6881 | 6881 | qBittorrent BT |

SSH 连入 Alpine：`ssh root@192.168.1.100 -p 2222`

### 7.5 Alpine 内装 Docker
```bash
apk update && apk upgrade -y
apk add docker docker-compose
service docker start
rc-update add docker default
docker info
docker run --rm hello-world
```

### 7.6 挂载外接数据盘（免 9p）
```bash
# 在 Alpine 内，数据盘为 vdb（第二块 virtio 盘）
mkfs.ext4 /dev/vdb
mkdir -p /mnt/downloads
mount /dev/vdb /mnt/downloads
echo "/dev/vdb /mnt/downloads ext4 defaults 0 0" >> /etc/fstab
```

---

## 8. Phase 4：NAS 服务部署（compose 修正版）

SSH 进 Alpine，`mkdir -p /root/nas && cd /root/nas`，创建 `docker-compose.yml`：

```yaml
services:
  qbittorrent:
    image: linuxserver/qbittorrent:latest
    container_name: qbittorrent
    environment:
      - PUID=0
      - PGID=0
      - TZ=Asia/Shanghai
      - WEBUI_PORT=8080
    volumes:
      - ./qb/config:/config
      - /mnt/downloads:/downloads
    ports:
      - "8080:8080"
      - "6881:6881"
      - "6881:6881/udp"
    restart: unless-stopped

  jellyfin:
    image: jellyfin/jellyfin:latest
    container_name: jellyfin
    environment:
      - TZ=Asia/Shanghai
    volumes:
      - ./jellyfin/config:/config
      - ./jellyfin/cache:/cache
      - /mnt/downloads:/media
    ports:
      - "8096:8096"
    restart: unless-stopped

  alist:
    image: xhofe/alist:latest
    container_name: alist
    environment:
      - PUID=0
      - PGID=0
      - TZ=Asia/Shanghai
    volumes:
      - ./alist/data:/opt/alist/data
      - /mnt/downloads:/opt/alist/download
    ports:
      - "5244:5244"
    restart: unless-stopped

  aria2:
    image: p3terx/aria2-pro:latest
    container_name: aria2
    environment:
      - PUID=0
      - PGID=0
      - TZ=Asia/Shanghai
      - RPC_SECRET=nas_aria2_secret
    volumes:
      - ./aria2/config:/config
      - /mnt/downloads:/downloads
    ports:
      - "6800:6800"
      - "6888:6888"
      - "6888:6888/udp"
    restart: unless-stopped
```

> 已删除过时的 `version: "3.8"` 字段。所有数据卷指向 `/mnt/downloads`（外接 SSD 镜像盘）。

启动与配置同初版（qBittorrent `http://192.168.1.100:8080`、Jellyfin `:8096`、Alist `:5244`、Aria2 RPC `:6800`，密钥 `nas_aria2_secret`）。

**局域网安全**：qBittorrent/Alist 管理页裸奔在同 WiFi 下风险高，**公网只走 Tailscale**；不要在路由器做这些端口的 DMZ/UPnP 暴露。

---

## 9. Phase 5：自启动与远程访问（免 Root）

### 9.1 Termux:Boot 开机自启（免 Root，替代 Magisk 方案）
手机装好 Termux:Boot 后打开一次注册广播，创建 `~/.termux/boot.sh`：

```bash
mkdir -p ~/.termux
cat > ~/.termux/boot.sh << 'EOF'
#!/data/data/com.termux/files/usr/bin/sh
termux-wake-lock
sleep 10
tmux new-session -d -s nas "qemu-system-aarch64 \
  -machine virt \
  -cpu cortex-a78 \
  -smp 4 \
  -m 4096 \
  -accel tcg,thread=multi \
  -bios \$PREFIX/share/qemu/edk2-aarch64-code.fd \
  -netdev user,id=n1,hostfwd=tcp::2222-:22,hostfwd=tcp::8080-:8080,hostfwd=tcp::8096-:8096,hostfwd=tcp::5244-:5244,hostfwd=tcp::6800-:6800,hostfwd=tcp::6881-:6881 \
  -device virtio-net,netdev=n1 \
  -device virtio-rng-pci \
  -drive file=alpine-docker.qcow2,if=virtio,format=qcow2 \
  -drive file=/storage/1234-5678/k50-nas-data.qcow2,if=virtio,format=qcow2 \
  -nographic"
EOF
chmod +x ~/.termux/boot.sh
```

> 注意把 `/storage/1234-5678/` 换成你实际的 USB 挂载目录。重启手机后 Termux:Boot 自动拉起 QEMU。

### 9.2 Alpine 内 Docker 双保险
在 Alpine 的 `/etc/local.d/` 或 `rc-update` 里加 `docker compose up -d`，确保 VM 重启后容器自动拉起（`restart: unless-stopped` 已覆盖大部分情况）。

### 9.3 SSH 免密
电脑 `ssh-keygen -t ed25519` → `ssh-copy-id -p 2222 root@192.168.1.100`。

### 9.4 Tailscale 远程访问（userspace 模式，免 TUN）
```bash
# Alpine 内
apk add tailscale
rc-update add tailscale default
service tailscale start
tailscaled --tun=userspace-networking &
tailscale up
```
> **必须用 `userspace-networking`**：QEMU 用户态网络无 `/dev/net/tun`，默认 TUN 模式 `tailscale up` 建不起隧道。授权后得 `100.x.x.x` 内网 IP，外网直接访问各服务。

---

## 10. 故障排查（修正要点）

- **QEMU 启动报 `virtio-9p-pci is not a valid device`**：说明你的 qemu 没编译 9p——**不要用 9p**，改用本文的文件镜像 `-drive` 方案。
- **`-nographic` 黑屏**：内核加 `console=ttyS0`；或先去掉 `-nographic` 用默认显示确认能进系统再切回。
- **`-cpu cortex-a78` 报错**：改 `-cpu max`。
- **Alpine 内 Docker 卡在生成密钥/启动慢**：确认加了 `-device virtio-rng-pci` 补熵。
- **Tailscale 连不上**：确认用 `userspace-networking`。
- **后台被杀**：电池优化设「无限制」+ Termux:Boot + wake-lock + 锁定多任务卡片；必要时试 6.5 的 ADB 全局设置（可能需 Root，非必须）。
- **外接盘不识别**：`ls /storage/` 确认 UUID；`termux-setup-storage` 重跑；exFAT 在 Android 下可读写。

---

## 11. 进阶（可选）：原生 Docker 内核 —— 此路才需要 Root/BL 解锁

> 仅当你对 QEMU 性能不满意、且**愿意接受 168 小时等待**去拿 Root 时考虑。此章节保留初版思路，但需要先走官方 BL 解锁（绑定后等 168h）+ Magisk，且 MTK 内核编译易砖。

流程概要：
1. 开发者选项 → 绑定小米账号 → **等 168 小时** → Mi Unlock 解锁 BL。
2. 线刷干净 Fastboot 包 → Magisk 修补 boot.img → fastboot 刷回 → 获 Root。
3. ACC（Magisk 模块）限充 80%。
4. 编译开启 `CONFIG_NAMESPACES/CGROUPS/OVERLAY_FS/VETH/...` 的自定义内核（MediaTek 坑多，需线刷包救砖准备）。
5. Termux 内 `pkg install docker` + `su -c "dockerd &"` 跑原生 Docker。

> 风险：MediaTek 内核编译驱动闭源、编译器敏感，可能 boot loop，需线刷救回。**强烈建议先让 QEMU 方案稳定运行，再决定是否走这条路。** 对 99% 的下载/影视/网盘场景，QEMU 方案已够用。

---

## 12. 附录：性能预期（修正版）

| 指标 | 预期值 | 说明 |
|------|------|------|
| Samba/文件读写 | 30–40 MB/s | 被 K50 USB2.0 OTG 卡死（非 QEMU 瓶颈） |
| Docker 容器启动 | 5–15 秒 | 比原生慢 2–3 倍 |
| Jellyfin 播放 | **客户端直播放映无忧**；服务端转码 1080p 勉强、4K 基本不行（无 GPU 直通，纯 CPU 软解） | 建议客户端直接播放原画 |
| 下载 | 满带宽 | I/O 密集，CPU 影响小 |
| 功耗 | 3–5W | 月电费约 1–2 元 |
| CPU 温度 | 40–55°C | 配散热背夹 |
| 内存占用 | ~9–10 GB / 12 GB | HyperOS(~3.5–4G) + QEMU(4G) + Docker |

> **最大遗憾是 USB 2.0**：外接盘速度封顶 ~40MB/s，所以别为速度买 NVMe。若未来换支持 USB3 OTG 的机型，同样的 QEMU 文件镜像方案可直接提速。
