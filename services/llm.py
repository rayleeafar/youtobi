import time
import requests
import logging
from typing import Dict, Any, Optional, List
import openai

logger = logging.getLogger("youtobi.llm")

class LLMService:
    def __init__(self, config: Dict[str, Any]):
        self.config = config

    @staticmethod
    def fetch_models(api_key: str, base_url: str) -> List[str]:
        """Fetch available models list from LLM provider."""
        if not api_key:
            raise ValueError("API Key 不能为空。")
        url = base_url.rstrip("/") if base_url else "https://api.openai.com/v1"
        try:
            client = openai.OpenAI(api_key=api_key, base_url=url)
            models_res = client.models.list()
            model_ids = [m.id for m in models_res.data]
            return sorted(model_ids)
        except Exception as e:
            try:
                headers = {"Authorization": f"Bearer {api_key}"}
                r = requests.get(f"{url}/models", headers=headers, timeout=10)
                r.raise_for_status()
                data = r.json()
                models_list = data.get("data", [])
                return sorted([m["id"] for m in models_list if isinstance(m, dict) and "id" in m])
            except Exception as http_e:
                raise ValueError(f"无法从 LLM API 获取模型列表: {e}")

    @staticmethod
    def test_connection(api_key: str, base_url: str, model: str) -> Dict[str, Any]:
        """Test model availability and response latency."""
        if not api_key:
            raise ValueError("API Key 不能为空。")
        url = base_url.rstrip("/") if base_url else "https://api.openai.com/v1"
        model_name = model.strip() if model else "gpt-4o-mini"

        start_time = time.time()
        try:
            client = openai.OpenAI(api_key=api_key, base_url=url)
            res = client.chat.completions.create(
                model=model_name,
                messages=[{"role": "user", "content": "Hello"}],
                max_tokens=10,
                timeout=15
            )
            latency_ms = int((time.time() - start_time) * 1000)
            reply = res.choices[0].message.content or "OK"
            return {
                "success": True,
                "latency_ms": latency_ms,
                "reply": reply.strip(),
                "model": model_name
            }
        except Exception as e:
            raise ValueError(f"模型测试失败: {e}")


    def is_enabled(self) -> bool:
        enabled = self.config.get("llm_enabled", False)
        api_key = self.config.get("llm_api_key", "").strip()
        return bool(enabled and api_key)

    def regenerate_description(
        self,
        source_title: str,
        source_description: str,
        source_language: str = "en",
        max_retries: int = 3,
        task_logger: Optional[Any] = None
    ) -> Dict[str, Any]:
        """
        Regenerates description, title, and tags for Bilibili based on source YouTube info.
        Retries up to max_retries (3 times) on error.
        If all retries fail or LLM is disabled, falls back to original native description & title.
        """
        if not self.is_enabled():
            logger.info("LLM is disabled or API key not set. Using native source description.")
            return {
                "title": source_title,
                "description": source_description,
                "tags": ["YouTube", "搬运", "视频"],
                "used_llm": False
            }

        api_key = self.config.get("llm_api_key", "")
        base_url = self.config.get("llm_base_url", "https://api.openai.com/v1").rstrip("/")
        model = self.config.get("llm_model", "gpt-4o-mini")

        prompt = f"""你是一个优秀的B站视频运营专家。请根据以下YouTube视频信息，为B站视频重新撰写并优化标题、简洁生动的中文简介、以及推荐的视频标签。

YouTube视频原标题: {source_title}
YouTube视频原简介:
{source_description[:2000]}

请按以下JSON格式返回结果，确保输出为合法JSON字符串：
{{
  "title": "精炼且吸引人的中文标题（控制在30字以内）",
  "description": "吸引B站用户的生动简介（包含精彩看点、相关背景说明，末尾加上“视频来源：YouTube”等来源声明）",
  "tags": ["标签1", "标签2", "标签3", "标签4", "标签5"]
}}
"""

        last_error = None
        for attempt in range(1, max_retries + 1):
            try:
                log_msg = f"Calling LLM provider (attempt {attempt}/{max_retries}, model: {model})..."
                logger.info(log_msg)
                if task_logger:
                    task_logger(log_msg)

                client = openai.OpenAI(api_key=api_key, base_url=base_url)
                response = client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": "你是一个熟知B站文化与推荐机制的资深视频运营者，精通多语言转中文B站文案创作。"},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.7,
                    response_format={"type": "json_object"},
                    timeout=30
                )
                content = response.choices[0].message.content
                import json
                parsed = json.loads(content)
                
                new_title = parsed.get("title") or source_title
                new_desc = parsed.get("description") or source_description
                new_tags = parsed.get("tags") or ["YouTube", "搬运", "视频"]

                return {
                    "title": new_title,
                    "description": new_desc,
                    "tags": new_tags,
                    "used_llm": True
                }
            except Exception as e:
                last_error = e
                err_msg = f"LLM attempt {attempt}/{max_retries} failed: {e}"
                logger.warning(err_msg)
                if task_logger:
                    task_logger(err_msg)
                if attempt < max_retries:
                    time.sleep(1.5 * attempt)

        # Fallback to native source description if all retries failed
        fallback_msg = f"All {max_retries} LLM attempts failed ({last_error}). Falling back to native source description."
        logger.error(fallback_msg)
        if task_logger:
            task_logger(fallback_msg)

        return {
            "title": source_title,
            "description": source_description,
            "tags": ["YouTube", "搬运", "视频"],
            "used_llm": False,
            "error": str(last_error)
        }
