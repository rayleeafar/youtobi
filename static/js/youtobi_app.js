let activePollInterval = null;

document.addEventListener('DOMContentLoaded', () => {
  loadConfig();
  loadTasks();
  activePollInterval = setInterval(loadTasks, 3000);
});

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

  const btn = document.getElementById('submitBtn');
  btn.disabled = true;
  btn.innerText = '提交中...';

  try {
    const res = await fetch('/api/tasks', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ youtube_url: url, skip_subtitles: skipSubtitles })
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
    'SUBTITLE_PROCESSING': '字幕生成与烧录',
    'LLM_REGENERATION': 'AI简介生成中',
    'UPLOADING': '上传至Bilibili',
    'COMPLETED': '已完成发布',
    'FAILED': '处理失败',
    'PAUSED': '已暂停/停止',
    'CANCELLED': '已取消'
  };

  const logsHtml = (task.logs || []).map(l => `<div class="log-entry">${escapeHtml(l)}</div>`).join('');
  const isRunning = ['PENDING', 'DOWNLOADING', 'SUBTITLE_PROCESSING', 'LLM_REGENERATION', 'UPLOADING'].includes(task.status);
  const isStopped = ['PAUSED', 'STOPPED', 'CANCELLED', 'FAILED'].includes(task.status);
  const taskTitle = escapeHtml(task.final_title || task.youtube_info?.title || task.youtube_url);

  return `
    <div class="task-card">
      <div class="task-header">
        <div>
          <span class="task-id">TASK #${task.id}</span>
          <h3 style="font-size: 1.1rem; margin-top: 4px;">${taskTitle}</h3>
        </div>
        <div style="display: flex; align-items: center; gap: 8px;">
          ${task.skip_subtitles ? `<span class="badge" style="background: rgba(234, 179, 8, 0.2); color: #eab308; padding: 0.2rem 0.5rem; border-radius: 4px; font-size: 0.75rem;">⚡ 跳过字幕</span>` : ''}
          <span class="status-badge status-${task.status}">${statusLabels[task.status] || task.status}</span>
        </div>
      </div>

      <div class="progress-bar-container">
        <div class="progress-bar-fill" style="width: ${task.progress}%;"></div>
      </div>

      <!-- Action Buttons Row -->
      <div style="display: flex; gap: 8px; margin-bottom: 1rem; flex-wrap: wrap;">
        <button class="btn btn-secondary" style="padding: 0.35rem 0.75rem; font-size: 0.8rem;" onclick="openPreviewModal('${task.id}', '${taskTitle.replace(/'/g, "\\'")}')">🎬 视频预览</button>
        
        ${isRunning ? `<button class="btn btn-secondary" style="padding: 0.35rem 0.75rem; font-size: 0.8rem; border-color: rgba(234, 179, 8, 0.5); color: #eab308;" onclick="stopTask('${task.id}')">⏸️ 暂停</button>` : ''}
        ${isStopped ? `<button class="btn btn-secondary" style="padding: 0.35rem 0.75rem; font-size: 0.8rem; border-color: rgba(0, 230, 118, 0.5); color: #00e676;" onclick="startTask('${task.id}')">▶️ 启动</button>` : ''}
        
        <button class="btn btn-secondary" style="padding: 0.35rem 0.75rem; font-size: 0.8rem; ${task.skip_subtitles ? 'border-color: rgba(234, 179, 8, 0.6); color: #eab308;' : ''}" onclick="toggleTaskSkipSubtitles('${task.id}', ${!task.skip_subtitles})">
          ⚡ ${task.skip_subtitles ? '已跳过字幕' : '跳过字幕'}
        </button>
        
        <button class="btn btn-secondary" style="padding: 0.35rem 0.75rem; font-size: 0.8rem;" onclick="retryTask('${task.id}')">🔄 重试</button>
        <button class="btn btn-secondary" style="padding: 0.35rem 0.75rem; font-size: 0.8rem; border-color: rgba(255, 82, 82, 0.4); color: #ff5252;" onclick="deleteTask('${task.id}')">🗑️ 删除</button>
      </div>

      ${task.bvid ? `
        <div style="background: rgba(0, 230, 118, 0.1); border: 1px solid rgba(0, 230, 118, 0.3); padding: 0.8rem 1rem; border-radius: var(--radius-md); margin-bottom: 1rem; color: var(--success); display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px;">
          <div>🎉 已成功同步发布至 Bilibili! BV号: <strong>${task.bvid}</strong></div>
          <a href="https://www.bilibili.com/video/${task.bvid}" target="_blank" rel="noopener noreferrer" class="btn btn-secondary" style="border-color: rgba(0, 230, 118, 0.5); color: #00e676; text-decoration: none; padding: 0.3rem 0.75rem; font-size: 0.85rem; display: inline-flex; align-items: center; gap: 4px;">
            🔗 点击跳转观看 ↗
          </a>
        </div>
      ` : ''}

      ${task.final_description ? `
        <div style="margin-bottom: 1rem; font-size: 0.9rem; color: var(--text-main); background: rgba(255,255,255,0.03); padding: 0.8rem; border-radius: var(--radius-sm);">
          <strong>B站发布简介 (${task.used_llm ? '🧠 LLM 已生成' : '未启用/未配置 LLM'}):</strong>
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

function escapeHtml(str) {
  if (!str) return '';
  return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#039;");
}


