# Done — Execution Plan

> **Product:** Voice-first, self-healing commerce agent for iPhone  
> **Mobile:** React Native + Expo  
> **Backend:** FastAPI  
> **Agent orchestration:** LangGraph  
> **Primary interaction:** Voice  
> **Core promise:** “Say it once. Consider it done.”

---

## 1. Product vision

Done is a voice-first mobile agent that turns a spoken user intention into a completed commerce mission.

The user does not:

- write prompts,
- fill forms,
- compare products manually,
- supervise every step,
- recover failed payments,
- handle inventory or delivery problems.

The user speaks one sentence, closes the app, and returns only when:

- the mission is completed,
- a genuinely human decision is required,
- a hard constraint cannot be satisfied,
- a high-risk action requires approval.

### Example

> “Tomorrow I’m organizing a birthday party for ten children. Buy food, drinks and decorations for under 300 PLN, no nuts, delivered before 16:00.”

Done must:

1. transcribe the voice command,
2. extract the mission,
3. infer missing task components,
4. convert the request into a formal mission contract,
5. find candidate products,
6. build and optimize a basket,
7. validate hard constraints,
8. request approval only when needed,
9. execute the order,
10. recover from inventory, delivery or payment failures,
11. report the final outcome.

---

# 2. Hackathon success criteria

The demo is successful only if it shows an end-to-end mission.

## Minimum demo path

1. User opens the app.
2. User holds the microphone button and speaks.
3. The transcript is displayed.
4. Done confirms the interpreted mission.
5. The mobile app shows mission progress.
6. The backend invokes multiple agent tools.
7. Done builds a basket.
8. The user approves the purchase.
9. A simulated failure occurs.
10. Done repairs the plan.
11. The mission is marked as completed.
12. The app displays a transparent execution summary.

## Killer feature

**Self-healing missions**

The system must recover from at least two of the following:

- product out of stock,
- product price changed,
- delivery slot unavailable,
- payment soft decline,
- merchant unavailable,
- hard constraint violated by a replacement,
- total basket exceeds budget.

## Demo target

The judges must see:

```text
Voice command
    ↓
Mission created
    ↓
Agent planning
    ↓
Purchase plan
    ↓
Failure injected
    ↓
Automatic recovery
    ↓
Mission completed
```

---

# 3. Scope

## 3.1 MVP scope

The hackathon MVP supports:

- voice mission creation,
- one commerce domain: party/grocery shopping,
- synthetic product catalog,
- synthetic merchants,
- mission contract generation,
- product search,
- basket optimization,
- delivery selection,
- approval flow,
- payment simulation,
- failure injection,
- self-healing recovery,
- mission timeline,
- completed mission summary,
- push-style local notifications,
- mobile dark theme.

## 3.2 Post-MVP scope

Not required for the first version:

- real retailer integrations,
- real payments,
- Apple Pay execution,
- production identity verification,
- background execution for hours,
- household sharing,
- real recurring purchases,
- real order tracking,
- App Store release,
- production-grade PCI compliance,
- direct Siri integration,
- real Dynamic Island production integration.

## 3.3 Explicit non-goals

Do not build:

- a general-purpose chatbot,
- a large marketplace,
- a social network,
- a full recommendation engine,
- a complicated CRM,
- a large RAG platform,
- a Neo4j knowledge graph,
- a fully autonomous real payment system,
- dozens of agent roles,
- an over-engineered microservice architecture.

---

# 4. Target architecture

```text
┌──────────────────────────────────────────────────────────────┐
│                      Expo mobile app                         │
│                                                              │
│  Voice capture     Mission UI       Approval UI              │
│  Active missions   Completed        Settings                 │
│                                                              │
└──────────────────────────────┬───────────────────────────────┘
                               │ HTTPS / WebSocket / SSE
                               ▼
┌──────────────────────────────────────────────────────────────┐
│                         FastAPI API                          │
│                                                              │
│  Auth / session     Mission API       Event streaming        │
│  Catalog API        Approval API      Failure injection      │
│                                                              │
└──────────────────────────────┬───────────────────────────────┘
                               │
                               ▼
┌──────────────────────────────────────────────────────────────┐
│                       LangGraph runtime                       │
│                                                              │
│ Intent → Contract → Plan → Search → Optimize → Validate      │
│        → Approval → Execute → Recover → Complete             │
│                                                              │
└───────────────┬─────────────────────┬────────────────────────┘
                │                     │
                ▼                     ▼
┌─────────────────────────┐  ┌───────────────────────────────┐
│ Commerce tools          │  │ Control and evaluation        │
│                         │  │                               │
│ catalog_search          │  │ deterministic policies        │
│ product_details         │  │ LLM judge                    │
│ reserve_inventory       │  │ tracing                      │
│ calculate_delivery      │  │ metrics                      │
│ create_basket           │  │ event log                    │
│ authorize_payment       │  │ eval datasets                │
│ retry_payment           │  │                               │
│ replace_product         │  │                               │
└─────────────────────────┘  └───────────────────────────────┘
```

---

# 5. Technology decisions

## 5.1 Mobile

- React Native
- Expo
- TypeScript
- Expo Router
- Zustand
- TanStack Query
- React Hook Form only where unavoidable
- Expo AV or current Expo audio module
- Expo Notifications
- Expo Secure Store
- Reanimated
- NativeWind or StyleSheet-based design tokens
- EAS development build if native capabilities are required

## 5.2 Backend

- Python 3.13
- FastAPI
- Pydantic v2
- SQLAlchemy 2.x
- Alembic
- PostgreSQL
- Redis optional
- Uvicorn
- httpx
- structlog
- OpenTelemetry
- Langfuse
- pytest
- Ruff
- ty or mypy

## 5.3 Agent layer

- LangGraph
- OpenAI Responses API
- structured outputs
- tool calling
- checkpointing
- deterministic state transitions
- retry policies
- explicit interrupt/resume for approval

## 5.4 Local infrastructure

- Docker Compose
- PostgreSQL
- Redis optional
- backend container
- seed script
- mock merchant service optional

---

# 6. Repository structure

```text
done/
├── README.md
├── execution_plan.md
├── docker-compose.yml
├── .env.example
├── Makefile
├── docs/
│   ├── architecture.md
│   ├── demo-script.md
│   ├── api-contract.md
│   ├── agent-graph.md
│   ├── design-system.md
│   └── threat-model.md
│
├── apps/
│   ├── mobile/
│   │   ├── app/
│   │   │   ├── _layout.tsx
│   │   │   ├── index.tsx
│   │   │   ├── missions.tsx
│   │   │   ├── completed.tsx
│   │   │   ├── settings.tsx
│   │   │   ├── profile.tsx
│   │   │   └── mission/
│   │   │       └── [id].tsx
│   │   ├── components/
│   │   ├── features/
│   │   │   ├── voice/
│   │   │   ├── missions/
│   │   │   ├── approvals/
│   │   │   └── completed/
│   │   ├── hooks/
│   │   ├── services/
│   │   ├── stores/
│   │   ├── theme/
│   │   ├── types/
│   │   ├── assets/
│   │   └── package.json
│   │
│   └── api/
│       ├── app/
│       │   ├── main.py
│       │   ├── api/
│       │   │   ├── routes/
│       │   │   └── deps.py
│       │   ├── agents/
│       │   │   ├── graph.py
│       │   │   ├── state.py
│       │   │   ├── nodes/
│       │   │   ├── tools/
│       │   │   ├── prompts/
│       │   │   └── policies/
│       │   ├── core/
│       │   ├── db/
│       │   ├── models/
│       │   ├── schemas/
│       │   ├── services/
│       │   ├── repositories/
│       │   ├── telemetry/
│       │   └── tests/
│       ├── alembic/
│       ├── pyproject.toml
│       └── Dockerfile
│
├── packages/
│   ├── api-client/
│   ├── shared-types/
│   └── design-tokens/
│
├── data/
│   ├── products.json
│   ├── merchants.json
│   ├── delivery_options.json
│   ├── transactions.json
│   └── demo_scenarios.json
│
└── scripts/
    ├── seed.py
    ├── reset_demo.py
    ├── inject_failure.py
    └── run_evals.py
```

---

# 7. Product model

## 7.1 Core entities

### User

```text
id
name
locale
currency
timezone
default_budget_policy
autonomy_level
created_at
```

### Mission

```text
id
user_id
title
raw_voice_transcript
status
current_step
mission_type
budget_limit
currency
deadline
risk_level
requires_approval
created_at
updated_at
completed_at
```

### Mission contract

```text
id
mission_id
goal
participants
hard_constraints
soft_preferences
budget
deadline
approval_policy
allowed_categories
forbidden_categories
confidence
version
```

### Mission event

```text
id
mission_id
event_type
actor
title
description
payload
created_at
```

### Product

```text
id
merchant_id
sku
name
description
category
price
currency
stock
allergens
tags
rating
delivery_class
image_url
```

### Merchant

```text
id
name
reliability_score
return_policy_score
payment_success_rate
delivery_success_rate
active
```

### Basket

```text
id
mission_id
merchant_id
subtotal
delivery_cost
total
currency
status
```

### Basket item

```text
id
basket_id
product_id
quantity
unit_price
substitution_allowed
```

### Approval request

```text
id
mission_id
approval_type
question
options
status
selected_option
expires_at
created_at
resolved_at
```

### Payment attempt

```text
id
mission_id
merchant_id
amount
provider
status
decline_code
retry_number
created_at
```

---

# 8. Mission state machine

## 8.1 Mission statuses

```text
created
transcribing
understanding
clarification_required
planning
searching
optimizing
validating
approval_required
executing
recovering
completed
failed
cancelled
```

## 8.2 Allowed transitions

```text
created → transcribing
transcribing → understanding
understanding → clarification_required
understanding → planning
clarification_required → understanding
planning → searching
searching → optimizing
optimizing → validating
validating → approval_required
validating → executing
approval_required → executing
approval_required → cancelled
executing → recovering
executing → completed
recovering → validating
recovering → executing
recovering → failed
```

## 8.3 State transition rules

- Every transition must generate a mission event.
- The mobile application must render state from backend data.
- The mobile application must never invent workflow state.
- Approval must pause the graph.
- Recovery must preserve the original mission contract.
- Hard constraints cannot be relaxed without explicit user approval.
- Soft preferences can be relaxed when required.
- Every automatic relaxation must be logged.

---

# 9. LangGraph design

## 9.1 State schema

```python
class MissionState(TypedDict):
    mission_id: str
    user_id: str
    transcript: str
    contract: dict | None
    clarification_question: str | None
    plan: dict | None
    candidates: list[dict]
    baskets: list[dict]
    selected_basket: dict | None
    policy_result: dict | None
    approval_request: dict | None
    execution_result: dict | None
    failure: dict | None
    recovery_attempts: int
    events: list[dict]
```

## 9.2 Graph nodes

### 1. `parse_voice_intent`

Responsibilities:

- clean transcript,
- identify action,
- identify domain,
- detect entities,
- infer title,
- detect ambiguity.

Output:

```json
{
  "goal": "prepare_birthday_party",
  "confidence": 0.93,
  "missing_information": []
}
```

### 2. `build_mission_contract`

Responsibilities:

- convert free-form intent into structured contract,
- distinguish hard constraints from soft preferences,
- assign budget,
- assign deadline,
- define approval rules,
- define acceptable substitutions.

### 3. `decide_clarification`

Rules:

Ask only when:

- a missing value blocks execution,
- two interpretations materially differ,
- a legal or financial approval is required,
- deadline cannot be interpreted,
- budget is absent and cannot be inferred.

Do not ask when:

- a reasonable default can be applied,
- the decision can be deferred,
- the choice has low impact,
- historical preference can resolve the ambiguity.

### 4. `create_plan`

Responsibilities:

- decompose mission into tasks,
- identify product categories,
- estimate quantities,
- identify merchant/tool requirements,
- decide parallel searches.

### 5. `search_catalog`

Responsibilities:

- call product search tools,
- retrieve candidates,
- normalize products,
- filter obvious hard-constraint violations.

### 6. `optimize_basket`

Objective:

```text
maximize:
  constraint satisfaction
  preference match
  delivery confidence
  merchant reliability
  payment success probability

minimize:
  total cost
  number of deliveries
  risk
  unsupported assumptions
```

Possible scoring:

```text
score =
  0.30 * constraint_score
+ 0.20 * delivery_score
+ 0.15 * preference_score
+ 0.15 * merchant_score
+ 0.10 * payment_score
- 0.10 * normalized_cost
```

### 7. `validate_policy`

Must combine:

- deterministic policy checks,
- contract validation,
- budget validation,
- allergen validation,
- delivery validation,
- duplicate purchase validation,
- risk scoring,
- optional LLM judge.

### 8. `request_approval`

Creates an interrupt.

Example:

```json
{
  "type": "purchase_approval",
  "question": "Approve purchase for 287 PLN?",
  "options": [
    {"id": "approve", "label": "Approve"},
    {"id": "review", "label": "Review"},
    {"id": "cancel", "label": "Cancel"}
  ]
}
```

### 9. `execute_purchase`

Responsibilities:

- reserve inventory,
- create basket,
- create order,
- authorize payment,
- confirm order.

### 10. `classify_failure`

Failure types:

```text
inventory_failure
price_change
delivery_failure
payment_soft_decline
payment_hard_decline
merchant_failure
policy_violation
unknown_failure
```

### 11. `repair_plan`

Recovery strategies:

- replace product,
- switch merchant,
- split basket,
- switch delivery option,
- retry payment,
- route payment differently,
- request approval,
- reduce optional items,
- preserve all hard constraints.

### 12. `complete_mission`

Responsibilities:

- create summary,
- calculate business metrics,
- mark completed,
- emit completion event,
- generate user-facing voice response.

---

# 10. Agent tools

## 10.1 Catalog tools

### `search_products`

Input:

```json
{
  "query": "nut-free birthday snacks",
  "category": "snacks",
  "max_price": 50,
  "merchant_ids": []
}
```

Output:

```json
{
  "items": [],
  "total": 0
}
```

### `get_product_details`

Returns:

- price,
- allergens,
- inventory,
- merchant,
- delivery eligibility,
- substitutions.

### `find_substitutes`

Must enforce:

- same category,
- contract compatibility,
- budget tolerance,
- allergy compliance.

## 10.2 Merchant tools

### `get_merchants`

### `get_merchant_reliability`

### `check_inventory`

### `reserve_inventory`

## 10.3 Basket tools

### `create_basket`

### `add_item`

### `remove_item`

### `recalculate_basket`

### `split_basket`

## 10.4 Delivery tools

### `get_delivery_options`

### `select_delivery_option`

### `check_deadline_feasibility`

## 10.5 Payment tools

### `authorize_payment`

### `retry_payment`

### `route_payment`

### `classify_decline`

## 10.6 Mission control tools

### `request_user_approval`

### `emit_mission_event`

### `mark_mission_complete`

### `inject_demo_failure`

---

# 11. Deterministic policy engine

The LLM must not be the only safety mechanism.

## 11.1 Required checks

- basket total <= budget,
- every allergen rule satisfied,
- delivery ETA <= deadline,
- prohibited categories absent,
- approval threshold respected,
- maximum retry count respected,
- no duplicate payment,
- no product substitution outside policy,
- no hard constraint modified implicitly.

## 11.2 Policy result

```json
{
  "approved": false,
  "violations": [
    {
      "code": "BUDGET_EXCEEDED",
      "severity": "hard",
      "message": "Basket exceeds budget by 18 PLN."
    }
  ],
  "approval_required": true,
  "repairable": true
}
```

## 11.3 Risk score

```text
0–20     execute automatically
21–45    execute and inform
46–70    request approval
71–100   block
```

Example factors:

```text
known merchant                   -10
known product                    -10
within historical price range   -10
new merchant                     +20
high basket value                +25
deadline uncertainty             +15
policy conflict                  +30
payment retry                    +10
```

---

# 12. LLM judge

The LLM judge is secondary to deterministic checks.

## Inputs

- original transcript,
- mission contract,
- selected basket,
- rejected alternatives,
- deterministic validation result.

## Output

```json
{
  "intent_fidelity": 0.96,
  "constraint_coverage": 1.0,
  "unsupported_assumptions": [],
  "risk": "low",
  "recommendation": "approve"
}
```

## Judge responsibilities

- detect mismatch between request and basket,
- detect omitted mission components,
- detect unsupported assumptions,
- identify when user approval is appropriate,
- provide explanation.

## Judge limitations

The judge cannot:

- authorize payment,
- override deterministic hard constraints,
- change budget,
- change deadline,
- approve an allergen violation.

---

# 13. Mobile application

## 13.1 Navigation

Bottom navigation on every primary screen:

```text
Now
Missions
Completed
Settings
Profile
```

## 13.2 Screens

### Screen 1: Now

Elements:

- greeting,
- profile avatar,
- primary microphone control,
- short prompt,
- active mission previews,
- completed-today preview,
- bottom navigation.

Actions:

- hold to speak,
- tap mission,
- open active missions,
- open completed missions.

### Screen 2: Active Missions

Elements:

- active mission list,
- expanded current mission,
- mission steps,
- progress,
- latest agent update,
- statuses,
- voice shortcut,
- bottom navigation.

### Screen 3: Completed Today

Elements:

- completed count,
- completed mission cards,
- result details,
- money saved,
- recovered failures,
- bottom navigation.

### Screen 4: Mission Details

Elements:

- mission title,
- mission status,
- progress timeline,
- mission contract summary,
- current work,
- decision cards,
- delivery options,
- basket,
- event timeline,
- voice correction button,
- bottom navigation.

### Screen 5: Settings

Sections:

- voice and language,
- autonomy,
- approval thresholds,
- budgets,
- merchants,
- notifications,
- privacy,
- profile.

## 13.3 Voice flow

### Start recording

- long press microphone,
- haptic feedback,
- waveform animation,
- microphone permission check,
- start audio recording.

### Stop recording

- release button,
- upload audio,
- show “Understanding…”,
- display transcript,
- allow immediate cancellation.

### Confirmation

Spoken response:

> “Ten children, maximum 300 PLN, no nuts, delivery before 16:00. I’ll take care of it.”

### Correction

User can say:

> “Increase the budget to 350 PLN but do not buy plastic decorations.”

The backend creates a new mission contract version.

---

# 14. Mobile state management

## Zustand stores

### `useSessionStore`

```text
user
accessToken
locale
currency
```

### `useVoiceStore`

```text
isRecording
recordingDuration
audioUri
transcript
uploadStatus
```

### `useMissionStore`

```text
missions
activeMissionId
missionEvents
approvalRequests
```

## TanStack Query

Use for:

- mission list,
- mission details,
- completed missions,
- settings,
- product review.

## Real-time updates

Preferred:

- WebSocket for mission events.

Fallback:

- SSE.
- Poll every 2 seconds in hackathon mode.

---

# 15. API design

## Missions

### `POST /v1/missions/voice`

Multipart input:

```text
audio
locale
timezone
```

Response:

```json
{
  "mission_id": "uuid",
  "status": "understanding"
}
```

### `POST /v1/missions/text`

For debugging only.

### `GET /v1/missions`

Filters:

```text
status
created_from
created_to
```

### `GET /v1/missions/{mission_id}`

Returns:

- mission,
- contract,
- progress,
- selected basket,
- approvals,
- recent events.

### `POST /v1/missions/{mission_id}/cancel`

### `POST /v1/missions/{mission_id}/voice-update`

### `GET /v1/missions/{mission_id}/events`

### `GET /v1/missions/{mission_id}/stream`

## Approvals

### `POST /v1/approvals/{approval_id}/resolve`

```json
{
  "choice": "approve",
  "voice_transcript": null
}
```

## Demo

### `POST /v1/demo/reset`

### `POST /v1/demo/failures`

```json
{
  "mission_id": "uuid",
  "failure_type": "payment_soft_decline"
}
```

---

# 16. Event model

## Event types

```text
mission.created
voice.transcribed
intent.parsed
contract.created
clarification.requested
plan.created
catalog.searched
candidate.rejected
basket.optimized
policy.validated
approval.requested
approval.resolved
inventory.reserved
payment.attempted
payment.declined
recovery.started
product.replaced
merchant.switched
payment.rerouted
mission.completed
mission.failed
```

## User-facing event

```json
{
  "type": "payment.rerouted",
  "title": "Payment recovered",
  "description": "The first provider declined the payment. Done safely used an alternative route.",
  "severity": "info",
  "created_at": "..."
}
```

---

# 17. Failure injection

A hackathon-only control panel must support deterministic failure simulation.

## Supported failures

### Product unavailable

Effect:

- selected product stock becomes zero.

Expected recovery:

- find compliant substitute,
- revalidate allergens,
- recalculate basket.

### Price changed

Effect:

- product price increases.

Expected recovery:

- re-optimize,
- maintain budget,
- request approval if needed.

### Delivery slot lost

Effect:

- selected delivery option unavailable.

Expected recovery:

- choose new slot,
- split basket,
- switch merchant.

### Payment soft decline

Effect:

- first authorization fails.

Expected recovery:

- classify soft decline,
- switch provider,
- retry once.

### Payment hard decline

Expected:

- stop automatic retry,
- ask user for another payment method.

---

# 18. Database schema

## Initial tables

- users
- missions
- mission_contracts
- mission_events
- products
- merchants
- baskets
- basket_items
- delivery_options
- approval_requests
- payment_attempts
- failure_injections

## Indexes

- missions(user_id, status)
- mission_events(mission_id, created_at)
- products(category, merchant_id)
- products(stock)
- approval_requests(mission_id, status)
- payment_attempts(mission_id, created_at)

---

# 19. Seed data

## Products

Create 150–300 products.

Categories:

- snacks,
- drinks,
- cake,
- decorations,
- tableware,
- candles,
- napkins,
- party bags.

Product fields:

- ingredients,
- allergens,
- nut_free,
- price,
- inventory,
- merchant,
- delivery class,
- substitute group.

## Merchants

Create 3 merchants:

### Merchant A

- cheapest,
- lower delivery reliability,
- higher payment decline rate.

### Merchant B

- balanced,
- good delivery,
- medium price.

### Merchant C

- premium,
- most reliable,
- fastest delivery.

## Payment providers

- PSP_A
- PSP_B
- PSP_C

Each with:

- success probability,
- latency,
- processing cost,
- supported merchants.

---

# 20. Prompt strategy

## System prompt principles

- preserve user intent,
- distinguish hard constraints and preferences,
- minimize interruptions,
- never relax hard constraints silently,
- explain only decisions and actions,
- do not reveal chain-of-thought,
- use tools instead of guessing,
- stop when approval is required,
- prefer safe recovery over mission failure.

## Prompt files

```text
prompts/
├── intent_parser.md
├── contract_builder.md
├── planner.md
├── basket_optimizer.md
├── recovery_agent.md
├── judge.md
└── completion_summary.md
```

## Structured outputs

Every agent node returns Pydantic-validated data.

No free-form parsing between nodes.

---

# 21. Observability

## Langfuse

Track:

- mission trace,
- node execution,
- tool calls,
- model usage,
- latency,
- errors,
- recovery count,
- approval count.

## Structured logs

Required fields:

```text
timestamp
level
mission_id
node
tool
duration_ms
status
error_code
```

## Business metrics

Display in demo:

- mission completion rate,
- constraint satisfaction rate,
- number of recovered failures,
- human interventions,
- final basket cost,
- budget variance,
- delivery confidence,
- payment attempts.

---

# 22. Testing strategy

## 22.1 Unit tests

Backend:

- contract parsing,
- policy checks,
- budget enforcement,
- allergen checks,
- risk scoring,
- recovery selection,
- payment retry rules.

Mobile:

- mission card rendering,
- status mapping,
- approval action,
- voice state transitions,
- navigation.

## 22.2 Integration tests

- create mission from transcript,
- graph reaches approval,
- approval resumes graph,
- payment failure triggers recovery,
- completed mission persists events.

## 22.3 Agent evals

Dataset examples:

```text
birthday party
weekly groceries
gift purchase
refund request
late delivery
```

Metrics:

- contract accuracy,
- hard constraint recall,
- unsupported assumption rate,
- successful basket creation,
- recovery success,
- unnecessary clarification count.

## 22.4 End-to-end test

Scenario:

1. Create birthday mission.
2. Verify mission contract.
3. Verify product search.
4. Verify basket below 300 PLN.
5. Approve.
6. Inject out-of-stock.
7. Verify replacement.
8. Inject payment soft decline.
9. Verify reroute.
10. Verify completed status.

---

# 23. Security and safety

## Required

- no real card data,
- synthetic payment tokens,
- API keys only on backend,
- Secure Store for mobile tokens,
- environment variables,
- input validation,
- rate limiting,
- maximum graph step count,
- maximum retry count,
- tool allowlist,
- audit trail,
- no raw chain-of-thought storage.

## Prompt injection protection

- catalog content is untrusted data,
- product descriptions cannot instruct the model,
- strip or delimit retrieved text,
- tools validate all model inputs,
- policies are enforced outside the LLM.

## Financial safety

- no automatic real purchase,
- all hackathon transactions simulated,
- final purchase approval required,
- payment retry maximum: 1 or 2,
- hard decline cannot be retried automatically.

---

# 24. Design system

## Visual identity

- background: near-black navy,
- primary accent: electric violet,
- secondary accent: blue,
- success: green,
- warning: amber,
- cards: dark translucent surfaces,
- borders: low-opacity violet,
- corners: 20–28 px,
- subtle glow only on primary actions.

## Design tokens

```ts
export const colors = {
  background: "#070914",
  surface: "#0E1120",
  surfaceElevated: "#14182A",
  primary: "#9B5CFF",
  primarySoft: "#6F42C1",
  secondary: "#4B7BFF",
  success: "#48D66A",
  warning: "#FFB84D",
  error: "#FF5D73",
  text: "#F7F7FB",
  textSecondary: "#9FA5B7",
  border: "rgba(155, 92, 255, 0.20)",
};
```

## Component list

- `VoiceOrb`
- `MissionCard`
- `MissionProgress`
- `MissionStep`
- `StatusBadge`
- `ApprovalCard`
- `MetricPill`
- `EventTimeline`
- `BottomNavigation`
- `ScreenHeader`
- `CompletedMissionCard`
- `FailureRecoveryBanner`

---

# 25. Implementation phases

## Phase 0 — repository bootstrap

### Tasks

- create monorepo,
- initialize Expo app,
- initialize FastAPI app,
- configure Docker Compose,
- create `.env.example`,
- configure linting,
- configure formatting,
- configure tests,
- create CI workflow.

### Exit criteria

- mobile starts,
- API starts,
- mobile calls `/health`,
- PostgreSQL connection works.

---

## Phase 1 — static mobile UI

### Tasks

- implement design tokens,
- implement bottom navigation,
- implement Now screen,
- implement Active Missions,
- implement Completed,
- implement Mission Details,
- implement Settings,
- use mocked data.

### Exit criteria

- all main screens exist,
- visual identity is consistent,
- navigation works,
- demo can be presented with static data.

---

## Phase 2 — database and mission API

### Tasks

- create SQLAlchemy models,
- create Alembic migrations,
- create mission CRUD,
- create event API,
- seed products and merchants,
- implement mission list and details.

### Exit criteria

- missions persist,
- events persist,
- mobile displays backend missions.

---

## Phase 3 — voice mission creation

### Tasks

- request microphone permission,
- record audio,
- upload audio,
- transcribe audio,
- create mission,
- show transcript,
- speak confirmation.

### Exit criteria

- user creates mission with voice,
- mission appears in active list.

---

## Phase 4 — LangGraph orchestration

### Tasks

- define state,
- define nodes,
- compile graph,
- implement checkpointing,
- implement mission event emission,
- implement clarification branch,
- implement approval interrupt.

### Exit criteria

- mission moves through workflow,
- backend state matches UI,
- approval pauses execution.

---

## Phase 5 — commerce tools

### Tasks

- catalog search,
- candidate filtering,
- basket optimization,
- delivery selection,
- inventory reservation,
- payment simulation.

### Exit criteria

- mission creates a valid basket,
- basket meets constraints,
- payment simulation completes.

---

## Phase 6 — self-healing recovery

### Tasks

- implement failure classifier,
- implement recovery strategies,
- implement product substitution,
- implement merchant switching,
- implement basket split,
- implement payment rerouting,
- implement maximum retry rules.

### Exit criteria

- two injected failures recover,
- mission still completes,
- recovery actions are visible in UI.

---

## Phase 7 — approvals and mobile real-time updates

### Tasks

- WebSocket/SSE,
- approval card,
- resolve approval,
- resume graph,
- local notification,
- mission progress animation.

### Exit criteria

- approval arrives in app,
- user approves,
- graph resumes,
- UI updates live.

---

## Phase 8 — observability and evals

### Tasks

- Langfuse trace,
- structured logs,
- test scenarios,
- evaluation script,
- business metrics.

### Exit criteria

- every demo mission has a trace,
- eval summary generated,
- recovery count visible.

---

## Phase 9 — demo hardening

### Tasks

- reset script,
- deterministic seed,
- deterministic failure injection,
- fallback text input,
- local mock mode,
- preloaded mission,
- network failure fallback,
- demo narration.

### Exit criteria

- full demo runs repeatedly,
- no external retailer dependency,
- no random outputs block demo.

---

# 26. Hackathon execution schedule

## Hour 0–1

- repository bootstrap,
- design system,
- API skeleton,
- seed data,
- assign owners.

## Hour 1–2

- static mobile screens,
- mission API,
- database models,
- mock catalog.

## Hour 2–3

- voice recording,
- transcription,
- mission creation,
- LangGraph skeleton.

## Hour 3–4

- product search,
- basket optimizer,
- mission progress stream,
- approval interrupt.

## Hour 4–5

- payment simulation,
- failure injection,
- recovery agent,
- completed mission screen.

## Hour 5–6

- integrate mobile and backend,
- fix state issues,
- polish mission timeline,
- observability.

## Hour 6–7

- rehearse demo,
- create fallback scenario,
- record backup video,
- finalize pitch,
- freeze code.

---

# 27. Team responsibilities

## Mobile engineer

Owns:

- Expo,
- navigation,
- voice capture,
- mission screens,
- approval UI,
- real-time updates,
- design consistency.

## Agent engineer

Owns:

- LangGraph,
- prompts,
- structured outputs,
- interrupt/resume,
- recovery logic,
- LLM judge.

## Backend engineer

Owns:

- FastAPI,
- database,
- repositories,
- commerce tools,
- payment simulator,
- failure injection.

## Product/demo owner

Owns:

- seed data,
- user story,
- test scenario,
- UX wording,
- metrics,
- pitch,
- demo rehearsal.

If only three people:

- combine backend and commerce,
- product owner supports mobile,
- agent engineer owns observability.

---

# 28. Definition of done

## Mobile

- voice button works,
- navigation is consistent,
- active mission progress works,
- approval works,
- completed mission summary works.

## Backend

- API documented,
- database migrations work,
- mission events persist,
- real-time updates work,
- demo reset works.

## Agent

- mission contract is structured,
- graph is checkpointed,
- approval interrupt works,
- recovery works,
- hard constraints remain enforced.

## Demo

- one voice command,
- one approval,
- two injected failures,
- one completed mission,
- visible metrics,
- no manual backend intervention.

---

# 29. Demo script

## Opening

> “Shopping agents usually stop when they prepare a basket. Real commerce starts when something goes wrong.”

## User command

> “Tomorrow I’m organizing a birthday party for ten children. Buy food, drinks and decorations for under 300 PLN, no nuts, delivered before 16:00.”

## Expected system response

> “Ten children, maximum 300 PLN, no nuts, delivery before 16:00. I’ll take care of it.”

## Demo actions

1. Show mission progress.
2. Show basket optimization.
3. Approve purchase.
4. Inject product unavailable.
5. Show compliant replacement.
6. Inject payment soft decline.
7. Show payment rerouting.
8. Show mission completed.

## Closing

> “Done does not ask the user to manage an AI. The user delegates an outcome, and the agent safely completes the mission.”

---

# 30. Fallback plan

If voice fails:

- use debug text input hidden behind long press.

If OpenAI response is unstable:

- use deterministic demo fixture.

If WebSocket fails:

- use polling.

If LangGraph checkpoint fails:

- store state in PostgreSQL and resume manually.

If payment recovery fails:

- return scripted soft-decline recovery response from simulator.

If mobile build fails:

- run Expo development client or web preview.

If all integration fails:

- present static mobile UI with backend trace and recorded demo.

---

# 31. Post-hackathon roadmap

## Milestone 1

- real product catalog API,
- user preference memory,
- recurring purchases,
- merchant accounts.

## Milestone 2

- Apple Pay approval,
- real retailer checkout,
- order tracking,
- returns and refunds.

## Milestone 3

- Action Button integration,
- Siri/App Intents,
- Live Activities,
- Dynamic Island,
- background mission monitoring.

## Milestone 4

- household profiles,
- adaptive autonomy,
- proactive replenishment,
- personal budgets,
- shared missions.

---

# 32. Final product statement

**Done is a voice-first self-healing commerce agent.**

The user speaks once.

Done:

- understands the goal,
- creates a mission,
- makes a plan,
- executes the purchase,
- recovers from failures,
- asks only when necessary,
- reports the completed result.

> **Say it. Done.**
