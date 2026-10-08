"""Exercise package installation, partial repair and preservation of local edits."""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from miniclaw_web.bundled_skills import install_bundled_skills, migrate_canvas_binding, CANVAS_TOOLS, LEGACY_CANVAS_HASH


class BundledSkills(unittest.TestCase):
    def test_known_canvas_installation_upgrades_with_backup_and_preserves_user_edits(self):
        import hashlib
        legacy = (ROOT/'tests/fixtures/canvas-editor-v1.md').read_text(encoding='utf-8')
        self.assertEqual(hashlib.sha256(legacy.encode()).hexdigest(),LEGACY_CANVAS_HASH)
        with tempfile.TemporaryDirectory() as directory:
            home=Path(directory); target=home/'skills/canvas-editor/SKILL.md'
            target.parent.mkdir(parents=True); target.write_text(legacy,encoding='utf-8')
            install_bundled_skills(ROOT,home)
            self.assertEqual(target.read_bytes(),(ROOT/'skills/canvas-editor/SKILL.md').read_bytes())
            self.assertEqual((home/'skill-backups/canvas-editor'/f'{LEGACY_CANVAS_HASH}.md').read_text(encoding='utf-8'),legacy)
            target.write_text('my customized instructions',encoding='utf-8')
            install_bundled_skills(ROOT,home)
            self.assertEqual(target.read_text(encoding='utf-8'),'my customized instructions')

    def test_known_canvas_declaration_upgrade_preserves_custom_bindings(self):
        content = (ROOT/'skills/canvas-editor/SKILL.md').read_text(encoding='utf-8')
        prior = dict(version=1,required_tools=CANVAS_TOOLS[:-1],content_hash=LEGACY_CANVAS_HASH)
        result = migrate_canvas_binding(ROOT,'canvas-editor',content,prior)
        self.assertEqual(result['required_tools'],CANVAS_TOOLS)
        self.assertNotEqual(result['content_hash'],LEGACY_CANVAS_HASH)
        self.assertIsNone(migrate_canvas_binding(ROOT,'canvas-editor',content+'\nuser edit',prior))
        self.assertIsNone(migrate_canvas_binding(ROOT,'canvas-editor',content,{**prior,'required_tools':[]}))
        self.assertIsNone(migrate_canvas_binding(ROOT,'canvas-editor',content,{**prior,'content_hash':'user version'}))

    def test_install_is_complete_and_repeated_prepare_preserves_edits(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            install_bundled_skills(ROOT, home)
            skill = home / 'skills/mono-color'
            catalog = skill / 'design-system/colors.json'
            self.assertTrue((skill / 'LICENSE').is_file())
            self.assertTrue((skill / 'references/design-guide.md').is_file())
            self.assertTrue((home / 'skills/spoken-script/SKILL.md').is_file())
            self.assertEqual((home/'skills/creative/product-prompt-optimize/SKILL.md').read_bytes(),(ROOT/'skills/product-prompt-optimize/SKILL.md').read_bytes())
            install_bundled_skills(ROOT,home)
            self.assertFalse((home/'skills/product-prompt-optimize/SKILL.md').exists(), 'Do not install a second copy outside the native category')
            original = catalog.read_bytes()
            catalog.unlink()
            install_bundled_skills(ROOT, home)
            self.assertEqual(catalog.read_bytes(), original)
            catalog.write_text('local catalog edit', encoding='utf-8')
            install_bundled_skills(ROOT, home)
            self.assertEqual(catalog.read_text(encoding='utf-8'), 'local catalog edit')
            (skill / 'SKILL.md').write_text('local instructions', encoding='utf-8')
            catalog.unlink()
            install_bundled_skills(ROOT, home)
            self.assertEqual((skill / 'SKILL.md').read_text(encoding='utf-8'), 'local instructions')
            self.assertFalse(catalog.exists(), 'Do not mix a bundled package into a different local skill')


if __name__ == '__main__':
    unittest.main()
