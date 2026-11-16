"""Verified, warm, public-only HAIC engine for the MCP adapter.

Startup order: pinned release manifest -> every listed file's bytes -> declared source identity ->
import districtbrief from the same checkout -> loaded-module audit -> public packet/metadata
verification (the engine's own loaders) -> interpretation rules read from verified provider source
text by AST, without importing the provider.
"""
from __future__ import annotations

import ast
import hashlib
import json
import re
import sys
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
DEFAULT_ROOT = PACKAGE_DIR.parent
PIN = json.loads((PACKAGE_DIR / 'engine-pin.json').read_text(encoding='utf-8'))
CONNECTOR_NAME = 'haic-mcp'
CONNECTOR_VERSION = '0.1.0'
SESSION = 'haic-mcp-stateless'  # constant: no per-user session exists in this adapter

# Modules that carry provider transport, model jobs, funding/accounting or the website app.
FORBIDDEN_MODULES = ('districtbrief.ia_language_provider', 'districtbrief.ia_language_jobs',
                     'districtbrief.ia_language_funding', 'districtbrief.ia_language_accounting',
                     'districtbrief.ia_language_profiles', 'public_app', 'wsgi', 'openai')

# The provider builds its recipe-name list with exactly this expression; startup requires the same AST.
RECIPE_NAMES_EXPRESSION = ("'; '.join(' or '.join(f'\"{n}\"' for n in names)+' = '+issue "
                           "for issue,names in RECIPE_LABELS.items())")
TRANSPORT_SENTENCE = 'Return exactly one ia_language_decision function call.'
MCP_TRANSPORT_SENTENCE = 'Return one complete decision object matching decision_schema to validate_proposal.'
RULES_HEADER = ('INTERPRETATION PHASE RULES. These rules apply only while turning the user question into one '
                'decision object for validate_proposal. They do not restrict narrating facts that run_plan, '
                'inspect_source or build_brief later return.\n')
RULES_FOOTER = '\nEND OF INTERPRETATION PHASE RULES.'


class StartupError(RuntimeError):
    pass


def _sha256_file(path: Path) -> tuple[str, int]:
    h = hashlib.sha256()
    size = 0
    with open(path, 'rb') as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b''):
            h.update(chunk)
            size += len(chunk)
    return h.hexdigest(), size


def verify_release(root: Path, expected_sha256: str) -> dict:
    """Verify the pinned manifest and every file it lists. Extra files (this package) are allowed."""
    path = root / 'RELEASE-MANIFEST.json'
    if path.is_symlink() or not path.is_file():
        raise StartupError('release manifest missing')
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise StartupError('release manifest does not match the pinned SHA-256')
    manifest = json.loads(raw)
    rows = manifest.get('files')
    if not isinstance(rows, list) or not rows:
        raise StartupError('release manifest lists no files')
    for row in rows:
        rel = row['path']
        target = root / rel
        if '..' in Path(rel).parts or target.is_symlink() or not target.is_file():
            raise StartupError('listed release file missing: ' + rel)
        digest, size = _sha256_file(target)  # streamed; fixture contents are never parsed or logged
        if (digest, size) != (row['sha256'], row['bytes']):
            raise StartupError('listed release file changed: ' + rel)
    ordered = sorted(rows, key=lambda r: r['path'].encode('utf-8'))
    lines = ''.join(f"{r['sha256']}  {r['bytes']}  {r['path']}\n" for r in ordered)
    if 'sha256:' + hashlib.sha256(lines.encode('utf-8')).hexdigest() != manifest.get('source_identity'):
        raise StartupError('declared source identity does not match the listed files')
    return manifest


def audit_modules(root: Path, listed: set[str]) -> list[str]:
    """Every loaded districtbrief module must come from this checkout and be a listed release file."""
    loaded = []
    for name, module in sorted(sys.modules.items()):
        if name in FORBIDDEN_MODULES:
            raise StartupError('forbidden module loaded: ' + name)
        if name == 'districtbrief' or name.startswith('districtbrief.'):
            origin = Path(getattr(module, '__file__', '') or '').resolve()
            try:
                rel = origin.relative_to(root).as_posix()
            except ValueError:
                raise StartupError('engine module loaded from outside the verified checkout: ' + name) from None
            if rel not in listed:
                raise StartupError('engine module is not a listed release file: ' + rel)
            loaded.append(rel)
    return loaded


def interpretation_rules(root: Path, recipe_labels: dict, expected_literal_sha256: str) -> str:
    """Return the provider PROMPT adapted for MCP, read by AST from verified source text (never imported)."""
    source = (root / 'districtbrief' / 'ia_language_provider.py').read_text(encoding='utf-8')
    tree = ast.parse(source)
    assigns = [n for n in tree.body if isinstance(n, (ast.Assign, ast.AnnAssign, ast.AugAssign))
               and any(isinstance(t, ast.Name) and t.id == 'PROMPT'
                       for t in (n.targets if isinstance(n, ast.Assign) else [n.target]))]
    if len(assigns) != 1 or not isinstance(assigns[0], ast.Assign) or len(assigns[0].targets) != 1:
        raise StartupError('unexpected PROMPT assignment shape')
    call = assigns[0].value
    if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) and call.func.attr == 'replace'
            and isinstance(call.func.value, ast.Constant) and isinstance(call.func.value.value, str)
            and len(call.args) == 2 and not call.keywords
            and isinstance(call.args[0], ast.Constant) and call.args[0].value == '<RECIPE_NAMES>'):
        raise StartupError('unexpected PROMPT receiver or placeholder shape')
    expected = ast.parse(RECIPE_NAMES_EXPRESSION, mode='eval').body
    if ast.dump(call.args[1]) != ast.dump(expected):
        raise StartupError('unexpected RECIPE_NAMES replacement expression')
    literal = call.func.value.value
    if hashlib.sha256(literal.encode('utf-8')).hexdigest() != expected_literal_sha256:
        raise StartupError('PROMPT literal does not match the pinned text')
    if literal.count('<RECIPE_NAMES>') != 1 or literal.count(TRANSPORT_SENTENCE) != 1:
        raise StartupError('unexpected PROMPT placeholder or transport sentence count')
    names = '; '.join(' or '.join(f'"{n}"' for n in names) + ' = ' + issue for issue, names in recipe_labels.items())
    rules = literal.replace('<RECIPE_NAMES>', names)
    if re.search(r'<[A-Z_]+>', rules):
        raise StartupError('unresolved PROMPT placeholder')
    return RULES_HEADER + rules.replace(TRANSPORT_SENTENCE, MCP_TRANSPORT_SENTENCE) + RULES_FOOTER


def build_digest() -> str:
    """Connector build identity: owned code and dependency pins (README and tests excluded)."""
    files = sorted([p for p in PACKAGE_DIR.glob('*.py')] + [PACKAGE_DIR / 'engine-pin.json', PACKAGE_DIR / 'requirements.lock'])
    lines = ''.join(f'{_sha256_file(p)[0]}  {p.name}\n' for p in files)
    return 'sha256:' + hashlib.sha256(lines.encode('utf-8')).hexdigest()


class Engine:
    """One warm public Core plus Investigation, verified before any tool is served."""

    def __init__(self, root: Path | str | None = None, expected_manifest_sha256: str | None = None):
        root = Path(root or DEFAULT_ROOT).resolve()
        expected = expected_manifest_sha256 or PIN['release_manifest_sha256']
        manifest = verify_release(root, expected)
        listed = {r['path'] for r in manifest['files']}
        sys.dont_write_bytecode = True
        loaded = sys.modules.get('districtbrief')
        if loaded is not None and Path(loaded.__file__).resolve().parent != root / 'districtbrief':
            raise StartupError('districtbrief is already loaded from another checkout')
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        from districtbrief.public_packet import PublicPacket, public_metadata
        from districtbrief.core import Core
        from districtbrief.investigation import Investigation
        from districtbrief import ia_language
        self.root = root
        self.language = ia_language
        # As public_app.load_core('public'), constructed directly; the profile is fixed and never client-chosen.
        self.core = Core(PublicPacket(root / 'runtime-packet'), metadata=public_metadata(root / 'candidate-metadata'))
        self.investigation = Investigation(self.core)
        self.loaded_modules = audit_modules(root, listed)
        for rel in ('districtbrief/core.py', 'districtbrief/investigation.py', 'districtbrief/ia_language.py',
                    'districtbrief/public_packet.py', 'districtbrief/ia_language_provider.py'):
            if rel not in listed:
                raise StartupError('required engine file is not listed: ' + rel)
        self.rules = interpretation_rules(root, ia_language.RECIPE_LABELS, PIN['prompt_literal_sha256'])
        boot = self.investigation.bootstrap()
        if boot['release_id'] != 'sha256:' + expected or boot['input_profile'] != 'public':
            raise StartupError('engine identity does not match the verified release')
        self.manifest_sha256 = expected
        self.identity = {
            'engine': {
                'release_manifest_sha256': 'sha256:' + expected,
                'source_identity': manifest['source_identity'],
                'snapshot_id': boot['snapshot_id'],
                'data_snapshot_id': boot['data_snapshot_id'],
                'metadata_snapshot_id': boot['metadata_snapshot_id'],
                'investigation_schema_version': boot['schema_version'],
                'language_schema_version': ia_language.SCHEMA_VERSION,
                'operation_version': boot['operation_version'],
                'recipe_versions': list(boot['recipe_versions']),
                'input_profile': 'public',
            },
            'connector': {'name': CONNECTOR_NAME, 'version': CONNECTOR_VERSION, 'build_digest': build_digest()},
        }

    def still_pinned(self) -> bool:
        # Cheap per-call guard: the manifest the engine reports must still be the verified one.
        return self.investigation.release_id() == 'sha256:' + self.manifest_sha256
