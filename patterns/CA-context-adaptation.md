# CA — Context Adaptation Bugs (CtxBugs)

Context Adaptation Bug: an LLM generates code that is internally correct but fails at
the boundary between files. The unit of LLM generation is one file; the unit of failure
is the relationship between files. Academically termed "CtxBugs" in arXiv:2601.06497
("Coding in a Bubble? LLMs Miss Cross-File Context").

Each file looks right. The system is broken between them.

---

## CA1 — Topic / Channel Wildcard Depth Mismatch

**Mechanism:** A publisher emits on topic `sensor/+/data` (single-level wildcard matches
`sensor/device/data`). A subscriber registers on `sensor/device/type/data` (three
segments). The MQTT specification requires wildcard depth to match the segment count.
The LLM generates publisher and subscriber in separate files; each looks correct locally.

**Symptom:** Messages are published (visible in broker logs), but the subscriber receives
nothing. No error on either side.

**Concrete instance (anonymized):**
```python
# BAD — publisher and subscriber in separate files, topic depth mismatch

# file: telemetry_publisher.py
client.publish("sensor/+/data", payload=json.dumps(reading))

# file: telemetry_subscriber.py
client.subscribe("sensor/device/temperature/data")  # 4 segments, + only matches 1
```

```python
# GOOD — agree on a concrete topic string or wildcard that covers both
# publisher: "sensor/device/data"
# subscriber: "sensor/+/data"     ← wildcard matches exactly one segment
```

**Detection:**
```bash
# Find publish and subscribe call sites, compare topic strings
grep -rn "\.publish(\|mqtt.publish\|client.send(" . --include="*.py" --include="*.ts"
grep -rn "\.subscribe(\|client.subscribe\|on_message\|addEventListener" . --include="*.py" --include="*.ts"
# Cross-check: count '/' segments in published vs subscribed topic strings
```

**Fix rule:** Define all topic strings as constants in a shared module (`topics.py`,
`topics.ts`). Publisher and subscriber import from the same constant — they cannot drift.
Add a test that asserts the published topic matches the subscribed pattern.

---

## CA2 — Field Name Drift Across Serialization Boundary

**Mechanism:** A trainer or producer names an output field `threat_score`. An inference
consumer reads `score`. The rename happens in the definition file; string-based accesses
in other files are not updated. LLMs generate each file independently — the rename is
correct in the file where it was made, invisible to the file that reads it.

**Symptom:** The consumer silently receives `None` / `undefined` / key-not-found and
continues with a wrong value. No deserialization error.

**Concrete instance (anonymized):**
```python
# BAD — field renamed in producer, not updated in consumer

# file: model_trainer.py  (after renaming)
output = {"threat_score": float(logit), "confidence": float(conf)}

# file: inference_runner.py  (stale)
score = result.get("score")   # ← was "score", producer now uses "threat_score"
if score is None:              # silently falls through with wrong value
    score = 0.0
```

```python
# GOOD — define field name as a shared constant
# file: schema.py
THREAT_SCORE_FIELD = "threat_score"

# producer and consumer both import THREAT_SCORE_FIELD
```

**Detection:**
```bash
# Find field name definitions in producer models / serializers
grep -rn '"threat_score"\|"score"\|output_names\s*=' . --include="*.py"
# Find consumer dict accesses
grep -rn '\.get("score"\|\.get("threat_score"\|\["score"\]\|\["threat_score"\]' . --include="*.py"
# Any field that appears in one but not the other is a drift candidate
```

**Fix rule:** Extract all cross-boundary field names to a schema module. Never use raw
string literals for serialized field names in more than one file.

---

## CA3 — Class-Without-Caller (Silent Feature Absence)

**Mechanism:** A class is implemented with action methods (`record()`, `push()`,
`train()`, `sync()`). The class is never instantiated in production code — only in
tests. The feature is effectively absent. LLMs frequently generate the class when asked
to "add feature X" without wiring the instantiation into the startup or call path.

**Symptom:** The feature appears complete (class exists, method exists, tests pass).
In production, nothing ever happens.

**Concrete instance (anonymized):**
```python
# BAD — MetricsRecorder defined and tested, never wired into the application

# file: metrics.py
class MetricsRecorder:
    def record(self, event: str, value: float): ...

# file: app.py  — MetricsRecorder never imported or instantiated
# file: tests/test_metrics.py  — tests pass; production never calls record()
```

```python
# GOOD — wire into startup
# file: app.py
from metrics import MetricsRecorder
recorder = MetricsRecorder(config)
app.state.recorder = recorder  # or inject into the call path
```

**Detection:**
```bash
# Find classes with action-method names
grep -rn "class.*Recorder\|class.*Exporter\|class.*Publisher\|class.*Trainer\|class.*Syncer" . --include="*.py"
# For each: check if the class is instantiated in non-test files
grep -rn "MetricsRecorder(\|DataExporter(\|ModelTrainer(" . --include="*.py" | grep -v test
# Zero results = class-without-caller
```

**Fix rule:** After generating a new class, check that it is instantiated and its
action method is called in at least one non-test file. Add an integration test that
exercises the real production path (not just the class in isolation).

---

## CA4 — Cross-Language Schema Drift (Naming Convention + Type Mismatch)

**Mechanism:** A Python backend serializes a field as `user_id` (snake_case, integer).
A Go or TypeScript consumer deserializes as `userId` (camelCase, string). Each is
idiomatic in its own language. LLMs generate each service separately; neither sees the
other's convention. The mismatch causes a silent wrong value or deserialization failure
only visible in integration.

**Symptom:** A field is present in the payload but `None` / `undefined` / zero in the
consumer. Or a type assertion fails at runtime with no stack trace at the original
serialization site.

**Concrete instance (anonymized):**
```python
# Python backend (producer)
return jsonify({"user_id": int(user.id), "created_at": user.created_at.isoformat()})
```

```typescript
// TypeScript consumer (file generated separately)
interface UserResponse {
  userId: string;      // ← camelCase, string — neither matches
  createdAt: string;
}
const uid = response.userId;  // always undefined; backend sends "user_id"
```

**Detection:**
```bash
# Find field name definitions across languages
grep -rn '"user_id"\|user_id:' . --include="*.py" --include="*.go"
grep -rn '"userId"\|userId:' . --include="*.ts" --include="*.js"
# Any name that appears in one language's serializer but not the other is a drift candidate
```

**Fix rule:** Maintain an API schema file (OpenAPI, Protobuf, or a JSON Schema) as the
single source of truth. Generate client code from the schema. Never handwrite both
producer and consumer field names independently.
