# Rider profile requirements
_Last updated: 2026-09-29_

This document is the source of truth for backend rider profile and tour-participation requirements.

- Each rider has a tour-independent profile identified by `profileId`. Tour-specific rider IDs and operational state belong to a tour.
- Rider profile definitions must be configurable through shared `AppConfig` entries for sections, attributes, and lists of values.
- Profile create and update operations validate the submitted data against enabled definitions. Updates merge submitted values and preserve values that were not submitted.
- Rider-facing profile writes are limited to the signed-in rider's own profile. Staff visibility of profile attributes is role-filtered; sensitive or restricted attributes must not be exposed to unauthorized staff.
- Changes to profile definitions are versioned. Clients use the server-provided definitions version when submitting profile changes.
- A rider's participation lifecycle for a tour is maintained independently of the profile and independently of the operational `TourRider` record used during an active tour.

See [Rider profile schema design](../design/rider-profile-schema.md) and the [API reference](../design/api-reference.md#riders) for details.
