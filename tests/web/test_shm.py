"""Tests for shared memory IPC."""

import unittest
from pyaot.web.gil.shm import SharedMemoryArena, SharedBuffer, IPCChannel, MessageType


class TestSharedMemoryArena(unittest.TestCase):
    def test_arena_creation(self):
        arena = SharedMemoryArena("test_arena", size=1024 * 1024)
        try:
            self.assertEqual(arena.name, "test_arena")
            self.assertEqual(arena.size, 1024 * 1024)
        finally:
            arena.close()
    
    def test_allocate_and_write(self):
        arena = SharedMemoryArena("test_alloc", size=1024 * 1024)
        try:
            offset = arena.allocate(100)
            self.assertIsNotNone(offset)
            
            data = b"Hello, shared memory!"
            written = arena.write(offset, data)
            self.assertEqual(written, len(data))
            
            read_back = arena.read(offset, len(data))
            self.assertEqual(read_back, data)
        finally:
            arena.close()
    
    def test_free_region(self):
        arena = SharedMemoryArena("test_free", size=1024 * 1024)
        try:
            offset = arena.allocate(100)
            self.assertIsNotNone(offset)
            
            freed = arena.free(offset)
            self.assertTrue(freed)
        finally:
            arena.close()


class TestSharedBuffer(unittest.TestCase):
    def test_buffer_operations(self):
        arena = SharedMemoryArena("test_buffer", size=1024 * 1024)
        try:
            buffer = SharedBuffer(arena, size=256)
            
            data = b"Test data in buffer"
            buffer.write(data)
            
            read_back = buffer.read(len(data))
            self.assertEqual(read_back, data)
            
            buffer.free()
        finally:
            arena.close()
    
    def test_buffer_descriptor(self):
        arena = SharedMemoryArena("test_desc", size=1024 * 1024)
        try:
            buffer = SharedBuffer(arena, size=128)
            desc = buffer.to_descriptor()
            
            self.assertEqual(desc["arena"], "test_desc")
            self.assertEqual(desc["size"], 128)
            self.assertIn("offset", desc)
        finally:
            arena.close()


class TestIPCChannel(unittest.TestCase):
    def test_channel_creation(self):
        channel = IPCChannel("test_channel")
        try:
            self.assertEqual(channel.name, "test_channel")
        finally:
            channel.close()
    
    def test_send_message(self):
        channel = IPCChannel("test_send")
        try:
            payload = b"Hello IPC!"
            success = channel.send(MessageType.REQUEST, payload)
            self.assertTrue(success)
        finally:
            channel.close()


if __name__ == "__main__":
    unittest.main()
