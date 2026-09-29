# Notifications design
_Last updated: 2026-09-29_

This document defines the approved notification framework for `tour-data-api`. It is the backend source of truth for notification data model, routing, APIs, and push delivery.

## 1) Architecture

```mermaid
flowchart LR
  subgraph Clients
    RA[Rider App<br/>iOS/Android/Web]
    MA[Mgmt App<br/>iOS/Android/Web]
  end
  subgraph Auth
    RP[(Cognito Rider Pool)]
    MP[(Cognito Mgmt Pool)]
  end
  subgraph API[API Gateway HTTP APIs]
    RAPI[RiderApi]
    MAPI[TourDataApi]
  end
  subgraph Backend[Lambda + common layer]
    BL[Business Lambdas<br/>rides, check-ins, riders...]
    NS[[notification_service.notify]]
    NAPI[Notification APIs<br/>inbox / devices / rules / announce]
    SND[Push Sender Lambda]
  end
  subgraph Data[DynamoDB]
    NR[(NotificationRule)]
    RN[(RiderNotification)]
    MN[(MgmtNotification)]
    TN[(Notification-tourId)]
    RPD[(RiderPushDevice)]
    MPD[(MgmtPushDevice)]
    RT[(RiderTours GSI tourId+status)]
  end
  SSM[[SSM SecureString<br/>Expo access tokens]]
  EXPO[Expo Push Service]
  FCM[FCM / APNs]
  RA -- JWT --> RAPI
  MA -- JWT --> MAPI
  RA -.login.-> RP
  MA -.login.-> MP
  RAPI --> NAPI
  MAPI --> NAPI
  BL --> NS
  NAPI --> NS
  NS --> NR
  NS --> RN & MN & TN
  RN & MN & TN -- Streams --> SND
  SND --> RPD & MPD & RT
  SND --> SSM
  SND --> EXPO --> FCM --> RA & MA
```

## 2) Sequence diagrams

### 2.1 Device registration

```mermaid
sequenceDiagram
  participant App as Mobile App
  participant API as Notification Device API
  participant DDB as PushDevice tables
  App->>API: POST /v1/notifications/devices {token, platform}
  API->>API: Resolve identity from JWT only
  API->>DDB: Upsert own device token
  API->>DDB: If token belongs to other user, move token ownership
  API-->>App: 200/201
```

### 2.2 Notify + push

```mermaid
sequenceDiagram
  participant BL as Business/Admin API
  participant NS as notification_service.notify
  participant RULE as NotificationRule
  participant INBOX as Rider/Mgmt/Tour inbox
  participant STR as DynamoDB Stream
  participant SND as Push Sender
  participant SSM as SSM SecureString
  participant EX as Expo
  BL->>NS: notify(ruleId, tourId?, context?, audiences?)
  NS->>RULE: Load + cache rule
  NS->>NS: Validate/resolve audiences + render templates
  NS->>INBOX: Batch write inbox item(s)
  INBOX-->>STR: INSERT events
  STR->>SND: Stream trigger
  SND->>SSM: Get Expo token (cached)
  SND->>EX: POST batched push payloads
  EX-->>SND: tickets (DeviceNotRegistered etc)
  SND->>INBOX: cleanup stale push tokens
```

### 2.3 Inbox read/unread

```mermaid
sequenceDiagram
  participant App as App
  participant API as Notification Inbox API
  participant INBOX as Inbox tables
  App->>API: GET /v1/notifications?since&limit
  API->>INBOX: Query all derived audiences
  API->>INBOX: Read STATE#<user> lastReadAt
  API-->>App: items + unreadCount + isRead
  App->>API: PUT /v1/notifications/read {readAt?}
  API->>INBOX: Upsert STATE item
  API-->>App: 200
```

## 3) Data model

### 3.1 Shared SAM tables

1. **NotificationRule** (`{Stack}-NotificationRule`) PK `ruleId`
2. **RiderNotification** (`{Stack}-RiderNotification`) PK `audience`, SK `sk=<createdAt>#<notificationId>`
3. **MgmtNotification** (`{Stack}-MgmtNotification`) PK `audience`, SK `sk=<createdAt>#<notificationId>`
4. **RiderPushDevice** (`{Stack}-RiderPushDevice`) PK `profileId`, SK `token`
5. **MgmtPushDevice** (`{Stack}-MgmtPushDevice`) PK `cognitoSub`, SK `token`, with GSI `GroupKeyIndex(groupKey, updatedAt)` using one lightweight per-group index item approach.
6. **AppConfig** entry `NOTIFICATION/LIMITS` stores runtime-editable limits (`maxTitleLength`, `maxMessageLength`, `archiveAfterReadHours`).

All tables use PAY_PER_REQUEST, SSE enabled, and standard deployment tags including `SubscriptionId`.

### 3.2 Tour table redesign

`Notification-{tourId}` is redesigned to the same inbox schema:
- PK: `audience`
- SK: `sk`
- TTL attribute: `expiresAt` (epoch seconds)
- Stream: `NEW_IMAGE`

`NotificationArchive-{tourId}` is added with the same PK/SK schema for age + read-state aware archival from the active tour notification table.

Legacy `readBy` and old `TypeCreatedAtIndex` are removed.

### 3.3 RiderTours index

`RiderTours` adds GSI `TourStatusIndex`:
- PK `tourId`
- SK `status`

Used for status/applicant audience fan-out.

## 4) Audience expression support

| Expression | Recipients | Stored in |
|---|---|---|
| `ALL` | all users of both apps | RiderNotification (`APP#RIDER`) + MgmtNotification (`APP#MGMT`) |
| `APP#RIDER` | all rider app users incl. profile-only | RiderNotification |
| `APP#MGMT` | all mgmt users | MgmtNotification |
| `PROFILE#<profileId>` | one rider | RiderNotification |
| `USER#<cognitoSub>` | one staff user | MgmtNotification |
| `GROUP#<group>` | staff Cognito group | MgmtNotification |
| `TOUR#<t>#STATUS#<s>` | riders with RiderTours status s | Notification-{t} |
| `TOUR#<t>#APPLICANTS` | any RiderTours record for t | Notification-{t} |
| `TOUR#<t>#ALL` | registered riders + staff of tour | Notification-{t} |
| `TOUR#<t>#APP#RIDER` / `TOUR#<t>#APP#MGMT` | registered riders / staff of tour | Notification-{t} |
| `TOUR#<t>#GROUP#<g>` | staff group within tour | Notification-{t} |
| `TOUR#<t>#RIDER#<riderId>` | one registered rider | Notification-{t} |

Unknown forms are rejected by strict regex validation.

## API integration

Device registration, inbox, announcement, reminder, and notification-rule routes use the [API reference](api-reference.md#notifications) as their sole source of truth for paths, permissions, request and response fields, and errors.

## 6) Category semantics

- `ANNOUNCEMENT`: broad informational communication to wide audiences.
- `ALERT`: high-signal notification for urgent/time-sensitive actions.
- `PERSONAL`: recipient-specific lifecycle/status communication.
- `SYSTEM`: backend-generated operational updates.

## 7) Common layer service

`notification_service.notify(rule_id, tour_id=None, context=None, audience_override=None, actor=None) -> str | None`

Behavior:
1. Load rule with 5-minute in-memory cache.
2. Respect `enabled`; return `None` if missing/disabled.
3. Allow overrides only when `allowOverride=true`.
4. Render templates safely; missing keys do not raise.
5. Rule payload supports `messageTemplate` (primary) with backward-compatible `bodyTemplate` alias.
6. Enforce title/message limits from AppConfig (`NOTIFICATION/LIMITS`) at rule validation and at render time.
7. Route all `TOUR#...` audiences to `Notification-{tourId}`.
8. Inbox archiving uses age + read-state policy (`archiveAfterReadHours`) into `NotificationArchive-{tourId}`.
9. Route/write inbox records with TTL from `ttlHours`.
10. Never raise to caller; log structured error and return `None`.

## 8) Push sender

- Stream trigger from RiderNotification, MgmtNotification, and tour notification tables.
- Filters INSERT + `push=true`, skips `STATE` items.
- Resolves recipients by audience expression.
- Sends Expo payload in batches of 100 using `urllib`.
- Reads bearer tokens from SSM SecureString parameters (`/{stack}/push/expo-token/rider` and `/{stack}/push/expo-token/mgmt` by default).
- Missing token parameter is tolerated (log + skip).
- Immediate ticket errors handled; `DeviceNotRegistered` tokens are removed.
- Retry strategy: stream retries + SQS DLQ + CloudWatch alarm.
- Receipt polling is deferred to a future scheduled enhancement.

## 9) Trigger points

Business handlers should call `notify()` non-blocking for:
- `RIDE_OPENED`
- `RIDE_STARTED`
- `RIDE_CLOSED`
- `PIT_STOP_OPENED`
- `PIT_STOP_CLOSED`
- `RIDER_EXITED` (personal)
- `CHECKIN_CREATED`
- `CHECKIN_CANCELLED`
- `EVENT_COMPLETED_BY_RIDER` (when event definition enables completion notification)
- `REGISTRATION_STATUS_CHANGED` (personal)
- `HOTEL_ALLOCATION_PUBLISHED` (when applicable)
- `RIDE_CHECKIN_REMINDER` (admin reminder)
- `EVENT_CHECKIN_REMINDER` (admin reminder + event-level allow switch)

Rules not seeded are no-op.

## 10) Event definition notification controls

Each event definition can include:

```json
{
  "notificationConfig": {
    "completionNotifyEnabled": true,
    "completionRuleId": "EVENT_COMPLETED_BY_RIDER",
    "reminderEnabled": true,
    "reminderRuleId": "EVENT_CHECKIN_REMINDER"
  }
}
```

Completion means the rider has non-cancelled outcomes for all event activities that are:
- enabled for the occurrence, and
- not marked `skipped=true` in activity overrides by organizers.

## 11) Default seed rule

`ANNOUNCEMENT` rule (seeded):

```json
{
  "ruleId": "ANNOUNCEMENT",
  "enabled": true,
  "category": "ANNOUNCEMENT",
  "audiences": ["ALL"],
  "titleTemplate": "{title}",
  "messageTemplate": "{message}",
  "push": true,
  "priority": "NORMAL",
  "androidChannel": "general",
  "target": { "screen": "Notifications", "paramKeys": [] },
  "ttlHours": 168,
  "allowOverride": true,
  "version": 1
}
```

## 12) Sample rule IDs for backend trigger hooks

```json
[
  {"ruleId":"RIDE_OPENED","category":"SYSTEM","audiences":["TOUR#{tourId}#ALL"]},
  {"ruleId":"RIDE_STARTED","category":"ALERT","audiences":["TOUR#{tourId}#ALL"],"priority":"URGENT","androidChannel":"urgent"},
  {"ruleId":"RIDE_CLOSED","category":"SYSTEM","audiences":["TOUR#{tourId}#ALL"]},
  {"ruleId":"CHECKIN_CREATED","category":"PERSONAL","audiences":["TOUR#{tourId}#RIDER#{riderId}"]},
  {"ruleId":"CHECKIN_CANCELLED","category":"PERSONAL","audiences":["TOUR#{tourId}#RIDER#{riderId}"]},
  {"ruleId":"PIT_STOP_OPENED","category":"SYSTEM","audiences":["TOUR#{tourId}#ALL"]},
  {"ruleId":"PIT_STOP_CLOSED","category":"SYSTEM","audiences":["TOUR#{tourId}#ALL"]},
  {"ruleId":"EVENT_COMPLETED_BY_RIDER","category":"PERSONAL","audiences":["TOUR#{tourId}#RIDER#{riderId}"]},
  {"ruleId":"RIDE_CHECKIN_REMINDER","category":"ALERT","audiences":["TOUR#{tourId}#RIDER#{riderId}"]},
  {"ruleId":"EVENT_CHECKIN_REMINDER","category":"ALERT","audiences":["TOUR#{tourId}#RIDER#{riderId}"]},
  {"ruleId":"RIDER_EXITED","category":"PERSONAL","audiences":["PROFILE#{profileId}"]},
  {"ruleId":"REGISTRATION_STATUS_CHANGED","category":"PERSONAL","audiences":["PROFILE#{profileId}"]},
  {"ruleId":"HOTEL_ALLOCATION_PUBLISHED","category":"SYSTEM","audiences":["TOUR#{tourId}#APP#RIDER"]}
]
```

## 13) Cost note

Design remains low cost (DynamoDB on-demand + Lambda + API Gateway + Expo push), with expected notification overhead still in the <$1–2 per-tour range for this scale.

## 14) Deployment prerequisites for push delivery

Push delivery requires post-deploy setup beyond table/function creation:

1. Set Expo access tokens into SSM SecureString parameters used by push sender.
2. Seed `NotificationRule` and `AppConfig` defaults (`NOTIFICATION/LIMITS`). `make deploy` does this automatically; other deploy paths (CI, `make deploy-test/prod`, plain `sam deploy`) require running the seed targets.
3. Ensure each tour's `Notification-{tourId}` stream is connected to the push sender. Tour provisioning (API and CLI) does this automatically; tours provisioned before push setup need `PUT /v1/tours/{tourId}/provision` once.
4. Ensure client delivery credentials are configured in mobile delivery stack:
   - Apple APNs for iOS builds,
   - Google FCM (V1 service account) for Android builds,
   - Expo project configuration for both rider/mgmt apps.

See the [deployment guide → Notification Push Setup](../guides/deployment.md#after-deployment-notification-push-setup) for setup commands and the deployment checklist.
