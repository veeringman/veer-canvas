# 🧠 SentientOS — The AI-Native Operating System

**SentientOS** is a post-mobile era OS where intelligent agents are first-class citizens.

## Modules
- aish/: Shell interface
- runtime/: Agent execution logic
- memory/: Context persistence
- docs/: Architecture, roadmap, and design notes

## 🖥 Shell: AISH

**AISH** (AI Shell) is a native CLI/UX interface for controlling agents, context, and system behavior.

### 🔧 Sample Commands
```bash
# Spawn a new agent with a goal
> aish> spawn nova "monitor system logs for anomalies"

# View all running agents
> aish> list

# Write a memory log to an agent
> aish> write nova "Found suspicious pattern in /var/log"

# Read the last memory entries
> aish> mem nova

# Terminate an agent
> aish> kill nova
```

### 🧩 Architecture Overview
SentientOS is built with a modular, AI-native architecture:

- **AISH**: The intelligent shell interface for user-agent interaction.
- **Agent Runtime**: Executes and manages autonomous agents.
- **Syscall Interface**: Provides direct kernel access for agent actions.
- **Kernel Services**:
  - **Agent Manager**: Manages lifecycle and sandboxing of agents.
  - **Memory Engine**: Stores AI memory and context vectors.
  - **Governance**: Enforces permissions, policy, and coordination.
  - **Scheduling & I/O**: Traditional device and task management.

![SentientOS Architecture](./docs/sentientos_architecture.png)

---

Built for the future of intelligent, agentic, context-aware computing.

