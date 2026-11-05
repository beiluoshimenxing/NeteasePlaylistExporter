"""仅在本地存储配置；Windows 会话由当前 Windows 用户的 DPAPI 加密。"""
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path


def app_dir():
    path = Path(os.environ.get('LOCALAPPDATA', Path.home() / '.local/share')) / 'NeteasePlaylistExporter'
    path.mkdir(parents=True, exist_ok=True)
    return path


class Blob(ctypes.Structure):
    _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]


def protect(data, decrypt=False):
    if os.name != 'nt':
        raise RuntimeError('会话持久化需要 Windows DPAPI。')
    buf = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte)))
    target = Blob()
    fn = ctypes.windll.crypt32.CryptUnprotectData if decrypt else ctypes.windll.crypt32.CryptProtectData
    if not fn(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise OSError('Windows 无法加密或解密本地会话，请重新扫码。')
    try:
        return ctypes.string_at(target.data, target.size)
    finally:
        ctypes.windll.kernel32.LocalFree(ctypes.cast(target.data, ctypes.c_void_p))


class SessionStore:
    def __init__(self, path=None):
        self.path = Path(path) if path else app_dir() / 'session.dpapi'

    def save(self, cookies):
        payload = json.dumps(cookies).encode()
        temp = self.path.with_suffix('.tmp')
        temp.write_bytes(protect(payload))
        os.replace(temp, self.path)

    def load(self):
        if not self.path.exists():
            return []
        try:
            return json.loads(protect(self.path.read_bytes(), decrypt=True))
        except (OSError, ValueError):
            self.clear()
            return []

    def clear(self):
        self.path.unlink(missing_ok=True)


def load_config():
    try:
        value = json.loads((app_dir() / 'config.json').read_text('utf-8'))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def save_config(value):
    (app_dir() / 'config.json').write_text(json.dumps(value, ensure_ascii=False, indent=2), 'utf-8')
