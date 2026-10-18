# Klyqa Local

Home Assistant custom integration for **Klyqa / QConnex lights** (bulbs, strips and
merch devices such as the MontanaBlack *GET ON MY LVL* LED shield), controlled **locally**
over the Klyqa QCX protocol.

The official [Klyqa integration](https://github.com/klyqa/home-assistant-integration)
is no longer maintained, no longer works on current Home Assistant releases and
ignores products whose ID does not contain `.lighting`
(e.g. `@qcx.montana.black.ledshield.rgb`). This integration is a small, dependency-free
reimplementation.

## Features

- On / off, brightness, RGB colour
- 23 effects (the Klyqa app scenes, white-only scenes removed)
- Local polling every 30 s – no cloud needed after setup
- Config flow: log in **once** with your Klyqa account to read the device list and the
  per-device AES key. **The password is not stored**, only the device ID and its key.

## Installation

### HACS (custom repository)
1. HACS → ⋮ → *Custom repositories* → add `https://github.com/ChrisThomas78/klyqa_local`, type *Integration*
2. Install **Klyqa Local**, restart Home Assistant

### Manual
Copy `custom_components/klyqa_local` into your `config/custom_components/` folder and restart.

## Setup

*Settings → Devices & services → Add integration → Klyqa Local*

1. Enter your Klyqa e-mail and password
2. Pick the device; optionally enter its IP address (faster discovery – give the device a
   fixed DHCP lease)

## Requirements / network

Home Assistant must be in the same layer-2 network as the lights and must be able to bind
**UDP 2222** and **TCP 3333**: the integration broadcasts `QCX-SYN` on UDP 2222 and the
device connects back to TCP 3333 on the Home Assistant host.

If you reset or re-pair a device in the Klyqa app it gets a new key – remove the entry and
add it again.

## How it works

1. `QCX-SYN` broadcast (and unicast if an IP is configured) to UDP 2222
2. The device opens a TCP connection to port 3333 and sends its identity (plain JSON)
3. Both sides exchange 8-byte IVs; communication continues with AES-128-CBC
   (key from the Klyqa cloud, IV = own IV + peer IV), JSON padded with spaces
4. Messages: `{"type":"request"}` (status), `{"type":"request","status":"on"}`,
   `{"type":"request","color":{"red":..,"green":..,"blue":..}}`,
   `{"type":"request","brightness":{"percentage":..}}`,
   effects via `{"type":"routine","action":"put"|"start",...}`

## Credits

Protocol details and the effect definitions are taken from
[klyqa-ctl](https://github.com/klyqa/klyqa-ctl) (MIT License, Copyright (c) 2022 Klyqa).

Not affiliated with Klyqa / QConnex.
