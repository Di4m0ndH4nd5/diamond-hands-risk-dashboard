Di4m0ndH4nd5 Risk Dashboard V18

IMPORTANT GITHUB SETUP

This package contains:
.github/workflows/update-prices.yml

GitHub Actions only detects the updater when that exact hidden folder path exists in the repository.

After uploading V18, check your repository contains:
.github
  workflows
    update-prices.yml

Then go to:
GitHub repository -> Actions -> Update Di4m0ndH4nd5 prices and risk -> Run workflow

The workflow updates:
- Current prices
- 0-1 risk metrics
- Buy Zones
- Risk bars
- data.json timestamp

It then runs automatically every hour.
