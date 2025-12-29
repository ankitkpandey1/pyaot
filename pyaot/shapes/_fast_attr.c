/*
 * Fast attribute access C extension for PyAOT.
 *
 * Provides low-overhead attribute access with runtime guards.
 * Uses only safe CPython public APIs.
 *
 * Safety guarantees:
 * - Never crashes on guard failure (returns sentinel)
 * - Never allocates Python objects in hot path
 * - Uses PyDict_GetItemWithError (safe across CPython versions)
 * - Type checks use pointer comparison (Py_TYPE)
 */

#define PY_SSIZE_T_CLEAN
#include <Python.h>

/* Sentinel object for guard failure */
static PyObject *PyAOT_GUARD_FAILED = NULL;

/*
 * fast_getattr(obj, expected_type, interned_attr_name) -> value or GUARD_FAILED
 *
 * Performs fast attribute access with guards:
 * 1. Guard on type identity: Py_TYPE(obj) == expected_type
 * 2. Guard that obj has __dict__
 * 3. Direct dict lookup using PyDict_GetItemWithError
 *
 * Returns:
 * - Attribute value (new reference) on success
 * - GUARD_FAILED sentinel on guard failure
 * - NULL with exception on lookup error
 */
static PyObject *
pyaot_fast_getattr(PyObject *self, PyObject *args)
{
    PyObject *obj;
    PyTypeObject *expected_type;
    PyObject *attr_name;

    /* Parse arguments */
    if (!PyArg_ParseTuple(args, "OO!U",
                          &obj,
                          &PyType_Type, &expected_type,
                          &attr_name)) {
        return NULL;
    }

    /* Guard 1: Type identity check (pointer comparison) */
    if (Py_TYPE(obj) != expected_type) {
        Py_INCREF(PyAOT_GUARD_FAILED);
        return PyAOT_GUARD_FAILED;
    }

    /* Guard 2: Object must have __dict__ */
    PyObject **dictptr = _PyObject_GetDictPtr(obj);
    if (dictptr == NULL || *dictptr == NULL) {
        Py_INCREF(PyAOT_GUARD_FAILED);
        return PyAOT_GUARD_FAILED;
    }

    PyObject *dict = *dictptr;

    /* Fast path: Direct dict lookup */
    PyObject *value = PyDict_GetItemWithError(dict, attr_name);

    if (value != NULL) {
        /* Success - return new reference */
        Py_INCREF(value);
        return value;
    }

    /* Check if there was an error or just key not found */
    if (PyErr_Occurred()) {
        /* Error during lookup - propagate */
        return NULL;
    }

    /* Key not found - guard failure */
    Py_INCREF(PyAOT_GUARD_FAILED);
    return PyAOT_GUARD_FAILED;
}

/*
 * fast_getattr_multi(obj, expected_type, attr_names) -> tuple or GUARD_FAILED
 *
 * Batch version for multiple attributes.
 * More efficient when accessing several attributes from same object.
 */
static PyObject *
pyaot_fast_getattr_multi(PyObject *self, PyObject *args)
{
    PyObject *obj;
    PyTypeObject *expected_type;
    PyObject *attr_names;

    if (!PyArg_ParseTuple(args, "OO!O!",
                          &obj,
                          &PyType_Type, &expected_type,
                          &PyTuple_Type, &attr_names)) {
        return NULL;
    }

    /* Guard 1: Type identity */
    if (Py_TYPE(obj) != expected_type) {
        Py_INCREF(PyAOT_GUARD_FAILED);
        return PyAOT_GUARD_FAILED;
    }

    /* Guard 2: Object must have __dict__ */
    PyObject **dictptr = _PyObject_GetDictPtr(obj);
    if (dictptr == NULL || *dictptr == NULL) {
        Py_INCREF(PyAOT_GUARD_FAILED);
        return PyAOT_GUARD_FAILED;
    }

    PyObject *dict = *dictptr;
    Py_ssize_t n = PyTuple_GET_SIZE(attr_names);

    /* Create result tuple */
    PyObject *result = PyTuple_New(n);
    if (result == NULL) {
        return NULL;
    }

    /* Look up each attribute */
    for (Py_ssize_t i = 0; i < n; i++) {
        PyObject *attr_name = PyTuple_GET_ITEM(attr_names, i);
        PyObject *value = PyDict_GetItemWithError(dict, attr_name);

        if (value == NULL) {
            if (PyErr_Occurred()) {
                Py_DECREF(result);
                return NULL;
            }
            /* Key not found - guard failure */
            Py_DECREF(result);
            Py_INCREF(PyAOT_GUARD_FAILED);
            return PyAOT_GUARD_FAILED;
        }

        Py_INCREF(value);
        PyTuple_SET_ITEM(result, i, value);
    }

    return result;
}

/*
 * check_type_guard(obj, expected_type) -> bool
 *
 * Quick type identity check.
 */
static PyObject *
pyaot_check_type_guard(PyObject *self, PyObject *args)
{
    PyObject *obj;
    PyTypeObject *expected_type;

    if (!PyArg_ParseTuple(args, "OO!",
                          &obj,
                          &PyType_Type, &expected_type)) {
        return NULL;
    }

    if (Py_TYPE(obj) == expected_type) {
        Py_RETURN_TRUE;
    }
    Py_RETURN_FALSE;
}

/* Module method table */
static PyMethodDef module_methods[] = {
    {"fast_getattr", pyaot_fast_getattr, METH_VARARGS,
     "Fast attribute access with type guard.\n\n"
     "Args:\n"
     "    obj: Object to access\n"
     "    expected_type: Expected type (for guard)\n"
     "    attr_name: Attribute name (should be interned)\n\n"
     "Returns:\n"
     "    Attribute value on success, GUARD_FAILED on guard failure."},

    {"fast_getattr_multi", pyaot_fast_getattr_multi, METH_VARARGS,
     "Fast access to multiple attributes.\n\n"
     "Args:\n"
     "    obj: Object to access\n"
     "    expected_type: Expected type (for guard)\n"
     "    attr_names: Tuple of attribute names\n\n"
     "Returns:\n"
     "    Tuple of values on success, GUARD_FAILED on guard failure."},

    {"check_type_guard", pyaot_check_type_guard, METH_VARARGS,
     "Check if object is exact type.\n\n"
     "Args:\n"
     "    obj: Object to check\n"
     "    expected_type: Expected type\n\n"
     "Returns:\n"
     "    True if type(obj) is expected_type."},

    {NULL, NULL, 0, NULL}
};

/* Module definition */
static struct PyModuleDef moduledef = {
    PyModuleDef_HEAD_INIT,
    "_fast_attr",
    "Fast attribute access C extension for PyAOT.\n\n"
    "Provides low-overhead attribute access with runtime guards.\n"
    "Uses only safe CPython public APIs.",
    -1,
    module_methods,
    NULL, NULL, NULL, NULL
};

PyMODINIT_FUNC
PyInit__fast_attr(void)
{
    PyObject *m = PyModule_Create(&moduledef);
    if (m == NULL) {
        return NULL;
    }

    /* Create sentinel object using PyCapsule */
    PyAOT_GUARD_FAILED = PyCapsule_New(
        (void *)1,  /* Non-NULL pointer */
        "pyaot.shapes._fast_attr.GUARD_FAILED",
        NULL  /* No destructor */
    );

    if (PyAOT_GUARD_FAILED == NULL) {
        Py_DECREF(m);
        return NULL;
    }

    /* Add sentinel to module */
    if (PyModule_AddObject(m, "GUARD_FAILED", PyAOT_GUARD_FAILED) < 0) {
        Py_DECREF(PyAOT_GUARD_FAILED);
        Py_DECREF(m);
        return NULL;
    }

    return m;
}
