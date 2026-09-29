#!/usr/bin/env bash
# ==============================================================================
# youtobi 主机环境自动化配置与依赖安装脚本
# 支持系统: Ubuntu 20.04 / 22.04 / 24.04, Debian 11 / 12
# ==============================================================================

set -euo pipefail

echo "========================================================"
echo "🚀 开始配置 youtobi 运行环境..."
echo "========================================================"

# 1. 检测 root 权限或 sudo
SUDO=""
if [ "$(id -u)" -ne 0 ]; then
    if command -v sudo >/dev/null 2>&1; then
        SUDO="sudo"
    else
        echo "❌ 错误: 请使用 root 用户或配置了 sudo 权限的用户运行此脚本。"
        exit 1
    fi
fi

# 2. 更新软件源并安装基础依赖
echo "📦 正在安装系统基础包 (Python3, FFmpeg, Curl, Unzip, etc.)..."
$SUDO apt-get update -y
$SUDO apt-get install -y \
    python3 \
    python3-venv \
    python3-pip \
    ffmpeg \
    curl \
    wget \
    jq \
    unzip \
    ca-certificates

# 3. 安装/检查 Node.js
if ! command -v node >/dev/null 2>&1; then
    echo "📦 Node.js 未检测到，正在通过 apt 安装 nodejs..."
    $SUDO apt-get install -y nodejs || true
fi

# 4. 安装/检查 Deno 运行时 (yt-dlp YouTube EJS 签名计算核心依赖)
if ! command -v deno >/dev/null 2>&1 && [ ! -f "/usr/local/bin/deno" ]; then
    echo "📦 正在安装 Deno 引擎到 /usr/local/bin/deno (解决 YouTube EJS challenge / 429 反爬)..."
    ARCH="$(uname -m)"
    DENO_ARCH=""
    if [ "$ARCH" = "x86_64" ]; then
        DENO_ARCH="x86_64-unknown-linux-gnu"
    elif [ "$ARCH" = "aarch64" ] || [ "$ARCH" = "arm64" ]; then
        DENO_ARCH="aarch64-unknown-linux-gnu"
    else
        echo "⚠️ 未知架构: $ARCH，尝试通过官方通用安装器安装..."
    fi

    if [ -n "$DENO_ARCH" ]; then
        DENO_TMP="$(mktemp -d)"
        DENO_URL="https://github.com/denoland/deno/releases/latest/download/deno-${DENO_ARCH}.zip"
        echo "⬇️ 从 GitHub 下载最新 Deno: ${DENO_URL}"
        if curl -fsSL "$DENO_URL" -o "${DENO_TMP}/deno.zip"; then
            unzip -q "${DENO_TMP}/deno.zip" -d "${DENO_TMP}"
            $SUDO install -m 755 "${DENO_TMP}/deno" /usr/local/bin/deno
            rm -rf "${DENO_TMP}"
        else
            echo "⚠️ GitHub 直连较慢，回退到官方安装脚本..."
            curl -fsSL https://deno.land/install.sh | sh
            if [ -f "$HOME/.deno/bin/deno" ]; then
                $SUDO cp "$HOME/.deno/bin/deno" /usr/local/bin/deno
            fi
        fi
    else
        curl -fsSL https://deno.land/install.sh | sh
        if [ -f "$HOME/.deno/bin/deno" ]; then
            $SUDO cp "$HOME/.deno/bin/deno" /usr/local/bin/deno
        fi
    fi
fi

if command -v deno >/dev/null 2>&1 || [ -f "/usr/local/bin/deno" ]; then
    DENO_BIN="$(command -v deno || echo /usr/local/bin/deno)"
    echo "✅ Deno 安装就绪: $("$DENO_BIN" --version | head -n 1)"
else
    echo "⚠️ 警告: Deno 未能成功安装到 /usr/local/bin/deno，yt-dlp 将尝试回退使用 node。"
fi

# 5. 设置 Python 虚拟环境
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${PROJECT_DIR}/venv"

echo "🐍 正在配置 Python 虚拟环境: ${VENV_DIR}..."
if [ ! -d "${VENV_DIR}" ]; then
    python3 -m venv "${VENV_DIR}"
fi

echo "📦 升级 pip 并安装 requirements.txt (含 yt-dlp[default] 与 yt-dlp-ejs)..."
"${VENV_DIR}/bin/pip" install --upgrade pip
"${VENV_DIR}/bin/pip" install -r "${PROJECT_DIR}/requirements.txt"

# 6. 验证核心运行时
echo "🔍 验证环境依赖..."
"${VENV_DIR}/bin/python" -c "
import yt_dlp
import yt_dlp_ejs
import fastapi
import psutil
print('✅ Python 核心依赖验证通过: yt-dlp ' + yt_dlp.__version__ + ', yt-dlp-ejs ' + yt_dlp_ejs.__version__)
"

# 确保下载目录存在
mkdir -p "${PROJECT_DIR}/downloads"

echo "========================================================"
echo "🎉 youtobi 主机环境配置完成！"
echo "项目路径: ${PROJECT_DIR}"
echo "启动命令: ${VENV_DIR}/bin/uvicorn app:app --host 0.0.0.0 --port 8166"
echo "========================================================"
