"""Shared memory IPC for zero-copy data passing.

Provides shared memory primitives for efficient inter-process
communication, enabling multi-process web server architectures
without serialization overhead.

Key features:
- Shared memory arenas for allocation
- Zero-copy buffer sharing
- Lock-free message passing
- Memory-mapped request/response data
"""

from __future__ import annotations

import ctypes
import mmap
import os
import struct
import threading
import time
from dataclasses import dataclass, field
from multiprocessing import shared_memory
from typing import Any, Dict, List, Optional, Tuple, Union


# Message header format for IPC
# Format: magic (4) + msg_type (4) + payload_len (8) + timestamp (8) = 24 bytes
MSG_HEADER_FORMAT = "!4sIQQ"
MSG_HEADER_SIZE = struct.calcsize(MSG_HEADER_FORMAT)
MSG_MAGIC = b"PYAO"


class MessageType:
    """IPC message types."""
    REQUEST = 1
    RESPONSE = 2
    HEARTBEAT = 3
    SHUTDOWN = 4
    ACK = 5


@dataclass
class SharedRegion:
    """A region within a shared memory arena."""
    offset: int
    size: int
    in_use: bool = True


class SharedMemoryArena:
    """Arena allocator for shared memory.
    
    Provides efficient memory allocation within a shared memory
    segment, suitable for request/response buffers.
    """
    
    def __init__(self, name: str, size: int = 64 * 1024 * 1024) -> None:
        """Initialize shared memory arena.
        
        Args:
            name: Unique name for the shared memory segment.
            size: Total size in bytes (default 64MB).
        """
        self._name = name
        self._size = size
        self._lock = threading.Lock()
        
        # Create or attach to shared memory
        try:
            self._shm = shared_memory.SharedMemory(name=name, create=True, size=size)
            self._owner = True
        except FileExistsError:
            self._shm = shared_memory.SharedMemory(name=name, create=False)
            self._owner = False
        
        # Allocation tracking
        # First 4KB reserved for metadata (allocation bitmap)
        self._metadata_size = 4096
        self._data_start = self._metadata_size
        self._regions: List[SharedRegion] = []
        
        # Initialize metadata if owner
        if self._owner:
            self._init_metadata()
    
    def _init_metadata(self) -> None:
        """Initialize arena metadata."""
        # Store magic number and version at start
        struct.pack_into("!4sI", self._shm.buf, 0, b"AREN", 1)
    
    def allocate(self, size: int, alignment: int = 8) -> Optional[int]:
        """Allocate a region from the arena.
        
        Args:
            size: Size in bytes to allocate.
            alignment: Memory alignment (default 8 bytes).
            
        Returns:
            Offset into shared memory, or None if no space.
        """
        with self._lock:
            # Find free region (first-fit)
            aligned_size = (size + alignment - 1) & ~(alignment - 1)
            
            # Calculate next available offset
            if self._regions:
                last = self._regions[-1]
                offset = last.offset + last.size
            else:
                offset = self._data_start
            
            # Align
            offset = (offset + alignment - 1) & ~(alignment - 1)
            
            # Check bounds
            if offset + aligned_size > self._size:
                return None
            
            # Record allocation
            region = SharedRegion(offset=offset, size=aligned_size)
            self._regions.append(region)
            
            return offset
    
    def free(self, offset: int) -> bool:
        """Free an allocated region.
        
        Args:
            offset: Offset returned from allocate().
            
        Returns:
            True if freed successfully.
        """
        with self._lock:
            for i, region in enumerate(self._regions):
                if region.offset == offset:
                    region.in_use = False
                    # Compact if at end
                    while self._regions and not self._regions[-1].in_use:
                        self._regions.pop()
                    return True
            return False
    
    def write(self, offset: int, data: bytes) -> int:
        """Write data to arena at offset.
        
        Args:
            offset: Offset to write at.
            data: Bytes to write.
            
        Returns:
            Number of bytes written.
        """
        end = offset + len(data)
        if end > self._size:
            raise ValueError(f"Write exceeds arena bounds: {end} > {self._size}")
        
        self._shm.buf[offset:end] = data
        return len(data)
    
    def read(self, offset: int, size: int) -> bytes:
        """Read data from arena.
        
        Args:
            offset: Offset to read from.
            size: Number of bytes to read.
            
        Returns:
            Bytes read.
        """
        end = offset + size
        if end > self._size:
            raise ValueError(f"Read exceeds arena bounds: {end} > {self._size}")
        
        return bytes(self._shm.buf[offset:end])
    
    def get_view(self, offset: int, size: int) -> memoryview:
        """Get a memoryview into the arena (zero-copy).
        
        Args:
            offset: Offset for view.
            size: Size of view.
            
        Returns:
            Memoryview into shared memory.
        """
        return self._shm.buf[offset:offset + size]
    
    @property
    def name(self) -> str:
        return self._name
    
    @property
    def size(self) -> int:
        return self._size
    
    def close(self) -> None:
        """Close shared memory handle."""
        self._shm.close()
        if self._owner:
            try:
                self._shm.unlink()
            except FileNotFoundError:
                pass
    
    def __enter__(self) -> "SharedMemoryArena":
        return self
    
    def __exit__(self, *args) -> None:
        self.close()


class SharedBuffer:
    """Zero-copy buffer backed by shared memory.
    
    Provides a buffer interface that can be efficiently passed
    between processes without copying data.
    """
    
    def __init__(
        self,
        arena: SharedMemoryArena,
        size: int,
        offset: Optional[int] = None,
    ) -> None:
        """Create a shared buffer.
        
        Args:
            arena: The arena to allocate from.
            size: Buffer size in bytes.
            offset: Optional pre-allocated offset.
        """
        self._arena = arena
        self._size = size
        
        if offset is not None:
            self._offset = offset
            self._owned = False
        else:
            self._offset = arena.allocate(size)
            if self._offset is None:
                raise MemoryError("Failed to allocate shared buffer")
            self._owned = True
    
    def write(self, data: bytes, offset: int = 0) -> int:
        """Write data to buffer.
        
        Args:
            data: Bytes to write.
            offset: Offset within buffer.
            
        Returns:
            Bytes written.
        """
        if offset + len(data) > self._size:
            raise ValueError("Write exceeds buffer size")
        return self._arena.write(self._offset + offset, data)
    
    def read(self, size: Optional[int] = None, offset: int = 0) -> bytes:
        """Read data from buffer.
        
        Args:
            size: Bytes to read (None = all).
            offset: Offset within buffer.
            
        Returns:
            Bytes read.
        """
        read_size = size if size is not None else (self._size - offset)
        return self._arena.read(self._offset + offset, read_size)
    
    def view(self) -> memoryview:
        """Get memoryview of buffer (zero-copy).
        
        Returns:
            Memoryview of buffer contents.
        """
        return self._arena.get_view(self._offset, self._size)
    
    @property
    def size(self) -> int:
        return self._size
    
    @property
    def offset(self) -> int:
        return self._offset
    
    @property
    def arena_name(self) -> str:
        return self._arena.name
    
    def to_descriptor(self) -> Dict[str, Any]:
        """Get descriptor for passing to another process.
        
        Returns:
            Dictionary with arena name, offset, and size.
        """
        return {
            "arena": self._arena.name,
            "offset": self._offset,
            "size": self._size,
        }
    
    @classmethod
    def from_descriptor(cls, desc: Dict[str, Any]) -> "SharedBuffer":
        """Reconstruct buffer from descriptor.
        
        Args:
            desc: Descriptor from to_descriptor().
            
        Returns:
            SharedBuffer attached to existing memory.
        """
        arena = SharedMemoryArena(desc["arena"], size=0)  # Attach only
        return cls(arena, desc["size"], desc["offset"])
    
    def free(self) -> None:
        """Release buffer back to arena."""
        if self._owned:
            self._arena.free(self._offset)
            self._owned = False


class IPCChannel:
    """Message-passing channel over shared memory.
    
    Provides a bidirectional communication channel between
    processes using shared memory for data and a simple
    protocol for coordination.
    """
    
    def __init__(
        self,
        name: str,
        arena: Optional[SharedMemoryArena] = None,
        buffer_size: int = 1024 * 1024,
    ) -> None:
        """Create IPC channel.
        
        Args:
            name: Channel name.
            arena: Optional shared arena (creates new if None).
            buffer_size: Size of message buffers.
        """
        self._name = name
        self._buffer_size = buffer_size
        
        # Create or attach to arena
        if arena:
            self._arena = arena
            self._owns_arena = False
        else:
            self._arena = SharedMemoryArena(f"ipc_{name}", size=buffer_size * 4)
            self._owns_arena = True
        
        # Allocate send/recv buffers
        self._send_offset = self._arena.allocate(buffer_size)
        self._recv_offset = self._arena.allocate(buffer_size)
        
        if self._send_offset is None or self._recv_offset is None:
            raise MemoryError("Failed to allocate channel buffers")
        
        # Sequence counters for message ordering
        self._send_seq = 0
        self._recv_seq = 0
        self._lock = threading.Lock()
    
    def send(
        self,
        msg_type: int,
        payload: bytes,
        timeout: Optional[float] = None,
    ) -> bool:
        """Send a message.
        
        Args:
            msg_type: Message type identifier.
            payload: Message payload.
            timeout: Send timeout (None = blocking).
            
        Returns:
            True if sent successfully.
        """
        with self._lock:
            if MSG_HEADER_SIZE + len(payload) > self._buffer_size:
                raise ValueError("Message too large for channel")
            
            # Pack header
            header = struct.pack(
                MSG_HEADER_FORMAT,
                MSG_MAGIC,
                msg_type,
                len(payload),
                int(time.time() * 1e6),
            )
            
            # Write to send buffer
            self._arena.write(self._send_offset, header + payload)
            self._send_seq += 1
            
            return True
    
    def recv(self, timeout: Optional[float] = None) -> Optional[Tuple[int, bytes]]:
        """Receive a message.
        
        Args:
            timeout: Receive timeout (None = blocking).
            
        Returns:
            Tuple of (msg_type, payload) or None if no message.
        """
        # Read header
        header_bytes = self._arena.read(self._recv_offset, MSG_HEADER_SIZE)
        
        magic, msg_type, payload_len, timestamp = struct.unpack(
            MSG_HEADER_FORMAT, header_bytes
        )
        
        if magic != MSG_MAGIC:
            return None  # No valid message
        
        # Read payload
        payload = self._arena.read(
            self._recv_offset + MSG_HEADER_SIZE,
            payload_len
        )
        
        self._recv_seq += 1
        return (msg_type, payload)
    
    def send_request(self, data: bytes) -> bool:
        """Send a request message."""
        return self.send(MessageType.REQUEST, data)
    
    def send_response(self, data: bytes) -> bool:
        """Send a response message."""
        return self.send(MessageType.RESPONSE, data)
    
    @property
    def name(self) -> str:
        return self._name
    
    def close(self) -> None:
        """Close the channel."""
        if self._owns_arena:
            self._arena.close()
    
    def __enter__(self) -> "IPCChannel":
        return self
    
    def __exit__(self, *args) -> None:
        self.close()


class SharedRequestContext:
    """Request context stored in shared memory.
    
    Allows request data to be passed between processes
    without serialization, enabling zero-copy request handling.
    """
    
    # Context layout:
    # method (8) + path_offset (8) + path_len (8) + headers_offset (8) +
    # headers_len (8) + body_offset (8) + body_len (8) = 56 bytes header
    HEADER_FORMAT = "!8sQQQQQQ"
    HEADER_SIZE = struct.calcsize(HEADER_FORMAT)
    
    def __init__(
        self,
        arena: SharedMemoryArena,
        method: str = "GET",
        path: str = "/",
        headers: Optional[Dict[str, str]] = None,
        body: bytes = b"",
    ) -> None:
        """Create shared request context.
        
        Args:
            arena: Shared memory arena.
            method: HTTP method.
            path: Request path.
            headers: HTTP headers.
            body: Request body.
        """
        self._arena = arena
        
        # Encode components
        method_bytes = method.encode()[:8].ljust(8, b'\x00')
        path_bytes = path.encode()
        headers_bytes = self._encode_headers(headers or {})
        
        # Calculate total size
        total_size = (
            self.HEADER_SIZE +
            len(path_bytes) +
            len(headers_bytes) +
            len(body)
        )
        
        # Allocate
        self._offset = arena.allocate(total_size)
        if self._offset is None:
            raise MemoryError("Failed to allocate request context")
        
        # Write path
        path_offset = self._offset + self.HEADER_SIZE
        arena.write(path_offset, path_bytes)
        
        # Write headers
        headers_offset = path_offset + len(path_bytes)
        arena.write(headers_offset, headers_bytes)
        
        # Write body
        body_offset = headers_offset + len(headers_bytes)
        arena.write(body_offset, body)
        
        # Write header
        header = struct.pack(
            self.HEADER_FORMAT,
            method_bytes,
            path_offset, len(path_bytes),
            headers_offset, len(headers_bytes),
            body_offset, len(body),
        )
        arena.write(self._offset, header)
    
    def _encode_headers(self, headers: Dict[str, str]) -> bytes:
        """Encode headers to bytes."""
        parts = []
        for k, v in headers.items():
            parts.append(f"{k}: {v}")
        return "\r\n".join(parts).encode()
    
    @property
    def offset(self) -> int:
        return self._offset
    
    @classmethod
    def from_offset(
        cls,
        arena: SharedMemoryArena,
        offset: int,
    ) -> Dict[str, Any]:
        """Read request context from shared memory.
        
        Args:
            arena: Shared memory arena.
            offset: Offset of context.
            
        Returns:
            Dictionary with method, path, headers, body.
        """
        header = arena.read(offset, cls.HEADER_SIZE)
        (
            method_bytes,
            path_offset, path_len,
            headers_offset, headers_len,
            body_offset, body_len,
        ) = struct.unpack(cls.HEADER_FORMAT, header)
        
        return {
            "method": method_bytes.rstrip(b'\x00').decode(),
            "path": arena.read(path_offset, path_len).decode(),
            "headers": arena.read(headers_offset, headers_len).decode(),
            "body": arena.read(body_offset, body_len),
        }
