# Expo Push Notifications: External Setup Guide

Oct 15, 2026 · @Vijay

Push notifications need five external steps: Firebase and FCM for Android, an APNs key for iOS, an Expo access token, new native builds, and a test. This guide assumes your EAS builds already reach Play internal testing and TestFlight, and that you send through the Expo Push Service from AWS Lambda.

## 1. Android: Firebase and FCM V1

Use one Firebase project per environment, dev and prod, under the matching org. Each project needs its own Android app, `google-services.json`, and service account key, which you upload to EAS.

1. Create two Firebase projects at console.firebase.google.com, one under the dev org and one under the prod org.
2. In each project, register one Android app using that environment's package name. The package name must match exactly.
3. From each project, download that app's `google-services.json` and reference it in your app config under `android.googleServicesFile`, per variant if you use `app.config.js`. These files are safe to commit.
4. In each Firebase project, go to Project settings → Service accounts → Generate new private key. Keep both JSON files out of git and label them dev and prod.
5. Upload the key to EAS: run `eas credentials`, then choose Android → the profile → Google Service Account → Manage your Google Service Account Key for Push Notifications (FCM V1) → Upload a new service account key. Repeat for the other package name with the other project's key. A key works only for its own Firebase project, so each package name (dev and prod) gets its own key.

You don't need SHA fingerprints in Firebase for push. They matter only if you restrict the API key in Google Cloud Console. In that case, allow the FCM Registration and Firebase Installations APIs, and use the Play App Signing certificate SHA-1, not your upload key.

## 2. iOS: Enable push and create the APNs key

iOS needs one APNs key stored in EAS and the Push Notifications capability on each App ID. Nothing is configured in App Store Connect.

1. Run `eas credentials`, choose iOS → the profile → Push Notifications, and let EAS generate a new APNs key. EAS reuses the key across your bundle identifiers (dev and prod). Apple limits the number of APNs keys per team, so reuse an existing key if you already have one.
2. Add the `expo-notifications` plugin to your app config so the next iOS build carries the push entitlement. During that build, EAS turns on the Push Notifications capability for your app's bundle identifier (the value of ios.bundleIdentifier in your app config, such as com.yourco.app) and regenerates the provisioning profile. To confirm: sign in at developer.apple.com/account, open Certificates, Identifiers & Profiles → Identifiers, click your bundle identifier, and check that Push Notifications is ticked under Capabilities. Do this once per bundle identifier (dev and prod).
3. TestFlight and store builds use the production APNs environment automatically, and the same `.p8` key covers it.

## 3. Access token (enhanced push security)

Without an access token, anyone holding a leaked push token could send to your users. Turn on enhanced push security, in this order:

1. Go to expo.dev → Settings → Access tokens and create a token. For production, prefer an organization robot token over a personal one. If dev and prod live in separate Expo organizations, create one token in each.
2. Store it in AWS Secrets Manager or SSM Parameter Store, one secret per environment.
3. Make your Lambda send it as `Authorization: Bearer <token>`, or pass it via `new Expo({ accessToken })` in `expo-server-sdk-node` v3.6.0 or later.
4. Only then enable "Enhanced push security" on the same page. Once it is on, requests without a valid token fail with `UNAUTHORIZED`.

## 4. Ship new native builds

These changes are native, so an OTA update will not carry them:

- The `expo-notifications` plugin, which adds the iOS `aps-environment` entitlement
- `googleServicesFile` on Android
- The regenerated iOS provisioning profile

Run new `eas build` jobs for both platforms and upload them to TestFlight and Play internal testing. Increase the build number and `versionCode`. Testers must install the new builds.

## 5. Verify end to end

Test the Expo tool first, then your Lambda.

1. Install the new tester build, grant the permission prompt, and copy the `ExpoPushToken` your app logs or returns.
2. Send it from the Expo push notifications tool at expo.dev/notifications.
3. Repeat the test through your Lambda with the access token.

| Symptom | Likely cause |
| --- | --- |
| No push token on Android | `google-services.json` missing from the build, or the package name doesn't match the Firebase app |
| `InvalidCredentials` receipt | FCM key or APNs key missing for that app identifier |
| Nothing on iOS, no error | Build predates the entitlement, or notification permission was denied on the device |
| `UNAUTHORIZED` from the API | Enhanced push security is on but Lambda isn't sending the token |
| Lambda call times out | Function is in a VPC without a NAT gateway or other outbound route to `exp.host` |

## Sources

- [Expo push notifications setup](https://docs.expo.dev/push-notifications/push-notifications-setup/)
- [Add Android FCM V1 credentials](https://docs.expo.dev/push-notifications/fcm-credentials/)
- [Send notifications with the Expo Push Service](https://docs.expo.dev/push-notifications/sending-notifications/)
