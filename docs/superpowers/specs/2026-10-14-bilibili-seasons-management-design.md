# Bilibili 视频合集管理与自动归集技术设计方案

## 1. 概述与需求背景

在当前 `youtobi` 搬运流水线中，所有视频在发布到 B站 后均为独立稿件。对于连续剧集、分季节目或系列教程，用户希望：
1. **自动归集为合集**：默认转发上传的视频会自动创建或归入对应合集，方便在 B站 形成连贯的播放列表。
2. **后期指定已有合集**：当隔段时间更新后续季或新集数时，可以在创建任务时自由选择已有合集进行追加，或者指定新建合集。
3. **合集管理面板**：在 Web 前端增加「合集管理」功能，能够实时查看 B站 账号现有的全部合集信息，并支持手动快速创建新合集。

---

## 2. 系统架构与接口规范

### 2.1 Bilibili 服务层 (`services/bilibili.py`)

在 `BilibiliService` 中新增合集管理操作：

1. **`list_seasons(pn: int = 1, ps: int = 50) -> Dict[str, Any]`**：
   - 优先调用创作中心接口：
     - `GET https://member.bilibili.com/x2/creative/web/seasons?pn={pn}&ps={ps}&order=mtime&sort=desc&draft=1`
     - 携带 CookieCloud 完整 Cookies（包含 `SESSDATA`, `bili_jct`, `DedeUserID`, `buvid3/4`, `DedeUserID__ckMd5` 等）。
   - 备用容灾机制：若创作中心接口受限或返回异常，自动回退调用 `bilibili_api.user.User(mid).get_channel_list()`（基于 WBI 签名验证）。
   - 返回统一结构：
     ```json
     {
       "seasons": [
         {
           "id": 9036206,
           "title": "暴雨甄嬛",
           "cover": "https://...",
           "ep_count": 2,
           "section_id": 10086287,
           "mtime": 1788765653
         }
       ],
       "total": 1
     }
     ```

2. **`create_season(title: str, desc: str = "", cover: str = "") -> Dict[str, Any]`**：
   - 调用 `POST https://member.bilibili.com/x2/creative/web/season/add?csrf={self.bili_jct}`
   - Form Data 参数：`title`, `desc`, `cover`, `csrf`
   - 返回新建合集的 `season_id` 和对应默认分节 `section_id`。

3. **`add_to_season(season_id: int, bvid: str, section_id: Optional[int] = None) -> Dict[str, Any]`**：
   - 首先通过 `GET https://api.bilibili.com/x/web-interface/view?bvid={bvid}` 获取稿件的 `aid`、`cid` 和 `title`。
   - 若未提供 `section_id`，自动通过 `list_seasons` 或 `get_season_section` 检索该合集的默认主分节 ID（如“正片”分节）。
   - 调用 `POST https://member.bilibili.com/x2/creative/web/season/section/episodes/add?csrf={self.bili_jct}`
   - JSON 负载：
     ```json
     {
       "sectionId": 10086287,
       "episodes": [
         {
           "aid": 117228531944645,
           "cid": 1234567,
           "title": "剧集分集标题",
           "charging_pay": 0
         }
       ],
       "csrf": "..."
     }
     ```

---

### 2.2 任务数据结构与流水线改造 (`services/task_manager.py`)

#### 1. `Task` 模型字段扩展
```python
task.bilibili_season_mode: str = "create"  # "create" (默认新建/智能复用) | "existing" (加入指定合集) | "none" (不加入合集)
task.bilibili_season_id: Optional[int] = None      # 指定已有合集的 season_id
task.bilibili_season_name: Optional[str] = None    # 自定义合集标题
```

#### 2. 流水线阶段与自动归集
- 任务进入 `bilibili_upload` 发布成功并取得 `bvid` 后：
  - 若 `bilibili_season_mode == "create"`：
    - 智能获取合集名称：优先使用 `task.bilibili_season_name`；若未显式指定，使用根据视频标题智能清洗后的剧集系列名（去除 `EP01` 等剧集后缀）或 YouTube Playlist 名称。
    - 校验已有合集：查询 `list_seasons`，如果已存在同名合集，直接复用该合集；如果不存在，调用 `create_season` 动态新建合集。
    - 调用 `add_to_season` 将刚发布的 `bvid` 添加进该合集。
    - 记录任务日志：`"✓ 视频已成功加入B站合集：《{season_title}》 (ID: {season_id})"`。
  - 若 `bilibili_season_mode == "existing"`：
    - 验证 `bilibili_season_id` 有效性。
    - 调用 `add_to_season` 归入该合集。
    - 记录任务日志：`"✓ 视频已成功加入已有合集：《{season_title}》 (ID: {season_id})"`。
  - 若 `bilibili_season_mode == "none"`：
    - 跳过合集归集步骤。

---

### 2.3 Web API 接口扩展 (`app.py`)

1. **`GET /api/bilibili/seasons`**
   - 查询当前已登录 B 站账号的所有视频合集。
   - 支持 `?refresh=true` 强制穿透缓存向 B站 实时拉取最新合集。
   - 返回标准 JSON 结构。

2. **`POST /api/bilibili/seasons`**
   - 请求体：`{"title": "新合集名称", "description": ""}`
   - 在 B站 账号下直接新建一个合集。

3. **`POST /api/tasks` 接收扩展参数**
   - 在请求体 `TaskCreateRequest` 中新增：
     - `bilibili_season_mode`: `Optional[str] = "create"`
     - `bilibili_season_id`: `Optional[int] = None`
     - `bilibili_season_name`: `Optional[str] = None`

---

### 2.4 Web 前端交互实现 (`templates/index.html` & `static/js/app.js`)

1. **新建任务表单区「B站合集设置」**：
   - 增加独立配置卡片，仅在发布目标包含 `bilibili` 时激活：
     - 单选按钮项 1：`[🔘 默认新建合集]`，显示合集名称文本输入框（智能占位提示）。
     - 单选按钮项 2：`[🔘 加入已有合集]`，显示合集下拉选择列表（自动显示如《暴雨甄嬛 (2集)》），附带「🔄 刷新合集」小按钮。
     - 单选按钮项 3：`[🔘 不加入合集]`。
2. **顶部导航栏「合集管理」**：
   - 增加「合集管理」模态窗口：
     - 卡片式展示当前账号下所有合集封面、名称、视频数、最后更新时间、跳转查看外链。
     - 提供「新建合集」按钮，支持输入合集标题一键创建。

---

## 3. 错误处理与容灾保障

1. **合集接口调用失败不中断主发布状态**：
   - 如果视频已成功发布至 B站（获得 `bvid`），但因合集权限限制（如电磁力等级限制、合集已满）导致添加合集失败，流水线应捕获此异常并记录警告日志，**保留视频发布成功的 COMPLETED 状态**，并在日志中明确提示失败原因。
2. **同名合集防重复创建**：
   - 当任务配置为「新建合集」时，系统先检索当前合集列表，若已有同名合集，自动转为「追加至同名已有合集」，避免重复建同名垃圾合集。
