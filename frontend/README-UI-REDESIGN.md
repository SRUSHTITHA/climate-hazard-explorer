# Climate Hazard Explorer — UI refresh

This is a frontend-only visual redesign of the supplied React application.

## Run locally
1. Copy `.env.example` to `.env` and set the existing API base URL as needed.
2. Run `npm install`.
3. Run `npm run dev`.

## What changed
- New responsive dashboard shell and climate-focused design system.
- Configuration controls grouped into a dedicated panel.
- Summary cards derived from the existing analysis response.
- Improved chart styling while retaining Chart.js and existing metric options.
- More polished event table, insights, data-quality panel, loading/error states.
- Existing API and URL-state modules left unchanged.

No optional map/export features were added. Verify against your backend with the same environment configuration used by your original frontend.
