"""
ChatGPT Team 促销码扫描工具 — 配置模块

配置优先级: 环境变量 > config.toml > 默认值

必要配置:
  - OPENAI_TOKEN: ChatGPT accessToken（从浏览器 F12 获取）

可选配置:
  - CLASH_SOCKET: Clash Verge Unix socket 路径
  - HTTP_PROXY: HTTP 代理地址
"""
import os
try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:
    import tomli as tomllib  # Python < 3.11, pip install tomli
from pathlib import Path

CONFIG_FILE = Path(__file__).parent / "config.toml"

_config = {}


def _load_config():
    """读取 config.toml（如果存在）"""
    global _config
    if _config:
        return _config
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "rb") as f:
                _config = tomllib.load(f)
        except Exception:
            _config = {}
    else:
        _config = {}
    return _config


def get_token() -> str:
    """获取 OpenAI accessToken"""
    # 1. 环境变量
    token = os.getenv("OPENAI_TOKEN")
    if token:
        return token

    # 2. config.toml
    cfg = _load_config()
    token = cfg.get("openai", {}).get("token")
    if token:
        return token

    raise ValueError(
        "未设置 OPENAI_TOKEN\n"
        "  方式一: export OPENAI_TOKEN='...'\n"
        "  方式二: 在 config.toml 中设置 [openai] token = '...'\n\n"
        "获取方法:\n"
        "  1. 浏览器登录 chatgpt.com\n"
        "  2. F12 → Console\n"
        "  3. 执行:\n"
        "     const s = await (await fetch('/api/auth/session')).json();\n"
        "     console.log(s.accessToken);\n"
        "     复制输出的字符串"
    )


def get_clash_socket() -> str:
    """获取 Clash Verge Unix socket 路径"""
    env = os.getenv("CLASH_SOCKET")
    if env:
        return env
    cfg = _load_config()
    return cfg.get("clash", {}).get("socket", "/tmp/verge/verge-mihomo.sock")


def get_clash_controller() -> str:
    """获取 Clash external-controller 地址"""
    env = os.getenv("CLASH_CONTROLLER")
    if env:
        return env
    cfg = _load_config()
    return cfg.get("clash", {}).get("controller", "http://127.0.0.1:9097")


def get_clash_secret() -> str:
    """获取 Clash external-controller secret"""
    env = os.getenv("CLASH_SECRET")
    if env:
        return env
    cfg = _load_config()
    return cfg.get("clash", {}).get("secret", "")


def get_proxy_url() -> str:
    """获取 HTTP 代理地址"""
    env = os.getenv("HTTP_PROXY") or os.getenv("http_proxy") or os.getenv("HTTPS_PROXY") or os.getenv("https_proxy")
    if env:
        return env
    cfg = _load_config()
    return cfg.get("proxy", {}).get("url", "http://127.0.0.1:7890")


def get_proxy_group(mode: str) -> str:
    """根据 Clash 模式返回对应的代理组名
    rule → 🤖 AI    global → GLOBAL
    """
    cfg = _load_config()
    groups = cfg.get("clash", {}).get("proxy_groups", {})
    if mode == "global":
        return groups.get("global", "GLOBAL")
    return groups.get("rule", "🤖 AI")


def get_output_dir():
    """获取输出目录（默认为脚本所在目录）"""
    return os.path.dirname(os.path.abspath(__file__))
