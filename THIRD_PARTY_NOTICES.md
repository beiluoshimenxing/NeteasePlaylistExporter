# Third-party notices

The project source code is MIT licensed. The Windows distribution includes unmodified third-party runtimes and libraries with their own licenses, not relicensed by this project.

- CPython: Python Software Foundation License.
- PySide6 / Shiboken6 and Qt: distributed under their applicable LGPL/GPL/commercial alternatives; this distribution uses the open-source LGPL terms where applicable. Qt libraries are dynamically linked, unmodified, and remain separate files in `_internal`. Users may replace compatible shared libraries and reverse engineer for debugging modifications as permitted by LGPL. Qt WebEngine includes Chromium and additional components with their own notices.
- httpx, httpcore, anyio, idna, h11, certifi, qrcode, Pillow and their bundled components: see included license texts.
- PyInstaller bootloader: GPL with the distribution exception; application code keeps its own license.

Full installed package license texts and Qt WebEngine Chromium notices are copied into `third_party_licenses/` in the Windows package. Qt source and licensing information: https://www.qt.io/download-qt-installer-oss and https://code.qt.io/ ; PySide sources: https://code.qt.io/cgit/pyside/pyside-setup.git/ ; corresponding Qt module sources: https://code.qt.io/cgit/qt/ . Use the exact Qt/PySide version listed in the package's dependency manifest. PyInstaller sources: https://github.com/pyinstaller/pyinstaller . Python sources: https://www.python.org/downloads/source/ .

Protocol endpoint names and response field references were consulted in NeteaseCloudMusicApiEnhanced (MIT); its service and source code are not bundled: https://github.com/NeteaseCloudMusicApiEnhanced/api-enhanced .
