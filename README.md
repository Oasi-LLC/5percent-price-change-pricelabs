# PriceLabs 5% Price Adjustment Tool

Streamlit app to apply ±5% fixed-override adjustments across configured listings, with **BATNA minimum floors** (flat or weekday/weekend for SOS and Maya & Mod).

## Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Create `.env`:

```
PRICELABS_API_KEY=your_key
API_BASE_URL=https://api.pricelabs.co/v1
APP_PASSWORD=optional_shared_password
```

## Run

```bash
streamlit run streamlit_app.py
```

## Workflow

1. **Refresh listings** — loads active PriceLabs listings that appear in `properties_config.yaml`.
2. **Select listings** — checkboxes grouped by property.
3. **Apply** — posts ±5% adjusted overrides with BATNA floors to PriceLabs.

## Configuration

- `properties_config.yaml` — listing IDs, BATNA values, rate groups, SOS/Maya weekday-weekend floors.

## Project layout

```
streamlit_app.py          # UI
properties_config.yaml    # Listings & BATNA
pricelabs_tool/
  api_client.py           # PriceLabs API
  batna.py                # BATNA resolution & clamping
  adjustment.py           # Per-listing override computation
  property_config.py      # YAML helpers
  tests/test_batna.py     # Unit tests
```

## Tests

```bash
python3 -c "from pricelabs_tool.tests import test_batna; ..."
```
