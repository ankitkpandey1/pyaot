use pyo3::prelude::*;
use pyo3::types::{PyDict, PyTuple};
use libloading::{Library, Symbol};
use std::sync::RwLock;

// The C function signature
type EntryPoint = unsafe extern "C" fn(*mut pyo3::ffi::PyObject, *mut pyo3::ffi::PyObject, *mut pyo3::ffi::PyObject) -> *mut pyo3::ffi::PyObject;

struct LoadedRegion {
    _lib: Library, // Keep library alive
    func: Symbol<'static, EntryPoint>,
}

// Global registry: Vector of loaded regions
static REGISTRY: RwLock<Vec<LoadedRegion>> = RwLock::new(Vec::new());

/// Load a compiled region and return a handle (index).
#[pyfunction]
fn load_region(region_id: String, library_path: String) -> PyResult<usize> {
    unsafe {
        let lib = Library::new(&library_path)
            .map_err(|e| pyo3::exceptions::PyOSError::new_err(format!("Failed to load library: {}", e)))?;
            
        // Get symbol and prolong lifetime to static 
        // (Safety: we verify 'lib' stays alive in LoadedRegion)
        let func: Symbol<EntryPoint> = lib.get(b"pyaot_region_entry")
            .map_err(|e| pyo3::exceptions::PyAttributeError::new_err(format!("Symbol not found: {}", e)))?;
        let func: Symbol<'static, EntryPoint> = std::mem::transmute(func);
            
        let mut registry = REGISTRY.write().unwrap();
        let handle = registry.len();
        registry.push(LoadedRegion { _lib: lib, func });
        
        // Also simpler: we ignore region_id for the fast handle approach
        // The wrapper maps region_id -> handle if needed, but wrapper stores handle
        
        Ok(handle)
    }
}

/// Native region runner using fast handle.
#[pyfunction]
#[pyo3(signature = (handle, args, kwargs=None))]
fn run_region(
    py: Python<'_>,
    handle: usize,
    args: &Bound<'_, PyTuple>,
    kwargs: Option<&Bound<'_, PyDict>>,
) -> PyResult<PyObject> {
    
    let registry = REGISTRY.read().unwrap();
    if let Some(region) = registry.get(handle) {
        unsafe {
            // Unpack arguments to raw pointers
            let self_ptr = std::ptr::null_mut(); 
            let args_ptr = args.as_ptr();
            let kwargs_ptr = match kwargs {
                Some(d) => d.as_ptr(),
                None => std::ptr::null_mut(),
            };
            
            // Call the native function directly
            let result_ptr = (region.func)(self_ptr, args_ptr, kwargs_ptr);
            
            if result_ptr.is_null() {
                return Err(PyErr::fetch(py));
            }
            
            // Steal reference (assuming function returns new ref)
            return Ok(PyObject::from_owned_ptr_or_err(py, result_ptr)?);
        }
    }

    Err(pyo3::exceptions::PyRuntimeError::new_err("Invalid region handle"))
}

/// Benchmark helper to measure FFI overhead.
#[pyfunction]
fn benchmark_overhead() -> PyResult<()> {
    Ok(())
}

/// A module for the native extension.
#[pymodule]
fn pyaot_native(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(run_region, m)?)?;
    m.add_function(wrap_pyfunction!(load_region, m)?)?;
    m.add_function(wrap_pyfunction!(benchmark_overhead, m)?)?;
    Ok(())
}
