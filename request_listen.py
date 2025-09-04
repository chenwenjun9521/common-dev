import asyncio
import cv2
import numpy as np
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import HTMLResponse
from contextlib import asynccontextmanager
from aiortc import MediaStreamTrack, RTCPeerConnection, RTCSessionDescription
from aiortc.rtcicetransport import RTCIceCandidate
from playwright.async_api import async_playwright
import json
from PIL import Image
from io import BytesIO


# 使用Lifespan替代deprecated的on_event
@asynccontextmanager
async def lifespan_manager(app: FastAPI):
    # 启动时初始化资源
    global browser, page, playwright_instance, pcs
    browser = None
    page = None
    playwright_instance = None
    pcs = set()
    yield
    # 关闭时清理资源
    coros = [pc.close() for pc in pcs]
    await asyncio.gather(*coros)
    pcs.clear()
    if browser:
        await browser.close()
    if playwright_instance:
        await playwright_instance.stop()
    print("服务器已关闭，资源已清理")


app = FastAPI(lifespan=lifespan_manager)

# 全局变量
browser = None
page = None
playwright_instance = None
pcs = set()


# 浏览器页面捕获轨道
class BrowserTrack(MediaStreamTrack):
    kind = "video"

    def __init__(self, page):
        super().__init__()
        self.page = page
        self.frame = None
        self.running = True
        self.capture_task = asyncio.create_task(self.capture_frames())

    async def capture_frames(self):
        while self.running:
            try:
                screenshot = await self.page.screenshot(type="png")
                img = Image.open(BytesIO(screenshot))
                frame = np.array(img)
                if frame.shape[-1] == 4:
                    frame = cv2.cvtColor(frame, cv2.COLOR_RGBA2RGB)
                self.frame = cv2.resize(frame, (1280, 720))
            except Exception as e:
                print(f"捕获帧时出错: {e}")
                self.frame = np.zeros((720, 1280, 3), np.uint8)
                cv2.putText(self.frame, "Capture Error", (50, 360),
                            cv2.FONT_HERSHEY_SIMPLEX, 2, (0, 0, 255), 3)
            await asyncio.sleep(0.03)

    async def recv(self):
        pts, time_base = await self.next_timestamp()
        frame = self.frame.copy() if self.frame is not None else np.zeros((720, 1280, 3), np.uint8)
        from av import VideoFrame
        frame = VideoFrame.from_ndarray(frame, format="rgb24")
        frame.pts = pts
        frame.time_base = time_base
        return frame

    async def stop(self):
        self.running = False
        if self.capture_task and not self.capture_task.done():
            self.capture_task.cancel()
            try:
                await self.capture_task
            except asyncio.CancelledError:
                pass


async def initialize_browser():
    """确保浏览器初始化成功并返回有效实例"""
    global browser, page, playwright_instance
    if not browser or not page or not playwright_instance:
        print("初始化浏览器...")
        playwright_instance = await async_playwright().start()
        browser = await playwright_instance.chromium.launch(headless=False)
        page = await browser.new_page()
        await page.goto("http://time.syiban.com/haomiao.php")
        # 验证初始化结果
        if not browser or not page:
            raise RuntimeError("浏览器初始化失败")
    return browser, page


@app.websocket("/offer")
async def websocket_offer(websocket: WebSocket):
    global browser, page, playwright_instance
    await websocket.accept()
    pc = RTCPeerConnection({
        "iceServers": [{"urls": "stun:stun.l.google.com:19302"}]  # 明确添加STUN服务器
    })
    pcs.add(pc)
    browser_track = None

    try:
        # 1. 接收并验证客户端offer
        data = await websocket.receive_text()
        offer = json.loads(data)
        print(f"收到offer: {offer.get('type')}")

        # 严格验证offer格式
        if not isinstance(offer, dict) or "sdp" not in offer or "type" not in offer:
            raise ValueError("无效的offer格式：必须包含sdp和type字段")
        if offer["sdp"] is None or offer["type"] != "offer":
            raise ValueError("无效的offer数据：sdp不能为空且类型必须为'offer'")

        offer_sdp = RTCSessionDescription(sdp=offer["sdp"], type=offer["type"])

        # 2. 初始化浏览器
        browser, page = await initialize_browser()

        # 3. 创建媒体轨道并添加到连接
        browser_track = BrowserTrack(page)
        pc.addTrack(browser_track)

        # 4. 处理SDP应答（关键修复：确保localDescription有效）
        await pc.setRemoteDescription(offer_sdp)
        answer = await pc.createAnswer()
        await pc.setLocalDescription(answer)

        # 验证本地描述是否生成
        if pc.localDescription is None:
            raise RuntimeError("生成本地SDP描述失败")
        if pc.localDescription.sdp is None:
            raise RuntimeError("本地SDP描述中sdp为空")

        # 发送应答
        response = {
            "sdp": pc.localDescription.sdp,
            "type": pc.localDescription.type
        }
        await websocket.send_text(json.dumps(response))
        print("已发送应答")

        # 5. 处理ICE候选（强化过滤）
        while True:
            try:
                data = await websocket.receive_text()
                data = json.loads(data)
                print(f"收到消息: {list(data.keys())}")  # 打印消息类型，不打印完整数据

                if "candidate" in data:
                    candidate_data = data["candidate"]
                    # 多层验证：非None、是字典、包含必要字段
                    if candidate_data is None:
                        print("忽略空候选")
                        continue
                    if not isinstance(candidate_data, dict):
                        print(f"候选格式错误（非字典）: {type(candidate_data)}")
                        continue
                    if "candidate" not in candidate_data or "sdpMid" not in candidate_data:
                        print("候选缺少必要字段")
                        continue

                    # 安全创建ICE候选对象
                    try:
                        candidate = RTCIceCandidate(
                            candidate=candidate_data["candidate"],
                            sdpMid=candidate_data["sdpMid"],
                            sdpMLineIndex=candidate_data.get("sdpMLineIndex")
                        )
                        await pc.addIceCandidate(candidate)
                        print("添加ICE候选成功")
                    except Exception as e:
                        print(f"创建ICE候选失败: {e}")
                        continue

            except WebSocketDisconnect:
                print("客户端断开连接")
                break
            except Exception as e:
                print(f"处理消息时出错: {e}")
                break

    except Exception as e:
        print(f"WebSocket错误: {e}")
    finally:
        # 清理资源
        await pc.close()
        pcs.discard(pc)
        if browser_track:
            await browser_track.stop()
        print("连接已关闭并清理资源")


@app.get("/")
async def get():
    return HTMLResponse("""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Browser Stream Viewer</title>
    </head>
    <body>
        <h1>Browser Stream Viewer</h1>
        <video id="video" autoplay playsinline width="1280" height="720"></video>
        <script>
            const video = document.getElementById('video');
            const websocket = new WebSocket('ws://' + window.location.host + '/offer');

            let pc;

            async function start() {
                pc = new RTCPeerConnection({
                    iceServers: [{ urls: 'stun:stun.l.google.com:19302' }]
                });

                pc.ontrack = e => { video.srcObject = e.streams[0]; };
                pc.onicecandidate = e => {
                    if (e.candidate) {
                        websocket.send(JSON.stringify({ candidate: e.candidate }));
                    }
                };
                pc.oniceconnectionstatechange = () => {
                    console.log('ICE连接状态:', pc.iceConnectionState);
                };

                const offer = await pc.createOffer();
                await pc.setLocalDescription(offer);
                websocket.send(JSON.stringify({
                    sdp: pc.localDescription.sdp,
                    type: pc.localDescription.type
                }));
            }

            websocket.onmessage = async e => {
                const data = JSON.parse(e.data);
                if (data.sdp) {
                    await pc.setRemoteDescription(new RTCSessionDescription(data));
                } else if (data.candidate) {
                    await pc.addIceCandidate(new RTCIceCandidate(data.candidate));
                }
            };

            start();
        </script>
    </body>
    </html>
    """)


async def webrtc_cv2_client():
    import websockets
    from aiortc import RTCPeerConnection, RTCSessionDescription

    print("等待服务器启动...")
    server_ready = False
    while not server_ready:
        try:
            async with websockets.connect("ws://localhost:8000/offer", ping_interval=5) as test_ws:
                server_ready = True
            print("服务器已准备就绪")
        except Exception as e:
            print(f"等待服务器... {e}")
            await asyncio.sleep(2)

    pc = RTCPeerConnection({"iceServers": [{"urls": "stun:stun.l.google.com:19302"}]})
    frame_queue = asyncio.Queue(maxsize=10)

    @pc.on("track")
    def on_track(track):
        print("收到媒体轨道，开始接收画面...")

        async def frame_handler():
            while True:
                try:
                    frame = await track.recv()
                    img = frame.to_ndarray(format="bgr24")
                    if not frame_queue.full():
                        await frame_queue.put(img)
                except Exception as e:
                    print(f"帧处理错误: {e}")
                    break

        asyncio.create_task(frame_handler())

    try:
        async with websockets.connect("ws://localhost:8000/offer", ping_interval=5) as websocket:
            # 发送offer
            offer = await pc.createOffer()
            await pc.setLocalDescription(offer)
            await websocket.send(json.dumps({
                "sdp": pc.localDescription.sdp,
                "type": pc.localDescription.type
            }))

            # 接收应答
            response = await websocket.recv()
            data = json.loads(response)
            await pc.setRemoteDescription(RTCSessionDescription(sdp=data["sdp"], type=data["type"]))

            # 处理ICE候选
            async def handle_ice():
                while True:
                    try:
                        data = await websocket.recv()
                        data = json.loads(data)
                        if "candidate" in data and data["candidate"]:
                            await pc.addIceCandidate(data["candidate"])
                    except Exception as e:
                        print(f"ICE处理错误: {e}")
                        break

            asyncio.create_task(handle_ice())

            # 显示画面
            print("开始显示画面（按q退出）")
            while True:
                frame = await frame_queue.get()
                cv2.imshow("Browser Stream", frame)
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    break
            cv2.destroyAllWindows()

    except Exception as e:
        print(f"客户端错误: {e}")
    finally:
        await pc.close()


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "client":
        asyncio.run(webrtc_cv2_client())
    else:
        import uvicorn

        uvicorn.run(app, host="127.0.0.1", port=8000)  # 绑定本地回环地址，避免网络问题
