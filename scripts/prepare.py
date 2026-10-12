"""Create only missing local configuration; never overwrite credentials."""

import os
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ["HERMES_HOME"] = str(ROOT / ".hermes")

from hermes_cli.config import atomic_config_write
from miniclaw_web.bundled_skills import install_bundled_skills


def main():
    home = ROOT / ".hermes"
    home.mkdir(exist_ok=True)
    from miniclaw_web.identity import install_identity
    print(f"Luka identity: {install_identity(ROOT, home)}")
    env_path = home / ".env"
    if not env_path.exists():
        shutil.copyfile(ROOT / ".env.example", env_path)
    config_path = home / "config.yaml"
    if not config_path.exists():
        atomic_config_write(config_path, {
            "model": {"default": "deepseek-flash", "provider": "deepseek", "base_url": "https://api.deepseek.com/v1"},
            "platform_toolsets": {"cli": ["miniclaw-files", "clarify"]},
            "tools": {"tool_search": {"enabled": "off"}},
            "agent": {"max_turns": 12, "run_budget_seconds": 180, "disabled_toolsets": ["delegation", "memory", "session_search", "project", "desktop_ui"]},
            "terminal": {"backend": "local", "cwd": str(ROOT / "workspace")},
            "memory": {"memory_enabled": False, "user_profile_enabled": False},
            "curator": {"enabled": False},
            "auxiliary": {"background_review": {"enabled": False}, "title_generation": {"model_upgrade_enabled": False}},
            "plugins": {"enabled": ["miniclaw-files"], "entries": {"miniclaw-files": {"settings": {"workspace": str(ROOT / "workspace")}}}},
        })
    print(f"Configuration: {config_path}")
    # Add missing host defaults; preserve credentials and existing user settings.
    import yaml
    configured = yaml.safe_load(config_path.read_text(encoding='utf-8')) or {}
    toolsets = configured.setdefault('platform_toolsets', {}).setdefault('cli', ['miniclaw-files'])
    if 'clarify' not in toolsets:
        toolsets.append('clarify')
    if 'miniclaw-documents' not in toolsets:
        toolsets.append('miniclaw-documents')
    from miniclaw_web.chat_recovery import RecoveryPolicy
    from dataclasses import asdict
    recovery = configured.setdefault('miniclaw', {}).setdefault('chat_recovery', {})
    for key, value in asdict(RecoveryPolicy()).items():
        recovery.setdefault(key, value)
    # Use the same China-region service as existing image edits. Custom deployments
    # can override the chat endpoint without changing media service configuration.
    if 'fallback_providers' not in configured and 'fallback_model' not in configured:
        configured['fallback_providers'] = [{
            'provider': 'custom', 'model': 'qwen-plus', 'key_env': 'DASHSCOPE_API_KEY',
            'base_url': os.environ.get('MINICLAW_CHAT_FALLBACK_BASE_URL',
                                       'https://dashscope.aliyuncs.com/compatible-mode/v1'),
            'api_mode': 'chat_completions',
        }]
    RecoveryPolicy.from_config(configured)
    atomic_config_write(config_path, configured)
    print(f"Credentials: {env_path} (values not displayed)")
    install_bundled_skills(ROOT, home)


if __name__ == "__main__":
    main()
