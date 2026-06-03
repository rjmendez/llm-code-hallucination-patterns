# PB — Parse Boundary Patterns

Parse boundary: input validation is scattered across the call stack or placed after
mutation points. A bad value reaches production state before being rejected.

---

## PB1 — Validation After Mutation

**Mechanism:** A function partially mutates state, then validates, then raises. On
validation failure, the partial mutation has already happened — the database write,
the metric increment, or the queue push is permanent.

**Concrete instance (anonymized):**
```python
# BAD
def record_event(self, event_data: dict):
    self.event_count += 1                    # mutation 1
    self.db.insert("events", event_data)     # mutation 2
    if not event_data.get("source"):         # validation AFTER mutations
        raise ValueError("source required")  # too late: event was already written

# GOOD — validate first, then mutate
def record_event(self, event_data: dict):
    if not event_data.get("source"):
        raise ValueError("source required")  # validate first
    self.event_count += 1
    self.db.insert("events", event_data)
```

---

## PB2 — Pydantic Validation Bypassed via `model.dict()` Round-Trip

**Mechanism:** Pydantic validators run on `__init__` but NOT when constructing from
`.dict()` with `Model(**raw_dict)` if the source dict has extra keys — the extra keys
are silently ignored. A validator that should reject stale fields never fires.

**Concrete instance (anonymized):**
```python
class EventRecord(BaseModel):
    source: str
    severity: float
    @validator("severity")
    def severity_valid(cls, v):
        if not 0.0 <= v <= 1.0:
            raise ValueError("severity must be 0..1")
        return v

# Raw dict from DB has old field "criticality" instead of "severity":
raw = {"source": "sensor_1", "criticality": 0.9}  # "criticality" is old field name
rec = EventRecord(**raw)  # severity defaults to 0.0, validator not triggered for it
# rec.severity == 0.0, silently wrong
```

**Fix rule:** Use Pydantic's `model_validate` (v2) or `parse_obj` (v1) with
`strict=True`. Test round-trips explicitly:
```python
assert EventRecord.model_validate(raw).severity == 0.9
```

---

## PB3 — Optional Field Silently Defaults to None Across a Network Boundary

**Mechanism:** A field is `Optional[str] = None` in the source system but `required`
in the downstream consumer. The field passes type checks but a missing value triggers
a `NullPointerException` or `KeyError` downstream.

**Fix rule:** Validate at the outbound boundary, not the inbound one:
```python
def to_wire(self) -> dict:
    if self.required_field is None:
        raise ValueError("required_field must be set before serialization")
    return {"required_field": self.required_field, ...}
```

---

## PB4 — Float vs String Ambiguity from YAML Parsing

**Mechanism:** YAML parses bare unquoted strings that look like floats as `float`.
A config value `0.5e2` becomes `50.0`, not the string `"0.5e2"`.
Reading the field as a string at runtime raises `AttributeError: 'float' has no attribute 'lower'`.

**Concrete instance (anonymized):**
```yaml
# config.yaml — LLM wrote unquoted version string:
model_version: 1.2e3   # YAML parses as 1200.0, not string "1.2e3"
```

```python
config["model_version"].lower()  # AttributeError: 'float' has no attribute 'lower'
```

**Fix rule:** Always quote version strings, IDs, and any value that could be
misinterpreted as a number:
```yaml
model_version: "1.2e3"   # string
```
