import asyncio
import io
import time
import base64
from PIL import Image
import numpy as np
from playwright.async_api import async_playwright, Browser, Page, CDPSession

# 配置参数
CAPTURE_WIDTH = 1280
CAPTURE_HEIGHT = 720
TARGET_FPS = 30
TARGET_URL = "http://time.syiban.com/haomiao.php"


class PlaywrightCapture:
    def __init__(self):
        self.browser: Browser = None
        self.page: Page = None
        self.cdp_session: CDPSession = None
        self.running = False
        self.frame_interval = 1.0 / TARGET_FPS
        self.playwright = None
        # FPS 计算相关变量
        self.frame_count = 0
        self.last_fps_update = time.time()
        self.current_fps = 0.0

    async def init_browser(self):
        """初始化浏览器和 CDP 会话"""
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(
            headless=False,
            args=[
                f"--window-size={CAPTURE_WIDTH},{CAPTURE_HEIGHT}",
                "--enable-gpu-rasterization",
                "--disable-dev-shm-usage",
                "--no-sandbox",
                "--disable-audio-output",
                "--disable-background-networking",
                "--disable-extensions",
                '--disable-background-timer-throttling',
            ],
            ignore_default_args=["--enable-automation"],
            slow_mo=0,
        )

        context = await self.browser.new_context(
            viewport={"width": CAPTURE_WIDTH, "height": CAPTURE_HEIGHT},
            device_scale_factor=1.0,
        )
        self.page = await context.new_page()
        self.cdp_session = await self.page.context.new_cdp_session(self.page)
        await self.cdp_session.send("Page.enable")

        await self.page.goto(TARGET_URL, wait_until="networkidle")
        print(f"页面加载完成：{TARGET_URL}")

    async def capture_frame(self) -> Image:
        """捕获帧"""
        start_time = time.time()
        result = await self.cdp_session.send(
            "Page.captureScreenshot",
            {
                "format": "png",
                "quality": 80,
                "clip": {
                    "x": 0,
                    "y": 0,
                    "width": CAPTURE_WIDTH,
                    "height": CAPTURE_HEIGHT,
                    "scale": 1.0
                }
            }
        )

        img_bytes = base64.b64decode(result["data"])
        img = Image.open(io.BytesIO(img_bytes))

        capture_time = (time.time() - start_time) * 1000
        print(f"捕获耗时: {capture_time:.2f}ms")
        return img

    async def run_capture_loop(self):
        self.running = True
        last_frame_time = time.time()

        while self.running:
            current_time = time.time()
            elapsed = current_time - last_frame_time

            if elapsed < self.frame_interval:
                await asyncio.sleep(self.frame_interval - elapsed)

            try:
                frame = await self.capture_frame()
                last_frame_time = time.time()

                # 更新 FPS 计数
                self.update_fps_counter()
                self.process_frame(frame)
            except Exception as e:
                print(f"捕获失败: {e}")
                break

    def update_fps_counter(self):
        """更新帧率计数器"""
        self.frame_count += 1
        current_time = time.time()
        elapsed = current_time - self.last_fps_update

        # 每秒更新一次 FPS 值
        if elapsed >= 1.0:
            self.current_fps = self.frame_count / elapsed
            self.frame_count = 0
            self.last_fps_update = current_time
            print(f"当前 FPS: {self.current_fps:.2f}")

    def process_frame(self, frame: Image):
        """处理帧并在图像上叠加 FPS 信息"""
        frame_rgb = frame.convert("RGB")
        frame_np = np.array(frame_rgb)

        # 在图像上叠加 FPS 信息
        import cv2
        frame_bgr = cv2.cvtColor(frame_np, cv2.COLOR_RGB2BGR)

        # 创建 FPS 文本
        fps_text = f"FPS: {self.current_fps:.2f}"

        # 设置文本位置、字体和颜色
        position = (10, 30)  # 左上角位置
        font = cv2.FONT_HERSHEY_SIMPLEX
        font_scale = 0.8
        color = (0, 255, 0)  # 绿色文本
        thickness = 2

        # 添加文本到图像
        cv2.putText(frame_bgr, fps_text, position, font, font_scale, color, thickness)

        # 显示图像
        cv2.imshow("Capture", frame_bgr)
        if cv2.waitKey(1) & 0xFF == ord('q'):
            self.stop()

    def stop(self):
        self.running = False
        print("捕获已停止")

    async def close(self):
        """按正确顺序释放资源"""
        self.stop()
        if self.cdp_session:
            await self.cdp_session.detach()
        if self.page:
            await self.page.close()
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()
        print("所有资源已释放")


async def main():
    capture = PlaywrightCapture()
    try:
        await capture.init_browser()
        print(f"开始以 {TARGET_FPS}fps 捕获...（按 Ctrl+C 停止）")
        await capture.run_capture_loop()
    except KeyboardInterrupt:
        print("\n用户中断")
    finally:
        await capture.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except RuntimeError as e:
        if "Event loop is closed" not in str(e):
            raise