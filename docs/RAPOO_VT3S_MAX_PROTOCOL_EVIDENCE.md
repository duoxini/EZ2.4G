# Rapoo VT3S MAX A HUB WebHID protocol evidence

Checked 2026-10-22. Main bundle line/offset references below are actual line numbers and UTF-8 byte offsets (not decoded-character indices). Static-only analysis of assets downloaded from https://hub.rapoo.com/; no JS executed and no USB/HID device was enumerated or contacted.

## Files and provenance

- rapoo_assets/index-WEaXdsQS.js — official page main bundle from https://hub.rapoo.com/assets/index-WEaXdsQS.js; 638,195 bytes; SHA-256 c4131b8017b3544b198279440d3fcc0b9afe0bd084e9619c59d0b77e3c88bedf.
- rapoo_assets/enc.data — fetched from https://hub.rapoo.com/enc.data; 102,764 bytes; SHA-256 d3bf50b90c8c9ec8836d1f777f44f08696962c4f2213b05b9b30540de4c1e42c.
- rapoo_assets/enc-map.data — fetched from https://hub.rapoo.com/enc-map.data; 1,048 bytes; SHA-256 23ea27660ada4fbe15b4e7c8cd4fb1a2d388047d8a80b59e636e242bee038be3.
- enc.data and enc-map.data are OpenSSL Salted__ Base64 blobs. Main JS (line 131, UTF-8 byte offsets 449,959 and 450,065) fetches both, decrypts with key your-secret-key-here via AES.decrypt(...).toString(Utf8), then JSON.parse. Decrypted copies are retained as rapoo_assets/enc.data.json (77,051 bytes; SHA-256 634fe5a1be9f9b293784bd1c52dc1e1190ffcf979784cdeee7e60b8674f68a7c) and rapoo_assets/enc-map.data.json (755 bytes; SHA-256 af21edf2f9da5c9090ca91f51a3503c0928ef2e5c749b2aea77dc4feaa97c8a5). Decryption used Node built-in crypto and the CryptoJS/OpenSSL MD5 EVP_BytesToKey convention; no driver or JS bundle was executed.

## Confirmed device mapping

- Main JS line 46, UTF-8 byte offset 204,784: ln=65280 (usage page 0xFF00), rh=14 (0x0E), nh=2 (0x02), and j0=9390 (VID 0x24AE).
- Main JS line 131, UTF-8 byte offset 450,228: filters are constructed with vendorId j0, product ID, and usagePage ln; extUsagePages are included where present. Device support check accepts collections with usage page 0xFF00 and usage 14 or 2.
- Decrypted enc.data.json, key 17953 decimal (PID 0x4621): name VT3S MAX, type 1 (mouse), protocol 1 (VT_nrf54L parser), featureReportId 8.
- Decrypted enc-map.data.json, key 5153 decimal (PID 0x1421) maps to 17953 (PID 0x4621), so receiver alias resolves to the VT3S MAX product record. Main JS line 93, UTF-8 byte offset 315,821 uses alias map Je to select the canonical product record and marks the connection as a wireless receiver.

## Battery report parsing

- Main JS line 93, UTF-8 byte offset 310,539: class xc initializes for parser type VT_nrf54L and parses its input-report DataView using getUint8 offsets.
- Main JS line 93, UTF-8 byte offset 311,260: initParser listens for input report ID 7. For non-ESM models (VT3S MAX is not named ESM), it calls parserInputReport(n.data) and emits the battery event.
- Parser payload offsets: byte 6 is status (0 invalid, 1 valid, 2 charging; other values invalid); byte 7 is the raw battery value (the parser does not scale or validate it). Byte 11 is also read for config, so parser payload must be at least 12 bytes. These are zero-based offsets in the DataView supplied to the parser. This parser shows no checksum check.
- This is a passive input-report path; the battery parser does not issue a battery query. get_battery_level:[170] occurs in the VT_nrf54L command table at line 93, UTF-8 byte offset 302,105, but static search found no call site for it. Do not infer a request frame or response from that unused command-table entry.
- Generic executeSendCMD at line 93, UTF-8 byte offset 316,345 sends a command on report ID 6 (or productInfo.reportId if set), then reads feature report ID 8 (or product metadata featureReportId) with retry/timeout handling. This is a separate generic command path and is not evidenced as used by battery parsing.

## Implementation conclusion and limits

The official WebHID driver evidence is sufficient to identify VT3S MAX (VID 0x24AE, PID 0x4621; wireless receiver alias PID 0x1421) and implement a strictly passive input-report battery decoder for report ID 7, usage page 0xFF00, usages 0x0E/0x02, payload offset 7 with status at offset 6, minimum 12-byte payload. The JSON metadata also lists feature report ID 8, but that is not a battery request. There is no evidence here for an active battery query, checksum, battery response framing, or live device interoperability; those remain unverified. The common product records omit reportId, so report 7 is established by the VT parser listener, while outgoing command report 6 is established by generic command code.
