"""官方站点只读接口；不访问音频接口，不使用公共代理 API。"""
import json
import re
import time
from urllib.parse import urlparse, parse_qs

import httpx


class ApiError(RuntimeError):
    pass


class AuthRequired(ApiError):
    pass


class RateLimited(ApiError):
    pass


class VerificationRequired(ApiError):
    pass


def playlist_id(value):
    value = value.strip()
    if value.isdecimal() and int(value) > 0:
        return str(int(value))
    u = urlparse(value)
    if u.scheme not in ('http', 'https') or u.hostname != 'music.163.com':
        raise ValueError('请输入正整数歌单 ID 或 music.163.com 的完整歌单链接。')
    route = u.fragment if u.fragment else u.path + '?' + u.query
    match = re.fullmatch(r'/?playlist(?:/([0-9]+))?(?:\?(.*))?', route)
    if match:
        sid = match[1] or parse_qs(match[2] or '').get('id', [''])[0]
        if sid.isdecimal() and int(sid) > 0:
            return str(int(sid))
    raise ValueError('链接中未找到歌单 ID；短链接请先在浏览器打开，再复制完整链接。')


class NeteaseAPI:
    def __init__(self, store=None, client=None, interval=0.45, sleep=time.sleep):
        self.store = store
        self.client = client or httpx.Client(timeout=25, headers={
            'User-Agent': 'Mozilla/5.0', 'Referer': 'https://music.163.com/'}, follow_redirects=False)
        self.interval, self.sleep, self.last = interval, sleep, 0.0
        if store:
            for c in store.load():
                if c.get('domain', '').lstrip('.') in ('music.163.com', '163.com'):
                    self.client.cookies.set(c['name'], c['value'], domain=c['domain'], path=c.get('path', '/'))

    def request(self, path, params=None, allowed=(200,)):
        for attempt in range(3):
            self.sleep(max(0, self.interval - (time.monotonic() - self.last)))
            self.last = time.monotonic()
            try:
                response = self.client.get('https://music.163.com/api/' + path, params=params or {})
                if response.status_code in (401, 403):
                    raise AuthRequired('访问受限或登录已失效，请重新扫码；若有验证要求，请在官方 App 完成。')
                if response.status_code == 429:
                    raise RateLimited('网易云限制了请求频率，请稍后再试。')
                if response.status_code >= 500:
                    raise httpx.TransportError('server unavailable')
                if response.status_code != 200:
                    raise ApiError(f'接口 HTTP {response.status_code}，请稍后重试。')
                try:
                    body = response.json()
                except ValueError:
                    raise ApiError('接口未返回有效 JSON，可能需要在官方 App 完成验证。') from None
                if not isinstance(body, dict):
                    raise ApiError('接口数据结构已变化。')
                code = body.get('code')
                if code in (8821, 8830):
                    raise VerificationRequired(f'网易云要求安全验证（{code}）。扫码尚未建立会话，请使用“官方网页登录 / 安全验证”在官方页面完成登录。')
                if code == 429:
                    raise RateLimited('网易云限制了请求频率，请稍后再试。')
                if code in (301, 302, 401, 403):
                    raise AuthRequired('需要登录或会话已失效，请重新扫码。')
                if code not in allowed:
                    raise ApiError(f'网易云接口返回代码 {code}；可能无权限、歌单不存在或接口已变化。')
                return body
            except httpx.TransportError:
                if attempt == 2:
                    raise ApiError('网络连接失败或超时，已重试 3 次，请检查网络后重试。') from None
                self.sleep(1.5 * (attempt + 1))

    def save(self):
        if self.store:
            self.store.save([{'name': c.name, 'value': c.value, 'domain': c.domain, 'path': c.path}
                             for c in self.client.cookies.jar if not c.is_expired()])

    def profile(self):
        p = self.request('w/nuser/account/get').get('profile')
        if not p or not p.get('userId'):
            if self.store:
                self.store.clear()
            return None
        self.save()
        return {k: p.get(k) for k in ('userId', 'nickname', 'avatarUrl')}

    def qr_key(self):
        key = self.request('login/qrcode/unikey', {'type': 3}).get('unikey')
        if not isinstance(key, str) or not key:
            raise ApiError('二维码接口未返回有效凭证。')
        return key

    def qr_check(self, key):
        body = self.request('login/qrcode/client/login', {'key': key, 'type': 3}, (800, 801, 802, 803))
        if body['code'] == 803:
            # Official response Set-Cookie is handled by httpx, never logged.
            self.save()
        return body['code']

    def adopt_browser_cookies(self, cookies):
        """Validate user-authorized official browser session before adopting it."""
        probe = NeteaseAPI()
        try:
            for cookie in cookies:
                if cookie.get('domain', '').lstrip('.') in ('music.163.com', '163.com'):
                    probe.client.cookies.set(cookie['name'], cookie['value'],
                                             domain=cookie['domain'], path=cookie.get('path', '/'))
            profile = probe.profile()
            if profile:
                self.client.cookies.clear()
                self.client.cookies.update(probe.client.cookies)
                self.save()
            return profile
        finally:
            probe.client.close()

    def logout(self):
        try:
            self.request('logout')
        finally:
            self.client.cookies.clear()
            if self.store:
                self.store.clear()

    def playlists(self, uid):
        items, seen, offset = [], set(), 0
        while True:
            body = self.request('user/playlist', {'uid': uid, 'limit': 100, 'offset': offset, 'includeVideo': 'true'})
            page = body.get('playlist')
            if not isinstance(page, list):
                raise ApiError('用户歌单接口数据结构已变化。')
            previous_count = len(items)
            for p in page:
                if p.get('id') not in seen:
                    items.append(p)
                    seen.add(p.get('id'))
            if not body.get('more'):
                return items
            if not page or offset > 100000 or len(items) == previous_count:
                raise ApiError('用户歌单分页未前进，已停止以避免无限请求。')
            offset += len(page)

    def playlist(self, sid):
        body = self.request('v6/playlist/detail', {'id': sid, 'n': 100000, 's': 0})
        p = body.get('playlist')
        if not isinstance(p, dict) or str(p.get('id')) != str(sid) or not isinstance(p.get('trackCount'), int):
            raise ApiError('歌单详情不完整或 ID 不符，无法安全导出。')
        return p

    def songs(self, ids):
        # Small GET batches avoid URL length limits; authenticated cookies accompany every request.
        body = self.request('v3/song/detail', {'c': json.dumps([{'id': int(i)} for i in ids], separators=(',', ':'))})
        if not isinstance(body.get('songs'), list):
            raise ApiError('歌曲详情接口结构已变化。')
        return body

    def image(self, url):
        u = urlparse(url or '')
        if not u.hostname or not u.hostname.endswith('.music.126.net') or u.scheme not in ('http', 'https'):
            return b''
        try:
            with self.client.stream('GET', url.replace('http://', 'https://', 1)) as r:
                if r.status_code != 200:
                    return b''
                data = bytearray()
                for chunk in r.iter_bytes():
                    data.extend(chunk)
                    if len(data) > 5_000_000:
                        return b''
                return bytes(data)
        except httpx.HTTPError:
            return b''
