V29 logo-loading fix:
- Removed service-worker registration from index.html
- sw.js is intentionally not included in this package
- Added ?v=29 cache-busting to asset logo URLs
- Added a ticker fallback if an SVG fails to render

IMPORTANT: If sw.js still exists in the GitHub repository from an older version, delete it once.
