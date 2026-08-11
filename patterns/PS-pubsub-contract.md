# PS — Pub/Sub Contract Patterns

Pub/sub contract failure: publisher and subscriber both exist and compile correctly,
but the message never arrives. The contract break is at the topic/channel/routing layer,
not in the message payload. No exception is raised; the subscriber waits indefinitely
or processes zero messages.

These patterns occur at the boundary between two independently-generated components
that each have a valid-looking implementation but were never verified against each other.

---

## PS1 — MQTT Topic Path Segment Mismatch (Wildcard Fails Extra Segment)

**Mechanism:** MQTT single-level wildcard `+` matches exactly one path segment.
A publisher at `dama/{device_id}/inference/response/{request_id}` (4 segments after `dama/`)
is never matched by a subscriber at `dama/+/inference/response` (3 segments after `dama/`),
because the `{request_id}` segment is additional and unmatched.

LLMs commonly generate the publisher and subscriber independently, each looking locally
correct, without verifying that the wildcard depth matches the published path depth.
The result: zero messages received, zero errors raised, no timeout — the subscriber
just never fires.

**Symptom:** A subsystem that "processes cloud responses" has no observable activity
in logs. All integrations tests pass (they either mock the broker or test both sides
in isolation). Only end-to-end integration reveals the drop.

**Concrete instance (anonymized):**
```python
# Publisher (bridge component) — generated independently:
request_id = payload["request_id"]
topic = f"colony/{device_id}/inference/response/{request_id}"
mqtt_client.publish(topic, json.dumps(result))

# Subscriber (device component) — generated independently:
INFERENCE_TOPIC = "colony/+/inference/response"
mqtt_client.subscribe(INFERENCE_TOPIC)

def on_message(client, userdata, msg):
    if msg.topic.endswith("/inference/response"):
        handle_response(json.loads(msg.payload))
    # Never fires — topic is colony/{id}/inference/response/{req_id}
    # which has one more segment than the wildcard matches
```

**Detection:**
```bash
# Extract all MQTT publish topics in bridge/daemon:
grep -rn 'publish\|f".*topic' tools/ --include="*.rs" --include="*.py" \
  | grep -oP '"[^"]*"' | sort -u

# Extract all MQTT subscribe topics in client:
grep -rn 'subscribe\|TOPIC_' android/ --include="*.java" --include="*.kt" \
  | grep -oP '"[^"]*"' | sort -u

# Cross-reference: for each subscribe wildcard, does any publish topic match?
# Count '/' characters — subscribe depth must be <= publish depth
```

**Fix rule:**
1. Maintain a single source of truth for topic templates (one file, one constant,
   one schema) shared by or verified against both publisher and subscriber.
2. The `request_id` (or any per-request correlator) belongs in the **message payload**,
   not the topic path. Routing by payload field is far more robust than routing by
   topic wildcard depth.
3. Write an integration test that publishes a message on the real topic string and
   asserts the subscriber's handler was invoked.

**Cross-references:** SD4 (schema drift at serialization boundary), DC1 (distributed consistency)

---

## PS2 — Self-Loop Subscription (Device Is Sole Publisher and Subscriber)

**Mechanism:** A device subscribes to a topic for data it expects from a server-side
aggregator. The LLM also generates a publisher on the same device that publishes to
that same topic. No server-side aggregator is ever built. The result: the device
receives its own messages back, which may look correct in isolation but is a
semantic self-loop — no real data exchange occurs, and the "aggregated" value is
always just the local device's own reading.

**Symptom:** Metrics appear to work in development (one device, one broker —
the device publishes and subscribes and "sees" responses). In a multi-device
fleet, each device only sees its own data — not the fleet-wide aggregation
the UI implies.

**Concrete instance (anonymized):**
```kotlin
// Device code (subscriber) — expects fleet-aggregated peer data:
val PEER_TOPIC = "colony/mesh_peers"
mqtt.subscribe(PEER_TOPIC)   // expects data from server aggregator

fun onMessage(topic: String, payload: ByteArray) {
    if (topic == PEER_TOPIC) showPeerList(decode(payload))
}

// Device code (publisher) — also on the same device:
fun publishSelf() {
    val myData = buildPeerData()
    mqtt.publish("colony/mesh_peers", myData)  // publishes its own data to itself
}
// No server-side aggregator exists in the codebase.
// Single-device: looks correct. Multi-device: each device sees only itself.
```

**Detection:**
```bash
# Find topics that appear in both subscribe and publish calls:
PUB=$(grep -rn 'publish\b' . --include="*.kt" --include="*.java" | grep -oP '"[^"]*"' | sort -u)
SUB=$(grep -rn 'subscribe\b' . --include="*.kt" --include="*.java" | grep -oP '"[^"]*"' | sort -u)
comm -12 <(echo "$PUB") <(echo "$SUB")  # topics in both — check for self-loop

# Also check: search the entire codebase for a server-side subscriber to each publish topic
```

**Fix rule:**
1. For each pub/sub topic, the publisher and subscriber must be in **different components**.
   If both are in the same component, the pattern is almost certainly a self-loop.
2. Before shipping a pub/sub integration, explicitly identify every component that
   publishes to each topic and every component that subscribes — ensure no single
   component is both.
3. In integration tests, run publisher and subscriber as separate processes.

**Cross-references:** DC3 (distributed consistency — stale reads), WG1 (component that
looks integrated but never calls its backend)

---

## PS3 — Preview/Stub State as Live Initial Value for Reactive State Container

**Mechanism:** A reactive state container (`MutableStateFlow`, `LiveData`, `BehaviorSubject`,
Redux store initial state) is seeded with a rich preview/demo object containing plausible
fabricated values. This is correct for UI preview tooling, but when the same object is
used as the *live* initial value in a production class, real users see fabricated data
until the first real update arrives — or permanently if the update never arrives.

LLMs commonly reuse the preview object as the initial value because it is the most
convenient non-null default available in the file. The pattern passes all unit tests
because tests either replace the initial state or don't test what users see on cold launch.

**Symptom:** App opens and immediately shows a busy, populated state (`5 live peers`,
`142 events processed`, `threat detected`) before any real data has arrived. On
connection failure, these fabricated values are shown permanently and are indistinguishable
from real data to the user.

**Concrete instance (anonymized):**
```kotlin
// PREVIEW_STATE has rich fabricated values for UI preview tooling:
val PREVIEW_STATE = AppState(
    liveCount = 5,
    threatLevel = 1,
    peerCount = 4,
    eventsProcessed = 142,
    streak = 5,
)

// BAD — ViewModel seeds live state from preview object:
class AppViewModel : ViewModel() {
    private val _state = MutableStateFlow(PREVIEW_STATE)  // users see fake data
    val state: StateFlow<AppState> = _state.asStateFlow()
}

// GOOD — separate cold-start state with honest zero values:
val COLD_STATE = AppState(
    liveCount = 0,
    threatLevel = 0,
    peerCount = 0,
    eventsProcessed = 0,  // loaded from persistence in ViewModel.init
    streak = 0,
)

class AppViewModel : ViewModel() {
    private val _state = MutableStateFlow(COLD_STATE)
    val state: StateFlow<AppState> = _state.asStateFlow()
}
```

**Detection:**
```bash
# Find MutableStateFlow initializations that reference a PREVIEW or STUB constant:
grep -rn "MutableStateFlow\s*(\s*PREVIEW\|MutableStateFlow\s*(\s*STUB\|MutableStateFlow\s*(\s*DEMO" \
  --include="*.kt" .

# Find LiveData / BehaviorSubject patterns with the same anti-pattern:
grep -rn "MutableLiveData\s*(\s*PREVIEW\|BehaviorSubject\.create\s*\w*PREVIEW" \
  --include="*.kt" --include="*.java" .

# Also check Redux/store patterns in TypeScript:
grep -rn "initialState.*preview\|initialState.*stub\|initialState.*mock" \
  --include="*.ts" --include="*.tsx" .
```

**Fix rule:**
1. Keep the preview object for `@Preview` annotations only. Name it `PREVIEW_*` or `STUB_*`
   and annotate with `@VisibleForTesting` or equivalent.
2. Create a separate `COLD_STATE` / `EMPTY_STATE` with honest zero/null values and use
   ONLY that as the live initial value.
3. Load any persisted values (preferences, local DB) inside `ViewModel.init {}` AFTER
   seeding from `COLD_STATE`, so the first emission to collectors is the real persisted value.
4. Add a UI test that launches the app with an empty datastore and asserts the displayed
   values match `COLD_STATE` (not PREVIEW values).

**Cross-references:** TEC1 (test env contamination from shared state), H4 (None chain —
fabricated value propagates through the system as if real)
