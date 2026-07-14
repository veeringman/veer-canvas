# 🛠️ Tools

A lightweight collection of utility tools for Raspberry Pi and Linux systems. This repository currently contains a single tool:

---

## 🔍 Vitals
A terminal-based TUI system monitoring utility for Linux based systems. Designed for real-time vitals monitoring with a clean, colorized dashboard view.

### ✨ Features
- CPU, Memory, Disk, Network, Load, Uptime
- Top 5 processes by CPU and Memory
- Flicker-free terminal refresh
- ASCII/Emoji icon view (configurable)

### 🔧 Prerequisites
Vitals is a pure Bash script but relies on a few common utilities available on most Linux systems. To ensure full functionality, make sure these are installed:

```bash
sudo apt update
sudo apt install -y procps coreutils bc lsb-release util-linux
```

Optional (for IO monitoring):
```bash
sudo apt install -y iotop
```

### 🚀 Run
```bash
chmod +x vitals
./vitals
```

### 📂 Folder Structure
```
/tools
└── vitals
└── README.md
```

### 📝 Usage
Clone the repo and run the vitals tool directly:
```bash
git clone https://github.com/veeringman/tools.git
cd tools
./vitals.sh
```

---

## 🤝 Contributing
Pull requests are welcome! If you have improvements to the Vitals utility or ideas for future tools, feel free to contribute.

---

## 📜 License
MIT License © [Your Name or Handle]
