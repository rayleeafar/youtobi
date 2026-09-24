import unittest
import json
from pathlib import Path
from fastapi.testclient import TestClient

from app import app
from config import config_manager
from services.youtube import YouTubeService
from services.subtitle import SubtitleService
from services.llm import LLMService
from services.cookiecloud import CookieCloudService
from services.task_manager import task_manager
from services.bilibili import BilibiliService


import tempfile
from config import config_manager, DEFAULT_CONFIG


class TestYoutobi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.temp_config = Path(cls.temp_dir.name) / "test_config.json"
        cls.temp_tasks = Path(cls.temp_dir.name) / "test_tasks.json"

        # Back up original paths and state
        cls.orig_config_path = config_manager.file_path
        cls.orig_config_dict = config_manager._config.copy()
        cls.orig_task_path = task_manager.file_path
        cls.orig_tasks = task_manager.tasks.copy()

        # Switch to isolated temp test files
        config_manager.file_path = cls.temp_config
        config_manager._config = DEFAULT_CONFIG.copy()
        config_manager._config["admin_password"] = "admin"
        config_manager.save()

        task_manager.file_path = cls.temp_tasks
        task_manager.tasks = {}
        task_manager.save_tasks()

    @classmethod
    def tearDownClass(cls):
        # Restore original paths and state
        config_manager.file_path = cls.orig_config_path
        config_manager._config = cls.orig_config_dict
        if cls.orig_config_path.exists():
            config_manager.save()

        task_manager.file_path = cls.orig_task_path
        task_manager.tasks = cls.orig_tasks
        if cls.orig_task_path.exists():
            task_manager.save_tasks()

        cls.temp_dir.cleanup()

    def setUp(self):
        self.client = TestClient(app)
        pwd = config_manager.get("admin_password", "admin")
        self.client.post("/api/auth/login", json={"password": pwd})


    def test_config_update_skip_subtitles(self):
        res = self.client.post("/api/config", json={"skip_subtitles": True, "auto_delete_after_upload": True})
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json()["config"]["skip_subtitles"])
        self.assertTrue(res.json()["config"]["auto_delete_after_upload"])

        get_res = self.client.get("/api/config")
        self.assertEqual(get_res.status_code, 200)
        self.assertTrue(get_res.json()["config"]["skip_subtitles"])

    def test_config_new_fields_defaults(self):
        cfg = config_manager.all()
        self.assertIn("upload_targets", cfg)
        self.assertIn("youtube_upload_enabled", cfg)
        self.assertIn("youtube_privacy_status", cfg)
        self.assertIn("secondary_creation_enabled", cfg)
        self.assertIn("secondary_flip_horizontal", cfg)
        self.assertIn("secondary_border_ratio", cfg)
        self.assertIn("secondary_watermark_enabled", cfg)

        # Test updating new fields
        res = self.client.post("/api/config", json={
            "upload_targets": ["bilibili", "youtube"],
            "youtube_upload_enabled": True,
            "secondary_creation_enabled": True,
            "secondary_flip_horizontal": True,
            "secondary_border_ratio": 0.05,
            "secondary_watermark_enabled": True,
            "secondary_watermark_text": "MY_WATERMARK"
        })
        self.assertEqual(res.status_code, 200)
        updated = res.json()["config"]
        self.assertEqual(updated["upload_targets"], ["bilibili", "youtube"])
        self.assertTrue(updated["secondary_flip_horizontal"])
        self.assertEqual(updated["secondary_border_ratio"], 0.05)
        self.assertEqual(updated["secondary_watermark_text"], "MY_WATERMARK")

        # Reset config state for subsequent tests
        self.client.post("/api/config", json={
            "upload_targets": ["bilibili"],
            "youtube_upload_enabled": False,
            "secondary_creation_enabled": False,
            "secondary_flip_horizontal": False,
            "secondary_border_ratio": 0.0,
            "secondary_watermark_enabled": False
        })

    def _reset_public_ip_cache(self):
        import app as app_module
        app_module._public_ip_cache.update(ip=None, country=None, expires=0.0)

    def test_system_stats_requires_auth_and_shape(self):
        from unittest.mock import patch

        unauth = TestClient(app)
        denied = unauth.get("/api/system/stats")
        self.assertEqual(denied.status_code, 401)

        self._reset_public_ip_cache()
        calls = []

        def fake_get(url, timeout=2.0):
            calls.append(url)
            if "cdn-cgi/trace" in url:
                return "ip=8.8.8.8\nloc=US\n"
            raise AssertionError(url)

        with patch("app._http_get", side_effect=fake_get):
            res = self.client.get("/api/system/stats")
            again = self.client.get("/api/system/stats")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(
            set(data.keys()),
            {
                "hostname", "ip", "country", "cpu_percent", "cpu_count", "load_avg",
                "memory", "disk", "net", "uptime_seconds", "sampled_at",
            },
        )
        self.assertEqual(data["ip"], "8.8.8.8")
        self.assertEqual(data["country"], "US")
        self.assertEqual(again.json()["ip"], "8.8.8.8")
        self.assertEqual(again.json()["country"], "US")
        self.assertEqual(calls, ["https://1.1.1.1/cdn-cgi/trace"])
        self.assertTrue(data["hostname"])
        self.assertGreaterEqual(data["cpu_percent"], 0)
        self.assertLessEqual(data["cpu_percent"], 100)
        self.assertGreaterEqual(data["cpu_count"], 1)
        self.assertGreater(data["memory"]["total"], 0)
        self.assertLessEqual(data["memory"]["used"], data["memory"]["total"])
        self.assertGreaterEqual(data["memory"]["percent"], 0)
        self.assertLessEqual(data["memory"]["percent"], 100)
        self.assertGreater(data["disk"]["total"], 0)
        self.assertGreaterEqual(data["disk"]["percent"], 0)
        self.assertLessEqual(data["disk"]["percent"], 100)
        self.assertGreaterEqual(data["net"]["bytes_sent"], 0)
        self.assertGreaterEqual(data["net"]["bytes_recv"], 0)
        self.assertGreaterEqual(data["uptime_seconds"], 0)
        self.assertIsInstance(data["sampled_at"], float)

    def test_system_stats_public_ip_fallback(self):
        from unittest.mock import patch
        import app as app_module

        self._reset_public_ip_cache()

        def private_then_public(url, timeout=2.0):
            if "cdn-cgi/trace" in url:
                return "ip=172.16.0.5\nloc=US\n"
            if "ipify" in url:
                return "1.1.1.1"
            if "ipapi.co" in url:
                return "de"
            raise AssertionError(url)

        with patch("app._http_get", side_effect=private_then_public):
            res = self.client.get("/api/system/stats")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["ip"], "1.1.1.1")
        self.assertEqual(res.json()["country"], "DE")
        self.assertGreaterEqual(res.json()["cpu_percent"], 0)

        app_module._public_ip_cache["expires"] = 0.0
        with patch("app._http_get", side_effect=OSError("down")):
            kept = self.client.get("/api/system/stats")
        self.assertEqual(kept.status_code, 200)
        self.assertEqual(kept.json()["ip"], "1.1.1.1")
        self.assertEqual(kept.json()["country"], "DE")
        self.assertIn("memory", kept.json())

        self._reset_public_ip_cache()
        with patch("app._http_get", side_effect=OSError("down")):
            empty = self.client.get("/api/system/stats")
        self.assertEqual(empty.status_code, 200)
        self.assertIsNone(empty.json()["ip"])
        self.assertIsNone(empty.json()["country"])
        self.assertIn("disk", empty.json())

    def test_auth_flow(self):
        unauth_client = TestClient(app)
        res = unauth_client.get("/api/config")
        self.assertEqual(res.status_code, 401)

        admin_pwd = config_manager.get("admin_password", "admin")
        # Login with bad password
        bad_res = unauth_client.post("/api/auth/login", json={"password": "wrong_password_invalid"})
        self.assertEqual(bad_res.status_code, 400)

        # Login with correct password
        good_res = unauth_client.post("/api/auth/login", json={"password": admin_pwd})
        self.assertEqual(good_res.status_code, 200)
        self.assertTrue(good_res.json().get("success"))

        # Access config with auth
        conf_res = unauth_client.get("/api/config")
        self.assertEqual(conf_res.status_code, 200)


    def test_config_downloads_dir_fallback(self):
        from config import ConfigManager, BASE_DIR
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".json") as tmp:
            tmp_path = Path(tmp.name)
            cm = ConfigManager(file_path=tmp_path)
            cm.set("downloads_dir", "/invalid_nonexistent_root_dir_12345/downloads")
            cfg = cm.load()
            self.assertEqual(cfg["downloads_dir"], str(BASE_DIR / "downloads"))



    def test_task_creation_validation(self):
        # Empty URL test
        res = self.client.post("/api/tasks", json={"youtube_url": ""})
        self.assertEqual(res.status_code, 400)

        # Invalid domain test
        res = self.client.post("/api/tasks", json={"youtube_url": "https://example.com"})
        self.assertEqual(res.status_code, 400)

    def test_youtube_extract_items_with_custom_text(self):
        input_text = """https://www.youtube.com/watch?v=video1
# 侯府嫡女重生记 第一季
https://youtu.be/video2 # 第二个视频备注
"""
        items = YouTubeService.extract_items(input_text)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["url"], "https://www.youtube.com/watch?v=video1")
        self.assertEqual(items[0]["custom_text"], "侯府嫡女重生记 第一季")
        self.assertEqual(items[1]["url"], "https://youtu.be/video2")
        self.assertEqual(items[1]["custom_text"], "第二个视频备注")




    def test_llm_fallback(self):
        cfg = {"llm_enabled": False, "llm_api_key": ""}
        llm = LLMService(cfg)
        res = llm.regenerate_description("Test Title", "Test Description", "en")
        self.assertEqual(res["title"], "Test Title")
        self.assertEqual(res["description"], "Test Description")
        self.assertFalse(res["used_llm"])

    def test_llm_retry_and_fallback(self):
        from unittest.mock import patch, MagicMock

        cfg = {"llm_enabled": True, "llm_api_key": "sk-fake", "llm_model": "gpt-4o-mini"}
        llm = LLMService(cfg)

        logs = []
        def mock_logger(msg):
            logs.append(msg)

        # Case 1: Fails 3 times -> Fallback to native title & description
        with patch("openai.OpenAI") as mock_openai:
            mock_client = MagicMock()
            mock_openai.return_value = mock_client
            mock_client.chat.completions.create.side_effect = Exception("API connection error")

            res = llm.regenerate_description("Native Title", "Native Description", "en", max_retries=3, task_logger=mock_logger)
            self.assertEqual(res["title"], "Native Title")
            self.assertEqual(res["description"], "Native Description")
            self.assertFalse(res["used_llm"])
            self.assertEqual(mock_client.chat.completions.create.call_count, 3)
            self.assertTrue(any("Falling back to native source description" in l for l in logs))

    def test_vtt_to_srt_conversion(self):
        sub_service = SubtitleService()
        vtt = """WEBVTT

00:00:01.000 --> 00:00:05.000
Hello world

00:00:05.500 --> 00:00:09.000
Second subtitle line
"""
        srt = sub_service.vtt_to_srt(vtt)
        self.assertIn("00:00:01,000 --> 00:00:05,000", srt)
        self.assertIn("Hello world", srt)

    def test_whisper_srt_formatting(self):
        segments = [
            {"start": 1.25, "end": 4.5, "text": "Hello Whisper"},
            {"start": 5.0, "end": 8.123, "text": "Second line"}
        ]
        srt = SubtitleService.format_segments_to_srt(segments)
        self.assertIn("1\n00:00:01,250 --> 00:00:04,500\nHello Whisper", srt)
        self.assertIn("2\n00:00:05,000 --> 00:00:08,123\nSecond line", srt)

    def test_subtitle_processing_logic(self):
        import tempfile
        from unittest.mock import patch, MagicMock

        sub_service = SubtitleService()
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            video_file = tmp_path / "test.mp4"
            video_file.write_bytes(b"fake video content")

            srt_file = tmp_path / "test.srt"
            srt_file.write_text("1\n00:00:01,000 --> 00:00:02,000\n中文测试", encoding="utf-8")

            # Case 1: Chinese video WITH external subtitles -> should return original video without burn-in
            out_video, out_srt = sub_service.process_subtitles(video_file, srt_file, is_chinese=True, output_dir=tmp_path / "out1")
            self.assertEqual(out_video, video_file)

            # Case 2: Chinese video WITH embedded subtitles -> should return original video without burn-in
            with patch.object(sub_service, "has_embedded_subtitles", return_value=True):
                out_video, out_srt = sub_service.process_subtitles(video_file, None, is_chinese=True, output_dir=tmp_path / "out2")
                self.assertEqual(out_video, video_file)

            # Case 3: Non-Chinese video -> should process & burn subtitles
            dummy_cn_srt = tmp_path / "chinese.srt"
            dummy_cn_srt.write_text("1\n00:00:01,000 --> 00:00:02,000\n字幕", encoding="utf-8")
            with patch.object(sub_service, "_ensure_chinese_srt", return_value=dummy_cn_srt), \
                 patch.object(sub_service, "burn_subtitles", return_value=tmp_path / "burned_test.mp4") as mock_burn:
                out_video, out_srt = sub_service.process_subtitles(video_file, srt_file, is_chinese=False, output_dir=tmp_path / "out3")
                mock_burn.assert_called_once()
                self.assertEqual(out_video, tmp_path / "burned_test.mp4")

    def test_bilibili_video_splitter(self):
        from services.bilibili import BilibiliService
        from unittest.mock import patch, MagicMock
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            dummy_path = Path(tmpdir) / "dummy_long_video.mp4"
            dummy_path.write_bytes(b"dummy")

            # Under max limit (e.g. 5 hours = 18000s) -> returns single path
            with patch.object(BilibiliService, "get_video_duration", return_value=18000.0):
                parts = BilibiliService.split_video_if_needed(dummy_path, max_duration_sec=28800)
                self.assertEqual(len(parts), 1)
                self.assertEqual(parts[0], dummy_path)

            # Over max limit (e.g. 10.5 hours = 37800s) -> splits into 2 parts
            def fake_subprocess_run(cmd, *args, **kwargs):
                out_path = Path(cmd[-1])
                out_path.write_bytes(b"x" * 2000000)
                res = MagicMock()
                res.returncode = 0
                return res

            with patch.object(BilibiliService, "get_video_duration", return_value=37800.0), \
                 patch("subprocess.run", side_effect=fake_subprocess_run):
                parts = BilibiliService.split_video_if_needed(dummy_path, max_duration_sec=28800)
                self.assertEqual(len(parts), 2)

    def test_auto_delete_after_upload(self):

        from unittest.mock import patch, MagicMock
        from services.task_manager import Task

        task = Task("test1234", "https://youtu.be/test")
        task_manager.tasks[task.id] = task

        # Mock dependencies in pipeline
        dummy_info = {"title": "Test Title", "description": "Test Desc", "language": "zh", "is_chinese": True}
        with patch("services.task_manager.YouTubeService") as mock_yt_cls, \
             patch("services.task_manager.SubtitleService") as mock_sub_cls, \
             patch("services.task_manager.LLMService") as mock_llm_cls, \
             patch("services.task_manager.BilibiliService") as mock_bili_cls, \
             patch("services.task_manager.YouTubeUploaderService") as mock_yt_up_cls:

            mock_yt = mock_yt_cls.return_value
            mock_yt.extract_info.return_value = dummy_info

            # Create dummy task directory and dummy video file
            cfg = config_manager.all()
            task_dir = Path(cfg["downloads_dir"]) / task.id
            task_dir.mkdir(parents=True, exist_ok=True)
            dummy_video = task_dir / "test1234.mp4"
            dummy_video.write_bytes(b"dummy video data")
            
            mock_yt.download_video_and_subtitles.return_value = (dummy_video, None, dummy_info)

            mock_sub = mock_sub_cls.return_value
            mock_sub.prepare_chinese_srt.return_value = (None, False)
            mock_sub.process_subtitles.return_value = (dummy_video, None)

            mock_llm = mock_llm_cls.return_value
            mock_llm.regenerate_description.return_value = {"title": "Test Title", "description": "Test Desc", "used_llm": False}

            mock_bili = mock_bili_cls.return_value
            mock_bili.upload_video.return_value = {"bvid": "BV1234567890"}

            # Run pipeline
            task_manager._run_task_pipeline(task)

            # Verify task history is preserved
            self.assertEqual(task.status, "COMPLETED")
            self.assertEqual(task.bvid, "BV1234567890")
            self.assertEqual(task.final_title, "Test Title")
            self.assertTrue(any("Auto-deleted local video files" in log for log in task.logs))

            # Verify video file directory on disk was auto-deleted
            self.assertFalse(task_dir.exists())


    def test_task_lifecycle_api(self):
        from unittest.mock import patch
        with patch.object(task_manager, "_run_task_pipeline", return_value=None):
            res = self.client.post("/api/tasks", json={"youtube_url": "https://www.youtube.com/watch?v=demo12345", "skip_subtitles": True})
            self.assertEqual(res.status_code, 200)
            task_id = res.json()["task"]["id"]
            self.assertTrue(res.json()["task"]["skip_subtitles"])

            # Stop task
            stop_res = self.client.post(f"/api/tasks/{task_id}/stop")
            self.assertEqual(stop_res.status_code, 200)
            self.assertEqual(task_manager.get_task(task_id).status, "PAUSED")

            # Start task
            start_res = self.client.post(f"/api/tasks/{task_id}/start")
            self.assertEqual(start_res.status_code, 200)

            # Toggle skip subtitles
            skip_res = self.client.post(f"/api/tasks/{task_id}/skip_subtitles", json={"skip": False})
            self.assertEqual(skip_res.status_code, 200)
            self.assertFalse(task_manager.get_task(task_id).skip_subtitles)

            # Cancel task
            c_res = self.client.post(f"/api/tasks/{task_id}/cancel")
            self.assertEqual(c_res.status_code, 200)

            # Retry task
            r_res = self.client.post(f"/api/tasks/{task_id}/retry")
            self.assertEqual(r_res.status_code, 200)

            # Delete task
            d_res = self.client.delete(f"/api/tasks/{task_id}")
            self.assertEqual(d_res.status_code, 200)

    def test_task_persistence_across_reboot(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        from services.task_manager import TaskManager

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_tasks_file = Path(tmpdir) / "tasks.json"
            with patch.object(TaskManager, "_run_task_pipeline", return_value=None):
                tm1 = TaskManager(file_path=tmp_tasks_file)
                t1 = tm1.create_task("https://www.youtube.com/watch?v=persisted123", skip_subtitles=True)
                t1.status = "COMPLETED"
                t1.bvid = "BV_PERSIST_TEST"
                tm1.save_tasks()

                # Simulate reboot by instantiating new TaskManager
                tm2 = TaskManager(file_path=tmp_tasks_file)
                self.assertIn(t1.id, tm2.tasks)
                reloaded_task = tm2.get_task(t1.id)
                self.assertEqual(reloaded_task.bvid, "BV_PERSIST_TEST")
                self.assertEqual(reloaded_task.status, "COMPLETED")
                self.assertTrue(reloaded_task.skip_subtitles)


    def test_cookiecloud_decryption_legacy_and_fixed(self):
        import base64, hashlib
        from Crypto.Cipher import AES
        from Crypto.Util.Padding import pad
        
        uuid = "test-uuid"
        password = "test-pass"
        service = CookieCloudService("http://dummy", uuid, password)

        # 1. Test Fixed IV Mode
        key_bytes = hashlib.md5(f"{uuid}-{password}".encode("utf-8")).hexdigest()[:16].encode("utf-8")
        payload = json.dumps({"cookie_data": {".bilibili.com": [{"name": "SESSDATA", "value": "val123"}]}}).encode("utf-8")
        cipher_fixed = AES.new(key_bytes, AES.MODE_CBC, b"\x00" * 16)
        ct_fixed = cipher_fixed.encrypt(pad(payload, 16))
        b64_fixed = base64.b64encode(ct_fixed).decode("utf-8")
        
        dec_fixed = service._decrypt(b64_fixed)
        self.assertIn("SESSDATA", dec_fixed)

        # 2. Test Legacy OpenSSL Mode (Salted__ header)
        salt = b"12345678"
        k, iv = service._evp_bytes_to_key(key_bytes, salt, 32, 16)
        cipher_legacy = AES.new(k, AES.MODE_CBC, iv)
        ct_legacy = cipher_legacy.encrypt(pad(payload, 16))
        b64_legacy = base64.b64encode(b"Salted__" + salt + ct_legacy).decode("utf-8")

        dec_legacy = service._decrypt(b64_legacy)
        self.assertIn("SESSDATA", dec_legacy)

    def test_llm_models_and_test_routes(self):
        from unittest.mock import patch
        with patch.object(LLMService, "fetch_models", return_value=["gpt-4o", "gpt-4o-mini"]):
            res = self.client.post("/api/llm/models", json={"llm_api_key": "sk-test", "llm_base_url": "https://api.openai.com/v1"})
            self.assertEqual(res.status_code, 200)
            data = res.json()
            self.assertTrue(data.get("success"))
            self.assertEqual(data.get("models"), ["gpt-4o", "gpt-4o-mini"])

        with patch.object(LLMService, "test_connection", return_value={"success": True, "latency_ms": 120, "reply": "Hi", "model": "gpt-4o-mini"}):
            res = self.client.post("/api/llm/test", json={"llm_api_key": "sk-test", "llm_model": "gpt-4o-mini"})
            self.assertEqual(res.status_code, 200)
            data = res.json()
            self.assertTrue(data.get("success"))
            self.assertIn("连接成功", data.get("message"))

    def test_cookiecloud_sync_before_youtube_download(self):
        from unittest.mock import patch, MagicMock
        from services.task_manager import Task

        # Set up CookieCloud configs
        config_manager.update({
            "cookiecloud_url": "https://cc.example.com",
            "cookiecloud_uuid": "uuid-123",
            "cookiecloud_password": "pwd-123",
            "youtube_cookies": "old_yt_cookie",
            "bilibili_sessdata": "old_sess"
        })

        task = Task("test_cc_sync", "https://youtu.be/sync_test")
        task_manager.tasks[task.id] = task

        dummy_yt_cookie = "# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t2147483647\tLOGIN_INFO\tnew_token"
        dummy_bili_cookies = {"SESSDATA": "new_sessdata_val", "bili_jct": "new_jct_val", "DedeUserID": "9999"}

        with patch("services.task_manager.CookieCloudService") as mock_cc_cls, \
             patch("services.task_manager.YouTubeService") as mock_yt_cls, \
             patch("services.task_manager.SubtitleService") as mock_sub_cls, \
             patch("services.task_manager.LLMService") as mock_llm_cls, \
             patch("services.task_manager.BilibiliService") as mock_bili_cls, \
             patch("services.task_manager.YouTubeUploaderService") as mock_yt_up_cls:

            mock_cc = mock_cc_cls.return_value
            mock_cc.fetch_all_synced_cookies.return_value = (dummy_bili_cookies, dummy_yt_cookie)

            mock_yt = mock_yt_cls.return_value
            mock_yt.extract_info.return_value = {"title": "Sync Test", "description": "Desc", "language": "zh", "is_chinese": True}
            
            cfg = config_manager.all()
            task_dir = Path(cfg["downloads_dir"]) / task.id
            task_dir.mkdir(parents=True, exist_ok=True)
            dummy_video = task_dir / "sync_test.mp4"
            dummy_video.write_bytes(b"dummy")
            mock_yt.download_video_and_subtitles.return_value = (dummy_video, None, {})

            mock_sub = mock_sub_cls.return_value
            mock_sub.prepare_chinese_srt.return_value = (None, False)
            mock_sub.process_subtitles.return_value = (dummy_video, None)

            mock_llm = mock_llm_cls.return_value
            mock_llm.regenerate_description.return_value = {"title": "Sync Test", "description": "Desc", "used_llm": False}

            mock_bili = mock_bili_cls.return_value
            mock_bili.upload_video.return_value = {"bvid": "BV_SYNC_OK"}

            # Run pipeline
            task_manager._run_task_pipeline(task)

            # Verify CookieCloud was fetched
            mock_cc.fetch_all_synced_cookies.assert_called_once()
            self.assertEqual(config_manager.get("youtube_cookies"), dummy_yt_cookie)
            self.assertEqual(config_manager.get("bilibili_sessdata"), "new_sessdata_val")
            self.assertTrue(any("Syncing fresh cookies from CookieCloud before downloading from YouTube" in log for log in task.logs))
            self.assertEqual(task.status, "COMPLETED")

    def test_video_editor_filter_building(self):
        from services.video_editor import VideoEditor
        
        # Test individual filters
        f_hflip = VideoEditor.build_filter_chain(flip_horizontal=True)
        self.assertEqual(f_hflip, "hflip")

        f_border = VideoEditor.build_filter_chain(border_ratio=0.05)
        self.assertIn("scale=w=trunc(iw*0.9", f_border)
        self.assertIn("pad=w=trunc", f_border)
        self.assertIn("color=black", f_border)

        f_wm = VideoEditor.build_filter_chain(watermark_text="COPYRIGHT_TEST", watermark_opacity=0.015)
        self.assertIn("drawtext=text='COPYRIGHT_TEST'", f_wm)
        self.assertIn("fontcolor=white@0.015", f_wm)

        # Test combined with fake srt
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".srt") as tmp_srt:
            srt_p = Path(tmp_srt.name)
            f_all = VideoEditor.build_filter_chain(
                flip_horizontal=True,
                border_ratio=0.08,
                watermark_text="SECRET:MARK",
                watermark_opacity=0.012,
                srt_path=srt_p
            )
            self.assertIn("hflip", f_all)
            self.assertIn("scale=", f_all)
            self.assertIn("subtitles=", f_all)
            self.assertIn("drawtext=", f_all)
            self.assertIn("SECRET\\:MARK", f_all)

    def test_video_editor_process_video(self):
        from services.video_editor import VideoEditor
        from unittest.mock import patch, MagicMock
        import tempfile

        editor = VideoEditor()
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_p = Path(tmpdir)
            in_vid = tmp_p / "input.mp4"
            in_vid.write_bytes(b"dummy")
            out_vid = tmp_p / "output.mp4"

            # 1. No filters -> returns in_vid directly
            res_vid = editor.process_video(in_vid, out_vid)
            self.assertEqual(res_vid, in_vid)

            # 2. With filters -> invokes ffmpeg
            def fake_ffmpeg(cmd, *args, **kwargs):
                out_p = Path(cmd[-1])
                out_p.write_bytes(b"processed_data")
                m = MagicMock()
                m.returncode = 0
                return m

            with patch("subprocess.run", side_effect=fake_ffmpeg):
                res_proc = editor.process_video(
                    video_path=in_vid,
                    output_path=out_vid,
                    flip_horizontal=True,
                    border_ratio=0.05,
                    watermark_text="WM"
                )
                self.assertEqual(res_proc, out_vid)
                self.assertTrue(out_vid.exists())

    def test_youtube_uploader_auth_and_token_refresh(self):
        from services.youtube_uploader import YouTubeUploaderService
        from unittest.mock import patch, MagicMock

        # 1. Auth URL generation
        auth_url = YouTubeUploaderService.generate_auth_url(client_id="test_client_123", redirect_uri="http://localhost:8000/callback")
        self.assertIn("client_id=test_client_123", auth_url)
        self.assertIn("redirect_uri=http%3A%2F%2Flocalhost%3A8000%2Fcallback", auth_url)
        self.assertIn("response_type=code", auth_url)

        # 2. Token Exchange
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.json.return_value = {"access_token": "acc_123", "refresh_token": "ref_456", "expires_in": 3600}
        with patch("requests.post", return_value=mock_resp) as mock_post:
            res = YouTubeUploaderService.exchange_code_for_tokens(
                client_id="cid", client_secret="csec", code="code_abc", redirect_uri="http://cb"
            )
            self.assertEqual(res["access_token"], "acc_123")
            self.assertEqual(res["refresh_token"], "ref_456")

        # 3. Token Refresh
        svc = YouTubeUploaderService(client_id="cid", client_secret="csec", refresh_token="ref_old")
        mock_resp.json.return_value = {"access_token": "acc_refreshed", "expires_in": 3600}
        with patch("requests.post", return_value=mock_resp):
            token = svc.get_access_token(force_refresh=True)
            self.assertEqual(token, "acc_refreshed")

    def test_youtube_uploader_channel_info_and_upload(self):
        from services.youtube_uploader import YouTubeUploaderService
        from unittest.mock import patch, MagicMock
        import tempfile

        svc = YouTubeUploaderService(access_token="valid_token")

        # 1. Channel Info
        mock_ch_resp = MagicMock()
        mock_ch_resp.ok = True
        mock_ch_resp.json.return_value = {
            "items": [
                {
                    "id": "UC_TEST_123",
                    "snippet": {"title": "Test Channel", "customUrl": "@testchan"},
                    "statistics": {"subscriberCount": "1000", "videoCount": "50"}
                }
            ]
        }
        with patch("requests.get", return_value=mock_ch_resp):
            ch_info = svc.get_channel_info()
            self.assertEqual(ch_info["channel_id"], "UC_TEST_123")
            self.assertEqual(ch_info["title"], "Test Channel")
            self.assertEqual(ch_info["subscriber_count"], "1000")

        # 2. Upload Video
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_p = Path(tmpdir)
            test_vid = tmp_p / "upload_sample.mp4"
            test_vid.write_bytes(b"dummy_mp4_content" * 100)
            test_cover = tmp_p / "cover.jpg"
            test_cover.write_bytes(b"dummy_jpg")

            # Mock initiate POST
            init_resp = MagicMock()
            init_resp.status_code = 200
            init_resp.headers = {"Location": "https://upload.youtube.com/resumable_session_url"}

            # Mock chunk PUT
            chunk_resp = MagicMock()
            chunk_resp.status_code = 200
            chunk_resp.json.return_value = {"id": "YT_VID_999", "snippet": {"title": "Uploaded Title"}}

            # Mock thumbnail POST
            thumb_resp = MagicMock()
            thumb_resp.ok = True

            progresses = []
            def on_prog(pct, msg):
                progresses.append((pct, msg))

            def mock_requests_post(url, *args, **kwargs):
                if "uploadType=resumable" in url:
                    return init_resp
                elif "thumbnails/set" in url:
                    return thumb_resp
                return MagicMock(status_code=400)

            with patch("requests.post", side_effect=mock_requests_post), \
                 patch("requests.put", return_value=chunk_resp):
                upload_res = svc.upload_video(
                    video_path=test_vid,
                    title="Uploaded Title",
                    description="Uploaded Desc",
                    tags=["tag1", "tag2"],
                    cover_path=test_cover,
                    progress_callback=on_prog
                )

                self.assertEqual(upload_res["video_id"], "YT_VID_999")
                self.assertEqual(upload_res["url"], "https://www.youtube.com/watch?v=YT_VID_999")
                self.assertTrue(len(progresses) > 0)
                self.assertEqual(progresses[-1][0], 100)

    def test_task_manager_dual_upload_orchestration(self):
        from services.task_manager import Task, TaskManager
        from unittest.mock import patch, MagicMock
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_tasks_file = Path(tmpdir) / "tasks.json"
            mgr = TaskManager(file_path=tmp_tasks_file)

            # 1. Test Task serialization with dual upload & secondary options
            task = Task(
                task_id="t123",
                youtube_url="https://youtube.com/watch?v=abc12345",
                upload_targets=["bilibili", "youtube"],
                secondary_creation={"flip_horizontal": True, "border_ratio": 0.05, "watermark_text": "TEST_WM", "watermark_enabled": True}
            )
            d = task.to_dict()
            self.assertEqual(d["upload_targets"], ["bilibili", "youtube"])
            self.assertTrue(d["secondary_creation"]["flip_horizontal"])
            self.assertEqual(d["secondary_creation"]["watermark_text"], "TEST_WM")

            rebuilt = Task.from_dict(d)
            self.assertEqual(rebuilt.upload_targets, ["bilibili", "youtube"])
            self.assertEqual(rebuilt.secondary_creation["border_ratio"], 0.05)

            # 2. Test Pipeline Execution with Dual Upload
            fake_vid = Path(tmpdir) / "fake_input.mp4"
            fake_vid.write_bytes(b"dummy_video_data")
            fake_sub = Path(tmpdir) / "fake_sub.srt"
            fake_sub.write_text("1\n00:00:00,000 --> 00:00:05,000\nHello world\n", encoding="utf-8")

            with patch("services.youtube.YouTubeService.extract_info", return_value={"title": "YT Video", "description": "Desc", "language": "en", "is_chinese": False}), \
                 patch("services.youtube.YouTubeService.download_video_and_subtitles", return_value=(fake_vid, fake_sub, {})), \
                 patch("services.video_editor.VideoEditor.process_video", return_value=fake_vid) as mock_editor, \
                 patch("services.bilibili.BilibiliService.upload_video", return_value={"bvid": "BV1DUAL_BILI"}), \
                 patch("services.youtube_uploader.YouTubeUploaderService.upload_video", return_value={"video_id": "YT_DUAL_123", "url": "https://www.youtube.com/watch?v=YT_DUAL_123"}):
                
                mgr._run_task_pipeline(task)

                self.assertEqual(task.status, "COMPLETED")
                self.assertEqual(task.bvid, "BV1DUAL_BILI")
                self.assertEqual(task.youtube_video_id, "YT_DUAL_123")
                self.assertEqual(task.youtube_watch_url, "https://www.youtube.com/watch?v=YT_DUAL_123")
                self.assertTrue(mock_editor.called)

    def test_youtube_api_routes(self):
        from unittest.mock import patch, MagicMock
        from starlette.testclient import TestClient
        from app import app, _get_auth_token, AUTH_COOKIE_NAME
        from config import config_manager

        client = TestClient(app)
        admin_pwd = config_manager.get("admin_password", "admin")
        token = _get_auth_token(admin_pwd)
        client.cookies.set(AUTH_COOKIE_NAME, token)

        # 1. /api/youtube/auth-url
        resp = client.post("/api/youtube/auth-url", json={"client_id": "test_cid.apps.googleusercontent.com"})
        self.assertEqual(resp.status_code, 200)
        self.assertIn("auth_url", resp.json())
        self.assertIn("test_cid", resp.json()["auth_url"])

        # 2. /api/youtube/oauth-callback
        with patch("services.youtube_uploader.YouTubeUploaderService.exchange_code_for_tokens", return_value={"refresh_token": "rt_test_777"}):
            cb_resp = client.post("/api/youtube/oauth-callback", json={
                "code": "auth_code_123",
                "client_id": "cid",
                "client_secret": "csec"
            })
            self.assertEqual(cb_resp.status_code, 200)
            self.assertTrue(cb_resp.json()["has_refresh_token"])
            self.assertEqual(config_manager.get("youtube_refresh_token"), "rt_test_777")

        # 3. /api/youtube/test
        with patch("services.youtube_uploader.YouTubeUploaderService.get_channel_info", return_value={"title": "My Channel", "subscriber_count": "500"}):
            test_resp = client.post("/api/youtube/test", json={
                "client_id": "cid",
                "client_secret": "csec",
                "refresh_token": "rt_test_777"
            })
            self.assertEqual(test_resp.status_code, 200)
            self.assertIn("My Channel", test_resp.json()["message"])

        # 4. /api/tasks with dual targets & secondary creation
        with patch("services.youtube.YouTubeService.extract_items", return_value=[{"url": "https://youtube.com/watch?v=sample1", "custom_text": None}]), \
             patch("services.task_manager.task_manager._run_task_pipeline"):
            task_resp = client.post("/api/tasks", json={
                "youtube_url": "https://youtube.com/watch?v=sample1",
                "skip_subtitles": True,
                "upload_targets": ["bilibili", "youtube"],
                "secondary_creation": {
                    "enabled": True,
                    "flip_horizontal": True,
                    "border_ratio": 0.05,
                    "watermark_enabled": True,
                    "watermark_text": "WATERMARK"
                }
            })
            self.assertEqual(task_resp.status_code, 200)
            data = task_resp.json()
            self.assertTrue(data["success"])
            self.assertEqual(data["task"]["upload_targets"], ["bilibili", "youtube"])
            self.assertEqual(data["task"]["secondary_creation"]["watermark_text"], "WATERMARK")

        # 5. /oauth2callback GET endpoint
        with patch("services.youtube_uploader.YouTubeUploaderService.exchange_code_for_tokens", return_value={"refresh_token": "rt_test_page_999"}):
            config_manager.update({"youtube_client_id": "test_id", "youtube_client_secret": "test_secret"})
            oauth_page_res = client.get("/oauth2callback?code=sample_code_456")
            self.assertEqual(oauth_page_res.status_code, 200)
            self.assertIn("YouTube 账号授权成功", oauth_page_res.text)
            self.assertEqual(config_manager.get("youtube_refresh_token"), "rt_test_page_999")

    def _config_snapshot(self):
        keys = (
            "cookiecloud_url", "cookiecloud_uuid", "cookiecloud_password",
            "youtube_cookies", "bilibili_sessdata", "bilibili_bili_jct", "bilibili_dedeuserid",
            "downloads_dir", "auto_delete_after_upload", "skip_subtitles", "llm_enabled",
        )
        return {key: config_manager.get(key) for key in keys}

    def test_retry_resumes_completed_stages_and_syncs_cookies(self):
        from unittest.mock import patch, MagicMock
        from services.task_manager import Task
        import tempfile

        snapshot = self._config_snapshot()
        with tempfile.TemporaryDirectory() as tmpdir:
            config_manager.update({
                "cookiecloud_url": "https://cc.example.com",
                "cookiecloud_uuid": "uuid-resume",
                "cookiecloud_password": "pwd-resume",
                "youtube_cookies": "stale-yt",
                "bilibili_sessdata": "stale-sess",
                "downloads_dir": tmpdir,
                "auto_delete_after_upload": False,
                "skip_subtitles": False,
                "llm_enabled": False,
            })
            try:
                task = Task(
                    "resume1",
                    "https://youtu.be/resume1",
                    skip_subtitles=True,
                    upload_targets=["bilibili", "youtube"],
                )
                task._manager = task_manager
                task_manager.tasks[task.id] = task
                video = Path(tmpdir) / task.id / "vid.mp4"
                info = {
                    "id": "resume1",
                    "url": task.youtube_url,
                    "title": "Resume Title",
                    "description": "Desc",
                    "language": "zh",
                    "is_chinese": True,
                }
                downloads = {"n": 0}

                def fake_download(url, task_id):
                    downloads["n"] += 1
                    video.parent.mkdir(parents=True, exist_ok=True)
                    video.write_bytes(b"video-bytes")
                    return video, None, info

                yt_seen = []
                bili_seen = []

                def bili_factory(sessdata, bili_jct, dedeuserid, extra_cookies=None):
                    bili_seen.append(dict(extra_cookies or {}))
                    service = MagicMock()
                    service.upload_video.return_value = {"bvid": "BV_RESUME"}
                    return service

                def yt_factory(client_id="", client_secret="", refresh_token=""):
                    service = MagicMock()

                    def upload_video(**kwargs):
                        yt_seen.append(config_manager.get("youtube_cookies"))
                        if len(yt_seen) == 1:
                            raise RuntimeError("yt down")
                        return {"video_id": "yt123", "url": "https://www.youtube.com/watch?v=yt123"}

                    service.upload_video.side_effect = upload_video
                    return service

                with patch("services.task_manager.CookieCloudService") as mock_cc_cls, \
                     patch("services.task_manager.YouTubeService") as mock_yt_cls, \
                     patch("services.task_manager.BilibiliService", side_effect=bili_factory), \
                     patch("services.task_manager.YouTubeUploaderService", side_effect=yt_factory):
                    mock_cc_cls.return_value.fetch_all_synced_cookies.side_effect = [
                        ({"SESSDATA": "sess-1", "bili_jct": "jct-1", "DedeUserID": "11"}, "yt-cookie-1"),
                        ({"SESSDATA": "sess-2", "bili_jct": "jct-2", "DedeUserID": "22"}, "yt-cookie-2"),
                    ]
                    mock_yt = mock_yt_cls.return_value
                    mock_yt.extract_info.return_value = info
                    mock_yt.download_video_and_subtitles.side_effect = fake_download

                    task_manager._run_task_pipeline(task)
                    self.assertEqual(task.status, "FAILED")
                    self.assertIn("download", task.completed_stages)
                    self.assertIn("bilibili_upload", task.completed_stages)
                    self.assertNotIn("youtube_upload", task.completed_stages)
                    self.assertEqual(downloads["n"], 1)
                    self.assertEqual(mock_cc_cls.return_value.fetch_all_synced_cookies.call_count, 1)

                    saved = json.loads(task_manager.file_path.read_text(encoding="utf-8"))
                    reloaded = Task.from_dict(saved[task.id])
                    reloaded._manager = task_manager
                    task_manager.tasks[task.id] = reloaded
                    self.assertEqual(reloaded.stage_artifacts["download"]["video_path"], str(video))
                    self.assertEqual(reloaded.bvid, "BV_RESUME")

                    task_manager._run_task_pipeline(reloaded, resume=True)

                self.assertEqual(downloads["n"], 1)
                self.assertEqual(mock_yt.extract_info.call_count, 1)
                self.assertEqual(len(bili_seen), 1)
                self.assertEqual(bili_seen[0].get("SESSDATA"), "sess-1")
                self.assertEqual(yt_seen, ["yt-cookie-1", "yt-cookie-2"])
                self.assertEqual(config_manager.get("bilibili_sessdata"), "sess-2")
                self.assertEqual(reloaded.status, "COMPLETED")
                self.assertEqual(reloaded.youtube_video_id, "yt123")
                self.assertTrue(any("Skipping download" in line for line in reloaded.logs))
                self.assertTrue(any("Skipping Bilibili upload" in line for line in reloaded.logs))
                self.assertTrue(any("Resume requested" in line for line in reloaded.logs))
            finally:
                task_manager.tasks.pop("resume1", None)
                config_manager.update(snapshot)

    def test_retry_redownloads_corrupt_video(self):
        from unittest.mock import patch, MagicMock
        from services.task_manager import Task
        import tempfile

        snapshot = self._config_snapshot()
        with tempfile.TemporaryDirectory() as tmpdir:
            config_manager.update({
                "cookiecloud_url": "https://cc.example.com",
                "cookiecloud_uuid": "uuid-resume",
                "cookiecloud_password": "pwd-resume",
                "downloads_dir": tmpdir,
                "auto_delete_after_upload": False,
                "skip_subtitles": False,
                "llm_enabled": False,
            })
            try:
                task = Task("resume2", "https://youtu.be/resume2", skip_subtitles=True)
                task._manager = task_manager
                task_manager.tasks[task.id] = task
                video = Path(tmpdir) / task.id / "vid.mp4"
                info = {"id": "resume2", "url": task.youtube_url, "title": "Corrupt", "description": "", "language": "zh", "is_chinese": True}
                downloads = {"n": 0}
                uploads = {"n": 0}

                def fake_download(url, task_id):
                    downloads["n"] += 1
                    video.parent.mkdir(parents=True, exist_ok=True)
                    video.write_bytes(b"video-bytes")
                    return video, None, info

                def bili_factory(*args, **kwargs):
                    service = MagicMock()

                    def upload_video(**upload_kwargs):
                        uploads["n"] += 1
                        if uploads["n"] == 1:
                            raise RuntimeError("bili down")
                        return {"bvid": "BV_AGAIN"}

                    service.upload_video.side_effect = upload_video
                    return service

                with patch("services.task_manager.CookieCloudService") as mock_cc_cls, \
                     patch("services.task_manager.YouTubeService") as mock_yt_cls, \
                     patch("services.task_manager.BilibiliService", side_effect=bili_factory):
                    mock_cc_cls.return_value.fetch_all_synced_cookies.return_value = (
                        {"SESSDATA": "sess-ok", "bili_jct": "jct", "DedeUserID": "1"},
                        "yt-ok",
                    )
                    mock_yt_cls.return_value.extract_info.return_value = info
                    mock_yt_cls.return_value.download_video_and_subtitles.side_effect = fake_download

                    task_manager._run_task_pipeline(task)
                    self.assertEqual(task.status, "FAILED")
                    self.assertIn("download", task.completed_stages)
                    self.assertTrue(video.stat().st_size > 0)
                    video.write_bytes(b"")

                    task_manager._run_task_pipeline(task, resume=True)

                self.assertEqual(downloads["n"], 2)
                self.assertEqual(mock_cc_cls.return_value.fetch_all_synced_cookies.call_count, 2)
                self.assertEqual(uploads["n"], 2)
                self.assertEqual(task.status, "COMPLETED")
                self.assertGreater(video.stat().st_size, 0)
                self.assertGreaterEqual(sum(1 for line in task.logs if "Downloaded video file" in line), 2)
            finally:
                task_manager.tasks.pop("resume2", None)
                config_manager.update(snapshot)

    def test_retry_cookie_sync_failure_stops_before_pipeline(self):
        from unittest.mock import patch, MagicMock
        from services.task_manager import Task
        import tempfile

        snapshot = self._config_snapshot()
        with tempfile.TemporaryDirectory() as tmpdir:
            config_manager.update({
                "cookiecloud_url": "https://cc.example.com",
                "cookiecloud_uuid": "uuid-resume",
                "cookiecloud_password": "pwd-resume",
                "youtube_cookies": "stale-yt",
                "bilibili_sessdata": "stale-sess",
                "downloads_dir": tmpdir,
                "auto_delete_after_upload": False,
                "skip_subtitles": False,
                "llm_enabled": False,
            })
            try:
                task = Task("resume3", "https://youtu.be/resume3", skip_subtitles=True)
                task._manager = task_manager
                task_manager.tasks[task.id] = task
                video = Path(tmpdir) / task.id / "vid.mp4"
                info = {"id": "resume3", "url": task.youtube_url, "title": "Sync Fail", "description": "", "language": "zh", "is_chinese": True}

                def fake_download(url, task_id):
                    video.parent.mkdir(parents=True, exist_ok=True)
                    video.write_bytes(b"video-bytes")
                    return video, None, info

                with patch("services.task_manager.CookieCloudService") as mock_cc_cls, \
                     patch("services.task_manager.YouTubeService") as mock_yt_cls, \
                     patch("services.task_manager.BilibiliService") as mock_bili_cls:
                    mock_cc_cls.return_value.fetch_all_synced_cookies.side_effect = [
                        ({"SESSDATA": "sess-1", "bili_jct": "jct-1", "DedeUserID": "1"}, "yt-cookie-1"),
                        RuntimeError("cloud down"),
                    ]
                    mock_yt = mock_yt_cls.return_value
                    mock_yt.extract_info.return_value = info
                    mock_yt.download_video_and_subtitles.side_effect = fake_download
                    mock_bili_cls.return_value.upload_video.side_effect = RuntimeError("bili down")

                    task_manager._run_task_pipeline(task)
                    self.assertEqual(task.status, "FAILED")
                    video.unlink()

                    task_manager._run_task_pipeline(task, resume=True)

                self.assertEqual(mock_yt.download_video_and_subtitles.call_count, 1)
                self.assertEqual(mock_yt.extract_info.call_count, 1)
                self.assertEqual(mock_bili_cls.return_value.upload_video.call_count, 1)
                self.assertEqual(task.status, "FAILED")
                self.assertEqual(task.current_stage, "cookie_sync")
                self.assertIn("CookieCloud", task.last_error or "")
                self.assertEqual(config_manager.get("youtube_cookies"), "yt-cookie-1")
            finally:
                task_manager.tasks.pop("resume3", None)
                config_manager.update(snapshot)

    def test_retry_api_keeps_artifacts_and_fresh_tasks_do_not_resume(self):
        from unittest.mock import patch
        from services.task_manager import Task

        task = Task("retryapi1", "https://youtu.be/retryapi")
        task.status = "FAILED"
        task.progress = 55
        task.completed_stages = ["metadata", "download"]
        task.stage_artifacts = {"download": {"video_path": "/tmp/keep.mp4", "sub_path": None}}
        task.logs = ["kept-log"]
        task.current_stage = "edit"
        task.last_error = "upload boom"
        task_manager.tasks[task.id] = task
        try:
            with patch("services.task_manager.threading.Thread") as thread_cls:
                res = self.client.post(f"/api/tasks/{task.id}/retry")
                start = self.client.post(f"/api/tasks/{task.id}/start")
                created = task_manager.create_task("https://youtu.be/freshitem", skip_subtitles=True)
            self.assertEqual(res.status_code, 200)
            self.assertIn("CookieCloud", res.json()["message"])
            body = res.json()["task"]
            self.assertIn("download", body["completed_stages"])
            self.assertEqual(body["stage_artifacts"]["download"]["video_path"], "/tmp/keep.mp4")
            self.assertEqual(body["progress"], 55)
            self.assertTrue(any("kept-log" in line for line in body["logs"]))
            self.assertIn("CookieCloud", start.json()["message"])
            self.assertEqual(thread_cls.call_args_list[0].kwargs["kwargs"], {"resume": True})
            self.assertEqual(thread_cls.call_args_list[1].kwargs["kwargs"], {"resume": True})
            self.assertNotIn("kwargs", thread_cls.call_args_list[2].kwargs)
            task_manager.tasks.pop(created.id, None)
        finally:
            task_manager.tasks.pop(task.id, None)

    def test_cancel_stops_resume_before_work(self):
        from services.task_manager import Task

        task = Task("resume-cancel", "https://youtu.be/cancelme", skip_subtitles=True)
        task.cancelled = True
        task.status = "CANCELLED"
        task_manager.tasks[task.id] = task
        try:
            task_manager._run_task_pipeline(task, resume=True)
            self.assertEqual(task.status, "CANCELLED")
            self.assertIsNone(task.last_error)
            self.assertTrue(any("cancellation" in line for line in task.logs))
        finally:
            task_manager.tasks.pop(task.id, None)

    def test_bilibili_upload_preflight_invalid_credentials(self):
        from unittest.mock import patch
        from services.bilibili import BilibiliService
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            fake_vid = Path(tmpdir) / "test.mp4"
            fake_vid.write_bytes(b"dummy")

            service = BilibiliService(sessdata="invalid_sess", bili_jct="jct", dedeuserid="123")
            with patch.object(service, "validate_credentials", return_value={"valid": False, "message": "账号未登录"}):
                with self.assertRaises(RuntimeError) as ctx:
                    service.upload_video(video_path=fake_vid, title="Title", description="Desc", tags=["test"])
                self.assertIn("Bilibili 登录凭据无效或已失效 (账号未登录)", str(ctx.exception))
                self.assertIn("CookieCloud", str(ctx.exception))

    def test_cookiecloud_sync_api_bilibili_validation(self):
        from unittest.mock import patch

        dummy_cookies = {"SESSDATA": "fake_sess", "bili_jct": "fake_jct", "DedeUserID": "888"}

        with patch("services.cookiecloud.CookieCloudService.fetch_all_synced_cookies", return_value=(dummy_cookies, "fake_yt")), \
             patch("services.bilibili.BilibiliService.validate_credentials", return_value={"valid": True, "uname": "TestUser", "mid": 888, "level": 6}):
            resp = self.client.post("/api/cookiecloud/sync", json={
                "cookiecloud_url": "https://cc.example.com",
                "cookiecloud_uuid": "uuid",
                "cookiecloud_password": "pass"
            })
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertTrue(data["success"])
            self.assertIn("已验证用户: TestUser", data["message"])
            self.assertTrue(data["bilibili_check"]["valid"])


if __name__ == "__main__":
    unittest.main()

