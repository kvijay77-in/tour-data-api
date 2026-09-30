# Tour artifact requirements
_Last updated: 2026-09-29_

This document is the source of truth for backend requirements for tour and ride artifacts.

- Organizers must be able to upload and replace configured tour-level and ride-level artifacts without requiring a client app release.
- Artifact type identifiers and their tour/ride category are configurable through shared `AppConfig`.
- Artifact files are stored privately in S3. DynamoDB metadata identifies each artifact and its current version.
- Upload and download access is provided through backend-generated presigned URLs. Artifact write operations require the appropriate backend permission.
- The artifact API must provide clients with the metadata and temporary download URL needed to retrieve an available artifact.

See [Artifacts design](../design/artifacts.md) and the [API reference](../design/api-reference.md#artifacts) for storage and API details.
