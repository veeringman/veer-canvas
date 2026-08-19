# RK3588-SBC

Open hardware single-board computer based on Rockchip **RK3588**.

| Spec | Target |
|------|--------|
| SoC | RK3588 (4× Cortex-A76 + 4× Cortex-A55, Mali-G610 MP4, 6 TOPS NPU) |
| Memory | 8 GB LPDDR4X-4266 (4× 16-bit devices) |
| Storage | 64 GB eMMC 5.1 + M.2 2280 NVMe (PCIe 3.0 ×4) |
| Display | HDMI 2.1 (8K30 / 4K120) + MIPI DSI |
| Camera | 2× MIPI CSI |
| USB | 1× USB 3.1 Type-C (DP Alt Mode optional), 2× USB 3.0 Type-A, 2× USB 2.0 |
| Network | 1× Gigabit Ethernet (RTL8211F) |
| Wireless | Optional M.2 E-key Wi-Fi 6 / BT module |
| GPIO | 40-pin Raspberry Pi–compatible header |
| Power | USB-C PD 12 V / DC barrel 12 V |
| Board size | 100 × 72 mm (≈ 4-layer carrier + 8-layer core routing density) |
| PCB | 8-layer impedance-controlled, ENIG |

## Project layout

```
docs/           Architecture, power tree, stackup, BOM, layout rules
hardware/kicad/ KiCad schematics, PCB, libraries, fab outputs
mechanical/     Enclosure / heatsink STEP + drawings
firmware/       U-Boot / kernel notes, device-tree stubs
scripts/        BOM export, DRC helpers
```

## Design approach

1. **Follow Rockchip reference templates** for RK3588 + LPDDR4X + RK806 (NDA package required).
2. Keep SoC, DRAM, and PMIC in a tight core cluster; copy Rockchip DDR placement relative positions.
3. Route high-speed interfaces with controlled impedance and length matching before low-speed GPIO.
4. Use an 8-layer stackup (TOP–GND–SIG–PWR–GND–SIG–GND–BOT) unless HDI is required for fan-out.

## Prerequisites

- Rockchip RK3588 hardware design package (schematic templates, PCB guidelines whitepaper, DDR SI files) under NDA
- KiCad 8+ (or Altium if preferred)
- PDN / SI tools for DDR4266 and PCIe / HDMI validation (optional but recommended)

## Status

See [docs/architecture/OVERVIEW.md](docs/architecture/OVERVIEW.md) and the build checklist in [docs/pcb/LAYOUT_RULES.md](docs/pcb/LAYOUT_RULES.md).

## License

Hardware design files: CERN-OHL-S v2 (or as noted per file). Software notes: MIT.
