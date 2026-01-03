"""Native worker threads for GIL-free execution.

Provides a thread pool that releases the GIL when executing compiled
native code, enabling true parallel execution of request handlers.

Key features:
- Thread pool with configurable worker count
- GIL release during native code execution
- Work stealing for load balancing
- Metrics collection for monitoring
"""

from __future__ import annotations

import ctypes
import queue
import threading
import time
from concurrent.futures import Future
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Callable, Dict, List, Optional, Tuple


class TaskPriority(Enum):
    """Task execution priority."""
    HIGH = 0
    NORMAL = 1
    LOW = 2


@dataclass
class CompiledTask:
    """A task for execution by native workers.
    
    Represents a compiled trace invocation with all required
    context for execution.
    """
    function_ptr: int           # Native function pointer
    args: Tuple[Any, ...] = ()  # Arguments (as ctypes-compatible values)
    priority: TaskPriority = TaskPriority.NORMAL
    callback: Optional[Callable[[Any], None]] = None
    error_callback: Optional[Callable[[Exception], None]] = None
    
    # Tracking
    submitted_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None


@dataclass
class WorkerStats:
    """Statistics for a worker thread."""
    worker_id: int
    tasks_completed: int = 0
    total_execution_ns: int = 0
    idle_time_ns: int = 0
    last_active: float = field(default_factory=time.time)


class NativeWorker(threading.Thread):
    """A worker thread that executes compiled native code.
    
    Releases the GIL during native function execution to enable
    true parallelism.
    """
    
    def __init__(
        self,
        worker_id: int,
        task_queue: queue.PriorityQueue,
        shutdown_event: threading.Event,
    ) -> None:
        super().__init__(daemon=True, name=f"NativeWorker-{worker_id}")
        self._worker_id = worker_id
        self._task_queue = task_queue
        self._shutdown = shutdown_event
        self._stats = WorkerStats(worker_id=worker_id)
        self._current_task: Optional[CompiledTask] = None
    
    @property
    def stats(self) -> WorkerStats:
        return self._stats
    
    def run(self) -> None:
        """Worker main loop."""
        while not self._shutdown.is_set():
            try:
                # Wait for task with timeout (allows checking shutdown)
                priority, task = self._task_queue.get(timeout=0.1)
            except queue.Empty:
                continue
            
            self._current_task = task
            task.started_at = time.time()
            
            try:
                # Execute the compiled function
                result = self._execute_native(task)
                
                # Invoke success callback
                if task.callback:
                    task.callback(result)
                    
            except Exception as e:
                # Invoke error callback
                if task.error_callback:
                    task.error_callback(e)
                    
            finally:
                task.completed_at = time.time()
                self._stats.tasks_completed += 1
                if task.started_at:
                    exec_ns = int((task.completed_at - task.started_at) * 1e9)
                    self._stats.total_execution_ns += exec_ns
                self._stats.last_active = time.time()
                self._current_task = None
                self._task_queue.task_done()
    
    def _execute_native(self, task: CompiledTask) -> Any:
        """Execute native function, releasing GIL.
        
        Args:
            task: The compiled task to execute.
            
        Returns:
            Result from native function.
        """
        # Create ctypes function type
        # Signature: int64 (*)(int64) for our simplified trace_entry
        FUNC_TYPE = ctypes.CFUNCTYPE(ctypes.c_int64, ctypes.c_int64)
        
        # Cast function pointer
        native_func = FUNC_TYPE(task.function_ptr)
        
        # Prepare arguments
        if task.args:
            arg = task.args[0] if isinstance(task.args[0], int) else 0
        else:
            arg = 0
        
        # Execute with GIL released
        # Note: ctypes automatically releases GIL for native calls
        # when using CFUNCTYPE (as opposed to WINFUNCTYPE on Windows)
        result = native_func(arg)
        
        return result


class NativeWorkerPool:
    """Pool of native worker threads for parallel execution.
    
    Manages a set of worker threads that execute compiled traces
    without holding the GIL, enabling true multi-core utilization.
    """
    
    def __init__(self, num_workers: Optional[int] = None) -> None:
        """Initialize the worker pool.
        
        Args:
            num_workers: Number of workers. Defaults to CPU count.
        """
        import os
        self._num_workers = num_workers or os.cpu_count() or 4
        self._task_queue: queue.PriorityQueue = queue.PriorityQueue()
        self._shutdown = threading.Event()
        self._workers: List[NativeWorker] = []
        self._started = False
        self._lock = threading.Lock()
    
    def start(self) -> None:
        """Start all worker threads."""
        with self._lock:
            if self._started:
                return
            
            for i in range(self._num_workers):
                worker = NativeWorker(i, self._task_queue, self._shutdown)
                worker.start()
                self._workers.append(worker)
            
            self._started = True
    
    def stop(self, wait: bool = True, timeout: float = 5.0) -> None:
        """Stop all worker threads.
        
        Args:
            wait: Whether to wait for workers to finish.
            timeout: Maximum time to wait per worker.
        """
        self._shutdown.set()
        
        if wait:
            deadline = time.time() + timeout
            for worker in self._workers:
                remaining = max(0, deadline - time.time())
                worker.join(timeout=remaining)
        
        self._workers.clear()
        self._started = False
        self._shutdown.clear()
    
    def submit(self, task: CompiledTask) -> Future:
        """Submit a task for execution.
        
        Args:
            task: The compiled task to execute.
            
        Returns:
            Future that will contain the result.
        """
        if not self._started:
            self.start()
        
        future: Future = Future()
        
        # Wrap callbacks to set future result
        original_callback = task.callback
        original_error = task.error_callback
        
        def on_success(result: Any) -> None:
            future.set_result(result)
            if original_callback:
                original_callback(result)
        
        def on_error(exc: Exception) -> None:
            future.set_exception(exc)
            if original_error:
                original_error(exc)
        
        task.callback = on_success
        task.error_callback = on_error
        
        # Queue with priority
        self._task_queue.put((task.priority.value, task))
        
        return future
    
    def submit_function(
        self,
        function_ptr: int,
        args: Tuple[Any, ...] = (),
        priority: TaskPriority = TaskPriority.NORMAL,
    ) -> Future:
        """Submit a function pointer for execution.
        
        Args:
            function_ptr: Native function pointer.
            args: Arguments to pass.
            priority: Execution priority.
            
        Returns:
            Future that will contain the result.
        """
        task = CompiledTask(
            function_ptr=function_ptr,
            args=args,
            priority=priority,
        )
        return self.submit(task)
    
    def map(
        self,
        function_ptr: int,
        args_list: List[Tuple[Any, ...]],
        timeout: Optional[float] = None,
    ) -> List[Any]:
        """Execute function with multiple argument sets.
        
        Args:
            function_ptr: Native function pointer.
            args_list: List of argument tuples.
            timeout: Maximum time to wait.
            
        Returns:
            List of results in order.
        """
        futures = [
            self.submit_function(function_ptr, args)
            for args in args_list
        ]
        
        results = []
        for future in futures:
            try:
                results.append(future.result(timeout=timeout))
            except Exception as e:
                results.append(e)
        
        return results
    
    def get_stats(self) -> Dict[str, Any]:
        """Get pool statistics.
        
        Returns:
            Dictionary with pool metrics.
        """
        total_tasks = sum(w.stats.tasks_completed for w in self._workers)
        total_exec_ns = sum(w.stats.total_execution_ns for w in self._workers)
        
        return {
            "num_workers": self._num_workers,
            "total_tasks_completed": total_tasks,
            "total_execution_ms": total_exec_ns / 1e6,
            "avg_task_ms": (total_exec_ns / total_tasks / 1e6) if total_tasks > 0 else 0,
            "queue_size": self._task_queue.qsize(),
            "workers": [
                {
                    "id": w.stats.worker_id,
                    "tasks": w.stats.tasks_completed,
                    "exec_ms": w.stats.total_execution_ns / 1e6,
                }
                for w in self._workers
            ],
        }
    
    def __enter__(self) -> "NativeWorkerPool":
        self.start()
        return self
    
    def __exit__(self, *args) -> None:
        self.stop()
