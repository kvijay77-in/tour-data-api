# Tour artifact design
_Last updated: 2026-10-04_

## Storage model

Artifact files are private S3 objects. The owning tour's `Artifacts-{tourId}` DynamoDB table stores metadata keyed by `artifactFor` and `artifactId`. `artifactFor` is the `tourId` for a tour artifact or `tourId#rideId` for a ride artifact. Artifact type identifiers and their `tour` or `ride` category are configured in shared `AppConfig` entries with `configType=ARTIFACTS`.

Object key patterns:

| Scope | S3 key pattern |
|---|---|
| Tour | `tours/{tourId}/{artifactId}.{extension}` |
| Ride | `tours/{tourId}/rides/{rideId}/{artifactId}.{extension}` |

Metadata includes the S3 key, content type, current version, file size, upload time and actor, and display title. Replacing an artifact updates its metadata version.

## Upload and read flow

```mermaid
sequenceDiagram
    participant Admin as Management app
    participant API as Tour Data API
    participant S3 as Private artifact bucket
    participant Rider as Rider app
    Admin->>API: Request upload URL
    API->>API: Check ARTIFACT_MANAGE and artifact configuration
    API-->>Admin: Presigned PUT URL
    Admin->>S3: Upload file
    Rider->>API: Request tour or ride artifact manifest
    API->>API: Check read access and load metadata
    API-->>Rider: Metadata and presigned download URL
    Rider->>S3: Download file
```

The API validates the tour, ride (when applicable), configured artifact category, and supported content type before issuing a presigned URL. Artifact deletion removes the S3 object and the corresponding metadata item. Read endpoints can filter by `artifactId` and accept an expiry duration within the API's supported range.

The management web upload flow uses a browser `PUT` to the presigned URL with the same `Content-Type` used to sign it; it does not send the API `Authorization` header to S3. A valid presigned URL authorizes the object operation but does not satisfy browser CORS, which is configured separately on the private artifact bucket. When the backend's `ManagementWebAllowedOrigins` parameter is populated, the template enables only `PUT` for those origins and `Content-Type`, with a 600-second preflight cache. The empty parameter leaves the existing bucket CORS configuration absent. The deployed setting has not been verified. The app handoff identifies no photo-bucket fetch/upload flow, so photo CORS is not assumed to be required.

Rider API reads use the same `READ` permission and presigned URL behavior as management reads. Each manifest entry returns `artifactId`, `s3Key`, `contentType`, `version`, `title`, `downloadUrl`, `expiresIn`, `createdAt`, and `updatedAt`. `title` is the configured display name/description; category is implied by the tour or ride endpoint, and file name is the final path component of `s3Key` (there are no separate `category` or `fileName` response properties).

The rider client may cache downloaded artifact files as an optimization; that does not imply general offline operation. The backend remains the authority for metadata, authorization, and URL generation.

## Security and ownership

- The artifact bucket is private; reads and writes use short-lived presigned URLs.
- Upload and delete operations require `ARTIFACT_MANAGE`.
- The management app is the intended artifact writer; authenticated clients with read access may request manifests.
- Rider profile photos use their separate profile-photo flow and are not stored in the tour artifact namespace.

See [API reference](api-reference.md#artifacts), [Data model](data-model.md), and [Artifacts requirements](../requirements/artifacts.md) for the contract, table inventory, and product requirements.
