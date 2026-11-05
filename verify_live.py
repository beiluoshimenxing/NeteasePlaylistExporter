"""显式真实网络验证，不需要登录，不使用模拟回退。"""
import argparse
import json
from pathlib import Path
from npe.api import NeteaseAPI, playlist_id
from npe.service import PlaylistService
from npe.exporter import export_bundle

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--id', required=True, help='用户自行提供的公开歌单 ID 或完整链接')
    parser.add_argument('--output', default='exports/真实联网验收')
    args = parser.parse_args()
    api = NeteaseAPI()
    try:
        data = PlaylistService(api, print).collect(playlist_id(args.id))
        files = export_bundle(data, args.output)
        print(json.dumps({'playlist': data['playlist']['name'], 'report': data['report'], 'files': files}, ensure_ascii=True, indent=2))
        raise SystemExit(0 if data['report']['complete'] else 2)
    finally:
        api.client.close()
