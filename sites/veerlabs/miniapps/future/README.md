# Future Library

The **Future Library** is a lightweight C implementation of asynchronous programming with support for:

- Promise/Future-like behavior
- Multiple callbacks
- Thread-safe operations
- Flexibility to integrate into real-world applications

This library is designed to simplify asynchronous programming in C by encapsulating thread management, callback execution, and result synchronization.

---

## Features

- **Thread Safety**: Built-in synchronization for concurrent access.
- **Multiple Callbacks**: Register multiple callbacks to be executed on future resolution.
- **Flexible Design**: Supports chaining asynchronous operations.
- **Easy to Use**: Simple API for developers.

---

## Getting Started

### **Prerequisites**

- GCC or any compatible C compiler
- POSIX threads library (`pthread`)

### **Building the Library**

1. Clone the repository:

   ```bash
   git clone https://github.com/veeringman/future.git
   cd future
   ```

2. Build the library and example program:

   ```bash
   make
   ```

3. Run the example program:

   ```bash
   make run
   ```

---

## Usage

### **Including the Library**

Include the header file in your C program:

```c
#include "future.h"
```

### **Example Program**

Below is a basic example of using the Future Library:

```c
#include "future.h"
#include <stdio.h>
#include <unistd.h>

void example_callback(void* result, void* context) {
    printf("Callback executed: %s\n", (char*)result);
}

int main() {
    Future* future = future_create();

    // Simulate an async operation
    sleep(1);
    future_resolve(future, "Hello, Future!");

    future_then(future, example_callback, NULL);

    char* result = (char*)future_wait(future);
    printf("Main result: %s\n", result);

    future_destroy(future);
    return 0;
}
```

Compile and run the program:

```bash
gcc -o example example.c -I./src -L./build -lfuture -lpthread
./example
```

---

## API Documentation

### `Future* future_create()`
- **Description**: Creates a new `Future`.
- **Returns**: Pointer to the created `Future`.

### `void future_resolve(Future* future, void* result)`
- **Description**: Resolves the `Future` with a result.

### `void future_reject(Future* future, void* error)`
- **Description**: Rejects the `Future` with an error.

### `void future_then(Future* future, FutureCallback callback, void* context)`
- **Description**: Attaches a callback to be executed when the `Future` is resolved or rejected.

### `void* future_wait(Future* future)`
- **Description**: Blocks until the `Future` is resolved or rejected.
- **Returns**: The result or error of the `Future`.

### `void future_destroy(Future* future)`
- **Description**: Frees the `Future` and associated resources.

---

## Contributing

Contributions are welcome! Feel free to open issues or submit pull requests.

1. Fork the repository
2. Create a feature branch
3. Commit your changes
4. Open a pull request

---

## License

This project is licensed under the MIT License. See the `LICENSE` file for details.

---

## Author

Created by **Veeringman**.
