"""User-operated official web login; no form automation or verification bypass."""
from PySide6.QtCore import QUrl, Signal
from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QPushButton
from PySide6.QtWebEngineCore import QWebEngineProfile, QWebEnginePage
from PySide6.QtWebEngineWidgets import QWebEngineView


class OfficialLogin(QDialog):
    cookies_changed = Signal()

    def __init__(self, parent=None, load_home=True):
        super().__init__(parent)
        self.setWindowTitle('网易云音乐官方网页登录 · 请自行扫码及完成验证')
        self.resize(1100, 800)
        self.cookies = {}
        layout = QVBoxLayout(self)
        notice = QLabel('这是网易云官方网页。请点击网页右上角“登录”，自行扫码并完成必要验证。\n'
                        '登录成功后会自动返回歌单工具；无需复制 Cookie。浏览器会话仅在内存中保留。')
        notice.setWordWrap(True)
        layout.addWidget(notice)
        self.view = QWebEngineView(self)
        # Unnamed profile is off-the-record: Chromium never writes cookies to disk.
        self.profile = QWebEngineProfile(self)
        self.profile.setPersistentCookiesPolicy(QWebEngineProfile.PersistentCookiesPolicy.NoPersistentCookies)
        self.page = QWebEnginePage(self.profile, self.view)
        self.view.setPage(self.page)
        self.page.newWindowRequested.connect(lambda request: request.openIn(self.page))
        self.profile.cookieStore().cookieAdded.connect(self.add_cookie)
        self.profile.cookieStore().cookieRemoved.connect(self.remove_cookie)
        layout.addWidget(self.view, 1)
        close = QPushButton('关闭网页登录窗口')
        close.clicked.connect(self.close)
        layout.addWidget(close)
        if load_home:
            self.view.load(QUrl('https://music.163.com/'))

    def add_cookie(self, cookie):
        domain = cookie.domain()
        if domain.lstrip('.') not in ('music.163.com', '163.com'):
            return
        record = {'name': bytes(cookie.name()).decode('utf-8', 'replace'),
                  'value': bytes(cookie.value()).decode('utf-8', 'replace'),
                  'domain': domain, 'path': cookie.path() or '/'}
        self.cookies[(domain, record['path'], record['name'])] = record
        self.cookies_changed.emit()

    def remove_cookie(self, cookie):
        self.cookies.pop((cookie.domain(), cookie.path() or '/',
                          bytes(cookie.name()).decode('utf-8', 'replace')), None)
        self.cookies_changed.emit()

    def snapshot(self):
        return [dict(value) for value in self.cookies.values()]

    def closeEvent(self, event):
        self.view.stop()
        self.profile.cookieStore().deleteAllCookies()
        self.cookies.clear()
        super().closeEvent(event)
