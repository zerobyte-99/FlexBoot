"""Persistent display labels and ordering, independent of boot resources."""
from __future__ import annotations

import json
from pathlib import Path

from .errors import FlexBootError


def validate_label(value: str) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > 160:
        raise FlexBootError("Menu labels must contain 1–160 characters")
    if any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise FlexBootError("Menu labels may not contain control characters")


def settings_path(paths) -> Path:
    return paths.data / '.flexboot/menu.json'


def validate_settings(settings: dict) -> None:
    if not isinstance(settings, dict) or set(settings) != {'schema_version', 'labels', 'order'} or type(settings['schema_version']) is not int or settings['schema_version'] != 1:
        raise FlexBootError("Malformed menu settings")
    labels, order = settings['labels'], settings['order']
    if not isinstance(labels, dict) or not isinstance(order, list) or not all(isinstance(key, str) for key in order) or len(order) != len(set(order)):
        raise FlexBootError("Malformed menu labels or ordering")
    from .iso import validate_filename
    for key in [*labels, *order]:
        if not isinstance(key, str) or ':' not in key or key.split(':', 1)[0] not in ('Linux', 'Windows'):
            raise FlexBootError("Invalid menu entry identifier")
        validate_filename(key.split(':', 1)[1])
    for value in labels.values():
        validate_label(value)


def load_settings(paths) -> dict:
    path = settings_path(paths)
    if path.is_symlink() or path.parent.is_symlink():
        raise FlexBootError("Menu settings may not be symlinks")
    if not path.exists():
        return {'schema_version': 1, 'labels': {}, 'order': []}
    try:
        if path.stat().st_size > 1024 * 1024:
            raise FlexBootError("Menu settings exceed the size limit")
        settings = json.loads(path.read_text(encoding='utf-8'))
        validate_settings(settings)
        return settings
    except (OSError, ValueError, TypeError) as exc:
        raise FlexBootError(f"Malformed menu settings: {exc}") from exc


def entries(records, windows=None, settings=None) -> list[dict]:
    settings = settings or {'schema_version': 1, 'labels': {}, 'order': []}
    validate_settings(settings)
    result = []
    for os_name, items in [('Linux', records), ('Windows', (windows or {}).get('images', []))]:
        for record in items:
            filename = record.filename if os_name == 'Linux' else record['filename']
            key = f'{os_name}:{filename}'
            default = f'{filename} — {record.profile}' if os_name == 'Linux' else f'{filename} — Windows installer'
            result.append({'id': key, 'filename': filename, 'os': os_name,
                           'label': settings['labels'].get(key, default), 'record': record})
    ranks = {key: i for i, key in enumerate(settings['order'])}
    return sorted(result, key=lambda item: (ranks.get(item['id'], len(ranks)), item['label'].casefold(), item['id']))


def listing(paths) -> list[dict]:
    from .manifest import Manifest
    from .windows import load
    return [{k: v for k, v in item.items() if k != 'record'}
            for item in entries(Manifest.load(paths.manifest).isos, load(paths), load_settings(paths))]


def resolve(value: str, items: list[dict]) -> str:
    matches = [item['id'] for item in items if value == item['id'] or value == item['filename']]
    if len(matches) != 1:
        raise FlexBootError(f"Unknown or ambiguous menu entry: {value}. Use the ID from menu list.")
    return matches[0]


def configure(paths, action: str, *, entry=None, label=None, order=(), runner=None) -> list[dict]:
    from .grub import atomic_text, base_config, validate_config
    from .manifest import Manifest
    from .media import regenerate
    settings = load_settings(paths)
    items = listing(paths)
    if action == 'label':
        key = resolve(entry, items)
        if label is None:
            settings['labels'].pop(key, None)
        else:
            validate_label(label)
            settings['labels'][key] = label
    elif action == 'order':
        keys = [resolve(value, items) for value in order]
        if len(keys) != len(set(keys)):
            raise FlexBootError("Menu order contains duplicate entries")
        settings['order'] = keys
    elif action == 'reset':
        settings = {'schema_version': 1, 'labels': {}, 'order': []}
    else:
        raise FlexBootError(f"Unknown menu operation: {action}")
    validate_settings(settings)
    path = settings_path(paths)
    base = paths.grub_dir / 'grub.cfg'
    generated = paths.grub_dir / 'generated.cfg'
    originals = {p: p.read_text(encoding='utf-8') if p.exists() else None for p in (path, base, generated)}
    candidate = base.with_name('grub.cfg.menu-new')
    try:
        atomic_text(candidate, base_config(Manifest.load(paths.manifest).data_filesystem_uuid))
        validate_config(candidate, runner)
        atomic_text(path, json.dumps(settings, indent=2, sort_keys=True) + '\n')
        regenerate(paths, Manifest.load(paths.manifest), runner)
        atomic_text(base, candidate.read_text(encoding='utf-8'))
    except BaseException:
        for p, text in originals.items():
            if text is None:
                p.unlink(missing_ok=True)
            else:
                atomic_text(p, text)
        raise
    finally:
        candidate.unlink(missing_ok=True)
    return listing(paths)
