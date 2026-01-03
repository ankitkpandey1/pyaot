"""Realistic E2E benchmark with simulated database CRUD operations.

Simulates a real-world web application with:
- SQLite in-memory database
- User CRUD operations
- JSON serialization
- Authentication checks

Run with: python benchmarks/web/bench_realistic_crud.py
"""

from __future__ import annotations

import json
import sqlite3
import time
import hashlib
from typing import Any, Callable, Iterator
from dataclasses import dataclass, asdict

import matplotlib.pyplot as plt
import numpy as np

from pyaot.web.frameworks.generic import WSGIMiddleware
from pyaot.web.trace.config import TracerConfig
from pyaot.web.ops.metrics import reset_metrics, get_metrics


# =============================================================================
# Simulated Database Layer
# =============================================================================


@dataclass
class User:
    """User model."""
    id: int
    name: str
    email: str
    password_hash: str
    created_at: str


class Database:
    """Simple SQLite in-memory database for benchmarking."""

    def __init__(self):
        self.conn = sqlite3.connect(":memory:", check_same_thread=False)
        self._create_tables()
        self._seed_data()

    def _create_tables(self):
        self.conn.execute("""
            CREATE TABLE users (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        self.conn.commit()

    def _seed_data(self):
        """Seed with initial data."""
        for i in range(100):
            self.conn.execute(
                "INSERT INTO users (name, email, password_hash, created_at) VALUES (?, ?, ?, ?)",
                (f"User {i}", f"user{i}@example.com",
                 hashlib.sha256(f"password{i}".encode()).hexdigest(),
                 "2024-01-01T00:00:00Z")
            )
        self.conn.commit()

    def get_user(self, user_id: int) -> dict | None:
        """Get user by ID."""
        cursor = self.conn.execute(
            "SELECT id, name, email, password_hash, created_at FROM users WHERE id = ?",
            (user_id,)
        )
        row = cursor.fetchone()
        if row:
            return {
                "id": row[0], "name": row[1], "email": row[2],
                "password_hash": row[3], "created_at": row[4]
            }
        return None

    def create_user(self, name: str, email: str, password: str) -> dict:
        """Create new user."""
        password_hash = hashlib.sha256(password.encode()).hexdigest()
        cursor = self.conn.execute(
            "INSERT INTO users (name, email, password_hash, created_at) VALUES (?, ?, ?, ?)",
            (name, email, password_hash, "2024-01-01T00:00:00Z")
        )
        self.conn.commit()
        return {"id": cursor.lastrowid, "name": name, "email": email}

    def update_user(self, user_id: int, name: str) -> dict | None:
        """Update user name."""
        self.conn.execute(
            "UPDATE users SET name = ? WHERE id = ?",
            (name, user_id)
        )
        self.conn.commit()
        return self.get_user(user_id)

    def delete_user(self, user_id: int) -> bool:
        """Delete user."""
        cursor = self.conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        self.conn.commit()
        return cursor.rowcount > 0

    def list_users(self, limit: int = 10) -> list[dict]:
        """List users."""
        cursor = self.conn.execute(
            "SELECT id, name, email FROM users LIMIT ?", (limit,)
        )
        return [{"id": r[0], "name": r[1], "email": r[2]} for r in cursor.fetchall()]


# =============================================================================
# WSGI Application with Real Database
# =============================================================================


def create_crud_app(db: Database) -> Callable:
    """Create WSGI app with database CRUD operations."""

    def app(environ: dict, start_response: Callable) -> Iterator[bytes]:
        # Simulate DB latency (1ms) - HandlerOptimizer caching will BYPASS this for GETs!
        time.sleep(0.001)

        path = environ.get("PATH_INFO", "/")
        method = environ.get("REQUEST_METHOD", "GET")

        # Route: GET /users - list users
        if path == "/users" and method == "GET":
            users = db.list_users(limit=10)
            body = json.dumps({"users": users}).encode()
            start_response("200 OK", [("Content-Type", "application/json")])
            return iter([body])

        # Route: GET /users/{id} - get user
        if path.startswith("/users/") and method == "GET":
            try:
                user_id = int(path.split("/")[-1])
                user = db.get_user(user_id)
                if user:
                    # Remove password hash from response
                    user.pop("password_hash", None)
                    body = json.dumps(user).encode()
                    start_response("200 OK", [("Content-Type", "application/json")])
                else:
                    body = json.dumps({"error": "not found"}).encode()
                    start_response("404 Not Found", [("Content-Type", "application/json")])
            except ValueError:
                body = json.dumps({"error": "invalid id"}).encode()
                start_response("400 Bad Request", [("Content-Type", "application/json")])
            return iter([body])

        # Route: POST /users - create user
        if path == "/users" and method == "POST":
            # Simulate reading request body
            user = db.create_user("New User", f"new{time.time_ns()}@example.com", "password123")
            body = json.dumps(user).encode()
            start_response("201 Created", [("Content-Type", "application/json")])
            return iter([body])

        # Route: PUT /users/{id} - update user
        if path.startswith("/users/") and method == "PUT":
            try:
                user_id = int(path.split("/")[-1])
                user = db.update_user(user_id, f"Updated User {user_id}")
                if user:
                    user.pop("password_hash", None)
                    body = json.dumps(user).encode()
                    start_response("200 OK", [("Content-Type", "application/json")])
                else:
                    body = json.dumps({"error": "not found"}).encode()
                    start_response("404 Not Found", [("Content-Type", "application/json")])
            except ValueError:
                body = json.dumps({"error": "invalid id"}).encode()
                start_response("400 Bad Request", [("Content-Type", "application/json")])
            return iter([body])

        # Route: DELETE /users/{id} - delete user
        if path.startswith("/users/") and method == "DELETE":
            try:
                user_id = int(path.split("/")[-1])
                if db.delete_user(user_id):
                    body = b""
                    start_response("204 No Content", [])
                else:
                    body = json.dumps({"error": "not found"}).encode()
                    start_response("404 Not Found", [("Content-Type", "application/json")])
            except ValueError:
                body = json.dumps({"error": "invalid id"}).encode()
                start_response("400 Bad Request", [("Content-Type", "application/json")])
            return iter([body])

        # Default: 404
        body = json.dumps({"error": "not found"}).encode()
        start_response("404 Not Found", [("Content-Type", "application/json")])
        return iter([body])

    return app


# =============================================================================
# Benchmark
# =============================================================================


def make_environ(
    method: str = "GET",
    path: str = "/users",
    client_ip: str = "192.168.1.1"
) -> dict[str, Any]:
    """Create WSGI environ."""
    return {
        "REQUEST_METHOD": method,
        "PATH_INFO": path,
        "QUERY_STRING": "",
        "SERVER_NAME": "localhost",
        "SERVER_PORT": "8000",
        "REMOTE_ADDR": client_ip,
        "HTTP_AUTHORIZATION": "Bearer token123",
        "wsgi.version": (1, 0),
        "wsgi.url_scheme": "http",
        "wsgi.input": None,
        "wsgi.errors": None,
    }


def mock_start_response(status: str, headers: list, exc_info: Any = None) -> Callable:
    return lambda exc_info=None: None


def consume(response: Iterator[bytes]) -> bytes:
    return b"".join(response)


def run_realistic_benchmark(n_iterations: int = 500) -> dict:
    """Run benchmark with realistic CRUD workload."""
    reset_metrics()

    # Setup database
    db = Database()
    baseline_app = create_crud_app(db)

    # PyAOT wrapped app with relaxed config
    config = TracerConfig(
        min_observations=10,
        min_client_prefixes=3,
        min_observation_window_seconds=0,
        min_branch_stability=0.5,
    )

    pyaot_app = WSGIMiddleware(create_crud_app(db), config=config)

    baseline_times = []
    pyaot_times = []
    operations = []

    # Simulate realistic workload:
    # 60% reads, 15% creates, 15% updates, 10% deletes
    # Use diverse IPs to satisfy poisoning protection (needs distinct /16 prefixes)
    client_ips = [f"10.{i}.{j}.1" for i in range(5) for j in range(5)]

    for i in range(n_iterations):
        client_ip = client_ips[i % len(client_ips)]
        op = i % 20

        if op < 12:  # 60% GET
            environ = make_environ("GET", f"/users/{(i % 100) + 1}", client_ip)
            op_name = "GET"
        elif op < 15:  # 15% POST
            environ = make_environ("POST", "/users", client_ip)
            op_name = "POST"
        elif op < 18:  # 15% PUT
            environ = make_environ("PUT", f"/users/{(i % 100) + 1}", client_ip)
            op_name = "PUT"
        else:  # 10% DELETE (use high IDs to avoid deleting seed data)
            environ = make_environ("DELETE", f"/users/{500 + i}", client_ip)
            op_name = "DELETE"

        operations.append(op_name)

        # Baseline
        start = time.perf_counter_ns()
        consume(baseline_app(environ, mock_start_response))
        baseline_times.append(time.perf_counter_ns() - start)

        # PyAOT
        start = time.perf_counter_ns()
        consume(pyaot_app(environ, mock_start_response))
        pyaot_times.append(time.perf_counter_ns() - start)

        if (i + 1) % 50 == 0:
            print(f"  Progress: {i + 1}/{n_iterations} requests (Compiled: {len(pyaot_app._compiled_traces)})")

    return {
        "baseline_ns": baseline_times,
        "pyaot_ns": pyaot_times,
        "operations": operations,
        "n_iterations": n_iterations,
        "compiled_traces": len(pyaot_app._compiled_traces),
        # "metrics": get_metrics().get_summary(),  # Avoiding lock contention
    }


def analyze_by_operation(data: dict) -> dict:
    """Analyze performance by operation type."""
    ops = data["operations"]
    baseline = data["baseline_ns"]
    pyaot = data["pyaot_ns"]

    results = {}
    for op in ["GET", "POST", "PUT", "DELETE"]:
        indices = [i for i, o in enumerate(ops) if o == op]
        if indices:
            b_times = [baseline[i] for i in indices]
            p_times = [pyaot[i] for i in indices]
            results[op] = {
                "count": len(indices),
                "baseline_avg_us": np.mean(b_times) / 1000,
                "pyaot_avg_us": np.mean(p_times) / 1000,
                "overhead_pct": ((np.mean(p_times) - np.mean(b_times)) / np.mean(b_times)) * 100,
            }
    return results


def generate_graph(data: dict, output_path: str) -> None:
    """Generate benchmark visualization."""
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))

    # Plot 1: Overall latency over time
    ax1 = axes[0, 0]
    baseline = np.array(data["baseline_ns"]) / 1000
    pyaot = np.array(data["pyaot_ns"]) / 1000

    window = 20
    baseline_smooth = np.convolve(baseline, np.ones(window) / window, mode="valid")
    pyaot_smooth = np.convolve(pyaot, np.ones(window) / window, mode="valid")

    ax1.plot(baseline_smooth, label="Baseline", color="#4CAF50", linewidth=1.5)
    ax1.plot(pyaot_smooth, label="PyAOT Web", color="#2196F3", linewidth=1.5)
    ax1.set_xlabel("Request #")
    ax1.set_ylabel("Latency (μs)")
    ax1.set_title("Request Latency Over Time (20-req rolling avg)")
    ax1.legend()
    ax1.grid(True, alpha=0.3)

    # Plot 2: By operation type
    ax2 = axes[0, 1]
    op_data = analyze_by_operation(data)
    ops = list(op_data.keys())
    x = np.arange(len(ops))
    width = 0.35

    baseline_vals = [op_data[op]["baseline_avg_us"] for op in ops]
    pyaot_vals = [op_data[op]["pyaot_avg_us"] for op in ops]

    ax2.bar(x - width / 2, baseline_vals, width, label="Baseline", color="#4CAF50")
    ax2.bar(x + width / 2, pyaot_vals, width, label="PyAOT Web", color="#2196F3")
    ax2.set_xlabel("Operation")
    ax2.set_ylabel("Average Latency (μs)")
    ax2.set_title("Latency by CRUD Operation")
    ax2.set_xticks(x)
    ax2.set_xticklabels(ops)
    ax2.legend()
    ax2.grid(axis="y", alpha=0.3)

    # Plot 3: Overhead distribution
    ax3 = axes[1, 0]
    overhead = (np.array(data["pyaot_ns"]) - np.array(data["baseline_ns"])) / 1000
    ax3.hist(overhead, bins=50, color="#9C27B0", alpha=0.7, edgecolor="black")
    ax3.axvline(x=np.median(overhead), color="red", linestyle="--",
                label=f"Median: {np.median(overhead):.1f}μs")
    ax3.set_xlabel("Overhead (μs)")
    ax3.set_ylabel("Frequency")
    ax3.set_title("PyAOT Overhead Distribution")
    ax3.legend()
    ax3.grid(True, alpha=0.3)

    # Plot 4: Summary stats
    ax4 = axes[1, 1]
    ax4.axis("off")

    summary_text = f"""
    REALISTIC CRUD BENCHMARK SUMMARY
    ================================

    Total Requests: {data['n_iterations']}
    Compiled Traces: {data['compiled_traces']}

    Operation Mix:
      GET:    60%
      POST:   15%
      PUT:    15%
      DELETE: 10%

    Average Latency:
      Baseline: {np.mean(baseline):.1f} μs
      PyAOT:    {np.mean(pyaot):.1f} μs
      Overhead: {((np.mean(pyaot) - np.mean(baseline)) / np.mean(baseline)) * 100:.1f}%

    Note: Overhead is tracing cost.
    Compiled execution not yet implemented.
    """
    ax4.text(0.1, 0.9, summary_text, transform=ax4.transAxes,
             fontsize=11, verticalalignment="top", fontfamily="monospace")

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches="tight")
    print(f"\n✅ Graph saved to: {output_path}")


def main():
    """Run realistic CRUD benchmark."""
    print("=" * 70)
    print("PyAOT Web Realistic CRUD Benchmark")
    print("=" * 70)
    print()
    print("Simulates real-world web application:")
    print("  - SQLite in-memory database")
    print("  - User CRUD operations (GET 60%, POST 15%, PUT 15%, DELETE 10%)")
    print("  - JSON serialization")
    print("  - Multiple client IPs")
    print()

    N = 1000
    print(f"Running {N} requests...")
    data = run_realistic_benchmark(n_iterations=N)

    print("\n" + "=" * 70)
    print("RESULTS BY OPERATION")
    print("=" * 70)

    op_data = analyze_by_operation(data)
    print(f"\n{'Operation':<10} {'Count':<8} {'Baseline (μs)':<15} {'PyAOT (μs)':<15} {'Overhead':<12}")
    print("-" * 60)

    for op, stats in op_data.items():
        print(f"{op:<10} {stats['count']:<8} {stats['baseline_avg_us']:<15.1f} "
              f"{stats['pyaot_avg_us']:<15.1f} {stats['overhead_pct']:+.1f}%")

    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)

    baseline = np.array(data["baseline_ns"])
    pyaot = np.array(data["pyaot_ns"])
    overhead = ((np.mean(pyaot) - np.mean(baseline)) / np.mean(baseline)) * 100

    print(f"\nTotal requests: {N}")
    print(f"Compiled traces: {data['compiled_traces']}")
    print(f"\nAverage latency:")
    print(f"  Baseline: {np.mean(baseline)/1000:.1f} μs")
    print(f"  PyAOT:    {np.mean(pyaot)/1000:.1f} μs")
    print(f"  Overhead: {overhead:+.1f}%")

    print(f"\nDatabase operations (SQLite) dominate latency.")
    print(f"PyAOT tracing overhead: {(np.mean(pyaot) - np.mean(baseline))/1000:.1f} μs per request")

    if data["compiled_traces"] == 0:
        print("\n⚠️  No traces compiled - TraceCompiler returns placeholder")

    generate_graph(data, "benchmarks/web/realistic_crud_benchmark.png")

    # Table for BENCHMARKS.md
    print("\n" + "=" * 70)
    print("TABLE FOR BENCHMARKS.md")
    print("=" * 70)
    print("\n| Operation | Baseline | PyAOT Web | Overhead |")
    print("|-----------|----------|-----------|----------|")
    for op, stats in op_data.items():
        print(f"| {op} | {stats['baseline_avg_us']:.1f}μs | "
              f"{stats['pyaot_avg_us']:.1f}μs | {stats['overhead_pct']:+.1f}% |")


if __name__ == "__main__":
    main()
