# Frontend Deploy Plan

## Goal

Deploy the frontend demo to Vercel from the latest GitHub Release, not from every `main` push. Generated frontend data is published as a GitHub Release asset and restored during the deploy workflow. The deployed site should be protected with Basic Auth, including direct access to generated JSON files.

## Already Done

1. `frontend/public/generated/` is ignored and not committed.
2. `frontend-generated-examples.tar.gz` is ignored.
3. Added `scripts/publish_frontend_release_data.sh`.
   - Packages `frontend/public/generated`.
   - Uploads it as a GitHub Release asset.
   - Prints archive size and SHA-256 checksum.
4. Added `.github/workflows/deploy_frontend_release.yml`.
   - Runs on `release: published`.
   - Downloads the generated data release asset.
   - Builds the frontend.
   - Deploys with the Vercel CLI.
5. Added `frontend/middleware.ts`.
   - Protects all Vercel requests with Basic Auth.
   - Also protects direct access to generated JSON files.
   - Uses `BASIC_AUTH_USER` and `BASIC_AUTH_PASSWORD`.
6. Linked the local frontend directory to a Vercel project.
   - Project name: `ropeway-skip-stop-optimization-frontend`.
   - Vercel created `frontend/.vercel/project.json` locally.
   - `frontend/.vercel/` is ignored through `frontend/.gitignore`.
7. Added the required GitHub Action secrets.
   - `VERCEL_TOKEN`
   - `VERCEL_ORG_ID`
   - `VERCEL_PROJECT_ID`
   - `BASIC_AUTH_USER`
   - `BASIC_AUTH_PASSWORD`

## Open Steps

### 1. Avoid Vercel Auto-Deploy From `main`

Production should come from the GitHub Release workflow only.

Options:

- do not connect Vercel Git auto-deploy; or
- configure Vercel so pushes to `main` do not automatically create production deployments.

### 2. Commit and Push Deploy Setup

Commit these files:

- `.gitignore`
- `.github/workflows/deploy_frontend_release.yml`
- `scripts/publish_frontend_release_data.sh`
- `frontend/.gitignore`
- `frontend/middleware.ts`
- this plan file

### 3. Prepare Release Data

Ensure `frontend/public/generated/examples` contains the intended data.

Upload the generated data archive to an existing GitHub Release:

```bash
scripts/publish_frontend_release_data.sh <tag>
```

### 4. Publish GitHub Release

Example flow:

```bash
gh release create web-v1 \
  --draft \
  --target main \
  --title "Web demo v1" \
  --notes "Frontend demo release."

scripts/publish_frontend_release_data.sh web-v1

gh release edit web-v1 --draft=false
```

Publishing the release triggers `.github/workflows/deploy_frontend_release.yml`.

### 5. Verify Deployment

Check:

- GitHub Action finished successfully.
- Vercel deployment is reachable.
- Basic Auth prompt appears.
- Frontend loads generated examples after authentication.
- Direct JSON access under `/generated/...` is also protected.
