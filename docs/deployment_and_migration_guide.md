# youtobi 生产部署与跨机器迁移终极指南 (Deployment & Migration Guide)

> 本文档针对 `youtobi` 在 Linux（Ubuntu 20.04/22.04/24.04、Debian 11/12）环境下的全新安装部署以及跨主机无损迁移，总结了历次部署与排错过程中的全部踩坑经验，提供标准化、一步到位的落地实践。

---

## 目录 (Table of Contents)

1. [核心架构与依赖清单](#1-核心架构与依赖清单)
2. [关键问题复盘与避坑指南 (必读)](#2-关键问题复盘与避坑指南-必读)
   - [2.1 YouTube 报错 "The page needs to be reloaded" 与 EJS 解密](#21-youtube-报错-the-page-needs-to-be-reloaded-与-ejs-解密)
   - [2.2 systemd PATH 环境变量缺失导致 Deno 无法调用](#22-systemd-path-环境变量缺失导致-deno-无法调用)
   - [2.3 历史任务 `tasks.json` 路径硬编码导致断点续跑失败](#23-历史任务-tasksjson-路径硬编码导致断点续跑失败)
   - [2.4 Web 管理员密码重置机制](#24-web-管理员密码重置机制)
   - [2.5 主机磁盘空间暴满与自动化清理](#25-主机磁盘空间暴满与自动化清理)
   - [2.6 Bilibili 报 "preupload HTTP 403 出错啦/未登录页面"](#26-bilibili-报-preupload-http-403-出错啦未登录页面)
   - [2.7 前端轮询导致选中文本失去焦点与页面闪烁](#27-前端轮询导致选中文本失去焦点与页面闪烁)
3. [方案 A：全新机器一步到位部署指南](#3-方案-a全新机器一步到位部署指南)
4. [方案 B：跨机器数据无损热迁移 SOP](#4-方案-b跨机器数据无损热迁移-sop)
5. [系统服务与自启动配置 (systemd)](#5-系统服务与自启动配置-systemd)
6. [迁移后验证核对清单 (Checklist)](#6-迁移后验证核对清单-checklist)

---

## 1. 核心架构与依赖清单

`youtobi` 是一个由 FastAPI + yt-dlp + FFmpeg 驱动的视频自动化流水线系统。由于涉及多媒体压制与强反爬对抗，系统必须具备以下依赖组件：

| 依赖组件 | 类别 | 最小版本/建议 | 作用与关键说明 |
| :--- | :--- | :--- | :--- |
| **Python** | 语言环境 | `>= 3.10` (建议 3.12) | 运行 FastAPI、Uvicorn 及流水线核心逻辑。 |
| **FFmpeg** | 媒体处理 | `>= 4.4` (需含 `libass`) | 视频转码、二创滤镜（水平翻转/画边黑框/隐形水印）、字幕烧录。 |
| **Deno** | JS 运行时 | `>= 2.0.0` (装于 `/usr/local/bin/deno`) | **核心反爬依赖**：供 `yt-dlp` 解决 YouTube 复杂的 EJS 挑战与签名计算。 |
| **Node.js** | 备用 JS 引擎 | `>= 18.0.0` | 作为 Deno 之后的二级备用 JS 运行时。 |
| **yt-dlp[default]** | Python 包 | `>= 2026.8.19` | 核心下载组件，包含 `pycryptodomex` 加密支持。 |
| **yt-dlp-ejs** | Python 包 | `>= 0.8.0` | **必须依赖**：EJS 挑战解密插件，缺少此包会导致 YouTube 报错。 |
| **biliup** | CLI 二进制 | `>= 1.2.10` (装于 `/usr/local/bin/biliup`) | **B站上传核心引擎**：使用 B-Cut Android / UPOS 协议上传视频，规避网页端 403 出错啦拦截。 |
| **CookieCloud** | 服务/插件 | 独立或自建部署 | 自动拉取更新 YouTube 与 Bilibili 登录态 Cookie。 |

---

## 2. 关键问题复盘与避坑指南 (必读)

### 2.1 YouTube 报错 "The page needs to be reloaded" 与 EJS 解密

* **现象**：
  下载 YouTube 视频或提取元数据时，任务日志报：
  `ERROR: [youtube] {id}: The page needs to be reloaded.`
* **根本原因**：
  1. **缺少 JS 运行时与解密扩展**：YouTube 2024~2026 年全面收紧了客户端验证（EJS Challenge）。`yt-dlp` 若未安装 `deno` 运行时以及 `yt-dlp-ejs` 插件，无法解密 YouTube 的 JavaScript 签名。
  2. **Cookie 与环境指纹冲突 (DBSC)**：从桌面浏览器通过 CookieCloud 同步下来的 Cookie 往往携带了客户端绑定的 DBSC 会话（如 `__Secure-1PSIDTS`）。当机房/VPS IP 在缺少 JS 求解器的情况下使用该 Cookie 发起抓取，YouTube 会判定为异常请求，直接阻断并提示刷新。
* **解决与预防措施**：
  1. 在主机安装 Deno 二进制到标准路径 `/usr/local/bin/deno`。
  2. 虚拟环境中安装 `pip install "yt-dlp[default]>=2026.8.19" "yt-dlp-ejs>=0.8.0"`。
  3. `services/youtube.py` 中显式配置：`"js_runtimes": {"deno": None, "node": None}`。
  4. 代码内已集成容灾重试：若携带 Cookie 下载遇到 `The page needs to be reloaded`，会自动回退尝试无 Cookie 纯净重试，保障公开视频正常下载。

---

### 2.2 systemd PATH 环境变量缺失导致 Deno 无法调用

* **现象**：
  在终端直接运行 `python app.py` 能成功下载 YouTube 视频，但使用 `systemctl start youtobi` 后台启动后，又报 `The page needs to be reloaded` 或找不到 Deno。
* **根本原因**：
  systemd 服务默认的 `Environment="PATH=..."` 通常仅包含 `/usr/bin:/bin`。如果不包含 `/usr/local/bin`，systemd 子进程即使在全局装了 `/usr/local/bin/deno`，也无法通过 PATH 找到 Deno，导致 yt-dlp 回退失败。
* **解决与预防措施**：
  在 `/etc/systemd/system/youtobi.service` 中必须严格保证包含 `/usr/local/bin`：
  ```ini
  Environment="PATH=/home/<user>/youtobi/venv/bin:/usr/local/bin:/usr/bin:/bin"
  ```

---

### 2.3 历史任务 `tasks.json` 路径硬编码导致断点续跑失败

* **现象**：
  从旧机器拷贝 `tasks.json` 到新机器后，任务卡片上以前下载好的视频无法重试，阶段续跑检测失效，或者重新从第一阶段从头全量下载。
* **根本原因**：
  `tasks.json` 内部各任务的 `video_path`、`cover_path`、`stage_artifacts`、`edit_video_path` 等字段保存的是旧机器绝对路径（如 `/home/ubuntu/youtobi/downloads/...`）。在新机器（例如用户名变为 `ray`，路径变成 `/home/ray/youtobi/downloads/...`）后，`os.path.exists()` 判定文件不存在。
* **解决与预防措施**：
  迁移数据后，执行一键路径替换命令：
  ```bash
  sed -i 's#/home/旧用户名/youtobi/#/home/新用户名/youtobi/#g' tasks.json
  sed -i 's#/home/旧用户名/youtobi/#/home/新用户名/youtobi/#g' config.json
  ```

---

### 2.4 Web 管理员密码重置机制

* **现象**：
  迁移后打开 Web UI，无法使用默认密码或原先设定的密码登录。
* **根本原因**：
  `config.json` 中的 `admin_password` 会被 SHA-256 哈希加密保存。新环境如果历史密码遗忘或哈希混淆，Web 接口将持续返回 401。
* **解决与预防措施**：
  直接编辑新机器上的 `config.json`，将 `admin_password` 重置为明文字符串 `"admin"`（程序检测到明文会自动进行首登处理），重启服务后即可用 `admin` 登录，再前往后台「设置」页面重新修改为生产强密码。

---

### 2.5 主机磁盘空间暴满与自动化清理

* **现象**：
  服务器运行一段时间或由多容器宿主机承载时，磁盘占用超 85%，导致大视频压制时出现 `No space left on device`。
* **清理脚本与应急方案**：
  在目标机执行标准化瘦身命令：
  ```bash
  # 1. 清理 Docker 无用构建缓存与孤立卷 (通常可释放数十 GB)
  docker builder prune -af
  docker system prune -a --volumes -f

  # 2. 清理系统超大日志与 APT 缓存
  sudo journalctl --vacuum-size=200M
  sudo apt-get clean

  # 3. 清理 Snap 禁用的历史残余版本 (仅保留最多 2 个 revision)
  sudo snap set system refresh.retain=2
  snap list --all | awk '/disabled/{print $1, $3}' | while read -r snapname revision; do
      [ -n "$snapname" ] && sudo snap remove "$snapname" --revision="$revision"
  done
  ```

---

### 2.6 Bilibili 报 "preupload HTTP 403 出错啦/未登录页面"

* **现象**：
  视频下载切分完成后，进入 Bilibili 上传阶段，任务报错：
  `Bilibili upload error: Upload failed: Bilibili preupload HTTP 403: Bilibili 会话验证失败 (HTTP 403 出错啦/未登录页面)，请确认 SESSDATA 有效性`
* **根本原因**：
  1. **缺少 `biliup` 引擎**：B站网页版创作者中心（`member.bilibili.com`）对直接模拟 Web 预上传请求（Method C）启用了严格的风控策略（缺少 Wbi 签名、缺少 `DedeUserID__ckMd5` 等完整上下文，或直接对服务器 IP 403 拦截）。
  2. 当 `biliup` 二进制未安装到系统 PATH 时，程序会降级到网页模拟上传，从而触发该报错。
* **解决与预防措施**：
  1. 主机安装官方预编译 `biliup` 二进制到 `/usr/local/bin/biliup`（`./scripts/setup_host.sh` 已自动化集成）。
  2. `services/bilibili.py` 已增强 `biliup` 显式路径搜索 (`/usr/local/bin/biliup`, `/usr/bin/biliup` 等)，优先采用官方 B-Cut 协议 (`--submit b-cut-android`) 稳定投稿，彻底规避 Web 403 拦截。
  3. Method C 中已补齐 `buvid3`/`buvid4` 字段纠错与全量 Cookie 传递支持。

---

### 2.7 前端轮询导致选中文本失去焦点与页面闪烁

* **现象**：
  在 Web 控制台查看任务列表时，想要选中文本（如复制错误日志或视频链接），每过 3 秒页面就会刷新一次，导致选中的文字自动失去焦点被清除。
* **根本原因**：
  原 `loadTasks()` 在每次 3 秒轮询拉取任务数据后，均直接执行 `container.innerHTML = ...` 全量重构任务列表 DOM，瞬间销毁所有原有 DOM 节点与浏览器的文本选择状态 (`window.getSelection()`)。
* **解决与预防措施**：
  1. **主动选择守卫**：在 `loadTasks` 执行前检测 `window.getSelection()`，当用户在任务卡片区域有活动高亮选区时，自动推迟当前周期的 DOM 更新，绝不打断复制操作。
  2. **JSON 无变动跳过**：当任务列表数据未变动时，完全不触碰 DOM，杜绝无意义重绘。
  3. **单卡差量更新 (Differential Patching)**：为每张任务卡片绑定 `id="task-card-${id}"`，仅当该任务卡片数据实际发生变化时，精准替换对应单张卡片节点，其他卡片与页面焦点完全不受干扰。

---

## 3. 方案 A：全新机器一步到位部署指南

在新服务器上部署 youtobi 时，可直接使用仓库内置的自动化初始化脚本：

```bash
# 1. 克隆代码仓库
git clone https://github.com/rayleeafar/youtobi.git /home/ray/youtobi
cd /home/ray/youtobi

# 2. 运行一键配置脚本 (自动安装系统包、Deno 运行时、创建 Python venv 并安装全套依赖)
./scripts/setup_host.sh

# 3. 初始化配置文件
cp config.example.json config.json
# 修改 downloads_dir 为当前服务器绝对路径 (例如 /home/ray/youtobi/downloads)
sed -i "s#./downloads#/home/ray/youtobi/downloads#g" config.json

# 4. 配置并启动 systemd 系统服务 (详见第 5 节)
sudo cp youtobi.service /etc/systemd/system/youtobi.service
sudo systemctl daemon-reload
sudo systemctl enable --now youtobi
```

---

## 4. 方案 B：跨机器数据无损热迁移 SOP

假设我们要将服务从 **源主机 (A: `tencent-jp`)** 迁移到 **目标主机 (B: `ray-nas-ubt-pub`)**：

```
[源主机 A: tencent-jp] ────(rsync 数据备份与传输)────> [目标主机 B: ray-nas-ubt-pub]
```

### 第一步：源主机 A (下线旧服务)
在源主机上停止旧服务，防止新任务写入：
```bash
sudo systemctl stop youtobi
sudo systemctl disable youtobi
# 确认进程完全退出
sudo ss -tulpn | grep 8166
```

### 第二步：目标主机 B (初始化基础环境)
登录目标主机 B，拉取代码并运行一键配置脚本：
```bash
cd /home/ray/youtobi
./scripts/setup_host.sh
```

### 第三步：数据同步 (rsync)
从源主机 A 同步关键业务数据（配置、历史任务、已下载媒体、Cookies）到目标主机 B：
```bash
# 在目标主机 B 上执行拉取：
rsync -avzP ray@tencent-jp:/home/ubuntu/youtobi/config.json /home/ray/youtobi/config.json
rsync -avzP ray@tencent-jp:/home/ubuntu/youtobi/tasks.json /home/ray/youtobi/tasks.json
rsync -avzP ray@tencent-jp:/home/ubuntu/youtobi/downloads/ /home/ray/youtobi/downloads/
```

### 第四步：路径与配置归一化适配 (关键)
```bash
cd /home/ray/youtobi

# 1. 替换 tasks.json 中的所有旧机器路径
sed -i 's#/home/ubuntu/youtobi/#/home/ray/youtobi/#g' tasks.json

# 2. 检查并替换 config.json 中的 downloads_dir
sed -i 's#/home/ubuntu/youtobi/downloads#/home/ray/youtobi/downloads#g' config.json

# 3. 校验并确保下载目录存在与权限正常
mkdir -p /home/ray/youtobi/downloads
chmod -R 755 /home/ray/youtobi/downloads
```

### 第五步：启动服务与验证
```bash
# 启动新服务
sudo systemctl daemon-reload
sudo systemctl restart youtobi
sudo systemctl status youtobi
```

---

## 5. 系统服务与自启动配置 (systemd)

在 `/etc/systemd/system/youtobi.service` 中写入配置（替换对应的用户名与项目目录）：

```ini
[Unit]
Description=youtobi YouTube to Bilibili Automation Engine
After=network.target

[Service]
Type=simple
User=ray
WorkingDirectory=/home/ray/youtobi
# 极其关键: 必须显式引入 /usr/local/bin，确保 deno 与 ffmpeg 全局二进制可被直接调用
Environment="PATH=/home/ray/youtobi/venv/bin:/usr/local/bin:/usr/bin:/bin"
ExecStart=/home/ray/youtobi/venv/bin/uvicorn app:app --host 0.0.0.0 --port 8166
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

应用并自启：
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now youtobi
```

---

## 6. 迁移后验证核对清单 (Checklist)

迁移或部署完成后，按以下顺序依次检查，确认所有功能健康：

- [ ] **1. 服务状态与端口**
  ```bash
  sudo systemctl is-active youtobi  # 应输出 active
  curl -I http://127.0.0.1:8166/    # 应返回 200 OK
  ```
- [ ] **2. Deno 与 FFmpeg 环境变量探测**
  ```bash
  /usr/local/bin/deno --version
  ffmpeg -version
  ```
- [ ] **3. Web 控制台登录**
  - 访问 `http://<HOST_IP>:8166/`，使用设置的管理员密码登录。
  - 观察顶部主机资源条（CPU、内存、根磁盘容量、公网 IP）是否正常显示并定期刷新。
- [ ] **4. 历史任务连续性**
  - 检查页面是否加载了历史全部任务列表。
  - 检查历史已完成任务的视频封面和下载路径是否可识别。
- [ ] **5. CookieCloud 同步**
  - 在「设置」中点击「手动同步 Cookie」或触发任意任务，检查日志确认是否成功同步 YouTube (`yt_cookies.txt`) 与 Bilibili (`bili_cookies.json`)。
- [ ] **6. YouTube 端到端下载与 EJS 测试**
  - 提交一个测试 YouTube 链接（例如 `https://www.youtube.com/watch?v=7LDR6sFh2zk`）。
  - 观察任务日志是否顺利度过 `metadata` 与 `download` 阶段，无 `The page needs to be reloaded` 错误，确认 Deno 挑战正常求解。
- [ ] **7. 单元测试自检**
  ```bash
  cd /home/ray/youtobi
  ./venv/bin/python -m unittest tests.test_youtobi
  # 应提示: Ran 33 tests in ...s, OK
  ```
