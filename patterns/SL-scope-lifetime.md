# SL — Scope / Lifetime Patterns

Scope/lifetime: a resource (variable, mock, context manager) is alive at definition
but dead at the point of use — or vice versa.

---

## SL1 — UnboundLocalError from Conditional Variable Definition

**Mechanism:** A variable defined only inside `if condition:` is referenced after the
block. Python raises `UnboundLocalError` at RUNTIME (not parse time) only when
`condition` is False.

**Concrete instance (anonymized):**
```python
# BAD
def handle_request(request, use_cache=False):
    if use_cache:
        cache_key = build_cache_key(request)   # only defined when use_cache=True
        cached = cache.get(cache_key)
        if cached:
            return cached

    result = expensive_compute(request)
    cache.set(cache_key, result)   # UnboundLocalError when use_cache=False
    return result

# GOOD — hoist with safe default
def handle_request(request, use_cache=False):
    cache_key = build_cache_key(request) if use_cache else None
    if use_cache and cache_key:
        cached = cache.get(cache_key)
        if cached:
            return cached
    result = expensive_compute(request)
    if cache_key:
        cache.set(cache_key, result)
    return result
```

---

## SL2 — pytest Fixture `return` Inside `with mock.patch()` Tears Down Mock Early

**Mechanism:** `return obj` inside `with mock.patch(...)` exits the context manager
immediately. The object is returned but the patch is already gone. Subsequent test
calls hit the real backend.

**Symptom:** "initialized OK" in setup log, then connection/auth failure on first
test call body.

**Concrete instance (anonymized):**
```python
# BAD — mock exits at return, test hits real database
@pytest.fixture
def db_client():
    with mock.patch("myapp.database.psycopg2.connect") as mock_conn:
        mock_conn.return_value.cursor.return_value = MagicMock()
        client = DatabaseClient(dsn="postgresql://test:test@localhost/test")
        return client   # ← mock context exits HERE; next line is already real

# GOOD — yield keeps mock alive through the test body
@pytest.fixture
def db_client():
    with mock.patch("myapp.database.psycopg2.connect") as mock_conn:
        mock_conn.return_value.cursor.return_value = MagicMock()
        client = DatabaseClient(dsn="postgresql://test:test@localhost/test")
        yield client   # ← mock stays active until test completes
```

**Detection:**
```bash
# Find fixtures that use return inside with-blocks
grep -A20 "@pytest.fixture" --include="test_*.py" -rn . \
  | grep -B5 "return " | grep "with mock\|with patch"
```
