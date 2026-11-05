"""所有本文件数据均为明确构造的模拟数据，不代表网易云实测。"""
import copy
import csv
import json
from pathlib import Path

import httpx
import pytest

from npe.api import NeteaseAPI, ApiError, AuthRequired, playlist_id
from npe.service import PlaylistService
from npe.exporter import export_bundle, export_batch, safe_name
from npe.storage import SessionStore


def song(i):
    return {'id': i, 'name': f'中文 日本語 한국어 🎵 {i} (Live Remix)',
            'ar': [{'name': '歌手甲'}, {'name': '歌手乙'}],
            'al': {'name': '专辑', 'id': 9}, 'dt': 123456, 'no': 2, 'cd': '1'}


class FakeAPI:
    def __init__(self, count=1253, missing=None, truncated=False):
        self.ids = list(range(1, count + 1))
        if count > 1:
            self.ids[-1] = 1  # Deliberate duplicate position.
        self.count, self.missing, self.truncated = count, missing, truncated
        self.calls = []

    def playlist(self, sid):
        return {'id': int(sid), 'name': '模拟测试歌单', 'trackCount': self.count,
                'trackIds': [{'id': i} for i in (self.ids[:20] if self.truncated else self.ids)],
                'creator': {'nickname': '模拟用户'}}

    def songs(self, ids):
        self.calls.append(ids)
        return {'songs': [song(int(i)) for i in reversed(ids) if str(i) != str(self.missing)],
                'privileges': [{'id': int(i), 'st': -200} for i in ids]}


def test_large_playlist_order_duplicates_and_multiple_artists():
    api = FakeAPI()
    result = PlaylistService(api).collect('123')
    assert result['report']['complete']
    assert len(result['tracks']) == 1253
    assert [r['song_id'] for r in result['tracks']] == list(map(str, api.ids))
    assert result['tracks'][-1]['position'] == 1253
    assert max(map(len, api.calls)) <= 50
    assert result['tracks'][0]['artists'] == ['歌手甲', '歌手乙']
    assert '(Live Remix)' in result['tracks'][0]['title']
    assert result['tracks'][0]['availability'] == 'unavailable_or_restricted'
    assert result['tracks'][0]['release_date'] is None


def test_missing_metadata_retains_position_and_retries():
    api = FakeAPI(5, missing=3)
    b = PlaylistService(api).collect('123')
    assert not b['report']['complete']
    assert len(b['tracks']) == 5
    assert b['tracks'][2]['title'] is None
    assert b['report']['missing_records'][0]['song_id'] == '3'
    assert sum('3' in call for call in api.calls) == 3


def test_truncated_ids_never_succeed():
    b = PlaylistService(FakeAPI(100, truncated=True)).collect('123')
    assert not b['report']['complete']
    assert b['report']['missing_id_count'] == 80


def test_csv_json_encoding_and_configurable_mapping(tmp_path):
    b = PlaylistService(FakeAPI(3)).collect('123')
    paths = list(map(Path, export_bundle(b, tmp_path)))
    assert paths[0].read_bytes().startswith(b'\xef\xbb\xbf')
    rows = list(csv.DictReader(paths[0].open(encoding='utf-8-sig', newline='')))
    assert json.loads(rows[0]['artists']) == ['歌手甲', '歌手乙']
    assert json.loads(paths[1].read_text('utf-8')) == b
    download = list(csv.DictReader(paths[2].open(encoding='utf-8-sig', newline='')))
    assert download[0]['artist'] == '歌手甲 / 歌手乙'
    assert download[0]['length'] == '123.456'
    config = tmp_path / 'mapping.json'
    config.write_text(json.dumps({'fields': {'name': 'title', 'performers': 'artists'}, 'artist_separator': ';'}), 'utf-8')
    paths = export_bundle(b, tmp_path / 'custom', config)
    assert '歌手甲;歌手乙' in Path(paths[2]).read_text('utf-8-sig')


def test_incomplete_names_and_batch(tmp_path):
    out = export_batch(FakeAPI(5, missing=3), ['123', '124'], tmp_path)
    assert len(out) == 2 and all(not r['complete'] for r in out)
    assert all('不完整' in r['files'][0] for r in out)
    assert (tmp_path / '批次报告.json').exists()


@pytest.mark.parametrize('value', ['123456789', 'https://music.163.com/#/playlist?id=123456789',
                                  'https://music.163.com/playlist?id=123456789&userid=3',
                                  'https://music.163.com/playlist/123456789'])
def test_parse_id(value):
    assert playlist_id(value) == '123456789'


@pytest.mark.parametrize('value', ['-1', '0', 'https://evil.example/playlist?id=123', 'https://music.163.com/song?id=123'])
def test_reject_bad_id(value):
    with pytest.raises(ValueError):
        playlist_id(value)


def client_api(handler):
    return NeteaseAPI(client=httpx.Client(transport=httpx.MockTransport(handler)), interval=0, sleep=lambda _: None)


def test_timeout_redacted_and_retried():
    count = []
    def handler(req):
        count.append(req)
        raise httpx.ConnectError('SECRET_COOKIE')
    with pytest.raises(ApiError) as e:
        client_api(handler).playlist('123')
    assert len(count) == 3
    assert 'SECRET' not in str(e.value)


@pytest.mark.parametrize('response', [httpx.Response(200, text='<html>captcha</html>'),
                                    httpx.Response(200, json={'code': 200, 'playlist': []}),
                                    httpx.Response(429)])
def test_invalid_interface(response):
    with pytest.raises(ApiError):
        client_api(lambda _: response).playlist('123')


def test_expired_auth():
    with pytest.raises(AuthRequired):
        client_api(lambda _: httpx.Response(200, json={'code': 301})).profile()


def test_qr_flow_and_cookie_saved(tmp_path):
    store = SessionStore(tmp_path / 'session.dpapi')
    states = iter([801, 802, 803])
    def handler(req):
        if req.url.path.endswith('unikey'):
            return httpx.Response(200, json={'code': 200, 'unikey': 'mock-key'})
        if req.url.path.endswith('logout'):
            return httpx.Response(200, json={'code': 200})
        return httpx.Response(200, json={'code': next(states)}, headers={'set-cookie': 'MUSIC_U=MOCK_SECRET; Path=/; Domain=music.163.com; Secure'})
    api = client_api(handler)
    api.store = store
    assert api.qr_key() == 'mock-key'
    assert [api.qr_check('mock-key') for _ in range(3)] == [801, 802, 803]
    assert b'MOCK_SECRET' not in store.path.read_bytes()
    restored = NeteaseAPI(store, client=httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, json={'code': 200, 'profile': None}))))
    assert any(c.value == 'MOCK_SECRET' for c in restored.client.cookies.jar)
    assert restored.profile() is None
    api.logout()
    assert not store.path.exists()


def test_partial_response_recovers():
    api = FakeAPI(20)
    original = api.songs
    count = []
    def songs(ids):
        count.append(1)
        data = original(ids)
        if len(count) == 1:
            data['songs'] = data['songs'][:2]
        return data
    api.songs = songs
    assert PlaylistService(api).collect('123')['report']['complete']
    assert len(count) == 2


def test_paginated_user_playlists():
    offsets = []
    def handler(req):
        offset = int(req.url.params['offset'])
        offsets.append(offset)
        return httpx.Response(200, json={'code': 200, 'playlist': [{'id': offset + 1}], 'more': offset < 2})
    assert len(client_api(handler).playlists(1)) == 3
    assert offsets == [0, 1, 2]


def test_filename_safety():
    assert safe_name('CON') == '_CON'
    assert '/' not in safe_name('a/b:c')


def test_repeated_pagination_stops():
    calls = []
    def handler(req):
        calls.append(req)
        return httpx.Response(200, json={'code': 200, 'playlist': [{'id': 1}], 'more': True})
    with pytest.raises(ApiError, match='分页'):
        client_api(handler).playlists(1)
    assert len(calls) == 2


def test_batch_stops_network_after_rate_limit(tmp_path):
    from npe.api import RateLimited
    class Limited:
        calls = 0
        def playlist(self, sid):
            self.calls += 1
            raise RateLimited('请求频率受限')
    api = Limited()
    results = export_batch(api, ['1', '2', '3'], tmp_path)
    assert api.calls == 1
    assert len(results) == 3
    assert all(not r['complete'] for r in results)


def test_changing_playlist_never_claims_complete():
    class Changing(FakeAPI):
        ticks = 0
        def playlist(self, sid):
            self.ticks += 1
            p = super().playlist(sid)
            p['trackUpdateTime'] = self.ticks
            return p
    data = PlaylistService(Changing(3)).collect('123')
    assert not data['report']['complete']
    assert data['report']['snapshot_changed']


@pytest.mark.parametrize('code', [8821, 8830])
def test_security_verification_stops_with_clear_message(code):
    from npe.api import VerificationRequired
    requests = []
    def handler(req):
        requests.append(req)
        return httpx.Response(200, json={'code': code, 'message': 'sensitive upstream message'})
    with pytest.raises(VerificationRequired, match='安全验证') as error:
        client_api(handler).qr_check('MOCK_KEY')
    assert len(requests) == 1
    assert 'sensitive' not in str(error.value)


def test_browser_session_validated_before_adoption(monkeypatch):
    import npe.api as module
    api = client_api(lambda _: httpx.Response(200, json={'code': 200}))
    class Probe:
        def __init__(self):
            self.client = httpx.Client()
        def profile(self):
            assert len(list(self.client.cookies.jar)) == 1
            return {'userId': 123, 'nickname': '模拟网页登录用户'}
    monkeypatch.setattr(module, 'NeteaseAPI', Probe)
    profile = api.adopt_browser_cookies([
        {'name': 'MUSIC_U', 'value': 'MOCK_BROWSER_COOKIE', 'domain': '.music.163.com', 'path': '/'},
        {'name': 'unrelated', 'value': 'ignored', 'domain': 'example.com', 'path': '/'}])
    assert profile['userId'] == 123
    assert len(list(api.client.cookies.jar)) == 1
    assert next(iter(api.client.cookies.jar)).value == 'MOCK_BROWSER_COOKIE'


def test_empty_album_is_null_without_invention():
    from npe.service import normalize
    raw = song(1)
    raw['al'] = {'id': 0, 'name': ''}
    row = normalize('123', 1, '1', raw, None, 'mock-time')
    assert row['album'] is None
    assert row['album_id'] is None
    assert row['raw_song']['al']['name'] == ''
