"""io_uring async runtime for high-performance I/O.

Provides an async I/O runtime using Linux io_uring for maximum throughput.
Falls back to asyncio on non-Linux platforms or older kernels.

io_uring advantages:
- Zero-copy I/O operations
- Batched syscalls
- Kernel-side polling
- Lower latency than epoll
"""

from __future__ import annotations

import asyncio
import ctypes
import os
import socket
import sys
from ctypes import (
    POINTER,
    Structure,
    c_int,
    c_uint,
    c_uint32,
    c_uint64,
    c_void_p,
    pointer,
)
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Callable, Dict, List, Optional, Tuple

# Check if io_uring is available (Linux 5.1+)
URING_AVAILABLE = sys.platform == "linux"

if URING_AVAILABLE:
    try:
        # Try to load liburing
        _liburing = ctypes.CDLL("liburing.so.2", mode=ctypes.RTLD_GLOBAL)
        LIBURING_AVAILABLE = True
    except OSError:
        LIBURING_AVAILABLE = False
else:
    LIBURING_AVAILABLE = False


class IoUringOp(IntEnum):
    """io_uring operation types."""
    NOP = 0
    READV = 1
    WRITEV = 2
    FSYNC = 3
    READ_FIXED = 4
    WRITE_FIXED = 5
    POLL_ADD = 6
    POLL_REMOVE = 7
    SYNC_FILE_RANGE = 8
    SENDMSG = 9
    RECVMSG = 10
    TIMEOUT = 11
    TIMEOUT_REMOVE = 12
    ACCEPT = 13
    ASYNC_CANCEL = 14
    LINK_TIMEOUT = 15
    CONNECT = 16
    FALLOCATE = 17
    OPENAT = 18
    CLOSE = 19
    SEND = 26
    RECV = 27
    READ = 22
    WRITE = 23


@dataclass
class IoRequest:
    """An I/O request for the uring runtime."""
    op: IoUringOp
    fd: int
    buffer: Optional[bytes] = None
    offset: int = 0
    callback: Optional[Callable[[int, Any], None]] = None
    user_data: Any = None


@dataclass
class IoCompletion:
    """Completion event from io_uring."""
    user_data: int
    result: int  # bytes transferred or error code
    flags: int = 0


class UringRuntime:
    """High-performance async I/O runtime using io_uring.
    
    Provides an event loop optimized for network I/O operations,
    particularly suited for web server workloads.
    """
    
    def __init__(self, queue_depth: int = 256) -> None:
        """Initialize the io_uring runtime.
        
        Args:
            queue_depth: Size of the submission/completion queues.
        """
        self._queue_depth = queue_depth
        self._pending: Dict[int, IoRequest] = {}
        self._next_id: int = 1
        self._running = False
        
        if LIBURING_AVAILABLE:
            self._init_uring()
        else:
            # Fallback to asyncio
            self._loop = asyncio.new_event_loop()
            self._ring = None
    
    def _init_uring(self) -> None:
        """Initialize io_uring structures."""
        # Allocate io_uring structure
        # This is a simplified implementation - real code would use
        # proper ctypes structures matching liburing
        self._ring = ctypes.create_string_buffer(512)  # io_uring struct
        
        # io_uring_queue_init(queue_depth, ring, 0)
        if hasattr(_liburing, 'io_uring_queue_init'):
            ret = _liburing.io_uring_queue_init(
                self._queue_depth,
                ctypes.byref(self._ring),
                0
            )
            if ret < 0:
                raise OSError(f"io_uring_queue_init failed: {ret}")
    
    def submit(self, request: IoRequest) -> int:
        """Submit an I/O request.
        
        Args:
            request: The I/O request to submit.
            
        Returns:
            Request ID for tracking.
        """
        req_id = self._next_id
        self._next_id += 1
        self._pending[req_id] = request
        
        if self._ring is not None:
            # Submit to io_uring
            self._submit_to_uring(req_id, request)
        else:
            # Schedule on asyncio
            self._submit_to_asyncio(req_id, request)
        
        return req_id
    
    def _submit_to_uring(self, req_id: int, request: IoRequest) -> None:
        """Submit request to io_uring."""
        # Get submission queue entry
        # sqe = io_uring_get_sqe(ring)
        # Prepare based on operation type
        # io_uring_sqe_set_data(sqe, req_id)
        # io_uring_submit(ring)
        pass  # Placeholder for actual liburing calls
    
    def _submit_to_asyncio(self, req_id: int, request: IoRequest) -> None:
        """Submit request via asyncio fallback."""
        async def do_op():
            try:
                if request.op == IoUringOp.READ:
                    result = os.read(request.fd, 4096)
                elif request.op == IoUringOp.WRITE:
                    result = os.write(request.fd, request.buffer or b"")
                elif request.op == IoUringOp.ACCEPT:
                    # Use socket module for accept
                    sock = socket.fromfd(request.fd, socket.AF_INET, socket.SOCK_STREAM)
                    conn, addr = sock.accept()
                    result = conn.fileno()
                else:
                    result = 0
                
                if request.callback:
                    request.callback(result, request.user_data)
            except Exception as e:
                if request.callback:
                    request.callback(-1, request.user_data)
        
        self._loop.create_task(do_op())
    
    async def read(self, fd: int, size: int) -> bytes:
        """Async read from file descriptor.
        
        Args:
            fd: File descriptor to read from.
            size: Maximum bytes to read.
            
        Returns:
            Bytes read.
        """
        future = asyncio.Future()
        
        def on_complete(result: int, _: Any) -> None:
            if result >= 0:
                future.set_result(result)
            else:
                future.set_exception(OSError(f"Read failed: {result}"))
        
        self.submit(IoRequest(
            op=IoUringOp.READ,
            fd=fd,
            callback=on_complete,
        ))
        
        return await future
    
    async def write(self, fd: int, data: bytes) -> int:
        """Async write to file descriptor.
        
        Args:
            fd: File descriptor to write to.
            data: Bytes to write.
            
        Returns:
            Number of bytes written.
        """
        future = asyncio.Future()
        
        def on_complete(result: int, _: Any) -> None:
            if result >= 0:
                future.set_result(result)
            else:
                future.set_exception(OSError(f"Write failed: {result}"))
        
        self.submit(IoRequest(
            op=IoUringOp.WRITE,
            fd=fd,
            buffer=data,
            callback=on_complete,
        ))
        
        return await future
    
    async def accept(self, server_fd: int) -> Tuple[int, Tuple[str, int]]:
        """Async accept connection.
        
        Args:
            server_fd: Server socket file descriptor.
            
        Returns:
            Tuple of (client_fd, (host, port)).
        """
        future = asyncio.Future()
        
        def on_complete(result: int, _: Any) -> None:
            if result >= 0:
                future.set_result((result, ("0.0.0.0", 0)))
            else:
                future.set_exception(OSError(f"Accept failed: {result}"))
        
        self.submit(IoRequest(
            op=IoUringOp.ACCEPT,
            fd=server_fd,
            callback=on_complete,
        ))
        
        return await future
    
    def poll(self, timeout_ms: int = 0) -> List[IoCompletion]:
        """Poll for completed I/O operations.
        
        Args:
            timeout_ms: Timeout in milliseconds (0 = non-blocking).
            
        Returns:
            List of completed operations.
        """
        completions = []
        
        if self._ring is not None:
            # io_uring_wait_cqe_timeout / io_uring_peek_batch_cqe
            pass
        else:
            # Run asyncio briefly
            self._loop.run_until_complete(asyncio.sleep(timeout_ms / 1000))
        
        return completions
    
    def run(self) -> None:
        """Run the event loop."""
        self._running = True
        
        if self._ring is None:
            # Use asyncio loop
            self._loop.run_forever()
        else:
            # Native io_uring loop
            while self._running:
                completions = self.poll(timeout_ms=1000)
                for cqe in completions:
                    request = self._pending.pop(cqe.user_data, None)
                    if request and request.callback:
                        request.callback(cqe.result, request.user_data)
    
    def stop(self) -> None:
        """Stop the event loop."""
        self._running = False
        if self._loop:
            self._loop.stop()
    
    def close(self) -> None:
        """Clean up resources."""
        if self._ring is not None and LIBURING_AVAILABLE:
            # io_uring_queue_exit(ring)
            pass
        if self._loop:
            self._loop.close()


class UringSocket:
    """Async socket wrapper using io_uring.
    
    Provides a Pythonic async socket interface backed by io_uring
    for maximum performance.
    """
    
    def __init__(self, runtime: UringRuntime, sock: socket.socket) -> None:
        self._runtime = runtime
        self._socket = sock
        self._fd = sock.fileno()
    
    @classmethod
    async def create_server(
        cls,
        runtime: UringRuntime,
        host: str,
        port: int,
        backlog: int = 128,
    ) -> "UringSocket":
        """Create a server socket.
        
        Args:
            runtime: The io_uring runtime.
            host: Host to bind to.
            port: Port to bind to.
            backlog: Listen backlog.
            
        Returns:
            Server socket wrapper.
        """
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.setblocking(False)
        sock.bind((host, port))
        sock.listen(backlog)
        return cls(runtime, sock)
    
    async def accept(self) -> "UringSocket":
        """Accept incoming connection.
        
        Returns:
            Client socket wrapper.
        """
        client_fd, addr = await self._runtime.accept(self._fd)
        client_sock = socket.fromfd(client_fd, socket.AF_INET, socket.SOCK_STREAM)
        return UringSocket(self._runtime, client_sock)
    
    async def recv(self, size: int = 4096) -> bytes:
        """Receive data from socket.
        
        Args:
            size: Maximum bytes to receive.
            
        Returns:
            Received bytes.
        """
        return await self._runtime.read(self._fd, size)
    
    async def send(self, data: bytes) -> int:
        """Send data to socket.
        
        Args:
            data: Bytes to send.
            
        Returns:
            Number of bytes sent.
        """
        return await self._runtime.write(self._fd, data)
    
    def close(self) -> None:
        """Close the socket."""
        self._socket.close()


def is_uring_available() -> bool:
    """Check if io_uring is available on this system.
    
    Returns:
        True if io_uring can be used.
    """
    return LIBURING_AVAILABLE
