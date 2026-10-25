# K99 V3 GLW battery query: official static evidence

Date: 2026-10-22. Static-source analysis only. No JavaScript was executed and no HID/USB operation was performed. The captured screenshot showing 100% is contextual only; it is not used as a protocol fixture.

## Source and coordinate convention

Primary source: official MCHOSE Web HUB assets loaded from `https://www.mchose.com.cn/` via `/cizhou/CZ_SHARED_DATA/loader.js?v=3` and its asset manifest. The bundle was saved as `mchose_assets\main.504a955bfd84363d1e76.js`.

| Source | Size | SHA-256 |
|---|---:|---|
| [Official Web HUB](https://www.mchose.com.cn/) | HTML 6,996 bytes | `97081f481437a19b25870f06cb00d16620fcbe14eaf99290d309f13c123c68f0` |
| [CZ loader](https://www.mchose.com.cn/cizhou/CZ_SHARED_DATA/loader.js?v=3) | 27,910 bytes | `3cd59ccfc8555d612e3bb37aa3a04b9aaca6ba90a37c8bcde6e5255be2be51cf` |
| [CZ manifest](https://www.mchose.com.cn/cizhou/CZ_SHARED_DATA/asset-manifest.json?v=1) | 5,558 bytes | `3e5c93c8238efe95042d2041e881ad315859eb726bd36f4895ae157c50cb6d18` |
| [CZ main bundle](https://www.mchose.com.cn/cizhou/CZ_SHARED_DATA/main.504a955bfd84363d1e76.js) | 670,427 bytes | `c16055520ed1c43483a5357f74e265e3a356b0f7d2a4298a3d90ad6cf0a127ff` |

All offsets below are **zero-based UTF-8 byte offsets** in the exact main bundle above, not character positions. The bundle is minified onto one line. The stable function/key names and short source excerpts are included so offsets can be checked against the file.

## Model and GLW selection

The model record begins at byte **119,960** (module 80456): `storageKey/name/fullName: "K99 V3"`, `glbKeyboardKey: "K99V3"`, wired VID/PID `0x3837:0x2020`, and wireless child `0x3837:0x3033` with `productName: "MCHOSE K99 V3 2.4G"`. The record has no `AllowUpdateBattery` override. The manufacturer getter at byte **141,166** defaults to `"glw"` and the K99 record does not override it; the model uses the GLW path.

Runtime feature support is constructed at byte **137,509**. Relevant expression: `AllowUpdateBattery: ... X.featSupport.AllowUpdateBattery ... : "qhw"===q`. Thus an explicit model flag wins; otherwise only QHW defaults to enabled. K99 V3 resolves to GLW and leaves the property unspecified, so its static default is false. At byte **418,148**, `_proxyEvent` drops `updateBattery` when that feature is false. `changeAbility` at byte **419,286** updates ability/feature support, but the inspected code does not establish a runtime override that turns on `AllowUpdateBattery` for this K99 record.

## Official no-write battery-bearing configuration read

The GLW device class exposes `getPerformanceInfo(profile=0)` at byte **426,808**. Its body calls `this.channel.getFuncConfig(t)` and decodes the returned bytes with `xe`. `getFuncConfigStruct(profile=0)` at byte **425,573** calls the same `channel.getFuncConfig` and returns `{performanceInfo: xe(raw), lightConfig: be(raw, ...)}`. Decoder `xe` at byte **477,270** contains `rf_battery:127&e[32]` and `isCharging:e[32]>>7&1`: byte 32 of the returned 64-byte function-profile configuration carries battery in bits 0–6 and charging in bit 7. This is a configuration-read route, distinct from the `FA FB 07` notification parser.

The command implementation is explicit:

| Evidence | UTF-8 byte offset | Source behavior |
|---|---:|---|
| `_simpleGetCommand` | 273,720 | Splits reads into chunks of at most 56 bytes; each chunk constructs `CmdQueueItem` with `NORMAL_OPTIONS`, requested command, size, and offset; joins responses and clips to requested length. |
| `getFuncConfig(profile)` | 278,953 | Calls `_simpleGetCommand(5, 64*profile, 64, {priority: DELAY})`. Profile 0 is a 64-byte read at offset 0. |
| `setFuncConfig(profile, data)` | 279,358 | Separate setter calls `_simpleSendCommand(6, 64*profile, data, ...)`; it is not called by `getFuncConfig`. |
| Request packet construction | 307,439 | Builds `h=[dataLength, offsetLow, offsetHigh, 0, ...data]` (or equivalent size form); packet is `[flag, command, 0, 255 & sum(h), ...h]`. |
| `NORMAL_OPTIONS` | 309,124 | `{flag:85, expect:170, offset:0}` => request flag `0x55`, expected response flag `0xAA`. |
| Default report transport | 393,813 | Base queue item defaults to `packetLength:64`, `reportId:0`. |
| Actual `sendReport` | 396,347 | Calls `device.sendReport(this.reportId, paddedUint8Array)`. Payload is zero-filled to 64 bytes. |
| Response matcher | 308,357 | Requires response bytes 0=`expect` (`AA`), 1=`command`, response size byte 4 <= requested size byte 4, and bytes 5–6 equal requested offset low/high. It does not validate response checksum or report ID. |
| Response parsing | 395,692 | Returns `event.data.buffer` bytes from index 8 onward. |

The checksum helper in the header expression is Lodash `sumBy` over `h`, with the identity mapper (official dependency `lodash.20f32eab1d889405fdc6.js`, previously saved under `task-2/k99_assets`; SHA-256 `3fead47ee92897921b23c2c1f308261a69be8c31bd48a58fd2fc0e9e9376d128`). So byte 3 is the low 8 bits of the sum of the size/offset/reserved/data bytes, not CRC. The literal byte 2 in the outer packet is zero. The source does not name or document this byte; it is a constant/reserved position in this packet format, and no stronger semantic claim is supported.

For the official profile-0 64-byte GET, `_simpleGetCommand` creates two request reports because its chunk size is 56:

| Chunk | Data bytes requested | Offset | Header + four-byte GET descriptor | Remaining bytes |
|---|---:|---:|---|---|
| 1 | 56 (`0x38`) | 0 | `55 05 00 38 38 00 00 00` | zero padding to 64 bytes |
| 2 | 8 (`0x08`) | 56 (`0x38`) | `55 05 00 40 08 38 00 00` | zero padding to 64 bytes |

These are reconstructed from the official generic API’s size/offset/chunking and packet builder, not captured device traffic. The second checksum is `8+56=64`; first is `56`. Responses must match `AA 05` and the corresponding requested size/offset in bytes 4–6. Each response contributes bytes after index 7; the two pieces are concatenated then trimmed to 64 bytes. The battery field is in returned config byte 32. The source makes no explicit hardware side-effect guarantee; command 5 is invoked through `_simpleGetCommand` (input/read) and is separate from setting command 6. Static code therefore supports calling this a read-only configuration query at the protocol/API level, but cannot establish undocumented firmware side effects.

## Connection/init call-chain status

The supported SDK path is proven through `getPerformanceInfo -> channel.getFuncConfig -> _simpleGetCommand(5, 0, 64) -> xe(raw).rf_battery`. The model's `funcConfigStruct.read` schema at byte **196,358** delegates to `t.getFuncConfigStruct(n)`, which reaches the same GET. This proves the generic configuration-read mechanism can request and decode battery.

It does **not** prove that the K99 V3 connection/open routine automatically invokes that schema read. In the inspected static bundle, no decisive callsite from device connection/initialization to `funcConfigStruct.read`, `getFuncConfigStruct`, or `getPerformanceInfo` was established. Nor was a periodic interval or battery-specific subscription initialization found that overrides `AllowUpdateBattery`. The separate GLW notification handling at byte **272,573** recognizes `FA FB 07`, but the K99 model’s default event gate means that path is not evidence of the displayed 100% source. The screenshot is not used to fill this gap.

## Implementation implication and limits

The narrowest officially evidenced active read for this GLW model is the SDK's `getFuncConfig(profile 0)` operation: command `0x05`, offset 0, length 64, emitted as the two report-ID-0, 64-byte padded reports above; parse each `0xAA/0x05` response by matching size/offset and taking data at byte 8 onward, then decode returned byte 32 as `battery = b & 0x7f`, `charging = (b >> 7) & 1`. This is a minimum official config read, not a proposed one-byte partial read: no evidence supports changing the offset/length to 32/1. It does not use QHW `getBattery`, QHW report IDs, or legacy K99 command recipes.

This static evidence does not confirm whether the 2.4 GHz firmware accepts this command on the wireless interface, whether both reports receive responses, or whether the configuration byte is valid/current in that mode. No operation has been performed on a physical device. Any real-device query remains a separate opt-in validation step.
