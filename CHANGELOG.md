# Changelog

## [Unreleased] – 2025-03-05

### Added
- **Per-listing delay**: Throttle (default 2s) after each listing to avoid PriceLabs rate limits; configurable `per_listing_delay` in `batch_update`.
- **Smaller batch size**: Default batch size reduced from 20 to 10 to reduce request bursts.
- **Retries**: Up to 3 attempts per listing on any failure, with backoff (5s, then 10s) before retry.
- **Failed listings table**: After a run, failed listings appear in a table with a "Retry failed listings" button to re-run only those.
- **Skipped result**: Listings with no qualifying overrides (fixed, in range, price > 0) now show as "Skipped" with a reason instead of being omitted from results.
- **Success = all qualifying dates**: Success is only reported when the full set of qualifying overrides for that listing is sent and the API succeeds; success message shows "All N date(s) updated".
- **Skipped-override breakdown**: When some overrides are not changed (non-fixed, out of date range, bad price), the UI shows counts per reason (e.g. "210 out of date range").
- **Logging**: INFO logs for pulled overrides (listing, count, sample) and after-change sample rates (old→new) for debugging; `logging.basicConfig` so logs appear in the terminal.
- **Property-level `update_children`**: In `properties_config.yaml`, a property can set `update_children: true` so PriceLabs pushes overrides to child listings (used for FLOHOM/Hostaway so changes appear in PriceLabs).
- **Listings expander kept open**: "Select listings to adjust" expander uses `expanded=True` so it does not close on checkbox click, avoiding repeated scroll (e.g. when selecting all FLOHOM units).

### Changed
- **API re-raise**: `get_listing_overrides` and `update_listing_overrides` now re-raise the original request exception (instead of wrapping) so retry logic can see HTTP status.
- **Results summary**: Metrics now include Successful, Failed, and Skipped; per-listing messages show dates updated and any skipped-override breakdown.
- **Session state**: Added `failed_listings` and `last_increase` for the failed-listings table and manual retry.

### Config
- **properties_config.yaml**:
  - **pblu1 (ParcBlu)**: Entire property block commented out.
  - **flo1 (FLOHOM)**: Added `update_children: true` for Hostaway so overrides apply to child listings.

### Fixed
- FLOHOM listings not updating in PriceLabs: fixed by using `update_children: true` for the FLOHOM property so PriceLabs pushes to child listings.
