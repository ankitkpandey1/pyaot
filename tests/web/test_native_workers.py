"""Tests for native worker pool."""

import time
import unittest
from pyaot.web.gil.workers import NativeWorkerPool, CompiledTask, TaskPriority


class TestNativeWorkerPool(unittest.TestCase):
    def test_pool_initialization(self):
        pool = NativeWorkerPool(num_workers=2)
        self.assertEqual(pool._num_workers, 2)
        self.assertFalse(pool._started)
    
    def test_pool_start_stop(self):
        pool = NativeWorkerPool(num_workers=2)
        pool.start()
        self.assertTrue(pool._started)
        self.assertEqual(len(pool._workers), 2)
        
        pool.stop(wait=True, timeout=1.0)
        self.assertFalse(pool._started)
        self.assertEqual(len(pool._workers), 0)
    
    def test_pool_context_manager(self):
        with NativeWorkerPool(num_workers=2) as pool:
            self.assertTrue(pool._started)
        self.assertFalse(pool._started)
    
    def test_get_stats(self):
        with NativeWorkerPool(num_workers=2) as pool:
            stats = pool.get_stats()
            self.assertEqual(stats["num_workers"], 2)
            self.assertEqual(stats["total_tasks_completed"], 0)


class TestCompiledTask(unittest.TestCase):
    def test_task_creation(self):
        task = CompiledTask(
            function_ptr=0x12345,
            args=(42,),
            priority=TaskPriority.HIGH,
        )
        
        self.assertEqual(task.function_ptr, 0x12345)
        self.assertEqual(task.args, (42,))
        self.assertEqual(task.priority, TaskPriority.HIGH)
        self.assertIsNotNone(task.submitted_at)


if __name__ == "__main__":
    unittest.main()
