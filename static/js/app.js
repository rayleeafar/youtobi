let activePollInterval = null;
let hostStatsTimer = null;
let hostStatsKickoff = null;
let hostStatsPrev = null;
const HOST_STATS_INTERVAL_MS = 15000;

document.addEventListener('DOMContentLoaded', () => {
  loadConfig();
  loadTasks();
  activePollInterval = setInterval(loadTasks, 3000);
  refreshHostStats();
  // Second sample shortly after load so bandwidth has a delta before the 15s cadence.
  hostStatsKickoff = setTimeout(refreshHostStats, 1500);
  hostStatsTimer = setInterval(refreshHostStats, HOST_STATS_INTERVAL_MS);
});

window.addEventListener('pagehide', () => {
  if (activePollInterval) clearInterval(activePollInterval);
  if (hostStatsTimer) clearInterval(hostStatsTimer);
  if (hostStatsKickoff) clearTimeout(hostStatsKickoff);
});

function formatBytes(n) {
  if (n == null || !Number.isFinite(n)) return '—';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let value = n;
  let i = 0;
  while (value >= 1024 && i < units.length - 1) {
    value /= 1024;
    i += 1;
  }
  return (i === 0 ? value.toFixed(0) : value.toFixed(1)) + ' ' + units[i];
}

function formatRate(bytesPerSec) {
  if (bytesPerSec == null || !Number.isFinite(bytesPerSec) || bytesPerSec < 0) return '—';
  const bits = bytesPerSec * 8;
  if (bits >= 1e6) return (bits / 1e6).toFixed(bits >= 1e7 ? 0 : 1) + ' Mbps';
  if (bytesPerSec >= 1024) return (bytesPerSec / 1024).toFixed(1) + ' KB/s';
  return bytesPerSec.toFixed(0) + ' B/s';
}

function formatUptime(seconds) {
  const sec = Math.max(0, Math.floor(seconds || 0));
  const days = Math.floor(sec / 86400);
  const hours = Math.floor((sec % 86400) / 3600);
  const mins = Math.floor((sec % 3600) / 60);
  if (days > 0) return `已运行 ${days}天 ${hours}小时`;
  if (hours > 0) return `已运行 ${hours}小时 ${mins}分`;
  return `已运行 ${mins}分`;
}

function meterLevel(percent) {
  if (percent >= 90) return 'hot';
  if (percent >= 70) return 'warn';
  return 'ok';
}

function setMeter(meterId, barId, valId, subId, percent, subText) {
  const meter = document.getElementById(meterId);
  const bar = document.getElementById(barId);
  const val = document.getElementById(valId);
  const sub = document.getElementById(subId);
  const clamped = Math.max(0, Math.min(100, percent));
  if (meter) meter.dataset.level = meterLevel(clamped);
  if (bar) bar.style.width = clamped + '%';
  if (val) val.textContent = clamped.toFixed(0) + '%';
  if (sub) sub.textContent = subText;
}

function countryFlag(code) {
  if (!code || !/^[a-zA-Z]{2}$/.test(code)) return '';
  const base = 0x1F1E6;
  const upper = code.toUpperCase();
  return String.fromCodePoint(base + upper.charCodeAt(0) - 65, base + upper.charCodeAt(1) - 65);
}

function renderHostStats(data) {
  const banner = document.getElementById('hostBanner');
  if (banner) {
    banner.classList.remove('is-error');
    banner.setAttribute('aria-busy', 'false');
  }
  const flagEl = document.getElementById('hostFlag');
  const flag = countryFlag(data.country);
  if (flagEl) {
    flagEl.textContent = flag;
    flagEl.hidden = !flag;
    flagEl.title = data.country || '';
  }
  const identity = document.getElementById('hostIdentity');
  if (identity) {
    identity.textContent = `${data.hostname} · ${data.ip || '—'}`;
  }
  const uptime = document.getElementById('hostUptime');
  if (uptime) uptime.textContent = formatUptime(data.uptime_seconds);

  const load = data.load_avg && data.load_avg.length ? `负载 ${data.load_avg[0]}` : '';
  const cores = data.cpu_count ? `${data.cpu_count} 核` : '';
  setMeter('hostCpuMeter', 'hostCpuBar', 'hostCpuVal', 'hostCpuSub', data.cpu_percent, [cores, load].filter(Boolean).join(' · '));
  setMeter(
    'hostMemMeter', 'hostMemBar', 'hostMemVal', 'hostMemSub',
    data.memory.percent,
    `${formatBytes(data.memory.used)} / ${formatBytes(data.memory.total)}`
  );
  setMeter(
    'hostDiskMeter', 'hostDiskBar', 'hostDiskVal', 'hostDiskSub',
    data.disk.percent,
    `${formatBytes(data.disk.used)} / ${formatBytes(data.disk.total)}`
  );

  let down = null;
  let up = null;
  if (hostStatsPrev && data.net && hostStatsPrev.net) {
    const dt = data.sampled_at - hostStatsPrev.sampled_at;
    if (dt > 0.2) {
      const recv = (data.net.bytes_recv - hostStatsPrev.net.bytes_recv) / dt;
      const sent = (data.net.bytes_sent - hostStatsPrev.net.bytes_sent) / dt;
      if (recv >= 0 && sent >= 0) {
        down = recv;
        up = sent;
      }
    }
  }
  const downEl = document.getElementById('hostNetDown');
  const upEl = document.getElementById('hostNetUp');
  if (downEl) downEl.textContent = down == null ? '↓ 采样中' : `↓ ${formatRate(down)}`;
  if (upEl) upEl.textContent = up == null ? '↑ 采样中' : `↑ ${formatRate(up)}`;

  const updated = document.getElementById('hostUpdated');
  if (updated) {
    const stamp = new Date((data.sampled_at || Date.now() / 1000) * 1000);
    updated.textContent = stamp.toLocaleTimeString();
  }
  hostStatsPrev = data;
}

async function refreshHostStats() {
  const banner = document.getElementById('hostBanner');
  if (!banner) return;
  try {
    const res = await fetch('/api/system/stats');
    if (!res.ok) throw new Error('stats unavailable');
    renderHostStats(await res.json());
  } catch (err) {
    banner.classList.add('is-error');
    banner.setAttribute('aria-busy', 'false');
    const updated = document.getElementById('hostUpdated');
    if (updated) updated.textContent = '更新失败';
    if (!hostStatsPrev) {
      const identity = document.getElementById('hostIdentity');
      if (identity) identity.textContent = '主机状态暂不可用';
    }
  }
}

function openSettingsModal() {
  document.getElementById('settingsModal').classList.add('active');
  loadConfig();
}

function closeSettingsModal() {
  document.getElementById('settingsModal').classList.remove('active');
}

function openPreviewModal(taskId, title) {
  const modal = document.getElementById('previewModal');
  const video = document.getElementById('previewVideo');
  const titleEl = document.getElementById('previewTitle');

  titleEl.innerText = `🎬 视频预览 - ${title || taskId}`;
  video.src = `/api/tasks/${taskId}/stream`;
  modal.classList.add('active');
  video.play().catch(e => console.log('Auto-play blocked:', e));
}

function closePreviewModal() {
  const modal = document.getElementById('previewModal');
  const video = document.getElementById('previewVideo');
  video.pause();
  video.src = '';
  modal.classList.remove('active');
}

async function loadConfig() {
  try {
    const res = await fetch('/api/config');
    const data = await res.json();
    if (data.success) {
      const cfg = data.config;
      document.getElementById('llm_enabled').checked = cfg.llm_enabled || false;
      document.getElementById('llm_provider').value = cfg.llm_provider || 'openai';
      document.getElementById('llm_model').value = cfg.llm_model || 'gpt-4o-mini';
      const apiKeyInput = document.getElementById('llm_api_key');
      if (cfg.has_llm_api_key) {
        apiKeyInput.placeholder = `已配置 (${cfg.llm_api_key_masked}) - 如需修改请输入新 Key`;
        apiKeyInput.value = '';
      } else {
        apiKeyInput.placeholder = 'sk-...';
        apiKeyInput.value = '';
      }
      document.getElementById('llm_base_url').value = cfg.llm_base_url || 'https://api.openai.com/v1';

      document.getElementById('whisper_enabled').checked = cfg.whisper_enabled !== undefined ? cfg.whisper_enabled : true;
      document.getElementById('skip_subtitles').checked = cfg.skip_subtitles || false;
      const formSkip = document.getElementById('skip_subtitles_form');
      if (formSkip) formSkip.checked = cfg.skip_subtitles || false;
      document.getElementById('whisper_model').value = cfg.whisper_model || 'whisper-1';
      document.getElementById('ffmpeg_preset').value = cfg.ffmpeg_preset || 'fast';
      document.getElementById('youtube_cookies').value = cfg.youtube_cookies || '';

      if (cfg.bilibili_sessdata) document.getElementById('bilibili_sessdata').value = cfg.bilibili_sessdata;
      if (cfg.bilibili_bili_jct) document.getElementById('bilibili_bili_jct').value = cfg.bilibili_bili_jct;
      if (cfg.bilibili_dedeuserid) document.getElementById('bilibili_dedeuserid').value = cfg.bilibili_dedeuserid;

      // YouTube Upload Settings
      if (document.getElementById('youtube_upload_enabled')) {
        document.getElementById('youtube_upload_enabled').checked = cfg.youtube_upload_enabled || false;
        document.getElementById('youtube_client_id').value = cfg.youtube_client_id || '';
        document.getElementById('youtube_privacy_status').value = cfg.youtube_privacy_status || 'unlisted';
        const catId = cfg.youtube_category_id || '22';
        document.getElementById('youtube_category_id').value = catId;
        onYouTubeCategoryInput(catId);

        const ytSecretInput = document.getElementById('youtube_client_secret');
        if (cfg.has_youtube_client_secret) {
          ytSecretInput.placeholder = `已配置 (${cfg.youtube_client_secret_masked}) - 如需修改请输入`;
          ytSecretInput.value = '';
        } else {
          ytSecretInput.placeholder = 'GOCSPX-...';
          ytSecretInput.value = '';
        }

        const ytTokenInput = document.getElementById('youtube_refresh_token');
        if (cfg.has_youtube_refresh_token) {
          ytTokenInput.placeholder = `已授权 (${cfg.youtube_refresh_token_masked}) - 如需重设可重新授权`;
          ytTokenInput.value = '';
        } else {
          ytTokenInput.placeholder = '点击下方授权获取，或手动填入 Refresh Token';
          ytTokenInput.value = '';
        }
      }

      // Secondary Creation Global Defaults
      if (document.getElementById('cfg_secondary_flip_horizontal')) {
        document.getElementById('cfg_secondary_flip_horizontal').checked = cfg.secondary_flip_horizontal || false;
        document.getElementById('cfg_secondary_border_ratio').value = cfg.secondary_border_ratio !== undefined ? cfg.secondary_border_ratio : 0.0;
        document.getElementById('cfg_secondary_watermark_enabled').checked = cfg.secondary_watermark_enabled || false;
        document.getElementById('cfg_secondary_watermark_text').value = cfg.secondary_watermark_text || '';
        document.getElementById('cfg_secondary_watermark_opacity').value = cfg.secondary_watermark_opacity !== undefined ? cfg.secondary_watermark_opacity : 0.012;
      }

      // Initial task form values (from defaults)
      if (!window.__formInitialized) {
        window.__formInitialized = true;
        if (cfg.upload_targets && document.getElementById('target_bilibili')) {
          document.getElementById('target_bilibili').checked = cfg.upload_targets.includes('bilibili');
          document.getElementById('target_youtube').checked = cfg.upload_targets.includes('youtube');
        }
        if (document.getElementById('sec_flip_horizontal')) {
          document.getElementById('sec_flip_horizontal').checked = cfg.secondary_flip_horizontal || false;
          document.getElementById('sec_border_ratio').value = cfg.secondary_border_ratio || 0;
          document.getElementById('sec_border_ratio_val').innerText = Math.round((cfg.secondary_border_ratio || 0) * 100) + '%';
          document.getElementById('sec_watermark_enabled').checked = cfg.secondary_watermark_enabled || false;
          document.getElementById('sec_watermark_text').value = cfg.secondary_watermark_text || '';
        }
      }

      document.getElementById('cookiecloud_url').value = cfg.cookiecloud_url || '';
      document.getElementById('cookiecloud_uuid').value = cfg.cookiecloud_uuid || '';
      if (cfg.cookiecloud_password) document.getElementById('cookiecloud_password').value = cfg.cookiecloud_password;
    }
  } catch (err) {
    console.error('Error loading config:', err);
  }
}

async function handleLogout() {
  if (confirm('确定要退出登录吗？')) {
    try {
      await fetch('/api/auth/logout', { method: 'POST' });
    } catch (e) {}
    window.location.href = '/login';
  }
}

async function handleConfigSave(event) {
  event.preventDefault();
  const payload = {
    llm_enabled: document.getElementById('llm_enabled').checked,
    llm_provider: document.getElementById('llm_provider').value,
    llm_model: document.getElementById('llm_model').value,
    llm_api_key: document.getElementById('llm_api_key').value,
    llm_base_url: document.getElementById('llm_base_url').value,
    whisper_enabled: document.getElementById('whisper_enabled').checked,
    skip_subtitles: document.getElementById('skip_subtitles').checked,
    whisper_model: document.getElementById('whisper_model').value,
    ffmpeg_preset: document.getElementById('ffmpeg_preset').value,
    youtube_cookies: document.getElementById('youtube_cookies').value,
    bilibili_sessdata: document.getElementById('bilibili_sessdata').value,
    bilibili_bili_jct: document.getElementById('bilibili_bili_jct').value,
    bilibili_dedeuserid: document.getElementById('bilibili_dedeuserid').value,
    youtube_upload_enabled: document.getElementById('youtube_upload_enabled') ? document.getElementById('youtube_upload_enabled').checked : false,
    youtube_client_id: document.getElementById('youtube_client_id') ? document.getElementById('youtube_client_id').value : '',
    youtube_client_secret: document.getElementById('youtube_client_secret') ? document.getElementById('youtube_client_secret').value : '',
    youtube_refresh_token: document.getElementById('youtube_refresh_token') ? document.getElementById('youtube_refresh_token').value : '',
    youtube_privacy_status: document.getElementById('youtube_privacy_status') ? document.getElementById('youtube_privacy_status').value : 'unlisted',
    youtube_category_id: document.getElementById('youtube_category_id') ? (document.getElementById('youtube_category_id').value.trim() || '22') : '22',
    secondary_flip_horizontal: document.getElementById('cfg_secondary_flip_horizontal') ? document.getElementById('cfg_secondary_flip_horizontal').checked : false,
    secondary_border_ratio: document.getElementById('cfg_secondary_border_ratio') ? parseFloat(document.getElementById('cfg_secondary_border_ratio').value || '0') : 0.0,
    secondary_watermark_enabled: document.getElementById('cfg_secondary_watermark_enabled') ? document.getElementById('cfg_secondary_watermark_enabled').checked : false,
    secondary_watermark_text: document.getElementById('cfg_secondary_watermark_text') ? document.getElementById('cfg_secondary_watermark_text').value : '',
    secondary_watermark_opacity: document.getElementById('cfg_secondary_watermark_opacity') ? parseFloat(document.getElementById('cfg_secondary_watermark_opacity').value || '0.012') : 0.012,
    cookiecloud_url: document.getElementById('cookiecloud_url').value,
    cookiecloud_uuid: document.getElementById('cookiecloud_uuid').value,
    cookiecloud_password: document.getElementById('cookiecloud_password').value,
  };

  const adminPwdInput = document.getElementById('admin_password');
  if (adminPwdInput && adminPwdInput.value.trim()) {
    payload.admin_password = adminPwdInput.value.trim();
  }

  try {
    const res = await fetch('/api/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    const data = await res.json();
    if (data.success) {
      alert('配置已成功保存！');
      closeSettingsModal();
    }
  } catch (err) {
    alert('保存配置出错: ' + err.message);
  }
}

async function handleFormSubmit(event) {
  event.preventDefault();
  const urlInput = document.getElementById('youtubeUrl');
  const url = urlInput.value.trim();
  if (!url) return;

  const skipForm = document.getElementById('skip_subtitles_form');
  const skipSubtitles = skipForm ? skipForm.checked : false;

  const targets = [];
  if (document.getElementById('target_bilibili') && document.getElementById('target_bilibili').checked) {
    targets.push('bilibili');
  }
  if (document.getElementById('target_youtube') && document.getElementById('target_youtube').checked) {
    targets.push('youtube');
  }
  if (targets.length === 0) {
    alert('请至少勾选一个发布目标平台 (Bilibili 或 YouTube)！');
    return;
  }

  const secFlip = document.getElementById('sec_flip_horizontal') ? document.getElementById('sec_flip_horizontal').checked : false;
  const secBorder = document.getElementById('sec_border_ratio') ? parseFloat(document.getElementById('sec_border_ratio').value || '0') : 0;
  const secWmEnabled = document.getElementById('sec_watermark_enabled') ? document.getElementById('sec_watermark_enabled').checked : false;
  const secWmText = document.getElementById('sec_watermark_text') ? document.getElementById('sec_watermark_text').value.trim() : '';
  const secEnabled = secFlip || (secBorder > 0.001) || (secWmEnabled && secWmText.length > 0);

  const secondaryCreation = {
    enabled: secEnabled,
    flip_horizontal: secFlip,
    border_ratio: secBorder,
    watermark_enabled: secWmEnabled,
    watermark_text: secWmText
  };

  const btn = document.getElementById('submitBtn');
  btn.disabled = true;
  btn.innerText = '提交中...';

  try {
    const res = await fetch('/api/tasks', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        youtube_url: url,
        skip_subtitles: skipSubtitles,
        upload_targets: targets,
        secondary_creation: secondaryCreation
      })
    });
    const data = await res.json();
    if (data.success) {
      urlInput.value = '';
      loadTasks();
    } else {
      alert('提交失败: ' + (data.detail || '未知错误'));
    }
  } catch (err) {
    alert('请求失败: ' + err.message);
  } finally {
    btn.disabled = false;
    btn.innerText = '开始处理并上传';
  }
}

async function stopTask(taskId) {
  try {
    const res = await fetch(`/api/tasks/${taskId}/stop`, { method: 'POST' });
    const data = await res.json();
    if (data.success) {
      loadTasks();
    } else {
      alert('停止/暂停失败: ' + (data.detail || '未知错误'));
    }
  } catch (err) {
    alert('停止任务出错: ' + err.message);
  }
}

async function startTask(taskId) {
  try {
    const res = await fetch(`/api/tasks/${taskId}/start`, { method: 'POST' });
    const data = await res.json();
    if (data.success) {
      loadTasks();
    } else {
      alert('启动失败: ' + (data.detail || '未知错误'));
    }
  } catch (err) {
    alert('启动任务出错: ' + err.message);
  }
}

async function toggleTaskSkipSubtitles(taskId, skipVal) {
  try {
    const res = await fetch(`/api/tasks/${taskId}/skip_subtitles`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ skip: skipVal })
    });
    const data = await res.json();
    if (data.success) {
      loadTasks();
    } else {
      alert('设置字幕选项失败: ' + (data.detail || '未知错误'));
    }
  } catch (err) {
    alert('请求出错: ' + err.message);
  }
}

async function cancelTask(taskId) {
  try {
    const res = await fetch(`/api/tasks/${taskId}/cancel`, { method: 'POST' });
    const data = await res.json();
    if (data.success) {
      loadTasks();
    } else {
      alert('取消失败: ' + (data.detail || '未知错误'));
    }
  } catch (err) {
    alert('取消任务出错: ' + err.message);
  }
}

async function retryTask(taskId) {
  try {
    const res = await fetch(`/api/tasks/${taskId}/retry`, { method: 'POST' });
    const data = await res.json();
    if (data.success) {
      loadTasks();
    } else {
      alert('重试失败: ' + (data.detail || '未知错误'));
    }
  } catch (err) {
    alert('重试任务出错: ' + err.message);
  }
}

async function deleteTask(taskId) {
  if (!confirm(`确定要删除任务 TASK #${taskId} 及其临时文件吗？`)) return;
  try {
    const res = await fetch(`/api/tasks/${taskId}`, { method: 'DELETE' });
    const data = await res.json();
    if (data.success) {
      loadTasks();
    } else {
      alert('删除失败: ' + (data.detail || '未知错误'));
    }
  } catch (err) {
    alert('删除任务出错: ' + err.message);
  }
}

async function loadTasks() {
  try {
    const res = await fetch('/api/tasks');
    const data = await res.json();
    if (!data.success) return;

    const container = document.getElementById('taskList');
    if (!data.tasks || data.tasks.length === 0) {
      container.innerHTML = `
        <div class="task-card" style="text-align: center; color: var(--text-muted); padding: 3rem;">
          暂无活动任务，请在上方输入 YouTube 视频或播放列表链接开始。
        </div>`;
      return;
    }

    // Preserve scroll positions of log terminals
    const scrollStates = {};
    container.querySelectorAll('.log-terminal[data-task-id]').forEach(el => {
      const taskId = el.getAttribute('data-task-id');
      const isAtBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 30;
      scrollStates[taskId] = {
        scrollTop: el.scrollTop,
        isAtBottom: isAtBottom
      };
    });

    container.innerHTML = data.tasks.map(task => renderTaskCard(task)).join('');

    // Restore scroll position or auto-scroll to bottom
    container.querySelectorAll('.log-terminal[data-task-id]').forEach(el => {
      const taskId = el.getAttribute('data-task-id');
      const saved = scrollStates[taskId];
      if (saved) {
        if (saved.isAtBottom) {
          el.scrollTop = el.scrollHeight;
        } else {
          el.scrollTop = saved.scrollTop;
        }
      } else {
        el.scrollTop = el.scrollHeight;
      }
    });
  } catch (err) {
    console.error('Error loading tasks:', err);
  }
}

function renderTaskCard(task) {
  const statusLabels = {
    'PENDING': '等待处理',
    'DOWNLOADING': '下载视频中',
    'SUBTITLE_PROCESSING': '字幕与视频处理',
    'LLM_REGENERATION': 'AI简介生成中',
    'UPLOADING': '上传至目标平台',
    'COMPLETED': '已完成发布',
    'FAILED': '处理失败',
    'PAUSED': '已暂停/停止',
    'CANCELLED': '已取消'
  };

  const stageLabels = {
    cookie_sync: '同步 Cookie',
    metadata: '读取元数据',
    download: '下载视频',
    subtitles: '字幕',
    edit: '剪辑/烧录',
    llm: 'AI 简介',
    bilibili_upload: '上传 B站',
    youtube_upload: '上传 YouTube',
    done: '已完成'
  };
  const logsHtml = (task.logs || []).map(l => `<div class="log-entry">${escapeHtml(l)}</div>`).join('');
  const isRunning = ['PENDING', 'DOWNLOADING', 'SUBTITLE_PROCESSING', 'LLM_REGENERATION', 'UPLOADING'].includes(task.status);
  const isStopped = ['PAUSED', 'STOPPED', 'CANCELLED', 'FAILED'].includes(task.status);
  const doneStages = (task.completed_stages || [])
    .filter(stage => stage !== 'cookie_sync')
    .map(stage => stageLabels[stage] || stage);
  const resumeReady = doneStages.length > 0 && isStopped;
  const stageHintParts = [];
  if (task.current_stage) {
    stageHintParts.push(`当前阶段：${stageLabels[task.current_stage] || task.current_stage}`);
  }
  if (doneStages.length) {
    stageHintParts.push(`已完成 ${doneStages.join(' → ')}`);
  }
  if (resumeReady) {
    stageHintParts.push('重试会先同步 CookieCloud，再从第一个未完成阶段继续');
  }
  const stageHint = stageHintParts.length
    ? `<div style="font-size: 0.8rem; color: var(--text-muted); margin: -0.25rem 0 0.75rem;">${escapeHtml(stageHintParts.join(' · '))}</div>`
    : '';
  const lastError = task.last_error || task.error_message;
  const errorLine = lastError && isStopped
    ? `<div style="font-size: 0.8rem; color: #ff8a80; margin: -0.35rem 0 0.75rem;">上次错误：${escapeHtml(lastError)}</div>`
    : '';
  const taskTitle = escapeHtml(task.final_title || task.youtube_info?.title || task.youtube_url);

  // Target platform badges
  const targets = task.upload_targets || ['bilibili'];
  const targetBadgesHtml = targets.map(t => {
    if (t === 'bilibili') return `<span class="badge" style="background: rgba(0, 242, 254, 0.15); color: var(--accent-cyan); padding: 0.2rem 0.5rem; border-radius: 4px; font-size: 0.75rem;">📺 B站</span>`;
    if (t === 'youtube') return `<span class="badge" style="background: rgba(255, 82, 82, 0.15); color: #ff5252; padding: 0.2rem 0.5rem; border-radius: 4px; font-size: 0.75rem;">🔴 YouTube</span>`;
    return '';
  }).join(' ');

  // Secondary creation tags
  const sec = task.secondary_creation || {};
  const secChips = [];
  if (sec.flip_horizontal) secChips.push('<span class="tag-badge">🪞 镜像翻转</span>');
  if (sec.border_ratio > 0.001) secChips.push(`<span class="tag-badge">🖼️ 黑边 ${Math.round(sec.border_ratio*100)}%</span>`);
  if (sec.watermark_text) secChips.push(`<span class="tag-badge">🛡️ 水印</span>`);
  const secBadgesHtml = secChips.join(' ');

  // Platform Links
  let linksHtml = '';
  if (task.bvid) {
    linksHtml += `
      <div style="background: rgba(0, 230, 118, 0.1); border: 1px solid rgba(0, 230, 118, 0.3); padding: 0.6rem 1rem; border-radius: var(--radius-md); margin-bottom: 0.5rem; color: var(--success); display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px;">
        <div>📺 已发布至 <strong>Bilibili</strong> (BV: ${task.bvid})</div>
        <a href="https://www.bilibili.com/video/${task.bvid}" target="_blank" rel="noopener noreferrer" class="btn btn-secondary" style="border-color: rgba(0, 230, 118, 0.5); color: #00e676; text-decoration: none; padding: 0.25rem 0.65rem; font-size: 0.8rem;">
          🔗 前往 B 站观看 ↗
        </a>
      </div>
    `;
  }
  if (task.youtube_video_id || task.youtube_watch_url) {
    const ytWatchUrl = task.youtube_watch_url || `https://www.youtube.com/watch?v=${task.youtube_video_id}`;
    linksHtml += `
      <div style="background: rgba(255, 82, 82, 0.1); border: 1px solid rgba(255, 82, 82, 0.3); padding: 0.6rem 1rem; border-radius: var(--radius-md); margin-bottom: 0.5rem; color: #ff5252; display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px;">
        <div>🔴 已发布至 <strong>YouTube</strong> (ID: ${task.youtube_video_id || ''})</div>
        <a href="${ytWatchUrl}" target="_blank" rel="noopener noreferrer" class="btn btn-secondary" style="border-color: rgba(255, 82, 82, 0.5); color: #ff5252; text-decoration: none; padding: 0.25rem 0.65rem; font-size: 0.8rem;">
          🔗 前往 YouTube 观看 ↗
        </a>
      </div>
    `;
  }

  return `
    <div class="task-card">
      <div class="task-header">
        <div>
          <div style="display: flex; align-items: center; gap: 6px; flex-wrap: wrap; margin-bottom: 4px;">
            <span class="task-id">TASK #${task.id}</span>
            ${targetBadgesHtml}
            ${secBadgesHtml}
          </div>
          <h3 style="font-size: 1.1rem; margin-top: 2px;">${taskTitle}</h3>
        </div>
        <div style="display: flex; align-items: center; gap: 8px;">
          ${task.skip_subtitles ? `<span class="badge" style="background: rgba(234, 179, 8, 0.2); color: #eab308; padding: 0.2rem 0.5rem; border-radius: 4px; font-size: 0.75rem;">⚡ 跳过字幕</span>` : ''}
          <span class="status-badge status-${task.status}">${statusLabels[task.status] || task.status}</span>
        </div>
      </div>

      <div class="progress-bar-container">
        <div class="progress-bar-fill" style="width: ${task.progress}%;"></div>
      </div>
      ${stageHint}
      ${errorLine}

      <!-- Action Buttons Row -->
      <div style="display: flex; gap: 8px; margin-bottom: 1rem; flex-wrap: wrap;">
        <button class="btn btn-secondary" style="padding: 0.35rem 0.75rem; font-size: 0.8rem;" onclick="openPreviewModal('${task.id}', '${taskTitle.replace(/'/g, "\\'")}')">🎬 视频预览</button>
        
        ${isRunning ? `<button class="btn btn-secondary" style="padding: 0.35rem 0.75rem; font-size: 0.8rem; border-color: rgba(234, 179, 8, 0.5); color: #eab308;" onclick="stopTask('${task.id}')">⏸️ 暂停</button>` : ''}
        ${isStopped ? `<button class="btn btn-secondary" style="padding: 0.35rem 0.75rem; font-size: 0.8rem; border-color: rgba(0, 230, 118, 0.5); color: #00e676;" onclick="startTask('${task.id}')">▶️ 启动</button>` : ''}
        
        <button class="btn btn-secondary" style="padding: 0.35rem 0.75rem; font-size: 0.8rem; ${task.skip_subtitles ? 'border-color: rgba(234, 179, 8, 0.6); color: #eab308;' : ''}" onclick="toggleTaskSkipSubtitles('${task.id}', ${!task.skip_subtitles})">
          ⚡ ${task.skip_subtitles ? '已跳过字幕' : '跳过字幕'}
        </button>
        
        <button class="btn btn-secondary" style="padding: 0.35rem 0.75rem; font-size: 0.8rem;" onclick="retryTask('${task.id}')">🔄 ${resumeReady ? '从断点重试' : '重试'}</button>
        <button class="btn btn-secondary" style="padding: 0.35rem 0.75rem; font-size: 0.8rem; border-color: rgba(255, 82, 82, 0.4); color: #ff5252;" onclick="deleteTask('${task.id}')">🗑️ 删除</button>
      </div>

      ${linksHtml}

      ${task.final_description ? `
        <div style="margin-bottom: 1rem; font-size: 0.9rem; color: var(--text-main); background: rgba(255,255,255,0.03); padding: 0.8rem; border-radius: var(--radius-sm);">
          <strong>发布简介 (${task.used_llm ? '🧠 LLM 已生成' : '未启用/未配置 LLM'}):</strong>
          <p style="white-space: pre-line; color: var(--text-muted); margin-top: 4px;">${escapeHtml(task.final_description.slice(0, 200))}...</p>
        </div>
      ` : ''}

      <div class="log-terminal" id="logTerminal-${task.id}" data-task-id="${task.id}">
        ${logsHtml || '<div class="log-entry">等待开始任务...</div>'}
      </div>
    </div>
  `;
}

async function checkBilibiliLogin() {
  const badge = document.getElementById('biliStatusBadge');
  badge.style.color = '#ffab00';
  badge.innerText = '正在验证...';

  try {
    const res = await fetch('/api/bilibili/check', { method: 'POST' });
    const data = await res.json();
    if (data.success && data.result.valid) {
      badge.style.color = '#00e676';
      badge.innerText = `已登录: ${data.result.uname} (Lv.${data.result.level})`;
    } else {
      badge.style.color = '#ff5252';
      badge.innerText = `未登录: ${data.result?.message || 'Cookie无效'}`;
    }
  } catch (err) {
    badge.style.color = '#ff5252';
    badge.innerText = '验证出错';
  }
}

async function syncCookieCloud() {
  const url = document.getElementById('cookiecloud_url').value.trim();
  const uuid = document.getElementById('cookiecloud_uuid').value.trim();
  const password = document.getElementById('cookiecloud_password').value.trim();

  if (!url || !uuid || !password) {
    alert('请先填写 CookieCloud 服务器地址、UUID 及 密码！');
    return;
  }

  try {
    const res = await fetch('/api/cookiecloud/sync', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        cookiecloud_url: url,
        cookiecloud_uuid: uuid,
        cookiecloud_password: password
      })
    });
    const data = await res.json();
    if (res.ok && data.success) {
      alert(data.message || 'CookieCloud 同步成功！');
      if (data.youtube_cookies) {
        document.getElementById('youtube_cookies').value = data.youtube_cookies;
      }
      await loadConfig();
    } else {
      alert('CookieCloud 同步失败: ' + (data.detail || data.message || '未知错误'));
    }
  } catch (err) {
    alert('CookieCloud 同步出错: ' + err.message);
  }
}

async function fetchLLMModels() {
  const provider = document.getElementById('llm_provider').value;
  const apiKey = document.getElementById('llm_api_key').value.trim();
  const baseUrl = document.getElementById('llm_base_url').value.trim();
  const badge = document.getElementById('llmTestStatusBadge');

  badge.style.color = 'var(--text-muted)';
  badge.innerText = '正在获取模型列表...';

  try {
    const res = await fetch('/api/llm/models', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        llm_provider: provider,
        llm_api_key: apiKey,
        llm_base_url: baseUrl
      })
    });
    const data = await res.json();
    if (res.ok && data.success) {
      const datalist = document.getElementById('llm_models_list');
      if (datalist) {
        datalist.innerHTML = data.models.map(m => `<option value="${escapeHtml(m)}"></option>`).join('');
      }
      badge.style.color = '#00e676';
      badge.innerText = `✅ 获取成功 (共 ${data.count} 个模型)`;
      if (data.models.length > 0 && !document.getElementById('llm_model').value.trim()) {
        document.getElementById('llm_model').value = data.models[0];
      }
    } else {
      badge.style.color = '#ff5252';
      badge.innerText = `获取失败: ${data.detail || '接口报错'}`;
    }
  } catch (err) {
    badge.style.color = '#ff5252';
    badge.innerText = `网络错误: ${err.message}`;
  }
}

async function testLLMModel() {
  const provider = document.getElementById('llm_provider').value;
  const apiKey = document.getElementById('llm_api_key').value.trim();
  const baseUrl = document.getElementById('llm_base_url').value.trim();
  const model = document.getElementById('llm_model').value.trim();
  const badge = document.getElementById('llmTestStatusBadge');

  badge.style.color = 'var(--text-muted)';
  badge.innerText = '正在测试模型连通性...';

  try {
    const res = await fetch('/api/llm/test', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        llm_provider: provider,
        llm_api_key: apiKey,
        llm_base_url: baseUrl,
        llm_model: model
      })
    });
    const data = await res.json();
    if (res.ok && data.success) {
      badge.style.color = '#00e676';
      badge.innerText = `✅ 测试可用 (${data.result.latency_ms}ms, 响应: "${data.result.reply}")`;
    } else {
      badge.style.color = '#ff5252';
      badge.innerText = `❌ 测试失败: ${data.detail || '无法连接'}`;
    }
  } catch (err) {
    badge.style.color = '#ff5252';
    badge.innerText = `网络错误: ${err.message}`;
  }
}

function onYouTubeCategorySelectChange(val) {
  const catInput = document.getElementById('youtube_category_id');
  if (!catInput) return;
  if (val !== 'custom') {
    catInput.value = val;
  } else {
    catInput.focus();
    catInput.select();
  }
}

function onYouTubeCategoryInput(val) {
  const catSelect = document.getElementById('youtube_category_select');
  if (!catSelect) return;
  const cleanVal = (val || '').trim();
  let matched = false;
  for (let i = 0; i < catSelect.options.length; i++) {
    if (catSelect.options[i].value === cleanVal) {
      catSelect.selectedIndex = i;
      matched = true;
      break;
    }
  }
  if (!matched) {
    catSelect.value = 'custom';
  }
}

async function openYouTubeAuthWizard() {
  const clientId = document.getElementById('youtube_client_id').value.trim();
  if (!clientId) {
    alert('请先填写 YouTube OAuth2 Client ID 并保存设置！');
    return;
  }
  const redirectUri = window.location.origin + '/oauth2callback';
  try {
    const res = await fetch('/api/youtube/auth-url', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ client_id: clientId, redirect_uri: redirectUri })
    });
    const data = await res.json();
    if (data.success && data.auth_url) {
      window.open(data.auth_url, '_blank');
      const code = prompt('Google 授权页面已在新窗口打开。\n\n授权成功后页面会自动保存 Token；如果您需要手动粘贴 Code，请在此处粘贴 authorization code：');
      if (code && code.trim()) {
        const clientSecret = document.getElementById('youtube_client_secret').value.trim();
        const cbRes = await fetch('/api/youtube/oauth-callback', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            code: code.trim(),
            client_id: clientId,
            client_secret: clientSecret,
            redirect_uri: redirectUri
          })
        });
        const cbData = await cbRes.json();
        if (cbData.success) {
          alert('YouTube 授权成功并已获取 Refresh Token！');
          await loadConfig();
        } else {
          alert('换取 Token 失败: ' + (cbData.detail || '未知错误'));
        }
      }
    } else {
      alert('获取授权链接失败: ' + (data.detail || '未知错误'));
    }
  } catch (err) {
    alert('请求出错: ' + err.message);
  }
}

async function testYouTubeApi() {
  const badge = document.getElementById('youtubeTestStatusBadge');
  badge.style.color = 'var(--text-muted)';
  badge.innerText = '正在测试 YouTube API...';

  const clientId = document.getElementById('youtube_client_id').value.trim();
  const clientSecret = document.getElementById('youtube_client_secret').value.trim();
  const refreshToken = document.getElementById('youtube_refresh_token').value.trim();

  try {
    const res = await fetch('/api/youtube/test', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        client_id: clientId,
        client_secret: clientSecret,
        refresh_token: refreshToken
      })
    });
    const data = await res.json();
    if (res.ok && data.success) {
      badge.style.color = '#00e676';
      badge.innerText = `✅ ${data.message}`;
    } else {
      badge.style.color = '#ff5252';
      badge.innerText = `❌ 测试失败: ${data.detail || '无法连接 YouTube'}`;
    }
  } catch (err) {
    badge.style.color = '#ff5252';
    badge.innerText = `网络错误: ${err.message}`;
  }
}

function escapeHtml(str) {
  if (!str) return '';
  return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#039;");
}


