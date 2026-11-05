import io
from datetime import datetime
from pathlib import Path
import uuid

import qrcode
from PySide6.QtCore import Qt, QThread, Signal, QTimer, QUrl
from PySide6.QtGui import QPixmap, QDesktopServices, QFont
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QLineEdit, QListWidget, QListWidgetItem, QTableWidget, QTableWidgetItem,
    QSplitter, QFileDialog, QPlainTextEdit, QProgressBar, QMessageBox, QAbstractItemView)

from .api import NeteaseAPI, playlist_id, AuthRequired
from .storage import SessionStore, load_config, save_config
from .service import PlaylistService
from .exporter import export_batch


class Job(QThread):
    result = Signal(object)
    error = Signal(str, bool)
    progress = Signal(str)

    def __init__(self, fn, parent):
        super().__init__(parent)
        self.fn = fn

    def run(self):
        try:
            self.result.emit(self.fn(self.progress.emit))
        except Exception as e:
            # Never emit request URLs, headers, response bodies or arbitrary exception contents.
            from .api import ApiError
            message = str(e) if isinstance(e, (ApiError, ValueError)) else '操作失败，请检查网络、磁盘空间和导出目录权限。'
            self.error.emit(message, isinstance(e, AuthRequired))


class Window(QMainWindow):
    def __init__(self, auto_login=True, restore_session=True):
        super().__init__()
        self.setWindowTitle('NeteasePlaylistExporter · 网易云歌单导出')
        self.resize(1180, 800)
        self.api = NeteaseAPI(SessionStore())
        self.config = load_config()
        self.job = None
        self.auto_login = auto_login
        self.profile_data = None
        self.key = None
        self.preview_data = None
        self.last_folder = None
        self.browser_login = None
        self.browser_dirty = False
        import sys
        root = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent.parent
        self.mapping = root / 'download_mapping.json'
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        account = QHBoxLayout()
        self.avatar = QLabel()
        self.avatar.setFixedSize(54, 54)
        self.account = QLabel('尚未登录 · 可直接导入公开歌单')
        self.login_btn = QPushButton('扫码登录 / 刷新二维码')
        self.logout_btn = QPushButton('退出登录 / 切换账号')
        self.refresh_btn = QPushButton('刷新我的歌单')
        for widget in (self.avatar, self.account, self.login_btn, self.logout_btn, self.refresh_btn):
            account.addWidget(widget)
        layout.addLayout(account)
        self.qr = QLabel('点击“扫码登录”，使用网易云音乐 App 扫描并确认。')
        self.qr.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.qr.setMinimumHeight(70)
        layout.addWidget(self.qr)
        self.auth_status = QLabel('会话仅在本机加密保存；无需输入密码。')
        self.auth_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.auth_status)
        self.browser_btn = QPushButton('官方网页登录 / 安全验证（扫码受限时使用）')
        self.browser_btn.clicked.connect(self.open_official_login)
        layout.addWidget(self.browser_btn)
        link = QHBoxLayout()
        self.link = QLineEdit()
        self.link.setPlaceholderText('网易云歌单链接或歌单 ID')
        self.import_btn = QPushButton('导入歌单并预览')
        link.addWidget(self.link)
        link.addWidget(self.import_btn)
        layout.addLayout(link)
        splitter = QSplitter()
        self.playlists = QListWidget()
        self.playlists.setMinimumWidth(270)
        self.playlists.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        splitter.addWidget(self.playlists)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        meta = QHBoxLayout()
        self.cover = QLabel()
        self.cover.setFixedSize(84, 84)
        self.meta = QLabel('选择歌单查看歌曲；勾选多个歌单可批量导出。')
        self.meta.setWordWrap(True)
        meta.addWidget(self.cover)
        meta.addWidget(self.meta, 1)
        right_layout.addLayout(meta)
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(['位置', '歌名（保留版本）', '全部歌手', '专辑', '秒', '歌曲 ID', '状态'])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSortingEnabled(False)
        right_layout.addWidget(self.table)
        splitter.addWidget(right)
        splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter, 1)
        folder = QHBoxLayout()
        self.folder = QLineEdit(self.config.get('export_folder', str(Path.home() / 'Downloads' / '网易云歌单导出')))
        self.folder_btn = QPushButton('选择导出文件夹')
        folder.addWidget(self.folder)
        folder.addWidget(self.folder_btn)
        layout.addLayout(folder)
        actions = QHBoxLayout()
        self.export_one = QPushButton('导出当前歌单（CSV + JSON）')
        self.export_many = QPushButton('批量导出勾选歌单')
        self.open_btn = QPushButton('打开导出位置')
        for b in (self.export_one, self.export_many, self.open_btn):
            actions.addWidget(b)
        layout.addLayout(actions)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1)
        self.bar.setValue(0)
        layout.addWidget(self.bar)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(300)
        self.log.setMaximumHeight(115)
        layout.addWidget(self.log)
        self.controls = [self.login_btn, self.logout_btn, self.refresh_btn, self.import_btn,
                         self.export_one, self.export_many, self.folder_btn, self.playlists, self.browser_btn]
        self.login_btn.clicked.connect(self.login)
        self.logout_btn.clicked.connect(self.logout)
        self.refresh_btn.clicked.connect(self.refresh)
        self.import_btn.clicked.connect(self.import_link)
        self.link.returnPressed.connect(self.import_link)
        self.playlists.itemDoubleClicked.connect(lambda item: self.preview(str(item.data(Qt.ItemDataRole.UserRole))))
        self.export_one.clicked.connect(self.export_current)
        self.export_many.clicked.connect(self.export_checked)
        self.folder_btn.clicked.connect(self.choose_folder)
        self.open_btn.clicked.connect(self.open_folder)
        self.timer = QTimer(self)
        self.timer.setInterval(2500)
        self.timer.timeout.connect(self.poll)
        self.browser_timer = QTimer(self)
        self.browser_timer.setInterval(3000)
        self.browser_timer.timeout.connect(self.check_browser_session)
        if restore_session:
            QTimer.singleShot(100, self.restore)

    def message(self, text):
        self.log.appendPlainText(datetime.now().strftime('%H:%M:%S') + '  ' + text)

    def run_job(self, fn, done):
        if self.job is not None:
            return False
        for control in self.controls:
            control.setEnabled(False)
        self.bar.setRange(0, 0)
        self.job = Job(fn, self)
        self.job.progress.connect(self.message)
        self.job.result.connect(done)
        self.job.error.connect(self.failed)
        self.job.finished.connect(self.finished)
        self.job.start()
        return True

    def finished(self):
        job = self.job
        self.job = None
        job.deleteLater()
        for control in self.controls:
            control.setEnabled(True)
        self.bar.setRange(0, 1)
        self.bar.setValue(1)
        if self.auto_login:
            self.auto_login = False
            if self.profile_data is None:
                QTimer.singleShot(0, self.login)

    def failed(self, text, auth):
        self.message(text)
        # A network/interface failure during QR polling requires a deliberate retry.
        self.timer.stop()
        if auth:
            self.timer.stop()
            self.profile_data = None
            self.account.setText('会话失效或访问受限，请重新扫码登录')
            self.api.client.cookies.clear()
            self.api.store.clear()
        self.auth_status.setText(text)

    def restore(self):
        self.run_job(lambda _: self.account_payload(), self.set_account)

    def account_payload(self):
        profile = self.api.profile()
        return (profile, self.api.playlists(profile['userId']) if profile else [],
                self.api.image(profile.get('avatarUrl')) if profile else b'')

    def set_account(self, result):
        profile, playlists, avatar = result
        self.profile_data = profile
        if profile:
            self.timer.stop()
            self.key = None
            self.qr.clear()
            self.qr.setMinimumHeight(20)
            self.account.setText(f"{profile['nickname']}  ·  用户 ID {profile['userId']}")
            self.auth_status.setText('已登录，已读取有权限访问的歌单。')
            self.set_image(self.avatar, avatar, 54)
            self.show_playlists(playlists)
            self.message(f'已登录，读取到 {len(playlists)} 个歌单。')
        else:
            self.account.setText('尚未登录 · 可直接导入公开歌单')
            self.avatar.clear()
            self.playlists.clear()
            self.auth_status.setText('没有有效登录会话，请点击扫码登录。')

    def login(self):
        self.timer.stop()
        def task(_):
            key = self.api.qr_key()
            image = qrcode.make('https://music.163.com/login?codekey=' + key)
            stream = io.BytesIO()
            image.save(stream, format='PNG')
            return key, stream.getvalue()
        def done(result):
            self.key, data = result
            self.qr.setMinimumHeight(220)
            self.set_image(self.qr, data, 220)
            self.auth_status.setText('请使用网易云音乐 App 扫码，并在手机上确认登录。')
            self.timer.start()
        self.run_job(task, done)

    def open_official_login(self):
        from .browser_login import OfficialLogin
        self.timer.stop()
        if self.browser_login is None:
            self.browser_login = OfficialLogin(self)
            self.browser_login.cookies_changed.connect(self.mark_browser_dirty)
        self.browser_login.show()
        self.browser_login.raise_()
        self.browser_timer.start()

    def mark_browser_dirty(self):
        self.browser_dirty = True

    def check_browser_session(self):
        if self.job or not self.browser_login or not self.browser_login.isVisible() or not self.browser_dirty:
            return
        cookies = self.browser_login.snapshot()
        if not any(c['name'] == 'MUSIC_U' and c['value'] for c in cookies):
            return
        self.browser_dirty = False
        def task(_):
            profile = self.api.adopt_browser_cookies(cookies)
            return self.account_payload() if profile else None
        def done(payload):
            if payload and payload[0]:
                self.browser_timer.stop()
                self.browser_login.close()
                self.set_account(payload)
                self.message('已从用户操作的官方网页取得授权会话，并加密保存。')
            else:
                self.auth_status.setText('官方网页登录会话尚未确认，请继续在网页完成登录。')
        self.run_job(task, done)

    def poll(self):
        if self.job or not self.key:
            return
        def task(_):
            code = self.api.qr_check(self.key)
            return code, self.account_payload() if code == 803 else None
        def done(result):
            code, payload = result
            self.auth_status.setText({800:'二维码已过期，请点击刷新二维码。', 801:'等待扫码…',
                                      802:'已扫码，请在手机确认。', 803:'已授权，正在确认会话…'}[code])
            if code in (800, 803):
                self.timer.stop()
            if code == 803:
                self.set_account(payload)
        self.run_job(task, done)

    def logout(self):
        self.timer.stop()
        self.key = None
        def done(_):
            self.profile_data = None
            self.account.setText('已退出登录')
            self.auth_status.setText('本地登录会话已清除，可重新扫码。')
            self.avatar.clear()
            self.qr.setText('点击扫码登录以切换账号。')
            self.playlists.clear()
            self.table.setRowCount(0)
            self.preview_data = None
            self.meta.setText('请选择歌单')
            self.cover.clear()
            self.message('已删除本地登录会话。')
        def task(_):
            try:
                self.api.logout()
            except RuntimeError:
                pass  # Local credentials have still been cleared in finally.
        self.run_job(task, done)

    def refresh(self):
        self.restore()

    def show_playlists(self, values):
        self.playlists.clear()
        for p in values:
            self.add_playlist(p)

    def add_playlist(self, p):
        for n in range(self.playlists.count()):
            if str(self.playlists.item(n).data(Qt.ItemDataRole.UserRole)) == str(p['id']):
                return
        creator = (p.get('creator') or {}).get('nickname') or ''
        private = ' · 私人' if p.get('privacy') == 10 else ''
        item = QListWidgetItem(f"{p.get('name')}\n{p.get('trackCount')} 首 · {creator}{private}")
        item.setData(Qt.ItemDataRole.UserRole, str(p['id']))
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(Qt.CheckState.Unchecked)
        self.playlists.addItem(item)

    def import_link(self):
        try:
            sid = playlist_id(self.link.text())
        except ValueError as e:
            self.message(str(e))
            return
        self.preview(sid)

    def preview(self, sid):
        def task(progress):
            bundle = PlaylistService(self.api, progress).collect(sid)
            return bundle, self.api.image(bundle['playlist'].get('coverImgUrl'))
        def done(result):
            bundle, cover = result
            self.preview_data = bundle
            p, report = bundle['playlist'], bundle['report']
            self.add_playlist(p)
            self.meta.setText(f"{p['name']} · 创建者：{p['creator']['nickname']}\n平台总数：{report['expected_count']} · 读取：{report['exported_count']} · "
                              + ('完整' if report['complete'] else '不完整，导出会生成缺失报告'))
            self.set_image(self.cover, cover, 84)
            self.table.setRowCount(len(bundle['tracks']))
            states = {'unknown': '未知', 'metadata_unavailable': '详情缺失',
                      'unavailable_or_restricted': '下架或受限',
                      'playable_for_current_session': '当前会话可播放',
                      'requires_subscription_or_purchase': '需订阅或购买',
                      'restricted_for_current_session': '当前会话受限'}
            for n, row in enumerate(bundle['tracks']):
                for c, value in enumerate([row['position'], row['title'], ' / '.join(row['artists'] or []), row['album'],
                                            row['duration_seconds'], row['song_id'], states.get(row['availability'], '未知')]):
                    self.table.setItem(n, c, QTableWidgetItem('' if value is None else str(value)))
            self.table.resizeColumnsToContents()
            for column in range(self.table.columnCount()):
                self.table.setColumnWidth(column, min(self.table.columnWidth(column), 260))
            self.message(f"已读取歌单 {sid}：{report['exported_count']}/{report['expected_count']} 条。")
        self.run_job(task, done)

    def choose_folder(self):
        folder = QFileDialog.getExistingDirectory(self, '选择导出文件夹', self.folder.text())
        if folder:
            self.folder.setText(folder)

    def export_current(self):
        if self.preview_data:
            self.export_ids([str(self.preview_data['playlist']['id'])])
        elif self.playlists.currentItem():
            self.export_ids([str(self.playlists.currentItem().data(Qt.ItemDataRole.UserRole))])
        else:
            self.message('请先导入或双击预览一个歌单。')

    def export_checked(self):
        ids = [str(self.playlists.item(i).data(Qt.ItemDataRole.UserRole)) for i in range(self.playlists.count())
               if self.playlists.item(i).checkState() == Qt.CheckState.Checked]
        if ids:
            self.export_ids(ids)
        else:
            self.message('请先勾选需要导出的歌单。')

    def export_ids(self, ids):
        root = Path(self.folder.text().strip())
        self.config['export_folder'] = str(root)
        try:
            save_config(self.config)
        except OSError:
            self.message('无法保存目录偏好，本次仍继续导出。')
        target = root / (datetime.now().strftime('%Y%m%d_%H%M%S') + '_' + uuid.uuid4().hex[:6])
        def task(progress):
            return export_batch(self.api, ids, target, self.mapping, progress)
        def done(results):
            self.last_folder = target
            count = sum(r['complete'] for r in results)
            self.message(f'批次结束：完整 {count}/{len(results)} 个；目录 {target}')
            if count == len(results):
                QMessageBox.information(self, '导出完成', f'已完整导出 {count} 个歌单。\nCSV、JSON、下载 CSV 和报告已保存。')
            else:
                QMessageBox.warning(self, '存在未完整导出的歌单', '本批次有失败或缺失，不能视为成功。\n请查看批次报告和各歌单 report.json。')
        self.run_job(task, done)

    def open_folder(self):
        folder = self.last_folder or Path(self.folder.text())
        if folder.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder.resolve())))

    @staticmethod
    def set_image(label, data, size):
        pixmap = QPixmap()
        if data and pixmap.loadFromData(data):
            label.setPixmap(pixmap.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio,
                                          Qt.TransformationMode.SmoothTransformation))
        else:
            label.clear()

    def closeEvent(self, event):
        if self.job is not None:
            self.message('当前操作仍在进行，请等待结束后关闭窗口。')
            event.ignore()
        else:
            self.timer.stop()
            self.browser_timer.stop()
            if self.browser_login:
                self.browser_login.close()
            self.api.client.close()
            event.accept()


def main():
    import sys
    import os
    import tempfile
    smoke = '--smoke-test' in sys.argv
    temporary = tempfile.TemporaryDirectory() if smoke else None
    if temporary:
        os.environ['LOCALAPPDATA'] = temporary.name
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    app = QApplication.instance() or QApplication([])
    app.setStyle('Fusion')
    app.setFont(QFont('Microsoft YaHei UI', 10))
    official = '--official-login' in sys.argv
    window = Window(auto_login=not official and not smoke, restore_session=not smoke)
    window.show()
    if smoke:
        if '--browser-smoke-test' in sys.argv:
            from .browser_login import OfficialLogin
            dialog = OfficialLogin(window, load_home=False)
            dialog.view.setHtml('<html><body>Browser runtime startup verification</body></html>')
            dialog.show()
            QTimer.singleShot(500, app.quit)
            app.exec()
            dialog.close()
        else:
            app.processEvents()
        window.close()
        temporary.cleanup()
        return 0
    if official:
        QTimer.singleShot(0, window.open_official_login)
    return app.exec()
