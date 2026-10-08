"""App-owned skill packages; support files are installed without replacing edits."""
import json
import shutil
import hashlib
from pathlib import Path

CANVAS_TOOLS = ['miniclaw_canvas_view', 'miniclaw_canvas_region', 'miniclaw_canvas_ai', 'miniclaw_canvas_job', 'miniclaw_canvas_propose']
LEGACY_CANVAS_HASH = 'ebdfd4a30892d585e55c50758aa8069727d7508aa1f6d6b2d92664d020a87ab7'


def migrate_canvas_binding(root, name, content, declared):
    """Upgrade only the exact prior built-in declaration, never user custom bindings."""
    source = Path(root) / 'skills/canvas-editor/SKILL.md'
    if (name == 'canvas-editor' and source.is_file() and content == source.read_text(encoding='utf-8')
            and declared.get('content_hash') == LEGACY_CANVAS_HASH
            and declared.get('version') == 1
            and set(declared.get('required_tools', [])) == set(CANVAS_TOOLS[:-1])):
        return dict(version=1, required_tools=CANVAS_TOOLS[:], content_hash=hashlib.sha256(content.encode()).hexdigest())
    return None


CREATOR_SKILLS = {
    'product-prompt-optimize': {'tools': [], 'resources': [], 'extras': [], 'category': 'creative'},
    'product-video-plan': {'tools': [], 'resources': [], 'extras': []},
    'mono-color': {
        'tools': ['skill_view'],
        'resources': [
            'references/design-guide.md',
            'design-system/colors.json', 'design-system/compositions.json',
            'design-system/typography.json', 'design-system/carriers.json',
            'design-system/rhythm.json', 'design-system/imperfections.json',
        ],
        'extras': ['LICENSE', 'UPSTREAM.json'],
    },
    'spoken-script': {'tools': [], 'resources': [], 'extras': []},
    'overlay-plan': {'tools': ['miniclaw_overlay_compile'], 'resources': [], 'extras': []},
}


def install_bundled_skills(root, home):
    """Repair missing support files only for the unchanged, bundled entry point."""
    root, home = Path(root), Path(home)
    installed = []
    for name in ('product-image-edit', 'canvas-editor', *CREATOR_SKILLS):
        source = root / 'skills' / name
        entry = source / 'SKILL.md'
        if not entry.is_file():
            continue
        spec = CREATOR_SKILLS.get(name, {})
        target = home / 'skills' / spec.get('category', '') / name
        existing = target / 'SKILL.md'
        if existing.exists() and existing.read_bytes() != entry.read_bytes():
            if name == 'canvas-editor' and hashlib.sha256(existing.read_text(encoding='utf-8').encode()).hexdigest() == LEGACY_CANVAS_HASH:
                backup = home / 'skill-backups/canvas-editor' / (LEGACY_CANVAS_HASH + '.md')
                backup.parent.mkdir(parents=True, exist_ok=True)
                if not backup.exists():
                    shutil.copyfile(existing, backup)
                shutil.copyfile(entry, existing)
                installed.append('canvas-editor/SKILL.md (known bundled upgrade)')
            else:
                continue
        for relative in ['SKILL.md', *spec.get('resources', []), *spec.get('extras', [])]:
            original, destination = source / relative, target / relative
            if not original.is_file():
                raise ValueError(f'内置技能 {name} 缺少文件：{relative}')
            if not destination.exists():
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(original, destination)
                installed.append(f'{name}/{relative}')
    return installed


def creator_binding(root, name, skill_dir, content):
    """Assess only our exact wrapper. User-authored instructions remain unverified."""
    spec = CREATOR_SKILLS.get(name)
    source = Path(root) / 'skills' / name / 'SKILL.md'
    if not spec or not source.is_file() or content != source.read_text(encoding='utf-8'):
        return None
    issue = None
    directory = Path(skill_dir).resolve()
    for relative in spec['resources']:
        path = directory / relative
        try:
            path.resolve().relative_to(directory)
            if not path.is_file():
                raise ValueError()
            if path.suffix == '.json':
                data = json.loads(path.read_text(encoding='utf-8'))
                if not isinstance(data, dict) or data.get('schema_version') != 1:
                    raise ValueError()
        except (OSError, UnicodeError, ValueError):
            issue = f'配套资料缺失或不可用：{relative}。请运行 prepare 补齐缺失文件；已有修改不会被覆盖。'
            break
    return {'required_tools': list(spec['tools']), 'resource_error': issue}
