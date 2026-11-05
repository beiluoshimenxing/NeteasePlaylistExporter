"""Qt 离屏集成测试；认证与歌曲数据均为模拟。"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import time
from PySide6.QtWidgets import QApplication
from npe.gui import Window
from test_core import FakeAPI


class GUIFake(FakeAPI):
    def profile(self):
        return None

    def image(self, url):
        return b''

    def qr_key(self):
        return 'MOCK_QR_KEY'


def finish(app, window):
    end = time.monotonic() + 5
    while window.job is not None and time.monotonic() < end:
        app.processEvents()
        time.sleep(.01)
    assert window.job is None


def test_qt_preview_and_qr(tmp_path, monkeypatch):
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path))
    app = QApplication.instance() or QApplication([])
    window = Window(auto_login=False)
    real = window.api
    fake = GUIFake(120)
    fake.client = real.client
    window.api = fake
    window.show()
    time.sleep(.12)
    app.processEvents()  # startup session check
    finish(app, window)
    window.preview('123')
    finish(app, window)
    assert window.table.rowCount() == 120
    assert window.table.item(0, 2).text() == '歌手甲 / 歌手乙'
    assert window.preview_data['report']['complete']
    window.login()
    finish(app, window)
    assert window.key == 'MOCK_QR_KEY'
    assert not window.qr.pixmap().isNull()
    assert window.timer.isActive()
    window.close()
