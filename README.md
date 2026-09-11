# youtobi - YouTube & Bilibili Automated Video Processing & Publishing System

<p align="center">
  <b>一站式 YouTube / Bilibili 视频搬运、智能二创、双平台同步自动化系统</b><br>
  <i>All-in-One Automated Video Downloader, Secondary Creation, Subtitle Burn-in, and Multi-Platform Publishing Engine</i>
</p>

---

## 🌟 核心特性 (Features)

### 1. 🚀 双平台自动上传发布 (Dual-Platform Auto Upload)
- **多目标自由选择**：支持仅发布到 Bilibili (`bilibili`)、仅发布到 YouTube (`youtube`) 或**双平台并发同步发布** (`["bilibili", "youtube"]`)。
- **YouTube Data API v3 官方集成**：基于 Google OAuth 2.0 协议，支持断点续传（Resumable Upload）、缩略图上传、发布隐私状态（`public` / `unlisted` / `private`）与视频分类（`Category ID` 下拉选择 + 自定义输入）。
- **全自动 OAuth2 回调闭环**：内置 `/oauth2callback` 路由，一键唤起 Google 授权页面，自动完成 Code 换取 Refresh Token 并安全持久化保存。
- **Bilibili 分片并发直传**：支持大文件自动分片、原生视频切片与分P（超过B站时长限制时自动切片）、并保存 BV 号与完整跳转链接。

### 2. 🎨 视频智能二创引擎 (Secondary Creation Engine)
在处理搬运视频时提供多样化的二创混剪预处理，均在 **单次 FFmpeg 滤镜链中完成（Single-Pass）**，无二次转码损耗：
- **画面水平镜像翻转 (`hflip`)**：一键左右镜像，破除基础画面查重。
- **自定义黑边缩放比例 (`pad & scale`)**：支持 `0% ~ 20%` 自由调节边框黑边，按比例缩小画面并添加四周黑边边框。
- **极值对比度隐形数字水印 (`Steganographic Invisible Watermark`)**：采用超低透明度（Alpha 0.012）在视频画面中渲染水印文本，肉眼日常播放近乎不可见，但通过画面对比度/色阶拉到极值时即可清晰显现作为版权或溯源标记。
- **字幕烧录与二创无损合并**：若包含中文字幕，字幕烧录与镜像/黑边/水印在同一个滤镜图中单次压制，高效省时。

### 3. 🎙️ 智能字幕与语音识别 (Subtitles & Whisper STT)
- **多语言自动识别**：自动检测源视频语言。中文视频免烧录，英文及其他语言自动下载字幕轨。
- **Whisper 语音转写降级**：当 YouTube 视频缺乏自带字幕时，自动提取音频流调用 Whisper API 进行语音转文字并切分时间轴。
- **大模型精准汉化**：将非中文 SRT 字幕通过 LLM 分块批量翻译为地道流利的简体中文字幕。

### 4. 🤖 AI 标题与简介二次重写 (LLM Metadata Regeneration)
- 支持接入主流兼容 OpenAI 规范的 API（如 GPT-4o、DeepSeek、Gemini、Grok 等）。
- 自动提取 YouTube 原视频标题与详细描述，智能生成符合国内/目标受众喜好的吸引人标题、中文长描述与标签（Tags）。
- 未配置或未启用 LLM 时，平滑无缝回退使用原视频标题与简介。

### 5. ☁️ CookieCloud 凭据自动化同步与安全沙箱
- **任务前自动同步**：支持对接 CookieCloud 服务，在任务启动下载前自动拉取最新的 YouTube 与 Bilibili 登录 Cookie，彻底解决 Cookie 失效导致下载/上传中断的问题。
- **双重解密兼容**：原生兼容 CookieCloud 经典 MD5 与 AES-128-CBC 两种密钥派生解密格式。
- **脱敏与安全沙箱**：API Key、OAuth Client Secret、Refresh Token 前端统一掩码脱敏显示；测试套件自带沙箱隔离，绝不污染覆盖生产环境配置与历史任务。
- **自动清理磁盘空间**：支持视频成功发布后自动删除本地下载与压制的中间视频文件，杜绝磁盘爆满。

---

## 🏗️ 系统架构 (Architecture)

```
youtobi/
├── app.py                      # FastAPI Web 服务、API 路由及 OAuth 回调落地页
├── config.py                   # 统一配置管理器与默认配置
├── config.example.json         # 配置文件示例
├── requirements.txt            # Python 依赖清单
├── services/
│   ├── bilibili.py             # Bilibili 分片直传与视频分P服务
│   ├── cookiecloud.py          # CookieCloud 自动解密与同步服务
│   ├── llm.py                  # LLM 标题/简介翻译与生成服务
│   ├── subtitle.py             # 字幕转换、Whisper 语音识别与翻译
│   ├── task_manager.py         # 异步任务调度与多平台发布编排
│   ├── video_editor.py         # FFmpeg 单 pass 镜像、边框缩放与隐形水印引擎
│   ├── youtube.py              # yt-dlp 视频元数据与资源下载服务
│   └── youtube_uploader.py     # YouTube Data API v3 OAuth2 & 断点续传发布服务
├── static/
│   ├── css/style.css           # 现代化玻璃拟态暗色主题样式
│   └── js/app.js               # 前端交互逻辑、实时轮询与设置管理
├── templates/
│   ├── index.html              # 主控面板 UI（目标平台选择、二创折叠面板、系统设置）
│   └── login.html              # 后台管理登录界面
└── tests/
    └── test_youtobi.py         # 全量单元测试与沙箱测试套件 (24 passed)
```

---

## ⚡ 快速上手 (Quick Start)

### 1. 环境准备
- **操作系统**：Linux / macOS / Windows
- **Python**：Python 3.10+
- **系统依赖**：必须预装 `ffmpeg` 与 `ffprobe`
  ```bash
  # Ubuntu / Debian
  sudo apt-get update && sudo apt-get install -y ffmpeg

  # macOS
  brew install ffmpeg
  ```

### 2. 安装与运行
```bash
# 克隆仓库
git clone https://github.com/rayleeafar/youtobi.git
cd youtobi

# 创建并激活虚拟环境
python3 -m venv venv
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt

# 启动服务 (默认监听 8166 端口)
python3 app.py
```
启动后在浏览器访问 `http://localhost:8166`（默认初始管理员密码为 `admin`，可在设置中修改）。

---

## ⚙️ 详细配置指南 (Configuration Guide)

在 Web 界面右上角点击 **设置 (⚙️)**，可进行各项配置：

### 1. YouTube Data API v3 自动发布配置
1. 访问 [Google Cloud Console](https://console.cloud.google.com/) 创建项目。
2. 在 **API 和服务 -> 库** 中搜索并启用 `YouTube Data API v3`。
3. 在 **OAuth 同意屏幕 (OAuth consent screen)** 中：
   - 用户类型选择「外部」。
   - 范围添加 `https://www.googleapis.com/auth/youtube.upload` 与 `https://www.googleapis.com/auth/youtube.readonly`。
   - 在「测试用户 (Test users)」中添加您要用于发布视频的 Google 账号邮箱。
4. 在 **凭据 (Credentials)** 中创建 **OAuth 2.0 客户端 ID**（应用类型选 Web 应用）：
   - **已获授权的重定向 URI (Authorized redirect URIs)** 填写：
     - 公网地址示例：`https://your-domain.com/oauth2callback`
     - 本地测试示例：`http://localhost:8166/oauth2callback`
5. 将生成的 **Client ID** 和 **Client Secret** 填入 `youtobi` 设置，点击 **🔑 生成授权链接并登录**，在新标签页确认授权后系统将自动换取并存储 Refresh Token。
6. 点击 **🧪 测试 YouTube API 连通性**，看到频道名称即代表配置成功。

### 2. Bilibili 发布凭据
- 可直接手动填写 `SESSDATA`、`bili_jct`、`DedeUserID`。
- 或配置 **CookieCloud** 的服务器地址、UUID 与密码，点击 **一键同步** 自动获取并持久化。

### 3. AI 简介与字幕翻译 (LLM & Whisper)
- 支持输入任意兼容 OpenAI 规范的 API Key、Base URL（如 `https://api.openai.com/v1`、`https://api.deepseek.com` 等）与模型名称。
- 支持开启 Whisper 语音转文字能力。

---

## 🚢 生产环境部署 (Production Deployment)

### Systemd 服务示例
创建 `/etc/systemd/system/youtobi.service`：
```ini
[Unit]
Description=youtobi YouTube to Bilibili Automation Engine
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/youtobi
Environment="PATH=/home/ubuntu/youtobi/venv/bin:/usr/local/bin:/usr/bin:/bin"
ExecStart=/home/ubuntu/youtobi/venv/bin/python app.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

启动并设置开机自启：
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now youtobi
sudo systemctl status youtobi
```

### Nginx 反向代理配置示例
```nginx
server {
    listen 80;
    server_name youtobi.example.com;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name youtobi.example.com;

    ssl_certificate /path/to/fullchain.pem;
    ssl_certificate_key /path/to/privkey.pem;

    client_max_body_size 2048M;

    location / {
        proxy_pass http://127.0.0.1:8166;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

---

## 🧪 测试与质量保证 (Testing)

项目配备了完善的单元与集成测试，涵盖配置管理、任务生命周期、FFmpeg 滤镜图生成、断点续传、OAuth 回调、解密兼容等各个维度：

```bash
# 运行完整测试套件
PYTHONPATH=. pytest tests/
```

测试执行时自动在临时沙箱目录中运行，绝不读写或破坏现有的生产配置文件 `config.json` 与任务历史 `tasks.json`。

---

## 📄 许可与声明 (License & Disclaimer)

- 本项目采用 [MIT License](LICENSE) 开源许可。
- **免责声明**：本项目仅供个人学习、技术研究与合法授权的内容创作工作流自动化使用。使用者在使用本工具下载或发布视频时，须严格遵守 YouTube、Bilibili 等各平台的服务条款（Terms of Service）以及当地版权法律法规，严禁将本工具用于任何侵犯第三方知识产权的非法用途。
