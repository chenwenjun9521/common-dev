import asyncio
import sys
from PySide6.QtWidgets import (QApplication, QMainWindow, QVBoxLayout,
                               QHBoxLayout, QLineEdit, QPushButton,
                               QWidget, QProgressBar, QTabWidget, QFrame)
from PySide6.QtCore import QTimer, Signal, QObject
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebEngineCore import QWebEnginePage
from playwright.async_api import async_playwright
import threading
from functools import partial


class BrowserSignals(QObject):
    """信号类，用于线程间通信"""
    page_loaded = Signal(str, str)  # url, title
    progress_update = Signal(int)
    status_update = Signal(str)


class AsyncBrowserManager:
    """异步浏览器管理器"""

    def __init__(self, signals):
        self.signals = signals
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None
        self.is_running = False

    async def start_browser(self):
        """启动浏览器"""
        try:
            self.playwright = await async_playwright().start()
            self.browser = await self.playwright.chromium.launch(
                headless=False,
                args=['--no-sandbox', '--disable-web-security']
            )
            self.context = await self.browser.new_context(
                viewport={'width': 1280, 'height': 720}
            )
            self.page = await self.context.new_page()

            # 设置页面事件监听
            self.page.on("load", lambda: asyncio.create_task(self.on_page_loaded()))
            self.page.on("domcontentloaded", lambda: asyncio.create_task(self.on_dom_loaded()))

            self.is_running = True
            self.signals.status_update.emit("浏览器已启动")
            return True
        except Exception as e:
            self.signals.status_update.emit(f"启动浏览器失败: {str(e)}")
            return False

    async def navigate_to(self, url):
        """导航到指定URL"""
        if not self.page or not self.is_running:
            self.signals.status_update.emit("浏览器未启动")
            return

        try:
            if not url.startswith(('http://', 'https://')):
                url = 'https://' + url

            self.signals.status_update.emit(f"正在加载: {url}")
            self.signals.progress_update.emit(30)

            await self.page.goto(url, wait_until='domcontentloaded')

            self.signals.progress_update.emit(80)

        except Exception as e:
            self.signals.status_update.emit(f"加载页面失败: {str(e)}")
            self.signals.progress_update.emit(0)

    async def on_page_loaded(self):
        """页面加载完成时的回调"""
        try:
            title = await self.page.title()
            url = self.page.url
            self.signals.page_loaded.emit(url, title)
            self.signals.progress_update.emit(100)
            self.signals.status_update.emit(f"页面加载完成: {title}")

            # 重置进度条
            QTimer.singleShot(1000, lambda: self.signals.progress_update.emit(0))
        except Exception as e:
            self.signals.status_update.emit(f"获取页面信息失败: {str(e)}")

    async def on_dom_loaded(self):
        """DOM内容加载完成时的回调"""
        self.signals.progress_update.emit(60)

    async def close(self):
        """关闭浏览器"""
        try:
            self.is_running = False
            if self.context:
                await self.context.close()
            if self.browser:
                await self.browser.close()
            if self.playwright:
                await self.playwright.stop()
            self.signals.status_update.emit("浏览器已关闭")
        except Exception as e:
            self.signals.status_update.emit(f"关闭浏览器失败: {str(e)}")


class BrowserTab(QWidget):
    """浏览器标签页"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.browser_manager = None
        self.loop = None
        self.thread = None
        self.signals = BrowserSignals()
        self.setup_ui()
        self.connect_signals()

    def setup_ui(self):
        """设置UI"""
        layout = QVBoxLayout(self)

        # 地址栏和按钮
        nav_layout = QHBoxLayout()
        self.url_bar = QLineEdit()
        self.url_bar.setPlaceholderText("输入网址 (例如: https://www.google.com)")
        self.go_button = QPushButton("前往")
        self.back_button = QPushButton("后退")
        self.forward_button = QPushButton("前进")
        self.refresh_button = QPushButton("刷新")

        nav_layout.addWidget(self.back_button)
        nav_layout.addWidget(self.forward_button)
        nav_layout.addWidget(self.refresh_button)
        nav_layout.addWidget(self.url_bar)
        nav_layout.addWidget(self.go_button)

        # 进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)

        # 状态标签
        self.status_label = QLineEdit()
        self.status_label.setReadOnly(True)
        self.status_label.setPlaceholderText("状态信息将显示在这里...")

        # 网页视图
        self.web_view = QWebEngineView()
        self.web_view.setUrl("https://www.google.com")

        layout.addLayout(nav_layout)
        layout.addWidget(self.progress_bar)
        layout.addWidget(self.status_label)
        layout.addWidget(self.web_view)

    def connect_signals(self):
        """连接信号"""
        self.go_button.clicked.connect(self.navigate)
        self.back_button.clicked.connect(self.web_view.back)
        self.forward_button.clicked.connect(self.web_view.forward)
        self.refresh_button.clicked.connect(self.web_view.reload)
        self.url_bar.returnPressed.connect(self.navigate)

        # 连接浏览器信号
        self.signals.page_loaded.connect(self.on_page_loaded)
        self.signals.progress_update.connect(self.on_progress_update)
        self.signals.status_update.connect(self.on_status_update)

        # 连接网页视图信号
        self.web_view.loadStarted.connect(self.on_load_started)
        self.web_view.loadProgress.connect(self.on_web_load_progress)
        self.web_view.loadFinished.connect(self.on_web_load_finished)
        self.web_view.urlChanged.connect(self.on_url_changed)

    def on_load_started(self):
        """网页开始加载"""
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)

    def on_web_load_progress(self, progress):
        """网页加载进度"""
        self.progress_bar.setValue(progress)

    def on_web_load_finished(self, ok):
        """网页加载完成"""
        self.progress_bar.setVisible(False)
        if ok:
            self.status_label.setText("页面加载完成")
        else:
            self.status_label.setText("页面加载失败")

    def on_url_changed(self, url):
        """URL改变"""
        self.url_bar.setText(url.toString())

    def navigate(self):
        """导航到URL"""
        url = self.url_bar.text().strip()
        if url:
            # 使用Qt的WebEngineView进行显示
            if not url.startswith(('http://', 'https://')):
                url = 'https://' + url
            self.web_view.setUrl(url)

            # 同时使用Playwright进行后台操作
            if self.browser_manager and self.browser_manager.is_running:
                asyncio.run_coroutine_threadsafe(
                    self.browser_manager.navigate_to(url),
                    self.loop
                )

    def on_page_loaded(self, url, title):
        """页面加载完成回调"""
        self.status_label.setText(f"Playwright: 已加载 - {title}")
        self.url_bar.setText(url)

    def on_progress_update(self, progress):
        """进度更新回调"""
        if progress > 0:
            self.progress_bar.setVisible(True)
            self.progress_bar.setValue(progress)
        else:
            self.progress_bar.setVisible(False)

    def on_status_update(self, status):
        """状态更新回调"""
        self.status_label.setText(f"Playwright: {status}")

    def start_playwright(self):
        """启动Playwright浏览器"""

        def run_async():
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)

            self.browser_manager = AsyncBrowserManager(self.signals)

            async def main():
                await self.browser_manager.start_browser()

            self.loop.run_until_complete(main())
            self.loop.run_forever()

        self.thread = threading.Thread(target=run_async, daemon=True)
        self.thread.start()

    def closeEvent(self, event):
        """关闭事件"""
        if self.browser_manager and self.browser_manager.is_running:
            asyncio.run_coroutine_threadsafe(
                self.browser_manager.close(),
                self.loop
            )
        if self.loop:
            self.loop.call_soon_threadsafe(self.loop.stop)
        event.accept()


class MainWindow(QMainWindow):
    """主窗口"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Playwright 浏览器 - 异步GUI")
        self.setGeometry(100, 100, 1200, 800)

        self.setup_ui()
        self.setup_tabs()

    def setup_ui(self):
        """设置UI"""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        layout = QVBoxLayout(central_widget)

        # 标签页控件
        self.tab_widget = QTabWidget()
        self.tab_widget.setTabsClosable(True)
        self.tab_widget.tabCloseRequested.connect(self.close_tab)

        # 新建标签页按钮
        self.new_tab_button = QPushButton("新建标签页")
        self.new_tab_button.clicked.connect(self.create_new_tab)

        top_layout = QHBoxLayout()
        top_layout.addWidget(self.new_tab_button)
        top_layout.addStretch()

        layout.addLayout(top_layout)
        layout.addWidget(self.tab_widget)

    def setup_tabs(self):
        """设置初始标签页"""
        self.create_new_tab()

    def create_new_tab(self):
        """创建新标签页"""
        tab = BrowserTab()
        index = self.tab_widget.addTab(tab, "新标签页")
        self.tab_widget.setCurrentIndex(index)

        # 启动Playwright
        tab.start_playwright()

        # 连接标签标题更新
        tab.signals.page_loaded.connect(
            lambda url, title, idx=index: self.update_tab_title(idx, title)
        )

        return tab

    def update_tab_title(self, index, title):
        """更新标签页标题"""
        if title:
            # 限制标题长度
            display_title = title[:20] + "..." if len(title) > 20 else title
            self.tab_widget.setTabText(index, display_title)
            self.tab_widget.setTabToolTip(index, title)

    def close_tab(self, index):
        """关闭标签页"""
        if self.tab_widget.count() > 1:
            widget = self.tab_widget.widget(index)
            widget.close()
            self.tab_widget.removeTab(index)

    def closeEvent(self, event):
        """关闭事件"""
        # 关闭所有标签页
        for i in range(self.tab_widget.count()):
            widget = self.tab_widget.widget(i)
            if widget:
                widget.close()
        event.accept()


if __name__ == "__main__":
    # 创建应用
    app = QApplication(sys.argv)
    app.setApplicationName("Playwright Browser")

    # 创建主窗口
    window = MainWindow()
    window.show()

    # 运行应用
    try:
        sys.exit(app.exec())
    except KeyboardInterrupt:
        print("应用被用户中断")
    finally:
        print("应用已退出")