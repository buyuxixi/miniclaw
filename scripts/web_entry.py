"""Normal dashboard lifecycle, with app-owned adapters installed explicitly."""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'hermes-agent')]
from miniclaw_web.identity import install_identity
from hermes_cli.config import get_hermes_home
install_identity(ROOT, get_hermes_home())
from miniclaw_web.hermes_clarification_adapter import verify_compatibility
verify_compatibility(ROOT)
from hermes_cli import web_server
from miniclaw_web.runtime import install
install(web_server.app, ROOT)
from hermes_cli.main import main
if __name__ == '__main__':
    main()
