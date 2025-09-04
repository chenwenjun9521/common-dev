from pywinauto.application import Application
import time

# 1. 启动Windows计算器应用
# 对于UWP应用（如Windows 10/11自带计算器），需要用start方法并指定可执行文件路径
# 注意：不同系统的计算器路径可能不同，需根据实际情况调整
app = Application(backend="uia").start("calc.exe")

# 等待应用启动（根据系统性能调整等待时间）
time.sleep(10)

# 2. 连接到计算器窗口（通过窗口标题识别）
# Windows 11计算器默认标题为"计算器"，Windows 10可能为"计算器 - 标准"
calc_window = app.window(title="计算器")

# 确认窗口已打开
if not calc_window.exists():
    raise Exception("计算器窗口未找到，请检查应用是否启动")

# 3. 执行复杂计算：(123 + 456) × 789 ÷ 321
# 点击数字和运算符按钮（通过控件名称或文本识别）

# 输入123
calc_window["一"].click()
calc_window["二"].click()
calc_window["三"].click()

# 点击加号
calc_window["加"].click()

# 输入456
calc_window["四"].click()
calc_window["五"].click()
calc_window["六"].click()

# 点击等号（获取中间结果）
calc_window["等于"].click()
time.sleep(1)  # 等待计算完成

# 点击乘号
calc_window["乘"].click()

# 输入789
calc_window["七"].click()
calc_window["八"].click()
calc_window["九"].click()

# 点击除号
calc_window["除"].click()

# 输入321
calc_window["三"].click()
calc_window["二"].click()
calc_window["一"].click()

# 点击等号（获取最终结果）
calc_window["等于"].click()
time.sleep(1)

# 4. 获取并打印计算结果
# 计算器的结果显示控件通常名称为"显示"或"结果"，可通过inspect工具确认
result = calc_window["显示"].texts()[0]
print(f"计算结果: (123 + 456) × 789 ÷ 321 = {result}")

# 5. 操作菜单：切换到科学计算器模式
calc_window["菜单"].click()  # 点击左上角菜单按钮
time.sleep(0.5)
calc_window["科学"].click()  # 选择科学计算器模式
time.sleep(1)
print("已切换到科学计算器模式")

# 6. 关闭计算器
calc_window.close()
