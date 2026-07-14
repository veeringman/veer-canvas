# 🔍 lanpeek

**lanpeek** is a fast, real-time LAN scanner built in Rust. It discovers devices on your local network using parallel raw ICMP pings, resolves MAC addresses via ARP, and retrieves hostnames via reverse DNS and mDNS. All results are displayed live in a terminal UI.

---

## ✨ Features

- ⚡ Ultra-fast parallel ICMP scanning (no external `ping` binary)
- 📡 Automatically detects local subnet and interface
- 🧩 MAC address resolution using ARP cache
- 📛 Hostname resolution via reverse DNS and `.local` (mDNS)
- 🖥️ Live terminal UI with real-time updates using `ratatui`
- 🦀 Pure Rust, cross-platform (Linux and macOS)

---

## 📦 Installation

### 1. Clone and build

```bash
git clone https://github.com/veeringman/lanpeek.git
cd lanpeek
cargo build --release
```

### 2. Grant permissions for raw ICMP sockets

ICMP sockets require elevated privileges:

**Option 1 – Run with `sudo`:**

```bash
sudo ./target/release/lanpeek
```

**Option 2 – Set capability on the binary (Linux only):**

```bash
sudo setcap cap_net_raw=eip target/release/lanpeek
./target/release/lanpeek
```

---

## 🖼️ Example Output

```text
IP Address       MAC Address           Hostname
--------------   -------------------   ----------------------
192.168.999.1     1a:2b:3c:4d:5e:6f     router.local
192.168.999.5     -                     esp32-plug.local
192.168.999.12    aa:bb:cc:dd:ee:ff     hp-printer.local
```

---

## 🧰 Built With

- [tokio](https://crates.io/crates/tokio) – async runtime
- [ping](https://crates.io/crates/ping) – raw socket ICMP pings
- [dns-lookup](https://crates.io/crates/dns-lookup) – reverse DNS resolution
- [ratatui](https://crates.io/crates/ratatui) – terminal UI rendering
- [crossterm](https://crates.io/crates/crossterm) – terminal event/input support

---

## 🛣️ Roadmap

- ✅ Initial Scaffold
- [ ] Export results to CSV / JSON
- [ ] Display vendor info from MAC addresses (OUI lookup)
- [ ] Search, filter, and sort in the TUI
- [ ] Web UI and WASM support
- [ ] Windows support via `WinPcap` / `nping`

---

## 🎯 Goals

- Replace tools like `arp-scan` or `fing` with a native Rust alternative
- Provide a blazing-fast and pretty TUI for LAN visibility
- Stay dependency-light, secure, and open-source

---

## 📄 License

MIT License  
© 2025 [Veer Man]

---

> Built with 🦀 Rust. Inspired by `nmap`, `arp-scan`, and `fing`, but designed for modern TUI-first LAN visibility.
