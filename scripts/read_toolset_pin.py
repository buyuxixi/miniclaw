"""Bridge the configured selection to Hermes' existing operator pin.

The GUI resolver folds client tools back in after CLI configuration. Its
explicit HERMES_TUI_TOOLSETS pin replaces that fold-in and coding defaults.
"""
from __future__ import annotations

import os
import contextlib
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
os.environ['HERMES_HOME'] = str(ROOT / '.hermes')


def main() -> None:
    raw = yaml.safe_load((ROOT / '.hermes' / 'config.yaml').read_text(encoding='utf-8'))
    selection = (raw.get('platform_toolsets') or {}).get('cli')
    if isinstance(selection, list) and 'miniclaw-skills' in selection and (raw.get('skills') or {}).get('inline_shell'):
        raise ValueError('miniclaw-skills requires skills.inline_shell=false; refusing implicit shell execution')
    if not isinstance(selection, list) or not selection or any(
        not isinstance(name, str) or not re.fullmatch(r'[\w.:-]+', name) or name == 'all'
        for name in selection
    ):
        raise ValueError('platform_toolsets.cli must be a non-empty explicit toolset list')
    from hermes_cli.plugins import discover_plugins
    from toolsets import validate_toolset

    with contextlib.redirect_stdout(sys.stderr):
        discover_plugins()
    if any(not validate_toolset(name) for name in selection):
        raise ValueError('Unknown configured toolset; refusing an all-tools fallback')
    print(','.join(selection))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, TypeError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
