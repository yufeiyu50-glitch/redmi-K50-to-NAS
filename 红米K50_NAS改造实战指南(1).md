# 红米K50 NAS 改造实战指南

> 设备：红米K50（代号 rubens）12GB+256GB · 屏幕有坏区但仍可触控操作  
> 方案：Root + Termux + QEMU(aarch64) + Alpine Linux + Docker  
> 目标：离线下载 + 影视播放 + 网盘挂载，7x24 无人值守  
> 整理日期：2026-08-17（2026-08-14 初版）

---

## 方案选择理由

你的 K50 屏幕有坏区但触控仍可用、7x24 供电、要求流畅体验且发掘硬件性能。基于这些条件：

1. **必须 Root**：7x24 供电需要 ACC 控制充电防鼓包；Termux 后台保活需要 Root 权限；部分系统级优化（如固定唤醒、关闭省电策略）也需要 Root
2. **选 QEMU(aarch64) 而非 x86_64**：K50 是 ARM 架构，跑 aarch64 虚拟机同架构翻译效率远高于 x86_64 交叉模拟
3. **选 QEMU 而非编译自定义内核**：MediaTek 内核编译坑多易砖，QEMU 方案可靠性高得多，K50 的天玑8100+12GB 完全扛得住虚拟化开销
4. **选 Alpine 而非 Ubuntu/Debian**：Alpine 仅需 500MB 磁盘 + 50MB 内存，把更多资源留给 Docker 容器
5. **保留电池 + ACC 限充**：电池兼作 UPS，断电不丢数据；ACC 限充 80% 控制鼓包风险，安全且省事

**软件架构（从底到顶）**：

```
Android 14 (HyperOS)  ← 底层系统，提供硬件驱动
  └─ Termux            ← 终端环境，运行 QEMU
      └─ QEMU aarch64  ← 虚拟机，TCG 同架构翻译
          └─ Alpine Linux  ← 极轻量 Linux，原生支持 Docker
              └─ Docker Engine
                  ├─ qBittorrent  (离线下载 BT/PT)
                  ├─ Jellyfin     (影视播放/刮削)
                  ├─ Alist        (网盘聚合挂载)
                  └─ Aria2        (HTTP/磁力下载)
```

**总工期**：约 8-9 天（主要是 BL 解锁等待 168 小时），实际操作约 4-5 小时。

---

## 全流程准备清单

### 一、硬件清单

| 序号 | 硬件 | 用途 | 备注 |
|:---:|------|------|------|
| 1 | 红米K50 手机（12+256GB） | NAS 主机 | 屏幕有坏区但可触控 |
| 2 | Windows 电脑 | 刷机、解锁BL、Magisk修补、SSH远程管理 | Win10/11 均可，需有 USB 口 |
| 3 | 原装或高质量 USB 数据线 | 连接手机与电脑 | 传输线刷包（约6GB）+ ADB/fastboot 操作，劣质线会断连 |
| 4 | Type-C OTG 转接头 | 连接外接 SSD | 选支持 USB 3.0/3.1 的型号 |
| 5 | 外接 SSD（1TB+）+ M.2 硬盘盒 | NAS 存储扩展 | 256GB 内置不够存影视；硬盘盒建议带独立 Type-C 供电口 |
| 6 | 充电器（5V/3A） | 7x24 供电 | K50 原装充电器即可，确保持续供电稳定 |
| 7 | 散热背夹（半导体散热器） | 7x24 散热 | 约 30 元，Type-C 供电；天玑8100 满载发热明显 |
| 8 | 路由器（已接入家庭网络） | 网络连接 | 需支持 DHCP 地址保留功能（绝大多数路由器都支持） |

> 以上硬件除散热背夹外，大概率你手头已经有了。散热背夹建议买，7x24 运行没散热会降频。

### 二、软件清单

| 序号 | 软件 | 运行平台 | 用途 | 下载地址 |
|:---:|------|:---:|------|------|
| 1 | Mi Unlock 工具 | Windows | 解锁 Bootloader | <https://www.miui.com/unlock/index.html> |
| 2 | 小米线刷包（Fastboot ROM） | — | 刷入干净系统 | <https://xiaomirom.com> 搜索 "K50"，选 Fastboot 线刷包 |
| 3 | MiFlash 工具 | Windows | 刷入线刷包 | 随线刷包或小米官方论坛获取 |
| 4 | Android Platform Tools | Windows | ADB + fastboot 命令行 | <https://developer.android.com/tools/releases/platform-tools> |
| 5 | scrcpy | Windows | 手机投屏到电脑（辅助操作坏区） | <https://github.com/Genymobile/scrcpy/releases> 下载 zip 解压即用 |
| 6 | Magisk APK | 手机 | Root 手机 | <https://github.com/topjohnwu/Magisk/releases/latest> |
| 7 | AccA（ACC 充电控制） | 手机/Magisk模块 | 限制充电上限 80%，防止鼓包 | <https://github.com/MatteCarra/AccA/releases> |
| 8 | F-Droid | 手机 | 安装 Termux 和 Termux:Boot | <https://f-droid.org/F-Droid.apk> |
| 9 | Termux | 手机 | 终端环境，运行 QEMU | 从 F-Droid 安装（**不要用 Play Store 版，已停更**） |
| 10 | Termux:Boot | 手机 | 开机自动启动 QEMU | 从 F-Droid 安装 |
| 11 | Alpine Virt ISO（aarch64） | QEMU 内 | 轻量 Linux 系统 | <https://dl-cdn.alpinelinux.org/alpine/v3.20/releases/aarch64/alpine-virt-3.20.3-aarch64.iso> |
| 12 | QEMU UEFI 固件（QEMU_EFI.fd） | QEMU 内 | aarch64 虚拟机引导 | <https://releases.linaro.org/components/kernel/ueui-linaro/latest/release/qemu64/QEMU_EFI.fd> |

### 三、账号与网络准备

| 序号 | 项目 | 说明 |
|:---:|------|------|
| 1 | 小米账号 | 解锁 BL 必须绑定，且需在手机上登录同一个账号 |
| 2 | 路由器管理密码 | 用于设置 DHCP 地址保留（固定 IP） |
| 3 | 家庭 WiFi 密码 | 手机需连 WiFi |
| 4 | 网盘账号（可选） | 阿里云盘/夸克/115/百度等，用于 Alist 挂载 |

### 四、操作平台说明

全流程涉及两个操作平台，明确分工：

```
┌─────────────────────────────────────────────────────┐
│                    Windows 电脑                       │
│  Phase 1: Mi Unlock 解锁BL                           │
│  Phase 2: MiFlash 刷机 + fastboot 刷入 Magisk        │
│  Phase 3 起: 通过 SSH 远程管理手机（不再需要USB连接）    │
│  全程: 通过浏览器访问 NAS 各服务 Web 界面              │
└──────────────────────┬──────────────────────────────┘
                       │ USB 数据线 / WiFi SSH
┌──────────────────────┴──────────────────────────────┐
│                  红米K50 手机                         │
│  Phase 0: 开发者选项、USB调试（触屏可操作）             │
│  Phase 1: 绑定小米账号（触屏可操作）                    │
│  Phase 2: 安装 Magisk、修补 boot.img（触屏+scrcpy辅助） │
│  Phase 3: 安装 Termux、ACC（触屏+scrcpy辅助）          │
│  Phase 4 起: 全部通过 SSH 远程操作，屏幕不再需要        │
└─────────────────────────────────────────────────────┘
```

**关键节点**：Phase 3 装好 Termux 并开通 SSH 后，后续所有操作（Phase 4-6）均在电脑上通过 SSH 完成，手机屏幕不再需要操作。因此 Phase 0-3 期间屏幕能正常触控就够了。

---

## Phase 0：硬件改造与准备

### 0.1 屏幕坏区应对方案

你的屏幕有坏区但触控可用，大多数 UI 操作可以直接在手机上完成。遇到坏区挡住按钮的情况，用 scrcpy 辅助：

**scrcpy 投屏（辅助工具）**

1. 电脑安装 scrcpy：下载 zip 解压即可，无需安装 — <https://github.com/Genymobile/scrcpy/releases>
2. 手机用数据线连接电脑（需先开启 USB 调试，见 Phase 1.1）
3. 运行 `scrcpy`，电脑屏幕上出现手机画面，用鼠标操作

**使用策略**：
- 能在手机屏幕上点的就直接点
- 遇到按钮被坏区遮挡 → 切 scrcpy 用鼠标点
- Root 完成后（Phase 2 之后）装好 Termux SSH，就基本不需要屏幕了

> **建议**：先在手机上把开发者选项和 USB 调试开好（Phase 1.1），之后就可以全程用 scrcpy 辅助，不再受坏区困扰。

### 0.2 电池管理：ACC 限充 80%

7x24 插电最大的风险是锂电池鼓包甚至起火。方案：Root 后安装 ACC（Advanced Charging Controller），限制充电上限到 80%。

**原理**：
- 充电上限设为 80%，放电下限设为 70%
- 电量到 80% 自动停止充电，降到 70% 才恢复充电
- 电池长期保持 70-80% 区间，大幅降低鼓包风险
- 电池同时充当 UPS，断电时自动切换电池供电，不丢数据

**安装与配置**（Phase 3 Root 后操作，此处先记录）：
1. 下载 AccA（ACC 图形界面版）：<https://github.com/MatteCarra/AccA/releases>
2. 打开 Magisk → 模块 → 从本地安装 → 选择 AccA zip 包
3. 重启手机
4. 打开 AccA App → 设置：
   - 充电上限：80%
   - 放电下限：70%
   - 恢复充电：75%

> **为什么不拆电池**：保留电池 = 自带 UPS，断电不丢数据、服务不中断。ACC 限充 80% 已将鼓包风险降到可接受水平。电池长期保持 70-80% 的损耗远低于满电循环，一般可安全使用 2-3 年。

### 0.3 散热方案

天玑 8100 满载发热明显，7x24 运行需要散热：

- **最低要求**：手机背面朝上放在桌面，自然散热
- **推荐**：用散热背夹（半导体散热器，约 30 元），Type-C 供电
- **进阶**：3D 打印支架抬高 1.5cm，加 5V 静音风扇（约 6 元）

实测数据参考（社区反馈）：小米 10（骁龙 865）7x24 运行 NAS，CPU 日常 41°C，拷机 58°C，功耗仅 4.8W，月电费约 1.8 元。K50 的天玑 8100（5nm）功耗控制更好。

### 0.4 外接存储

256GB 内置存储扣除系统和虚拟机后约剩 200GB，不够存高清影视。扩展方案：

| 方案 | 容量 | 速度 | 供电 | 推荐度 |
|------|------|------|------|:---:|
| Type-C OTG + SSD（M.2 SATA/NVMe 硬盘盒） | 1TB+ | 400-1000 MB/s | 硬盘盒自供电 | 推荐 |
| Type-C OTG + 移动硬盘（2.5寸 HDD） | 2TB+ | 100-150 MB/s | 需独立供电 | 可选 |
| Type-C OTG + U盘 | 256GB+ | 30-150 MB/s | 手机供电 | 仅临时 |

> K50 的 OTG 口最大输出约 500mA，无法直接驱动机械硬盘。SSD 硬盘盒建议选带独立 Type-C 供电口的型号。
>
> **建议提前在电脑上把 SSD 格式化为 ext4**（Windows 用 DiskGenius，Linux 用 mkfs.ext4）。exFAT 在 9p 共享下可能有权限问题。

---

## Phase 1：解锁 Bootloader

### 1.1 开启开发者选项和 USB 调试

在手机上操作（坏区挡按钮时用 scrcpy 辅助）：

1. 设置 → 关于手机 → 连续点击"MIUI 版本"7 次 → 出现"您已处于开发者模式"
2. 设置 → 更多设置 → 开发者选项
3. 开启以下选项：
   - **USB 调试** ✓
   - **OEM 解锁** ✓
   - **USB 调试（安全设置）** ✓（部分版本需要）

> USB 调试开启后，后续可以随时用 scrcpy 投屏到电脑操作，彻底绕开屏幕坏区。

### 1.2 绑定小米账号

1. 开发者选项 → **Mi Unlock 状态** → 点击"绑定账号与设备"
2. 确保手机已登录小米账号
3. 如提示"账号未绑定设备"，退出小米账号重新登录后重试
4. 绑定成功后会显示"已绑定"

> **重要**：绑定后需要**等待 168 小时（7 天）**才能解锁。这是小米的强制等待期，无法绕过。请在日历上标记解锁日期。越早开始绑定越好，等待期间可以做其他准备工作。

### 1.3 下载解锁工具（等待期间完成）

1. 电脑访问 <https://www.miui.com/unlock/index.html>
2. 下载 **Mi Unlock 工具**（miflash_unlock.exe）
3. 安装小米 USB 驱动（解锁工具包内含）
4. 同时下载 Android Platform Tools 和 scrcpy，解压备用

### 1.4 执行解锁（等待 168 小时后）

1. 手机关机
2. 同时按住 **音量减 + 电源键**，直到出现 Fastboot 界面（米兔图标）
3. USB 连接电脑
4. 运行 miflash_unlock.exe，登录与手机相同的小米账号
5. 点击"解锁" → "解锁 anyway"
6. 等待解锁完成（会清除所有数据）
7. 点击"重启手机"

> 解锁会清除手机所有数据，确保没有需要保留的内容。解锁后手机会自动重启并进入初始设置。

---

## Phase 2：刷入干净系统 + Root

### 2.1 下载线刷包

1. 访问 <https://xiaomirom.com> 搜索 "K50"
2. 选择 **Fastboot 线刷包**（不是 Recovery 卡刷包）
3. 推荐选择最新稳定版 HyperOS（如 OS1.0.x.x.ULNCNXM）
4. 下载并解压到电脑（约 6GB）

### 2.2 MiFlash 刷机

1. 下载 **MiFlash 工具**（小米刷机工具）
2. 手机进入 Fastboot 模式（音量减 + 电源键）
3. USB 连接电脑
4. 打开 MiFlash → 选择线刷包解压目录
5. 点击"加载设备" → 确认识别到设备
6. 底部选择 **"全部删除"**（不要选 lock，否则 BL 又锁回去）
7. 点击"刷机" → 等待 5 分钟左右，状态变绿即成功
8. 手机自动开机，进入初始设置

### 2.3 提取 boot.img

从刚才下载的线刷包中提取 boot.img：

1. 打开线刷包解压目录
2. 进入 `images/` 文件夹
3. 找到 `boot.img`（部分机型还有 `vendor_boot.img`，两个都要）
4. 将 boot.img 复制到手机存储（用数据线传，或放网盘下载）

### 2.4 Magisk 修补 boot.img

1. 下载 Magisk APK：<https://github.com/topjohnwu/Magisk/releases/latest>
2. 安装到手机（触屏操作或通过 ADB 安装：`adb install Magisk.apk`）
3. 打开 Magisk App → "安装" → "选择并修补一个文件"
4. 选择刚才传入手机的 boot.img
5. Magisk 会生成修补后的文件，路径在日志中显示（通常在 `Download/magisk_patched-xxxxx.img`）
6. 将修补后的 img 文件复制到电脑

> 如果 vendor_boot.img 存在，也需要用同样方式修补并刷入。

### 2.5 fastboot 刷入修补后的 boot.img

```bash
# 手机进入 Fastboot 模式（音量减 + 电源键）
# 电脑上确认设备连接
fastboot devices

# 刷入修补后的 boot（A/B 分区都刷）
fastboot flash boot_a magisk_patched-xxxxx.img
fastboot flash boot_b magisk_patched-xxxxx.img

# 如果有 vendor_boot，也需要修补并刷入
# fastboot flash vendor_boot_a vendor_boot_patched.img
# fastboot flash vendor_boot_b vendor_boot_patched.img

# 重启
fastboot reboot
```

### 2.6 验证 Root

1. 手机开机后打开 Magisk App
2. 确认显示当前 Magisk 版本号
3. 确认 "Ramdisk: Yes"
4. 在 Magisk App 超级用户列表中能看到 root 权限管理

Root 成功。从此可以用 ADB 无线调试或 SSH 远程操作，不再依赖屏幕。

---

## Phase 3：系统优化

### 3.1 安装 ACC 充电控制

Root 之后立即操作：

1. 下载 AccA（ACC 图形界面版）：<https://github.com/MatteCarra/AccA/releases>
2. 打开 Magisk → 模块 → 从本地安装 → 选择 AccA zip 包
3. 重启手机
4. 打开 AccA App → 设置：
   - 充电上限：80%
   - 放电下限：70%
   - 恢复充电：75%
5. 手机长期保持 70-80% 电量，兼顾 UPS 功能和电池安全

### 3.2 关闭 Termux 电池优化

先装好 Termux（见 3.4），然后立即操作：

1. 设置 → 应用管理 → Termux
2. **省电策略** → 选择"无限制"
3. **后台弹出** → 允许
4. **自启动** → 允许
5. 设置 → 电池 → 关闭"智能省电"对 Termux 的限制

> 这是 7x24 稳定运行的关键。HyperOS 的后台杀进程策略很激进，不做这一步 Termux 会被杀导致 QEMU 停止。

### 3.3 路由器固定 IP

1. 登录路由器管理页面（通常 192.168.1.1 或 192.168.0.1）
2. 找到"DHCP 客户端列表"或"地址保留"
3. 找到 K50 的 MAC 地址，绑定固定 IP（如 192.168.1.100）
4. 以后所有设备通过这个 IP 访问 NAS 服务

### 3.4 安装 Termux

**重要：必须从 F-Droid 安装，不能用 Play Store 版（Play 版已停止更新）**

1. 下载 F-Droid：<https://f-droid.org/F-Droid.apk>
2. 安装 F-Droid 后搜索 "Termux"
3. 安装 Termux
4. 同时安装 **Termux:Boot**（开机自启动用）
5. 打开 Termux，初始化：

```bash
pkg update && pkg upgrade -y
pkg install openssh tsu wget curl git tmux
```

6. 设置 SSH 远程访问（以后可在电脑上 SSH 到 Termux 操作）：

```bash
# 设置密码
passwd

# 启动 SSH 服务
sshd

# 查看 IP
ifconfig wlan0 | grep inet
# 记下 IP 地址，如 192.168.1.100

# Termux SSH 端口是 8022（不是 22）
```

7. 在电脑上测试连接：

```bash
ssh -p 8022 192.168.1.100
# 输入刚才设置的密码
```

8. 回到手机设置，执行 3.2 的电池优化关闭操作。

> SSH 通了之后，后续所有操作都可以在电脑上远程完成，手机屏幕不再需要操作。

### 3.5 开启 ADB 无线调试（可选，方便调试）

```bash
# 在 Termux 中（需要 root）
su
setprop service.adb.tcp.port 5555
stop adbd
start adbd
```

电脑连接：

```bash
adb connect 192.168.1.100:5555
```

---

## Phase 4：Docker 环境搭建

> 以下所有操作在电脑上通过 SSH 到 Termux 执行（`ssh -p 8022 192.168.1.100`）。

### 4.1 安装 QEMU

```bash
pkg update && pkg upgrade -y
pkg install qemu-system-aarch64 qemu-utils wget tmux -y
```

### 4.2 下载 Alpine aarch64 和 UEFI 固件

```bash
cd ~

# 下载 Alpine Virtual 镜像（aarch64，约 60MB）
wget https://dl-cdn.alpinelinux.org/alpine/v3.20/releases/aarch64/alpine-virt-3.20.3-aarch64.iso

# 下载 QEMU aarch64 UEFI 固件（Linaro 提供）
wget https://releases.linaro.org/components/kernel/uefi-linaro/latest/release/qemu64/QEMU_EFI.fd
```

> 如果下载慢，可用国内镜像：  
> Alpine: 替换 `dl-cdn.alpinelinux.org` 为 `mirrors.tuna.tsinghua.edu.cn/alpine`

### 4.3 创建虚拟磁盘

```bash
qemu-img create -f qcow2 alpine-docker.qcow2 8G
```

> 8G 是虚拟磁盘大小，qcow2 格式是按需分配，初始仅占用约 500MB。

### 4.4 首次启动：安装 Alpine

```bash
qemu-system-aarch64 \
  -machine virt \
  -cpu cortex-a72 \
  -smp 4 \
  -m 6144 \
  -accel tcg,thread=multi \
  -bios QEMU_EFI.fd \
  -netdev user,id=n1,hostfwd=tcp::2222-:22 \
  -device virtio-net,netdev=n1 \
  -drive file=alpine-docker.qcow2,if=virtio,format=qcow2 \
  -cdrom alpine-virt-3.20.3-aarch64.iso \
  -nographic
```

参数说明：

- `-machine virt`：QEMU aarch64 虚拟机平台
- `-cpu cortex-a72`：模拟 Cortex-A72 CPU（与天玑8100 的 A78 架构接近，兼容性好）
- `-smp 4`：4 个 CPU 核心
- `-m 6144`：6GB 内存（K50 有 12GB，给 Android 留 6GB 足够）
- `-accel tcg,thread=multi`：多线程 TCG 翻译（同架构翻译效率较高）
- `-hostfwd=tcp::2222-:22`：端口转发，2222 → Alpine 的 22（SSH）

启动后会进入 Alpine 安装界面，执行以下步骤：

```bash
# 登录（root，无密码）
setup-alpine

# 按提示回答：
# Keyboard layout: us
# Keyboard variant: us
# Hostname: nas
# Interface: eth0
# IP address: dhcp
# Root password: 设置一个强密码（记好！）
# Timezone: Asia/Shanghai
# HTTP proxy: none
# NTP client: chrony
# Mirror: 选择一个国内源，如 mirrors.tuna.tsinghua.edu.cn
# Disk: vda
# Mode: sys
# Erase disk: y

# 安装完成后
poweroff
```

### 4.5 二次启动：正式运行（不带 ISO）

安装完成后，去掉 `-cdrom` 参数，添加全部端口转发：

```bash
qemu-system-aarch64 \
  -machine virt \
  -cpu cortex-a72 \
  -smp 4 \
  -m 6144 \
  -accel tcg,thread=multi \
  -bios QEMU_EFI.fd \
  -netdev user,id=n1,hostfwd=tcp::2222-:22,hostfwd=tcp::8080-:8080,hostfwd=tcp::8096-:8096,hostfwd=tcp::5244-:5244,hostfwd=tcp::6800-:6800,hostfwd=tcp::6881-:6881 \
  -device virtio-net,netdev=n1 \
  -drive file=alpine-docker.qcow2,if=virtio,format=qcow2 \
  -nographic
```

端口转发说明：

| 手机端口 | Alpine 内端口 | 服务 |
|:---:|:---:|------|
| 2222 | 22 | SSH（管理 Alpine） |
| 8080 | 8080 | qBittorrent Web UI |
| 8096 | 8096 | Jellyfin |
| 5244 | 5244 | Alist |
| 6800 | 6800 | Aria2 RPC |
| 6881 | 6881 | qBittorrent BT 传输 |

启动后从电脑 SSH 连入 Alpine：

```bash
ssh root@192.168.1.100 -p 2222
# 输入安装时设置的密码
```

### 4.6 在 Alpine 中安装 Docker

SSH 登入 Alpine 后：

```bash
# 更新系统
apk update && apk upgrade -y

# 安装 Docker 和 docker-compose
apk add docker docker-compose

# 启动 Docker 服务
service docker start

# 设置开机自启
rc-update add docker default

# 验证
docker info
docker run --rm hello-world
```

如果 `hello-world` 正常输出，Docker 环境搭建完成。

### 4.7 挂载外部存储（OTG SSD）

如果接了 OTG SSD/HDD，需要把存储传给 Alpine。

**步骤 1：在 Termux 中挂载 USB 设备（需要 root）**

```bash
su
# 查看块设备
blkid
# 找到你的 USB 设备，如 /dev/block/sda1

# 创建挂载点
mkdir -p /mnt/usb

# 挂载（如果 SSD 是 ext4 格式）
mount -t ext4 /dev/block/sda1 /mnt/usb
```

**步骤 2：修改 QEMU 启动命令，添加 9p 共享参数**

在 `qemu-system-aarch64` 命令中添加：
```bash
-virtfs local,path=/mnt/usb,mount_tag=usbshare,security_model=none,id=usbshare
```

**步骤 3：在 Alpine 中挂载 9p 共享**

```bash
mkdir -p /mnt/downloads
mount -t 9p -o trans=virtio,version=9p2000.L usbshare /mnt/downloads

# 写入 fstab 实现开机自动挂载
echo "usbshare /mnt/downloads 9p trans=virtio,version=9p2000.L 0 0" >> /etc/fstab
```

> 建议在电脑上提前把 SSD 格式化为 ext4（Windows 用 DiskGenius，Linux 用 mkfs.ext4）。exFAT 在 9p 下可能有权限问题。

---

## Phase 5：NAS 服务部署

### 5.1 创建 docker-compose.yml

SSH 登入 Alpine，创建工作目录：

```bash
mkdir -p /root/nas && cd /root/nas
```

创建 `docker-compose.yml`：

```yaml
version: "3.8"

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

> 注意：所有容器的数据卷都指向 `/mnt/downloads`，即外接 SSD。如果没接外接存储，改成 `./downloads`（存在 Alpine 虚拟磁盘里，但容量受限）。

### 5.2 启动所有服务

```bash
cd /root/nas
docker compose up -d

# 查看运行状态
docker compose ps

# 查看日志（如有问题排查）
docker compose logs -f
```

### 5.3 各服务配置

**qBittorrent**：
- 访问 `http://192.168.1.100:8080`
- 默认账号：admin
- 默认密码：查看日志 `docker logs qbittorrent | grep password`
- 首次登录后修改密码，设置下载目录为 `/downloads`

**Jellyfin**：
- 访问 `http://192.168.1.100:8096`
- 按向导完成初始设置（创建管理员账号、添加媒体库指向 `/media`）
- 自动刮削海报、简介、字幕

**Alist**：
- 访问 `http://192.168.1.100:5244`
- 获取初始密码：`docker exec -it alist ./alist admin random`
- 添加网盘：管理 → 存储 → 添加（支持阿里云盘、夸克、115、百度、OneDrive 等）
- 下载目录设为 `/opt/alist/download`

**Aria2**：
- RPC 地址：`http://192.168.1.100:6800/jsonrpc`
- RPC 密钥：`nas_aria2_secret`（在 docker-compose.yml 中设置）
- 可配合 Alist 的离线下载功能使用

### 5.4 端口访问汇总

| 服务 | 地址 | 用途 |
|------|------|------|
| SSH（Alpine） | `ssh root@192.168.1.100 -p 2222` | 管理 Alpine |
| SSH（Termux） | `ssh -p 8022 192.168.1.100` | 管理手机层 |
| qBittorrent | `http://192.168.1.100:8080` | BT/PT 下载 |
| Jellyfin | `http://192.168.1.100:8096` | 影视播放 |
| Alist | `http://192.168.1.100:5244` | 网盘挂载 |
| Aria2 RPC | `192.168.1.100:6800` | HTTP/磁力下载 |

---

## Phase 6：自启动与远程访问

### 6.1 Termux 开机自启

1. 在手机上安装 **Termux:Boot**（F-Droid 下载，与 Termux 同源）
2. 打开 Termux:Boot 一次（使其注册开机广播）
3. 创建启动脚本：

```bash
# 在 Termux 中
mkdir -p ~/.termux
cat > ~/.termux/boot.sh << 'EOF'
#!/data/data/com.termux/files/usr/bin/sh
termux-wake-lock

# 等待网络就绪
sleep 10

# 如果有挂载 USB，重新挂载（需要 root）
su -c "mount -t ext4 /dev/block/sda1 /mnt/usb" 2>/dev/null

# 在 tmux 中启动 QEMU
tmux new-session -d -s nas "qemu-system-aarch64 \
  -machine virt \
  -cpu cortex-a72 \
  -smp 4 \
  -m 6144 \
  -accel tcg,thread=multi \
  -bios QEMU_EFI.fd \
  -netdev user,id=n1,hostfwd=tcp::2222-:22,hostfwd=tcp::8080-:8080,hostfwd=tcp::8096-:8096,hostfwd=tcp::5244-:5244,hostfwd=tcp::6800-:6800,hostfwd=tcp::6881-:6881 \
  -device virtio-net,netdev=n1 \
  -drive file=alpine-docker.qcow2,if=virtio,format=qcow2 \
  -virtfs local,path=/mnt/usb,mount_tag=usbshare,security_model=none \
  -nographic"
EOF

chmod +x ~/.termux/boot.sh
```

4. 重启手机测试，开机后 Termux:Boot 会自动执行此脚本

### 6.2 验证自启动

重启手机后，在电脑上：

```bash
# 等待约 30 秒（开机 + Termux 启动 + QEMU 启动）
# 测试 SSH 到 Alpine
ssh root@192.168.1.100 -p 2222

# 检查 Docker 容器
docker compose ps

# 如果容器没自动启动（docker compose 的 restart: unless-stopped 应该会自动拉起）
# 手动启动：
# docker compose up -d
```

### 6.3 SSH 免密登录

在电脑上生成密钥并传到 Alpine：

```bash
# 生成密钥（如果已有可跳过）
ssh-keygen -t ed25519

# 传到 Alpine
ssh-copy-id -p 2222 root@192.168.1.100

# 之后免密登录
ssh -p 2222 root@192.168.1.100
```

### 6.4 Tailscale 远程访问（外网访问）

在外网也能访问 NAS 服务：

```bash
# SSH 登入 Alpine
ssh -p 2222 root@192.168.1.100

# 安装 Tailscale
apk add tailscale

# 启动并配置
rc-update add tailscale default
service tailscale start
tailscale up

# 按提示在浏览器中授权
# 授权后会获得一个 100.x.x.x 的内网 IP
```

配置完成后，在任何地方都可以通过 Tailscale IP 访问：

- Jellyfin：`http://100.x.x.x:8096`
- qBittorrent：`http://100.x.x.x:8080`
- Alist：`http://100.x.x.x:5244`
- SSH：`ssh -p 2222 root@100.x.x.x`

> Tailscale 免费版支持 100 台设备，足够个人使用。手机上也装一个 Tailscale App，在外随时访问 NAS。

---

## 故障排查

### QEMU 启动失败

```bash
# 检查 QEMU 是否正确安装
qemu-system-aarch64 --version

# 检查虚拟磁盘是否存在
ls -la ~/alpine-docker.qcow2

# 检查 UEFI 固件是否存在
ls -la ~/QEMU_EFI.fd

# 检查内存是否足够（K50 需要 6GB 给 QEMU）
free -h
# 如果 Android 占用太多内存，重启手机后立即启动 QEMU
```

### Docker 容器启动失败

```bash
# 查看具体错误
docker compose logs qbittorrent
docker compose logs jellyfin

# 常见问题：目录权限
chown -R root:root /root/nas/

# 常见问题：端口被占用
# 在 Alpine 中查看端口
netstat -tlnp

# 重启所有容器
docker compose restart
```

### 网络不通

```bash
# 在 Alpine 中测试网络
ping 8.8.8.8
# 如果不通，检查 DNS
echo "nameserver 8.8.8.8" > /etc/resolv.conf

# 在 Termux 中测试 QEMU 端口转发
ssh root@localhost -p 2222
# 如果能连上说明 QEMU 网络正常，问题在外部访问
```

### 手机重启后服务没启动

```bash
# 检查 Termux:Boot 是否运行
ls ~/.termux/boot.sh

# 手动执行启动脚本
bash ~/.termux/boot.sh

# 检查 tmux 会话
tmux ls

# 进入 QEMU 会话查看
tmux attach -t nas
# 按 Ctrl+B 再按 D 退出（不要按 Ctrl+C，会关闭 QEMU）
```

### Android 杀后台导致 QEMU 中断

```bash
# 确保 Termux 获得了 wake-lock
termux-wake-lock

# 检查电池优化是否已关闭
# 设置 → 应用 → Termux → 省电策略 → 无限制

# 如果还是被杀，考虑刷入 LineageOS 等类原生系统
# 类原生系统的后台管理比 MIUI/HyperOS 宽松得多
```

### 电池状态检查

```bash
# 在 Termux 中（需要 root）
su -c "dumpsys battery"
# 如果 status 显示过热或电压异常，立即断电检查

# ACC 模块记录
cat /data/acc/logs/*.log | tail -50
```

---

## 进阶选项：编译 Docker 兼容内核（原生 Docker）

如果你对 QEMU 性能不满意，想追求零虚拟化开销的原生 Docker，可以编译自定义内核。这是风险最高的操作，仅在 QEMU 方案稳定运行后考虑。

### 前提条件

- 一台 Linux 电脑（Ubuntu 20.04+ 推荐，需要约 30GB 磁盘空间）
- 已安装 Android NDK 和编译工具链
- 熟悉 Linux 命令行

### 大致流程

1. 获取 K50 内核源码：

```bash
git clone https://github.com/MiCode/Xiaomi_Kernel_OpenSource.git -b rubens-s-oss
```

2. 安装编译依赖：

```bash
sudo apt install build-essential libncurses-dev libssl-dev bc bison flex
```

3. 下载 MediaTek 工具链（GCC/aarch64）
4. 使用 check-config.sh 检查内核缺失的 Docker 选项：

```bash
wget https://raw.githubusercontent.com/moby/moby/master/contrib/check-config.sh
chmod +x check-config.sh
```

5. 修改内核 defconfig，开启以下关键选项：

```
CONFIG_NAMESPACES=y
CONFIG_CGROUPS=y
CONFIG_CGROUP_CPUACCT=y
CONFIG_CGROUP_DEVICE=y
CONFIG_CGROUP_FREEZER=y
CONFIG_CGROUP_SCHED=y
CONFIG_CPUSETS=y
CONFIG_MEMCG=y
CONFIG_OVERLAY_FS=y
CONFIG_VETH=y
CONFIG_BRIDGE=y
CONFIG_IP_NF_IPTABLES=y
CONFIG_NETFILTER_XT_TARGET_REDIRECT=y
CONFIG_BLK_DEV_LOOP=y
CONFIG_USER_NS=y
CONFIG_SECCOMP=y
```

6. 编译内核：

```bash
export ARCH=arm64
export CROSS_COMPILE=aarch64-linux-gnu-
make rubens_defconfig
make menuconfig  # 手动确认/修改配置
make -j$(nproc)
```

7. 刷入内核：

```bash
# 生成 boot.img（需要 mkbootimg 工具）
# fastboot 刷入
fastboot flash boot_a custom_kernel_boot.img
fastboot flash boot_b custom_kernel_boot.img
fastboot reboot
```

8. 在 Termux 中安装原生 Docker：

```bash
pkg install root-repo
pkg install docker tini

# 启动 Docker
su -c "dockerd &"

# 验证
docker info
docker run --rm hello-world
```

### 自定义内核的风险

- MediaTek 平台内核编译坑多（驱动闭源、编译器版本敏感）
- 可能遇到 boot loop（开机卡 logo），需要线刷救回
- 建议：先在 QEMU 方案稳定运行后，再尝试编译内核；编译前确保有线刷包和 MiFlash 可用

### 参考资源

- Docker on Android 完整教程：<https://saksham.thedev.id/Docker-On-Android>
- 内核 Docker 选项检查脚本：<https://github.com/moby/moby/blob/master/contrib/check-config.sh>
- 为手机内核开启 Docker 支持：<https://www.cnblogs.com/Moe-hacker/p/18520395>
- K50 内核源码：<https://github.com/MiCode/Xiaomi_Kernel_OpenSource/tree/rubens-s-oss>
- K50 LineageOS 设备树：<https://github.com/StaticReflection/android_device_xiaomi_rubens>

---

## 附录：方案性能预期

基于社区实测数据（骁龙 865 设备 + QEMU + Alpine + Docker）：

| 指标 | 预期值 | 说明 |
|------|------|------|
| Samba 读写 | 50-80 MB/s | 受 QEMU 网络层和 WiFi 带宽限制 |
| Docker 容器启动 | 5-15 秒 | 比原生慢 2-3 倍 |
| Jellyfin 转码 | 1080p 可用 | 4K 转码可能卡顿 |
| 直播播放 | 流畅 | 不需要转码的格式直接播放无压力 |
| qBittorrent 下载 | 满带宽 | 下载是 I/O 密集，CPU 影响小 |
| 功耗 | 3-5W | 月电费约 1-2 元 |
| CPU 温度 | 40-55°C | 配合散热背夹 |
| 内存占用 | 7-8 GB / 12 GB | Android + QEMU(6G) + Docker |

> K50 的天玑 8100（5nm）比骁龙 865 性能更强、功耗更低，实际体验应该优于上述数据。如果后续编译了 Docker 兼容内核，性能可提升 30-50%。
