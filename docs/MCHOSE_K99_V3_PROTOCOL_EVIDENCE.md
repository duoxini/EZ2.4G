# MCHOSE K99 V3：官方静态协议证据

核验日期：2026-10-22。键盘未连接，本轮没有枚举或访问任何 HID 设备。
仅使用 Python 标准库、正常 TLS 证书校验下载官方文本资源并静态检索；未执行网页 JS、
驱动、安装器或固件。本文的设备身份是官方型号表记录，不是用户实物描述符。

## 来源与可复核资源

[K99 V3 官方产品页](https://www.mchose.store/products/mchose-k99-v3-keyboard)
明确列出 M HUB Web/Desktop，并链接到 [官方 Web 驱动](https://www.mchose.com.cn/)。
[官方 HUB 下载页](https://www.mchose.store/pages/mchose-hub)也提供同一网页入口和桌面驱动下载。
没有下载、安装或启动桌面驱动；网页资源足以完成本轮静态分析。

HTML 引用 `/cizhou/CZ_SHARED_DATA/loader.js?v=3`；loader 读取同目录 manifest；
manifest 的 main entrypoint 指向下表的 CZ main 文件。未运行 loader。
资源副本位于 `mchose_assets`，不随项目发布。

| 官方资源 | 字节数 | SHA-256 |
|---|---:|---|
| [HTML](https://www.mchose.com.cn/) | 6996 | `97081f481437a19b25870f06cb00d16620fcbe14eaf99290d309f13c123c68f0` |
| [CZ loader](https://www.mchose.com.cn/cizhou/CZ_SHARED_DATA/loader.js?v=3) | 27910 | `3cd59ccfc8555d612e3bb37aa3a04b9aaca6ba90a37c8bcde6e5255be2be51cf` |
| [CZ manifest](https://www.mchose.com.cn/cizhou/CZ_SHARED_DATA/asset-manifest.json?v=1) | 5558 | `3e5c93c8238efe95042d2041e881ad315859eb726bd36f4895ae157c50cb6d18` |
| [CZ main](https://www.mchose.com.cn/cizhou/CZ_SHARED_DATA/main.504a955bfd84363d1e76.js) | 670427 | `c16055520ed1c43483a5357f74e265e3a356b0f7d2a4298a3d90ad6cf0a127ff` |

下面源码位置均指上述 CZ main 的第 1 行、零起始 UTF-8 字节偏移，**不是字符偏移**。
本机 `source_coordinates.json` 记录检索词、字符/字节偏移与短摘录。

## 精确型号、接收器与 collection 过滤

模块 80456，字节 119960 附近的记录明确为 `storageKey/name/fullName: K99 V3`，
`glbKeyboardKey: K99V3`，type 132。与旧 K99、K99 V2 分别建模，不能套用旧驱动解析器。

| 模式 | 官方身份 | 适配判断 |
|---|---|---|
| 正常有线 | VID `3837`，PID `2020`，productName 为 null | 精确 VID/PID |
| 正常 2.4G | VID `3837`，PID `3033`，productName `MCHOSE K99 V3 2.4G` | 必须同时匹配产品名；3033 被 K87S 等型号共享 |
| 有线 boot/update | `3837:201F` | 不接入读取 |
| 接收器 boot/update | `3837:2010`，同接收器产品名 | 不接入读取 |

型号 `hidFilters` 的正常项为 usage page `0001`、usage `0000`；
`FF00:0001` 项有 `boot:true`，不是正常模式备用接口。
接收器 spread 没有单列 hidFilters，但字节 127810 的 Ce 合并逻辑先复制父记录、再覆盖 spread 字段，
字节 128232 的 Ae 按 boot 标记分别构造过滤器，故接收器继承正常 `0001:0000` 过滤项。
这证明的是官方软件 collection 过滤配置；没有物理接口编号、端点或本机 report descriptor。
实现只读取正常过滤项，拒绝 `0001:0006` 键盘 collection、boot collection 和非目标产品名。

## K99 V3 使用 GLW 电量通知路径

静态调用链：

1. 模块 80456，字节 141166，manufacturer getter Lt 缺省返回 `glw`；K99 V3 记录没有覆盖。
2. 模块 55682，字节 403925，连接分发为 GLW SDK `g.vG`，而非 QHW SDK。
3. 模块 20721，字节 416448，GLW SDK 创建 `new Y.ZZ(hidDevice)`，对应模块 39318 的 GLW channel。
4. channel 基类模块 87033，字节 383933，注册 `inputreport` 回调。
5. 模块 39318，字节 272567 的 handleMessage 从 `event.data.buffer` 取得 payload。
   此 handler 没有检查 `event.reportId`，其电量分支如下。

| WebHID payload 偏移 | 含义 |
|---:|---|
| 0..2 | 必须为 `FA FB 07` |
| 3 | 仅在偏移 4 为 0 时，由官方代码作为 battery 数值发出 |
| 4 | 0：stopCharging + updateBattery；1：只发 charging 事件；其他不走此分支 |

因此纯解析器要求至少 5 字节 payload，非充电值只接受 0..100（本项目额外的范围验证），
充电通知返回 `level=None`。状态 0 命名为 `not_charging`，不据此推断正在放电。
它不把充电时的 payload[3] 当成有效百分比，不缩放、钳制或估算。
源码该分支未检查校验和，也没有声明完整报文固定长度，不能杜撰。

Windows `ReadFile` 与 WebHID 的 framing 不同：[Microsoft HIDP_CAPS](https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/hidpi/ns-hidpi-_hidp_caps)
说明 InputReportByteLength 包含前置 Report ID（无 ID 时为 0）；
[Obtaining HID Reports](https://learn.microsoft.com/en-us/windows-hardware/drivers/hid/obtaining-hid-reports)
说明 ReadFile 按 collection 接收输入报告。因此 native decoder 去掉 raw[0] 后调用 payload decoder，
最低 native 长度是 6 字节；这不是宣称目标描述符长度恰为 6。
官方 handler 不检查 report ID，本实现也不猜固定值。真实 ID、报告总长度、填充和上报时机待采样。
不能采用 QHW 的 Report 4D / command 0700 或旧 K99/V2 的 13 4A 查询。

## 已确认的限制：解析分支不等于设备一定发送

模块 20721 字节 418053 的 `_proxyEvent` 会在 `AllowUpdateBattery` 未启用时丢弃 updateBattery。
模块 80456 字节 137509 的默认值为 manufacturer 是否是 qhw；当前静态 K99 V3 记录没有覆盖，
所以按这份静态配置，GLW 电量事件会被丢弃。运行时配置是否改写此能力、固件是否发送上述通知、
官方 UI 是否通过配置读取显示电量，都没有实机证据。

本实现是有官方解析依据的**被动候选读取路径**，不是已验收的电量支持。
既没有证明被动监听需要初始化，也没有证明无需初始化即可收包。
官方完整连接流程包含查询/配置操作，本轮未复现，也未向设备发送任何报文。
充电时的百分比可能需要另一条配置读取路径；本轮只实现已确认的被动通知分支。

## 实现边界与下一步

`mchose_k99_protocol.py` 仅解释调用者提供的字节；`read_k99_v3` 使用现有只读 HID transport。
没有添加 Feature 请求、Output 写入、设备设置或固件路径。
`--once --k99-only` 在打开接口前限定上述 VID/PID；共享 PID 再按产品名和 collection 过滤。
枚举按 VID/PID 定位后，必须先以 access=0 打开同 PID 接口来取得产品名/能力元数据，
之后才能排除其他型号；其他型号不会进入 input 读取。
正常 read_all 也专门派发该型号，并从通用/用户协议 discovery 排除它。
3033 整个 PID 不加入 known_ids，以免误认其他型号。

离线验证、用户连接后所需的最小采样和未决问题见 [验证记录](MCHOSE_K99_V3_VALIDATION.md)。
