# User Testing
This provides certain test commands that can be used to test the Mgmt App Web Deployment for CORS.

Route to use: `GET /v1/tours` (it exists on both APIs). Run everything from the repo root with your AWS credentials active.

## 0. Set variables

```bash
REGION=ap-south-1
STACK=dev
SITE=https://d2jabz8s44foya.cloudfront.net

out() { aws cloudformation describe-stacks --region $REGION --stack-name $STACK \
  --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" --output text; }

API=$(out ApiEndpoint)            # management API base URL
RIDER_API=$(out RiderApiEndpoint) # rider API base URL
BUCKET=$(out ArtifactsBucketName)
echo "$API" "$RIDER_API" "$BUCKET"   # all three must be non-empty
```

If `API` has a trailing `/`, strip it: `API=${API%/}` (same for `RIDER_API`).

## 1. API preflight, allowed origin

A preflight is an `OPTIONS` request with no auth; the browser sends it before the real call.

```bash
curl -si -X OPTIONS "$API/v1/tours" \
  -H "Origin: $SITE" \
  -H "Access-Control-Request-Method: GET" \
  -H "Access-Control-Request-Headers: authorization,content-type,if-none-match"
```

Expect `HTTP/2 204` and these headers:
- `access-control-allow-origin: https://d2jabz8s44foya.cloudfront.net` (exactly the site, not `*`)
- `access-control-allow-headers` containing `authorization`, `content-type`, `if-none-match`
- `access-control-allow-methods` including `GET`
- `access-control-max-age: 600`

Repeat with `-H "Origin: http://localhost:8081"`. The expected result is the same, echoing that origin.

## 2. API preflight, disallowed origin

```bash
curl -si -X OPTIONS "$API/v1/tours" \
  -H "Origin: https://example.com" \
  -H "Access-Control-Request-Method: GET" \
  -H "Access-Control-Request-Headers: authorization"
```

Expect no `access-control-allow-origin` header in the response.

## 3. `etag` exposed on a real GET

This needs a management Cognito ID/access token. Get one however you normally log in, for example:

```bash
TOKEN=<paste management user JWT>   # do not save in files or docs

curl -si "$API/v1/tours" \
  -H "Origin: $SITE" \
  -H "Authorization: Bearer $TOKEN" | grep -i -E "^HTTP|access-control"
```

Expect `HTTP/2 200` and `access-control-allow-origin: $SITE`. The `access-control-expose-headers` check depends on whether API Gateway sends it on actual responses. The plan targets event-bootstrap, so for a precise `etag` check use an event read route that returns `ETag`. Find it with `grep -n "bootstrap" `template.yaml` | head`, then request that path with `-H "Origin: $SITE"` and expect `access-control-expose-headers: etag` and an `etag:` header. If you have no token handy, this check can wait for QA's browser test. Steps 1, 2, 4 and 5 need no token.

## 4. Artifacts bucket (S3) preflight

```bash
curl -si -X OPTIONS "https://$BUCKET.s3.$REGION.amazonaws.com/test-key" \
  -H "Origin: $SITE" \
  -H "Access-Control-Request-Method: PUT" \
  -H "Access-Control-Request-Headers: content-type"
```

Expect `HTTP/1.1 200 OK` with `access-control-allow-origin: $SITE`, `access-control-allow-methods: PUT`, and `access-control-allow-headers: content-type`. With a bad origin, S3 returns `403` (`CORSForbidden`).

## 5. RiderApi unchanged (wildcard)

```bash
curl -si -X OPTIONS "$RIDER_API/v1/tours" \
  -H "Origin: https://example.com" \
  -H "Access-Control-Request-Method: GET" \
  -H "Access-Control-Request-Headers: authorization"
```

Expect `access-control-allow-origin: *` (or the echoed origin), as before.

## Recording

Once checks 1, 2, 4 and 5 pass (3 if you have a token), tell me. I'll update the "Verified" line in `deployment.md` with the date and results.

## Extra CORS Origins 
aws apigatewayv2 get-api --api-id mgyezkldn2 --region ap-south-1 --query CorsConfiguration

