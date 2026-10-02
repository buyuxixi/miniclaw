"""Create only missing local configuration; never overwrite credentials."""

import os
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ["HERMES_HOME"] = str(ROOT / ".hermes")

from hermes_cli.config import atomic_config_write


def main():
    home = ROOT / ".hermes"
    home.mkdir(exist_ok=True)
    env_path = home / ".env"
    if not env_path.exists():
        shutil.copyfile(ROOT / ".env.example", env_path)
    config_path = home / "config.yaml"
    if not config_path.exists():
        atomic_config_write(config_path, {
            "model": {"default": "deepseek-flash", "provider": "deepseek", "base_url": "https://api.deepseek.com/v1"},
            "platform_toolsets": {"cli": ["miniclaw-files"]},
            "tools": {"tool_search": {"enabled": "off"}},
            "agent": {"max_turns": 12, "run_budget_seconds": 180, "disabled_toolsets": ["delegation", "memory", "session_search", "project", "desktop_ui"]},
            "terminal": {"backend": "local", "cwd": str(ROOT / "workspace")},
            "memory": {"memory_enabled": False, "user_profile_enabled": False},
            "curator": {"enabled": False},
            "auxiliary": {"background_review": {"enabled": False}, "title_generation": {"model_upgrade_enabled": False}},
            "plugins": {"enabled": ["miniclaw-files"], "entries": {"miniclaw-files": {"settings": {"workspace": str(ROOT / "workspace")}}}},
        })
    print(f"Configuration: {config_path}")
    print(f"Credentials: {env_path} (values not displayed)")


if __name__ == "__main__":
    main()
