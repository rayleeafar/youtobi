import logging
import urllib.request
import urllib.parse
import json
import socket
import time
from typing import Dict, Any, Optional, List, Tuple
from config import config_manager

logger = logging.getLogger("youtobi.proxy")

class ProxyPoolService:
    @staticmethod
    def get_pool_base_url() -> str:
        cfg = config_manager.all()
        url = str(cfg.get("proxy_pool_url") or "http://192.168.4.223:8088").strip()
        return url.rstrip("/")

    @staticmethod
    def fetch_pool_status() -> Dict[str, Any]:
        """Fetch general status, active nodes and tunnel status from ProxyPool."""
        base_url = ProxyPoolService.get_pool_base_url()
        try:
            req = urllib.request.Request(f"{base_url}/api/status", headers={"User-Agent": "youtobi/1.0"})
            with urllib.request.urlopen(req, timeout=3) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return {"online": True, "data": data}
        except Exception as e:
            return {"online": False, "error": str(e)}

    @staticmethod
    def fetch_nodes() -> List[Dict[str, Any]]:
        """Fetch running/available proxy nodes from ProxyPool."""
        base_url = ProxyPoolService.get_pool_base_url()
        try:
            req = urllib.request.Request(f"{base_url}/api/proxy/list", headers={"User-Agent": "youtobi/1.0"})
            with urllib.request.urlopen(req, timeout=3) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                if isinstance(data, list):
                    return data
        except Exception as e:
            logger.debug(f"fetch_nodes error: {e}")
        return []

    @staticmethod
    def fetch_tunnel_info() -> Optional[Dict[str, Any]]:
        """Fetch tunnel pool details (port, http_proxy, active_nodes)."""
        base_url = ProxyPoolService.get_pool_base_url()
        try:
            req = urllib.request.Request(f"{base_url}/api/proxy/tunnel", headers={"User-Agent": "youtobi/1.0"})
            with urllib.request.urlopen(req, timeout=3) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            logger.debug(f"fetch_tunnel_info error: {e}")
            return None

    @staticmethod
    def fetch_fastest_node() -> Optional[Dict[str, Any]]:
        """Fetch lowest-latency proxy node."""
        base_url = ProxyPoolService.get_pool_base_url()
        try:
            req = urllib.request.Request(f"{base_url}/api/proxy/fastest", headers={"User-Agent": "youtobi/1.0"})
            with urllib.request.urlopen(req, timeout=3) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            logger.debug(f"fetch_fastest_node error: {e}")
            return None

    @staticmethod
    def test_proxy(proxy_url: str, test_target: str = "https://cloudflare.com/cdn-cgi/trace", timeout_sec: int = 5) -> Dict[str, Any]:
        """Test a proxy URL directly and extract latency and exit IP."""
        if not proxy_url:
            return {"success": False, "error": "Proxy URL is empty"}
        
        t0 = time.time()
        try:
            handler = urllib.request.ProxyHandler({
                "http": proxy_url,
                "https": proxy_url
            })
            opener = urllib.request.build_opener(handler)
            req = urllib.request.Request(test_target, headers={"User-Agent": "curl/8.7.1"})
            with opener.open(req, timeout=timeout_sec) as resp:
                body = resp.read().decode("utf-8", errors="ignore")
                latency_ms = int((time.time() - t0) * 1000)
                
                exit_ip = None
                for line in body.splitlines():
                    if line.startswith("ip="):
                        exit_ip = line.split("=", 1)[1].strip()
                        break
                
                return {
                    "success": True,
                    "latency_ms": latency_ms,
                    "exit_ip": exit_ip or "detected",
                    "status_code": resp.status,
                    "proxy_url": proxy_url
                }
        except Exception as e:
            latency_ms = int((time.time() - t0) * 1000)
            return {
                "success": False,
                "latency_ms": latency_ms,
                "error": str(e),
                "proxy_url": proxy_url
            }

    @staticmethod
    def resolve_proxy_url(
        task_proxy_mode: Optional[str] = None,
        task_proxy_url: Optional[str] = None,
        ignore_enabled: bool = False
    ) -> Optional[str]:
        """
        Determines the actual proxy URL to use for a task or probe test.
        If task specifies custom settings, uses them; otherwise falls back to global settings.
        If ignore_enabled=True, resolves the configured proxy URL even if global proxy_enabled is False.
        
        Returns:
            - None: direct connection (no proxy)
            - str: "http://..." or "socks5://..."
        """
        cfg = config_manager.all()
        
        # Check task override first
        mode = task_proxy_mode if task_proxy_mode else ("global" if not task_proxy_mode else task_proxy_mode)
        
        if mode == "direct":
            return None
        
        if mode == "custom":
            custom_url = (task_proxy_url or "").strip()
            return custom_url if custom_url else None
        
        if mode == "node":
            node_url = (task_proxy_url or "").strip()
            return node_url if node_url else None

        # If mode is "global" (or None), evaluate global config
        if mode == "global" or not task_proxy_mode:
            if not ignore_enabled and not cfg.get("proxy_enabled", False):
                return None
            global_mode = cfg.get("proxy_mode", "pool_tunnel")
            
            if global_mode == "direct":
                return None
            elif global_mode == "custom":
                return (cfg.get("proxy_custom_url") or "").strip() or None
            elif global_mode == "pool_fastest":
                fastest = ProxyPoolService.fetch_fastest_node()
                if fastest:
                    return fastest.get("http_proxy") or fastest.get("socks5_proxy")
                # Fallback to tunnel if fastest not found
                tunnel = ProxyPoolService.fetch_tunnel_info()
                if tunnel:
                    return tunnel.get("http_proxy") or tunnel.get("socks5_proxy")
                return None
            elif global_mode == "pool_tunnel":
                tunnel = ProxyPoolService.fetch_tunnel_info()
                if tunnel:
                    return tunnel.get("http_proxy") or tunnel.get("socks5_proxy")
                # If tunnel info API fails, construct default tunnel address from pool base url
                pool_url = ProxyPoolService.get_pool_base_url()
                parsed = urllib.parse.urlparse(pool_url)
                host = parsed.hostname or "127.0.0.1"
                return f"http://{host}:10808"

        return None
