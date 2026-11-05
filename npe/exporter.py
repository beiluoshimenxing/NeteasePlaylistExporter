import csv
import json
import os
from pathlib import Path
import re
import tempfile

FIELDS = ['playlist_id', 'position', 'song_id', 'title', 'artists', 'primary_artist', 'album', 'album_id',
          'duration_ms', 'duration_seconds', 'release_date', 'track_number', 'disc_number', 'song_url',
          'cover_url', 'availability', 'exported_at']
DEFAULT_MAPPING = {'title': 'title', 'artist': 'artists', 'album': 'album', 'length': 'duration_seconds', 'song_id': 'song_id'}


def mapping_from(path=None):
    if not path:
        return DEFAULT_MAPPING, ' / '
    config = json.loads(Path(path).read_text('utf-8'))
    mapping = config['fields']
    if not isinstance(mapping, dict) or not mapping or any(v not in FIELDS for v in mapping.values()):
        raise ValueError('下载 CSV 字段映射无效，请检查 download_mapping.json。')
    separator = config.get('artist_separator', ' / ')
    if not isinstance(separator, str):
        raise ValueError('多歌手分隔符必须是文本。')
    return mapping, separator


def safe_name(value):
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', value or '未命名歌单').rstrip('. ')[:100]
    if not name or name.split('.')[0].upper() in {'CON', 'PRN', 'AUX', 'NUL', *[f'COM{i}' for i in range(1,10)], *[f'LPT{i}' for i in range(1,10)]}:
        name = '_' + name
    return name


def export_bundle(bundle, folder, mapping_path=None):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    mapping, separator = mapping_from(mapping_path)
    meta = bundle['playlist']
    base = f"{safe_name(meta['name'])}_{meta['id']}"
    if not bundle['report']['complete']:
        base += '_不完整'
    names = [base + '.csv', base + '.json', base + '_download.csv', base + '_report.json']
    # Stage all files first; an error never produces a completion message.
    with tempfile.TemporaryDirectory(dir=folder) as temp:
        root = Path(temp)
        with (root / names[0]).open('w', encoding='utf-8-sig', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=FIELDS)
            writer.writeheader()
            for row in bundle['tracks']:
                writer.writerow({k: json.dumps(row[k], ensure_ascii=False) if isinstance(row.get(k), list) else row.get(k) for k in FIELDS})
        (root / names[1]).write_text(json.dumps(bundle, ensure_ascii=False, indent=2), 'utf-8')
        with (root / names[2]).open('w', encoding='utf-8-sig', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=list(mapping))
            writer.writeheader()
            for row in bundle['tracks']:
                writer.writerow({dst: separator.join(row[src]) if isinstance(row.get(src), list) else row.get(src) for dst, src in mapping.items()})
        (root / names[3]).write_text(json.dumps(bundle['report'], ensure_ascii=False, indent=2), 'utf-8')
        for name in names:
            os.replace(root / name, folder / name)
    return [str(folder / name) for name in names]


def export_batch(api, ids, folder, mapping_path=None, progress=lambda text: None):
    from .service import PlaylistService
    from .api import AuthRequired, RateLimited
    results = []
    stopped = None
    for sid in ids:
        if stopped:
            results.append({'playlist_id': str(sid), 'complete': False, 'error': stopped})
            continue
        try:
            data = PlaylistService(api, progress).collect(sid)
            files = export_bundle(data, folder, mapping_path)
            results.append({'playlist_id': str(sid), 'complete': data['report']['complete'],
                            'report': data['report'], 'files': files})
            progress(f"歌单 {sid}：{'完整' if data['report']['complete'] else '不完整，请查看报告'}，{len(data['tracks'])} 条")
        except (RuntimeError, ValueError, OSError) as e:
            # Exception messages here originate in our safe API wrapper or local IO.
            results.append({'playlist_id': str(sid), 'complete': False, 'error': str(e)})
            progress(f'歌单 {sid}：失败，请查看批次报告。')
            if isinstance(e, (AuthRequired, RateLimited)):
                stopped = str(e)
    Path(folder).mkdir(parents=True, exist_ok=True)
    (Path(folder) / '批次报告.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), 'utf-8')
    return results
