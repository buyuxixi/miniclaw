"""Normal dashboard lifecycle, with app-owned adapters installed explicitly."""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'hermes-agent')]
from hermes_cli import web_server
from miniclaw_web.runtime import install
install(web_server.app, ROOT)
from hermes_cli.main import main
if __name__ == '__main__':
    main()
