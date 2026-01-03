"""Benchmark/Test for Query Profiler."""
import time
import sys
import os

# Ensure project root in path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from pyaot.web.frameworks.generic import WSGIMiddleware
from pyaot.web.io.query import QueryAnalyzer
from pyaot.web.trace.config import TracerConfig

class MockCursor:
    def execute(self, sql, params=()):
        # Simulate I/O
        pass

class MockApp:
    def __init__(self):
        self.cursor = MockCursor()
        
    def __call__(self, environ, start_response):
        # A recognizable SQL query
        self.cursor.execute("SELECT * FROM users WHERE id=1")
        start_response("200 OK", [("Content-Type", "text/plain")])
        return [b"OK"]

def main():
    app = MockApp()
    # Force immediate eligibility
    config = TracerConfig(
        min_observations=1, 
        min_client_prefixes=1,
        min_observation_window_seconds=0,
        min_branch_stability=0.0
    )
    middleware = WSGIMiddleware(app, config=config)
    middleware.enable()
    
    # Environment
    env = {
        "REQUEST_METHOD": "GET", 
        "PATH_INFO": "/users/1",
        "wsgi.input": None,
        "QUERY_STRING": "",
        "REMOTE_ADDR": "127.0.0.1"
    }
    
    print("Running request (Recording Trace)...")
    list(middleware(env, lambda x, y: None))
    
    # Check trace in store
    analyzer = QueryAnalyzer()
    
    # Access private store for verification
    # TraceStore uses internal dict _traces
    # But TraceStore interface is store(signature, ...) and get(signature).
    # It stores traces in memory?
    # Let's inspect generic.py -> _store is TraceStore instance.
    # store.py -> TraceStore has _traces dict?
    
    traces = []
    # Hack: access internal storage if public API doesn't list all
    if hasattr(middleware._store, "_traces"):
        traces = list(middleware._store._traces.values())
        print(f"Found {len(traces)} traces in store.")
    else:
        print("Cannot access traces in store.")
        return

    found_queries = []
    
    for trace in traces:
        queries = analyzer.analyze(trace)
        found_queries.extend(queries)

    print(f"\nDetected {len(found_queries)} queries:")
    for q in found_queries:
        print(f" - {q.sql}")

    if any("SELECT * FROM users" in q.sql for q in found_queries):
        print("\nSUCCESS: Query Profiler detected SQL.")
    else:
        print("\nFAILURE: No queries detected.")
        if traces:
             t = traces[0]
             print(f"\nTrace Length: {len(t.ops)}")
             print("First 10 Ops:")
             for op in t.ops[:10]:
                  print(op)
             print("\nCall Targets:")
             for idx in range(len(t.call_targets)):
                  print(t.call_targets.get(idx))

if __name__ == "__main__":
    main()
