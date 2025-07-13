# 后端：app.py
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from playwright.async_api import async_playwright
import asyncio
import base64
import json
import traceback

app = FastAPI()

# 允许跨域请求
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 存储浏览器实例
active_sessions = {}


# 启动Playwright浏览器实例
async def start_browser_session(session_id):
    playwright = await async_playwright().start()
    browser = await playwright.chromium.launch(headless=False)
    context = await browser.new_context(
        viewport={"width": 1280, "height": 720},
        device_scale_factor=1
    )
    page = await context.new_page()

    active_sessions[session_id] = {
        "playwright": playwright,
        "browser": browser,
        "context": context,
        "page": page,
        "last_screenshot": None,
        "mouse_down": False  # 添加鼠标状态跟踪
    }

    return page


# 关闭浏览器实例
async def close_browser_session(session_id):
    if session_id in active_sessions:
        session = active_sessions[session_id]
        await session["context"].close()
        await session["browser"].close()
        await session["playwright"].stop()
        del active_sessions[session_id]


# 处理鼠标事件
async def handle_mouse_event(page, event, session_id):
    event_type = event["eventType"]
    x = event["x"]
    y = event["y"]
    is_double_click = event.get("isDoubleClick", False)

    # 更新鼠标状态
    if event_type == "mousedown":
        active_sessions[session_id]["mouse_down"] = True
    elif event_type in ["mouseup", "dblclick"]:
        active_sessions[session_id]["mouse_down"] = False

    # 移动鼠标到指定位置
    await page.mouse.move(x, y)

    # 处理具体事件
    if event_type == "mousedown":
        await page.mouse.click(x, y)
    elif event_type == "mouseup":
        await page.mouse.up()
    elif event_type == "dblclick":
        await page.mouse.down()
        await page.mouse.up()
        await asyncio.sleep(0.1)
        await page.mouse.down()
        await page.mouse.up()

    # 拖动中的移动处理
    elif event_type == "mousemove" and active_sessions[session_id]["mouse_down"]:
        await page.mouse.move(x, y)


# 处理键盘事件
async def handle_keyboard_event(page, event):
    event_type = event["eventType"]
    key = event["key"]
    code = event.get("code", "")
    shift = event.get("shiftKey", False)
    ctrl = event.get("ctrlKey", False)
    alt = event.get("altKey", False)
    meta = event.get("metaKey", False)

    # 处理修饰键
    modifiers = []
    if shift: modifiers.append("Shift")
    if ctrl: modifiers.append("Control")
    if alt: modifiers.append("Alt")
    if meta: modifiers.append("Meta")

    # 确保页面有焦点
    await page.bring_to_front()

    if event_type == "keydown":
        # 特殊键处理
        special_keys = {
            "Backspace": "Backspace",
            "Enter": "Enter",
            "Tab": "Tab",
            "Escape": "Escape",
            "ArrowLeft": "ArrowLeft",
            "ArrowRight": "ArrowRight",
            "ArrowUp": "ArrowUp",
            "ArrowDown": "ArrowDown",
            "Delete": "Delete",
            "Home": "Home",
            "End": "End",
            "PageUp": "PageUp",
            "PageDown": "PageDown"
        }

        if key in special_keys:
            await page.keyboard.press(special_keys[key])
        # 普通字符输入
        elif len(key) == 1:
            await page.keyboard.type(key)
        # 功能键处理
        elif key == "F5":
            await page.reload()
        else:
            print(f"未处理的按键: {key}")
    elif event_type == "keyup":
        # 处理按键释放
        pass  # Playwright通常不需要单独处理keyup


# 处理滚动事件
async def handle_scroll_event(page, event):
    delta_x = event.get("deltaX", 0)
    delta_y = event.get("deltaY", 0)
    await page.mouse.wheel(delta_x, delta_y)


# 处理导航事件
async def handle_navigation_event(page, event):
    url = event["url"]
    await page.goto(url)


# WebSocket 端点
@app.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    await websocket.accept()
    # 启动或恢复浏览器会话
    if session_id in active_sessions:
        page = active_sessions[session_id]["page"]
    else:
        page = await start_browser_session(session_id)

    try:
        # 发送初始截图
        screenshot = await page.screenshot(type="jpeg", quality=85)
        base64_image = base64.b64encode(screenshot).decode("utf-8")
        await websocket.send_json({
            "type": "screenshot",
            "data": f"data:image/jpeg;base64,{base64_image}"
        })

        # 截图发送任务
        async def send_screenshots():
            while True:
                try:
                    # 获取新截图
                    screenshot = await page.screenshot(type="jpeg", quality=80)
                    base64_image = base64.b64encode(screenshot).decode("utf-8")

                    # 只发送有变化的截图
                    if base64_image != active_sessions[session_id]["last_screenshot"]:
                        await websocket.send_json({
                            "type": "screenshot",
                            "data": f"data:image/jpeg;base64,{base64_image}"
                        })
                        active_sessions[session_id]["last_screenshot"] = base64_image

                    # 控制帧率（约15fps）
                    await asyncio.sleep(0.001)
                except Exception as e:
                    print(f"截图发送错误: {e}")
                    break

        # 启动截图任务
        screenshot_task = asyncio.create_task(send_screenshots())

        # 处理来自前端的消息
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)
            print(f"收到来自客户端的消息: {message}")
            if message["type"] == "mouse":
                await handle_mouse_event(page, message, session_id)
            elif message["type"] == "keyboard":
                await handle_keyboard_event(page, message)
            elif message["type"] == "scroll":
                await handle_scroll_event(page, message)
            elif message["type"] == "navigation":
                await handle_navigation_event(page, message)
            elif message["type"] == "resize":
                await page.set_viewport_size({
                    "width": message["width"],
                    "height": message["height"]
                })

    except WebSocketDisconnect:
        print(f"客户端断开连接: {session_id}")
    except Exception as e:
        print(f"发生错误: {e}")
    finally:
        screenshot_task.cancel()
        await close_browser_session(session_id)


# 挂载前端静态文件
app.mount("/", StaticFiles(directory="static", html=True), name="static")

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)