# Notification requirements
_Last updated: 2026-09-29_

This document is the source of truth for backend notification requirements.

- Authenticated rider and management users can register and remove their own push-device tokens and read their notification inbox and unread count.
- The backend must resolve notification recipients from configured audience expressions and persist inbox records in the appropriate shared or tour-scoped table.
- Authorized administrators can send configured announcements, trigger supported reminders, and manage notification rules.
- Business workflows may request rule-driven notifications without making their primary operation depend on successful notification delivery.
- Push delivery is asynchronous. Missing delivery credentials or push-service errors must not prevent inbox data from being recorded.
- Notification rules and configuration must not contain application secrets. Push service access tokens are held in AWS Systems Manager Parameter Store SecureString parameters.

See [Notifications design](../design/notifications.md), [API reference](../design/api-reference.md#notifications), and the [deployment guide](../guides/deployment.md#after-deployment-notification-push-setup).
