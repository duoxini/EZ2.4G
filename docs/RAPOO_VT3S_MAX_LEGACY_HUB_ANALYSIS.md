# Rapoo legacy HUB (hub1.rapoo.cn) static protocol findings

Scope: downloaded official static assets only; no JavaScript was executed and no HID device was opened or queried. Main asset `rapoo_legacy_assets/index-DZpVMHJH.js` is 638,705 bytes, SHA-256 `b6730399b09197345b022366aa0dcb12b3e937c2378db28db38659e199fb0dc7`. Coordinates below are source line and UTF-8 byte offsets in that file. The bundle has line breaks; these are not character offsets.

## Official identity and report parser

- The main bundle sets the Rapoo vendor ID to decimal 9390 (`0x24AE`) at line 46, byte 205,070. Decrypted official `enc.data` maps PID decimal 17953 (`0x4621`) to `VT3S MAX`, type 1, protocol 1 (`VT_nrf54L`), feature report ID 8; the alias map maps PID decimal 5153 (`0x1421`) to 17953. The raw data hashes are `enc.data` SHA-256 `d1295ca6660ba281452b1fc9eae2900846fc7b9fef8b01e09ff4a5804c5ec7bd` and `enc-map.data` SHA-256 `f595710eb481a582c99b42331fd84839ee13dfb825925b555257b39e20b4720b`; decoded JSON hashes are `enc.data.json` SHA-256 `abf9f8fdd6cd36104d5f33125c253fe6a6b72ea3967a533d9f84603df1290005` and `enc-map.data.json` SHA-256 `6a1a565a603fc600336da6d88766d9f6c69f926da259958d94259c2faa3cf642`. Decoded JSON was produced locally from the published encrypted assets using the key embedded in the bundle; no code from the bundle was run.
- The VT_nrf54L parser registers input report ID 7 at line 96, byte 311,754. Its report data starts at WebHID `event.data` byte 0 (report ID is separate): status is byte 6 (`0` invalid, `1` valid, `2` charging), raw battery is byte 7; report fields continue through byte 11. It emits this battery/status object on the battery event. The parser code begins at line 96, byte 310,471 and report listener dispatch at byte 311,754.
- `fh.open` subscribes to `inputreport` events and routes by `event.reportId` to the registered listener; it does not send a request. This wrapper is at line 96, byte 300,933. The app's store listens to the battery event and updates the device battery state (home component chunk `index-B8GsKaMW.js`, byte 43,250). The user reports that both the legacy HUB and the application now display 54% after passive listening. This is a successful user-observed result for the passive implementation, but the screenshot does not provide raw report bytes and is not a parser fixture. It also does not support attributing battery delivery to the initialization firmware query.

## Initialization and battery request status

- Startup decrypts `/enc.data` and `/enc-map.data`, then calls `a0().initDevices()`, `deviceConnectListener()`, and `deviceDisconnectListener()` (line 134, byte 450,477). In `a0` store, `initDevices` runs `E(device)` on supported devices; `E` calls the imported `getFirmwareVerison(device, 0)` and treats success as device initialization. The call is at line 96, byte 363,388; `getFirmwareVerison` is at line 96, byte 357,517.
- For VT3S MAX protocol 1, `getFirmwareVerison(device, 0)` uses `CMD.get_firmware` = `0xA3`, with argument byte `00`. `executeSendCMD` at line 96, byte 316,772 uses output report ID 6 by default, prepends `FF` for wired USB (so payload `FF A3 00`) or `A5` for the wireless receiver (payload `A5 A3 00`), then reads `featureReportId` 8. The `getFirmwareVerison` ACK check requires response byte 0 to equal `01`; it reads firmware version from response bytes 1 and 2. This is a firmware check; it does not decode battery.
- The VT_nrf54L command table contains `get_battery_level:[170]` (`0xAA`) at line 96, byte 302,615. A full static search of downloaded JS assets found this as the only `get_battery_level` occurrence: no call site, no active `0xAA` frame, and no battery-specific feature-report decoder. Feature report 8 is consumed by the generic command path as an ACK/command response; the firmware caller reads version bytes 1 and 2. The bundle contains no evidence that this report provides the displayed battery value.
- The parser is event-driven on report 7. Searches of all downloaded JS chunks found no interval or timer that sends a battery command. The only nearby periodic HID code is a 1-second receiver-to-child pairing/device-identification check in the VT_nrf54L_Base parser, not the VT3S MAX battery path. Thus the available old HUB evidence is consistent with passive battery reports, as in `hub.rapoo.com`'s newer bundle; it does not prove that `A3` triggers report 7.

## Implementation boundary

The legacy and current HUB evidence both support passive listening for input report 7 as the battery path; the reported matching 54% display is consistent with the passive implementation succeeding. The `A3` firmware check is a separate app initialization step, and available source and screenshot evidence do not show it causing the battery report. WebHID command semantics for wired connection are output report ID 6 and payload `FF A3 00`; for the wireless receiver, report ID 6 and payload `A5 A3 00`. Feature report ID 8 is checked for ACK byte 0 = 1, with version bytes 1 and 2. This must remain separate from battery parsing. The bundle does not disclose native Windows HID descriptor report lengths or explicit output-report padding length. A native implementation should obtain those lengths from the selected collection's HID descriptor/caps rather than infer or hard-code them from the WebHID payload. The available source supports report ID 7 and a 12-byte WebHID payload minimum; it does not establish whether the native input buffer needs any additional bytes beyond the report-ID framing required by Windows.


## Source excerpts for review

From `index-DZpVMHJH.js`, line 96, UTF-8 byte 310,471, VT_nrf54L input parser:

```js
y=r.getUint8(6),f=(B=>{switch(B){case 0:return Z3.invalid;case 1:return Z3.valid;case 2:return Z3.charging;default:return Z3.invalid}})(y),_={battery:r.getUint8(7),status:f}
```

From the same file, line 96, byte 311,754, input subscription (ellipsis marks omitted surrounding code):

```js
initParser(r){r.setInputReportListener(7,n=>{try{let a; ... we.emit(Ce.battery,o(a.battery))
```

From the same file, line 96, byte 316,772, generic command transport (ellipsis marks omitted branches):

```js
let a=[255];this.connectType===Y3.WirelessReceiver&&(a=[165],...);let o=[...a,...r,...n];...let s=6;...await this.send(s,i)...const p=this.productInfo.featureReportId,g=await this.getFeatureReport(p)
```

The `get_battery_level:[170]` table entry occurs at line 96, byte 302,615; static search of downloaded JS assets found no second occurrence.
