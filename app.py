import os
import logging
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple
from fastapi import FastAPI, Request, HTTPException, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from config import config_manager, BASE_DIR
from services.task_manager import task_manager
from services.bilibili import BilibiliService
from services.cookiecloud import CookieCloudService
from services.youtube_uploader import YouTubeUploaderService

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("youtobi.app")

app = FastAPI(
    title="youtobi",
    description="YouTube to Bilibili Auto Downloader, Subtitle Generator & Uploader System",
    version="1.0.0"
)

# Setup directories
STATIC_DIR = BASE_DIR / "static"
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR.mkdir(parents=True, exist_ok=True)
TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.mount("/app_static", StaticFiles(directory=str(STATIC_DIR)), name="app_static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

import hashlib
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

AUTH_COOKIE_NAME = "youtobi_session"

def _get_auth_token(password: str) -> str:
    return hashlib.sha256(f"youtobi_salt_{password}".encode("utf-8")).hexdigest()

def is_authenticated(request: Request) -> bool:
    admin_pwd = config_manager.get("admin_password", "admin")
    if not admin_pwd:
        return True
    expected_token = _get_auth_token(admin_pwd)
    session_token = request.cookies.get(AUTH_COOKIE_NAME)
    return session_token == expected_token

@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    path = request.url.path
    if path.startswith("/static") or path.startswith("/app_static") or path in ["/login", "/api/auth/login"]:
        res = await call_next(request)
        if path.startswith("/static") or path.startswith("/app_static"):
            res.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
            res.headers["Pragma"] = "no-cache"
            res.headers["Expires"] = "0"
            res.headers["CDN-Cache-Control"] = "no-store"
            res.headers["Cloudflare-CDN-Cache-Control"] = "no-store"
        return res
    
    if not is_authenticated(request):
        if path.startswith("/api/"):
            return JSONResponse(status_code=401, content={"detail": "未登录或会话已过期，请先登录管理后台。"})
        return RedirectResponse(url="/login")

    res = await call_next(request)
    return res

class SecondaryCreationParams(BaseModel):
    enabled: Optional[bool] = False
    flip_horizontal: Optional[bool] = False
    border_ratio: Optional[float] = 0.0
    watermark_enabled: Optional[bool] = False
    watermark_text: Optional[str] = ""
    watermark_opacity: Optional[float] = 0.012

class TaskCreateRequest(BaseModel):
    youtube_url: str
    skip_subtitles: Optional[bool] = False
    upload_targets: Optional[List[str]] = None
    secondary_creation: Optional[SecondaryCreationParams] = None

class SkipSubtitlesRequest(BaseModel):
    skip: Optional[bool] = True

class LoginRequest(BaseModel):
    password: str

class ConfigUpdateRequest(BaseModel):
    admin_password: Optional[str] = None
    llm_enabled: Optional[bool] = None
    llm_provider: Optional[str] = None
    llm_api_key: Optional[str] = None
    llm_base_url: Optional[str] = None
    llm_model: Optional[str] = None
    bilibili_sessdata: Optional[str] = None
    bilibili_bili_jct: Optional[str] = None
    bilibili_dedeuserid: Optional[str] = None
    cookiecloud_url: Optional[str] = None
    cookiecloud_uuid: Optional[str] = None
    cookiecloud_password: Optional[str] = None
    ffmpeg_preset: Optional[str] = None
    whisper_enabled: Optional[bool] = None
    whisper_api_key: Optional[str] = None
    whisper_base_url: Optional[str] = None
    whisper_model: Optional[str] = None
    youtube_cookies: Optional[str] = None
    auto_delete_after_upload: Optional[bool] = None
    skip_subtitles: Optional[bool] = None
    upload_targets: Optional[List[str]] = None
    youtube_upload_enabled: Optional[bool] = None
    youtube_client_id: Optional[str] = None
    youtube_client_secret: Optional[str] = None
    youtube_refresh_token: Optional[str] = None
    youtube_privacy_status: Optional[str] = None
    youtube_category_id: Optional[str] = None
    secondary_creation_enabled: Optional[bool] = None
    secondary_flip_horizontal: Optional[bool] = None
    secondary_border_ratio: Optional[float] = None
    secondary_watermark_enabled: Optional[bool] = None
    secondary_watermark_text: Optional[str] = None
    secondary_watermark_opacity: Optional[float] = None


from services.youtube import YouTubeService
from services.llm import LLMService


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if is_authenticated(request):
        return RedirectResponse(url="/")
    return templates.TemplateResponse(request=request, name="login.html")

@app.post("/api/auth/login")
async def login(req: LoginRequest):
    admin_pwd = config_manager.get("admin_password", "admin")
    if req.password == admin_pwd:
        token = _get_auth_token(admin_pwd)
        res = JSONResponse(content={"success": True, "message": "登录成功"})
        res.set_cookie(key=AUTH_COOKIE_NAME, value=token, httponly=True, max_age=86400 * 30, path="/")
        return res
    else:
        raise HTTPException(status_code=400, detail="管理员密码错误，请重试。")

@app.post("/api/auth/logout")
async def logout():
    res = JSONResponse(content={"success": True, "message": "已成功退出登录"})
    res.delete_cookie(key=AUTH_COOKIE_NAME, path="/")
    return res

@app.get("/", response_class=HTMLResponse)
async def read_index(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")


@app.post("/api/tasks")
async def create_task(req: TaskCreateRequest):
    input_text = req.youtube_url.strip()
    if not input_text:
        raise HTTPException(status_code=400, detail="YouTube URL cannot be empty.")
    
    items = YouTubeService.extract_items(input_text)
    if not items:
        raise HTTPException(status_code=400, detail="No valid YouTube URLs found in input.")
    
    sec_dict = req.secondary_creation.model_dump() if req.secondary_creation else None
    tasks = task_manager.create_batch_tasks(
        items,
        skip_subtitles=req.skip_subtitles or False,
        upload_targets=req.upload_targets,
        secondary_creation=sec_dict
    )
    return {
        "success": True,
        "count": len(tasks),
        "task": tasks[0].to_dict(),
        "tasks": [t.to_dict() for t in tasks]
    }

@app.get("/api/tasks")
async def list_tasks():
    return {"success": True, "tasks": task_manager.list_tasks()}

from fastapi.responses import HTMLResponse, JSONResponse, FileResponse

@app.get("/api/tasks/{task_id}")
async def get_task(task_id: str):
    task = task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found.")
    return {"success": True, "task": task.to_dict()}

@app.post("/api/tasks/{task_id}/stop")
async def stop_task(task_id: str):
    success = task_manager.stop_task(task_id)
    if not success:
        raise HTTPException(status_code=404, detail="Task not found.")
    return {"success": True, "message": "Task stopped."}

@app.post("/api/tasks/{task_id}/start")
async def start_task(task_id: str):
    task = task_manager.start_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found.")
    return {"success": True, "task": task.to_dict(), "message": "Task started."}

@app.post("/api/tasks/{task_id}/skip_subtitles")
async def toggle_skip_subtitles(task_id: str, req: Optional[SkipSubtitlesRequest] = None):
    skip_val = req.skip if req else True
    task = task_manager.toggle_skip_subtitles(task_id, skip_val)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found.")
    return {"success": True, "task": task.to_dict()}

@app.post("/api/tasks/{task_id}/cancel")
async def cancel_task(task_id: str):
    success = task_manager.cancel_task(task_id)
    if not success:
        raise HTTPException(status_code=404, detail="Task not found.")
    return {"success": True, "message": "Task cancelled."}

@app.post("/api/tasks/{task_id}/retry")
async def retry_task(task_id: str):
    task = task_manager.retry_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found.")
    return {"success": True, "task": task.to_dict(), "message": "Task re-queued."}

@app.delete("/api/tasks/{task_id}")
async def delete_task(task_id: str):
    success = task_manager.delete_task(task_id)
    if not success:
        raise HTTPException(status_code=404, detail="Task not found.")
    return {"success": True, "message": "Task deleted."}

@app.get("/api/tasks/{task_id}/stream")
async def stream_task_video(task_id: str):
    task = task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found.")
    
    video_path = None
    if task.processed_video_path and Path(task.processed_video_path).exists():
        video_path = Path(task.processed_video_path)
    else:
        # Search task download directory for any video
        cfg = config_manager.all()
        downloads_dir = Path(cfg.get("downloads_dir", "./downloads")) / task_id
        if downloads_dir.exists():
            for f in downloads_dir.iterdir():
                if f.suffix in [".mp4", ".mkv", ".webm"]:
                    video_path = f
                    break
    
    if not video_path or not video_path.exists():
        raise HTTPException(status_code=404, detail="Processed video file not available yet.")

    return FileResponse(path=str(video_path), media_type="video/mp4", filename=video_path.name)


@app.get("/api/config")
async def get_config():
    cfg = config_manager.all()
    safe_cfg = cfg.copy()
    raw_llm_key = str(safe_cfg.get("llm_api_key") or "").strip()
    safe_cfg["has_llm_api_key"] = bool(raw_llm_key)
    safe_cfg["llm_api_key_masked"] = raw_llm_key[:4] + "...." + raw_llm_key[-4:] if len(raw_llm_key) > 8 else ("****" if raw_llm_key else "")
    safe_cfg["llm_api_key"] = ""

    raw_yt_secret = str(safe_cfg.get("youtube_client_secret") or "").strip()
    safe_cfg["has_youtube_client_secret"] = bool(raw_yt_secret)
    safe_cfg["youtube_client_secret_masked"] = raw_yt_secret[:3] + "...." + raw_yt_secret[-3:] if len(raw_yt_secret) > 6 else ("****" if raw_yt_secret else "")
    safe_cfg["youtube_client_secret"] = ""

    raw_yt_token = str(safe_cfg.get("youtube_refresh_token") or "").strip()
    safe_cfg["has_youtube_refresh_token"] = bool(raw_yt_token)
    safe_cfg["youtube_refresh_token_masked"] = raw_yt_token[:4] + "...." + raw_yt_token[-4:] if len(raw_yt_token) > 8 else ("****" if raw_yt_token else "")
    safe_cfg["youtube_refresh_token"] = ""
    return {"success": True, "config": safe_cfg}

@app.post("/api/config")
async def update_config(req: ConfigUpdateRequest):
    update_data = {k: v for k, v in req.model_dump().items() if v is not None}
    
    current_key = str(config_manager.get("llm_api_key", "") or "").strip()
    if "llm_api_key" in update_data:
        new_key = str(update_data["llm_api_key"]).strip()
        if ("...." in new_key or "****" in new_key or not new_key) and current_key:
            update_data.pop("llm_api_key")
        else:
            update_data["llm_api_key"] = new_key

    current_yt_secret = str(config_manager.get("youtube_client_secret", "") or "").strip()
    if "youtube_client_secret" in update_data:
        new_secret = str(update_data["youtube_client_secret"]).strip()
        if ("...." in new_secret or "****" in new_secret or not new_secret) and current_yt_secret:
            update_data.pop("youtube_client_secret")
        else:
            update_data["youtube_client_secret"] = new_secret

    current_yt_token = str(config_manager.get("youtube_refresh_token", "") or "").strip()
    if "youtube_refresh_token" in update_data:
        new_token = str(update_data["youtube_refresh_token"]).strip()
        if ("...." in new_token or "****" in new_token or not new_token) and current_yt_token:
            update_data.pop("youtube_refresh_token")
        else:
            update_data["youtube_refresh_token"] = new_token

    config_manager.update(update_data)
    
    safe_cfg = config_manager.all()
    raw_llm_key = str(safe_cfg.get("llm_api_key") or "").strip()
    safe_cfg["has_llm_api_key"] = bool(raw_llm_key)
    safe_cfg["llm_api_key_masked"] = raw_llm_key[:4] + "...." + raw_llm_key[-4:] if len(raw_llm_key) > 8 else ("****" if raw_llm_key else "")
    safe_cfg["llm_api_key"] = ""
    return {"success": True, "config": safe_cfg}

class CookieCloudSyncRequest(BaseModel):
    cookiecloud_url: Optional[str] = None
    cookiecloud_uuid: Optional[str] = None
    cookiecloud_password: Optional[str] = None

@app.post("/api/cookiecloud/sync")
async def sync_cookiecloud(req: Optional[CookieCloudSyncRequest] = None):
    cfg = config_manager.all()
    url = (req and req.cookiecloud_url) or cfg.get("cookiecloud_url")
    uuid = (req and req.cookiecloud_uuid) or cfg.get("cookiecloud_uuid")
    password = (req and req.cookiecloud_password) or cfg.get("cookiecloud_password")

    if not url or not uuid or not password:
        raise HTTPException(status_code=400, detail="请先在设置中填写 CookieCloud 服务器地址、UUID 及 密码。")

    try:
        service = CookieCloudService(url, uuid, password)
        bili_cookies, yt_netscape = service.fetch_all_synced_cookies()
        if not bili_cookies and not yt_netscape:
            return {"success": False, "message": "未在 CookieCloud 中查找到 Bilibili 或 YouTube 的登录 Cookie。"}
        
        update_dict = {
            "cookiecloud_url": url,
            "cookiecloud_uuid": uuid,
            "cookiecloud_password": password,
        }
        if bili_cookies:
            update_dict["bilibili_sessdata"] = bili_cookies.get("SESSDATA", cfg.get("bilibili_sessdata"))
            update_dict["bilibili_bili_jct"] = bili_cookies.get("bili_jct", cfg.get("bilibili_bili_jct"))
            update_dict["bilibili_dedeuserid"] = bili_cookies.get("DedeUserID", cfg.get("bilibili_dedeuserid"))
        if yt_netscape:
            update_dict["youtube_cookies"] = yt_netscape

        config_manager.update(update_dict)

        msg_parts = []
        if bili_cookies:
            msg_parts.append("Bilibili 登录 Cookie")
        if yt_netscape:
            msg_parts.append("YouTube Netscape Cookie")
        msg_str = " 及 ".join(msg_parts)

        return {"success": True, "cookies": bili_cookies, "youtube_cookies": yt_netscape, "message": f"CookieCloud 同步成功！已自动填入最新的 {msg_str}。"}

    except Exception as e:
        logger.error(f"CookieCloud sync error: {e}")
        raise HTTPException(status_code=500, detail=str(e))



class LLMModelsRequest(BaseModel):
    llm_provider: Optional[str] = None
    llm_api_key: Optional[str] = None
    llm_base_url: Optional[str] = None

class LLMTestRequest(BaseModel):
    llm_provider: Optional[str] = None
    llm_api_key: Optional[str] = None
    llm_base_url: Optional[str] = None
    llm_model: Optional[str] = None

@app.post("/api/llm/models")
async def get_llm_models(req: LLMModelsRequest):
    cfg = config_manager.all()
    api_key = (req.llm_api_key or "").strip() or cfg.get("llm_api_key", "")
    base_url = (req.llm_base_url or "").strip() or cfg.get("llm_base_url", "https://api.openai.com/v1")
    
    if not api_key:
        raise HTTPException(status_code=400, detail="请先输入 LLM API Key。")

    try:
        models = LLMService.fetch_models(api_key, base_url)
        return {"success": True, "models": models, "count": len(models)}
    except Exception as e:
        logger.error(f"Error fetching LLM models: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/llm/test")
async def test_llm_model(req: LLMTestRequest):
    cfg = config_manager.all()
    api_key = (req.llm_api_key or "").strip() or cfg.get("llm_api_key", "")
    base_url = (req.llm_base_url or "").strip() or cfg.get("llm_base_url", "https://api.openai.com/v1")
    model = (req.llm_model or "").strip() or cfg.get("llm_model", "gpt-4o-mini")
    
    if not api_key:
        raise HTTPException(status_code=400, detail="请先输入 LLM API Key。")

    try:
        result = LLMService.test_connection(api_key, base_url, model)
        return {
            "success": True,
            "result": result,
            "message": f"连接成功！延迟: {result['latency_ms']}ms，模型: {result['model']}，响应: '{result['reply']}'"
        }
    except Exception as e:
        logger.error(f"Error testing LLM model: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/bilibili/check")
async def check_bilibili():
    cfg = config_manager.all()
    bili_service = BilibiliService(
        sessdata=cfg.get("bilibili_sessdata", ""),
        bili_jct=cfg.get("bilibili_bili_jct", ""),
        dedeuserid=cfg.get("bilibili_dedeuserid", "")
    )
    result = bili_service.validate_credentials()
    return {"success": True, "result": result}


class YouTubeAuthUrlRequest(BaseModel):
    client_id: Optional[str] = None
    redirect_uri: Optional[str] = None

class YouTubeOAuthCallbackRequest(BaseModel):
    code: str
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    redirect_uri: Optional[str] = None

class YouTubeTestRequest(BaseModel):
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    refresh_token: Optional[str] = None

@app.post("/api/youtube/auth-url")
async def get_youtube_auth_url(req: Optional[YouTubeAuthUrlRequest] = None):
    cfg = config_manager.all()
    client_id = (req and req.client_id) or cfg.get("youtube_client_id", "")
    redirect_uri = (req and req.redirect_uri) or "http://localhost:8166/oauth2callback"
    if not client_id:
        raise HTTPException(status_code=400, detail="请先在设置中填写 YouTube Client ID。")
    
    url = YouTubeUploaderService.generate_auth_url(client_id, redirect_uri)
    return {"success": True, "auth_url": url}

@app.post("/api/youtube/oauth-callback")
async def handle_youtube_oauth_callback(req: YouTubeOAuthCallbackRequest):
    cfg = config_manager.all()
    client_id = req.client_id or cfg.get("youtube_client_id", "")
    client_secret = req.client_secret or cfg.get("youtube_client_secret", "")
    redirect_uri = req.redirect_uri or "http://localhost:8166/oauth2callback"

    if not client_id or not client_secret:
        raise HTTPException(status_code=400, detail="缺少 YouTube Client ID 或 Client Secret。")
    if not req.code:
        raise HTTPException(status_code=400, detail="缺少授权 Code。")

    try:
        token_data = YouTubeUploaderService.exchange_code_for_tokens(
            client_id=client_id,
            client_secret=client_secret,
            code=req.code,
            redirect_uri=redirect_uri
        )
        refresh_token = token_data.get("refresh_token")
        if refresh_token:
            config_manager.update({"youtube_refresh_token": refresh_token})
        return {
            "success": True,
            "has_refresh_token": bool(refresh_token),
            "message": "YouTube OAuth2 授权成功并已保存 Refresh Token！"
        }
    except Exception as e:
        logger.error(f"YouTube OAuth callback exchange error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/youtube/test")
async def test_youtube_api(req: Optional[YouTubeTestRequest] = None):
    cfg = config_manager.all()
    client_id = (req and req.client_id) or cfg.get("youtube_client_id", "")
    client_secret = (req and req.client_secret) or cfg.get("youtube_client_secret", "")
    refresh_token = (req and req.refresh_token) or cfg.get("youtube_refresh_token", "")

    if not client_id or not client_secret or not refresh_token:
        raise HTTPException(status_code=400, detail="请先在设置中填写 YouTube Client ID、Client Secret 并完成授权获取 Refresh Token。")

    try:
        uploader = YouTubeUploaderService(
            client_id=client_id,
            client_secret=client_secret,
            refresh_token=refresh_token
        )
        ch_info = uploader.get_channel_info()
        return {
            "success": True,
            "channel": ch_info,
            "message": f"YouTube API 连接成功！频道: {ch_info.get('title')} ({ch_info.get('custom_url')})，订阅量: {ch_info.get('subscriber_count')}"
        }
    except Exception as e:
        logger.error(f"YouTube API test error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8166, reload=True)

