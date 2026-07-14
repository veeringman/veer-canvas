# Green Thread Example in C

This repository contains a **minimal** user-space "green thread" (coroutine) implementation in C, supporting both **x86-64** and **ARM64 (AArch64)** architectures. It demonstrates how to:

1. **Create** and **initialize** green threads with their own stacks.
2. **Manually switch** between green threads (cooperative multitasking).
3. Provide a simple `yield()` mechanism for concurrency.

> **Disclaimer**: This example is strictly educational. It **does not** handle advanced features like stack growth, signal handling, or true preemption.

## Features

- **Architecture Support**: Compatible with both **x86-64** and **ARM64 (AArch64)** architectures, including macOS on Apple Silicon (M1, M2, M3) and Linux.
- **Minimal Context Switching**: Implements low-level context switching logic in assembly for each supported architecture, saving and restoring callee-saved registers, stack pointers (`rsp`/`sp`), and instruction/program counters.
- **Cooperative Multitasking**: Green threads voluntarily yield control, allowing for lightweight concurrency without the overhead of kernel threads.
- **Extensible Design**: Easily extendable to support more architectures, add more threads, or implement advanced scheduling and synchronization mechanisms.

## Table of Contents

- [Prerequisites](#prerequisites)
- [Project Structure](#project-structure)
- [Building the Project](#building-the-project)
- [Running the Example](#running-the-example)
- [File Overview](#file-overview)
- [Customization](#customization)
- [Caveats](#caveats)
- [License](#license)
- [Contributing](#contributing)

## Prerequisites

- **C Compiler**: `clang` (default on macOS) or `gcc`.
- **Make**: For building the project.
- **Supported Architectures**:
  - **x86-64**: Linux, macOS (Intel-based).
  - **ARM64 (AArch64)**: macOS (Apple Silicon: M1, M2, M3), Linux on ARM64.
- **Operating System**: Unix-like systems (Linux, macOS).

## Project Structure


- **`green_thread.h`**: Unified header defining the `green_ctx` structure and function prototypes with conditional compilation based on architecture.
- **`green_thread.c`**: Common C implementation for initializing green threads.
- **`green_switch_x86_64.S`**: Assembly implementation of `green_switch` for **x86-64**.
- **`green_switch_arm64.S`**: Assembly implementation of `green_switch` for **ARM64 (AArch64)**.
- **`main.c`**: Example usage demonstrating two green threads yielding control to each other.
- **`Makefile`**: Build script handling compilation for both architectures.
- **`README.md`**: Project documentation.
- **`.gitignore`**: Specifies files and directories to ignore in Git.

## Building the Project

1. **Clone the Repository**:

   ```bash
   git clone https://github.com/your-username/green_thread_example.git
   cd green_thread_example

2. **Build the Example**:
    Simply run:
    ```bash
    make

On x86-64 systems, this will produce an executable named example_x86_64.
On ARM64 systems, this will produce an executable named example_arm64.
Note: The Makefile automatically detects your system's architecture and compiles the appropriate assembly files.
Verify the Executable:
After building, you should see the executable corresponding to your architecture:

ls -l example_*
Running the Example

Execute the compiled binary based on your architecture:

./example_x86_64   # On x86-64 systems
./example_arm64    # On ARM64 systems
Expected Output:

Hello from green thread 1!
Hello from green thread 2!
Hello from green thread 1!
Hello from green thread 2!
...
This output demonstrates two green threads alternately printing messages by yielding control to each other indefinitely.

File Overview

green_thread.h
Defines the green_ctx structure, which stores the necessary registers, stack pointers, and program counters for context switching. Uses conditional compilation to differentiate between x86-64 and ARM64 architectures.
green_thread.c
Implements the green_init function to initialize green thread contexts. Handles setting up the stack pointers and program/instruction counters based on the architecture.
green_switch_x86_64.S
Assembly implementation of the green_switch function for x86-64. Handles saving and restoring callee-saved registers, stack pointers, and jumping to the new context's instruction pointer.
green_switch_arm64.S
Assembly implementation of the green_switch function for ARM64 (AArch64). Similar to the x86-64 version but adapted to ARM64's calling conventions and register usage.
main.c
Demonstrates the creation and usage of two green threads. Each thread prints a message and yields control to the other thread in an infinite loop.
Makefile
Automates the build process. Detects the system's architecture, compiles the appropriate assembly files along with C source files, and links them into an executable specific to the architecture.
.gitignore
Specifies patterns for files and directories that Git should ignore, such as build artifacts and system-specific files.
Customization

Stack Size:
The example uses a fixed stack size of 64 KB for each green thread. You can adjust this size in main.c:

const size_t STACK_SIZE = 64 * 1024; // 64 KB
Number of Threads:
Currently, the example demonstrates two green threads. To add more threads:

Define additional green_ctx structures.
Initialize them using green_init.
Modify the yield() function or implement a scheduler to manage multiple contexts.
Scheduler Implementation:
Replace the simple two-thread toggle mechanism with a more sophisticated scheduler (e.g., round-robin, priority-based) to manage multiple green threads efficiently.
Caveats

Not Preemptive:
Green threads rely on cooperative multitasking. Each green thread must explicitly call yield() to transfer control. If a thread doesn't yield, it can block the entire program.
Fixed Stack:
Each green thread has a single, statically allocated stack with a fixed size. There are no guard pages or mechanisms to handle stack growth, which can lead to stack overflows if not managed carefully.
Architecture-Specific Assembly:
The assembly code is written specifically for x86-64 and ARM64 (AArch64) architectures. It will not work on other architectures without significant modifications.
Minimal Error Handling:
The example includes basic error handling (e.g., checking malloc results) but lacks comprehensive safeguards against invalid context switches, stack overflows, or other potential issues.
Portability:
While the project supports both x86-64 and ARM64 on Unix-like systems (Linux and macOS), it does not support Windows or other operating systems without further modifications.
License

MIT License

(Replace with your preferred license)

Contributing

Contributions are welcome! If you find a bug, have an idea for an improvement, or want to extend support to more architectures or features, feel free to open an issue or submit a pull request.

Fork the Repository:
Click the Fork button at the top-right corner of the repository page.
Clone Your Fork:
git clone https://github.com/your-username/green_thread_example.git
cd green_thread_example
Create a Feature Branch:
git checkout -b feature/your-feature-name
Make Your Changes:
Implement your feature or fix in the appropriate files.
Commit Your Changes:
git add .
git commit -m "Description of your changes"
Push to Your Fork:
git push origin feature/your-feature-name
Create a Pull Request:
Navigate to your fork on GitHub and click the Compare & pull request button. Provide a clear description of your changes and submit the pull request.


