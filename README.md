# EZ2.4G 外设电量 · VT3S MAX / K99 V3 适配版

Windows 10/11 x64 无线外设电量托盘工具，使用 Python 标准库（`ctypes` + `tkinter`），无需第三方 Python 包。

本项目 fork 自 **[Ap0LoG1zE/EZ2.4G](https://github.com/Ap0LoG1zE/EZ2.4G)**，修改基于上游 **v1.0.0**（`604cfd422627b2c4edd2e88b6a25ac93d6ea64d4`）。原始工具、界面和通用协议归原作者；本 fork 新增雷柏 VT3S MAX、迈从 K99 V3 适配，并改进托盘、通知和启动体验。

## 适配了哪些设备

### 本 fork 新增

| 设备 | 连接方式 / VID:PID | 实现与验证状态 |
|---|---|---|
| **雷柏 Rapoo VT3S MAX** | **2.4G 接收器 `24AE:1421`** | 已实测；项目与官方旧版网页均显示 **54%**，GUI 持续被动监听 |
| 雷柏 Rapoo VT3S MAX | 有线 `24AE:4621` | 已实现识别和报告解析，尚未完成有线实测 |
| **迈从 MCHOSE K99 V3** | **2.4G 接收器 `3837:3033`** | 已实测 **100%**，与此前官网截图一致；GUI 启动即查询，此后默认每 60 秒刷新 |
| 迈从 MCHOSE K99 V3 | 有线 `3837:2020` | 已实现识别和查询路径，尚未完成有线实测 |

K99 V3 接收器 PID 与其他型号共享，必须同时匹配产品名 `MCHOSE K99 V3 2.4G`，不会将所有同 PID 键盘视为 K99 V3。蓝牙模式未适配。

### 保留的上游设备支持

| 设备 | VID:PID | 本 fork 状态 |
|---|---|---|
| ATK 蜻蜓 A9 mini 大师版（无线） | `373B:1278` | 保留上游协议，恢复被临时提前返回禁用的读取入口；本轮未实测 |
| ATK 蜻蜓 A9 mini 大师版（有线） | `373B:128E` | 同上 |
| MCHOSE V9 Turbo | `3837:600D` | 保留上游协议，恢复读取入口；本轮未实测 |

其他设备保留上游标准 HID 电量检测和自定义协议学习功能，不代表已逐一适配。

## 相比原项目做了什么修改

- **VT3S MAX 专用协议与持续监听**：根据雷柏官方网页驱动解析 HID `0x07` 电量报告。GUI 持续持有匹配接口，收到报告就更新，避免每分钟只监听约 3 秒而错过上报；不发送鼠标初始化或主动查询命令。
- **K99 V3 专用协议与定时查询**：根据迈从官方 M HUB 的 GLW `0x05` 配置读取路径，每次最多发送两条读取请求，解析电量和充电标志；不执行配置写入、完整 SDK 初始化或自动重试。保留被动通知诊断入口。
- **设备隔离**：专用设备不回退到通用探测或用户协议；限定诊断入口过滤目标 VID/PID、产品名和 collection。
- **Windows 异步 HID 修复**：取消读取后等待 OVERLAPPED 操作结束，再释放缓冲区和事件句柄；处理完成与取消的竞争，保留读取错误信息。
- **稳定的托盘图标**：每台设备使用固定 ID 和 GUID，减少设备增减或短暂超时导致的图标消失、位置变化；支持 Explorer 托盘重建后的恢复。
- **区分实时和历史电量**：从未读到电量的设备不显示图标；短暂失败最多保留 5 分钟灰色旧读数，断开或到期后移除。面板区分电量未知、读取超时、充电中和上次成功时间。
- **低电量与充满电通知**：默认严格低于 20% 提醒，阈值可设为 1–100，0 为关闭；同一次低电量期间只提醒一次，未知、失败、过期或充电中读数不触发低电量通知。新增“测试通知”，区分提交成功与 Windows 已显示回调；充满电通知等待托盘就绪后发送。
- **启动与面板体验**：移除原作者机器的固定 Python 路径；手动启动显示面板，开机自启静默运行。无参数优先用 `pythonw`，带参数保留控制台输出；托盘左键打开面板，底部状态可手动刷新。
- **离线回归测试**：新增协议解析、查询帧、设备派发、异步读取生命周期、监听队列、托盘、通知和启动测试。

## 快速开始

环境：**Windows 10/11 x64、Python 3.10+（包含 tkinter）**。

```powershell
git clone https://github.com/duoxini/EZ2.4G.git
cd EZ2.4G
python my_devices.py
```

也可双击 `启动.bat`。脚本优先使用当前用户已有的 Codex Python runtime，其次查找 PATH 中的 `python.exe`；普通 Python 环境可直接使用上述命令。

```powershell
python my_devices.py                 # 面板 + 托盘常驻
python my_devices.py --panel          # 只开面板，无托盘通知
python my_devices.py --once           # 全设备读取一次并打印本轮结果
python my_devices.py --list           # 列出 HID 接口
python my_devices.py --install        # 创建开机自启和桌面入口
```

配置文件：`%APPDATA%\BatteryTray\config.json`，保存刷新间隔、低电量阈值、设备名称、自定义协议及最近成功读数。开机自启入口在后台运行，手动启动显示面板。

## 单设备诊断

```powershell
# VT3S MAX：约 3 秒被动读取，不发送查询
python my_devices.py --once --rapoo-only

# K99 V3：两条官方 GLW 0x05 配置读取请求
python my_devices.py --once --k99-only --k99-query

# K99 V3：仅监听被动通知，不发送查询
python my_devices.py --once --k99-only
```

限定入口不读取其他设备电量，也不把历史缓存当成本次成功。鼠标首次电量取决于设备上报时机，约 3 秒无报告不等于未连接；日常 GUI 持续监听。键盘单次查询可能超时，面板标记旧值并等待下一轮刷新。

## 验证状态与限制

- 2026-10-25：**98 项离线测试通过**，使用合成字节、AST 提取和 mock，不访问实际设备。
- 已有实机记录：VT3S MAX 2.4G 电量 54%；K99 V3 2.4G 电量 100%，GUI 后台刷新再次成功；托盘拖动后用户确认正常；测试通知收到 Windows 显示回调且用户确认看到弹出。
- 有线、其他固件、长时间运行、完整休眠唤醒及多次重连尚未完成验收。键盘充电、0% 和真实低电量阈值穿越尚未逐项实测。
- 电量来自设备上报，不估算百分比；未实现无线 RSSI 或解决键盘 2.4G 卡顿。

```powershell
python -B -m unittest discover -s tests -v
```

## 协议与详细记录

- [双设备适配说明](双设备适配说明.md)：实现过程、实测结果及托盘/通知改进。
- 雷柏：[协议证据](docs/RAPOO_VT3S_MAX_PROTOCOL_EVIDENCE.md)、[初始化路径](docs/RAPOO_VT3S_MAX_INIT_PATH.md)、[旧版网页分析](docs/RAPOO_VT3S_MAX_LEGACY_HUB_ANALYSIS.md)、[验证记录](docs/RAPOO_VALIDATION.md)。
- 迈从：[通知协议证据](docs/MCHOSE_K99_V3_PROTOCOL_EVIDENCE.md)、[配置读取证据](docs/MCHOSE_K99_V3_QUERY_EVIDENCE.md)、[验证记录](docs/MCHOSE_K99_V3_VALIDATION.md)、[2.4G 排查记录](docs/K99_WIRELESS_DIAGNOSIS.md)。

这些文档保留了早期失败和待验证记录，阅读时请结合日期和末尾补记；当前支持范围以上表为准。官方原始 JS 资源和本地抓包不随仓库发布。

## 未知设备协议学习

保留上游 [USBPcap](https://desowin.org/usbpcap/) 抓包助手，需要单独安装驱动和管理员权限。当前助手按 USB 根集线器抓包，可能包含同集线器其他设备流量，**不是单设备隔离抓包**。已适配设备的日常电量读取不需要 USBPcap。

## 主要文件

| 文件 | 用途 |
|---|---|
| `my_devices.py` | Windows HID、设备派发、GUI、托盘和通知 |
| `rapoo_protocol.py` / `rapoo_monitor.py` | 雷柏报告解析及持续监听 |
| `mchose_k99_protocol.py` | K99 身份识别、通知与配置读取协议 |
| `battery_alerts.py` / `tray_state.py` | 提醒策略、托盘身份和读数状态 |
| `capture_helper.py` | 上游 USBPcap 抓包助手 |
| `启动.bat` | Windows 启动入口 |
| `tests/` | 无设备访问的离线回归测试 |

## 致谢与来源

- 原项目：[Ap0LoG1zE/EZ2.4G](https://github.com/Ap0LoG1zE/EZ2.4G)。
- 协议分析参考：[Rapoo 官方网页驱动](https://hub.rapoo.com/)、[迈从官方 M HUB](https://www.mchose.com.cn/)。

上游当前未声明许可证，本 fork 未另行添加授权条款。
