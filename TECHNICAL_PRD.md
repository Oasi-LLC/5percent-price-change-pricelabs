# Technical PRD: PriceLabs Price Adjustment Tool (MVP)

## 1. Project Overview

### Purpose
An automated tool to manage daily price adjustments for short-term rental properties in PriceLabs. The tool will:
- Retrieve listing-level override pricing data from PriceLabs
- Apply automated 5% price adjustments (increase/decrease) based on daily cycles
- Re-upload modified pricing data back to PriceLabs
- Handle data processing including filtering inactive listings and maintaining correct upload formats

### MVP Scope
- Automated daily price adjustment cycle
- Integration with PriceLabs API
- Pandas-based data processing
- Filtering of inactive listings
- Price adjustment calculations (5% up/down)
- Data format validation for re-upload
- Basic error handling
- Local file storage for logs and history

### Out of Scope
- User authentication
- Multi-user support
- Web interface
- Complex error recovery
- Data encryption
- API rate limiting
- Extensive logging

## 2. Technical Architecture

### 2.1 Core Components

#### Configuration Module
- API credentials storage
- Default parameters (5% adjustment)
- Data storage file paths
- Daily cycle settings

#### PriceLabs API Client
- Retrieve listing-level override pricing
- Upload modified pricing data
- Listing status verification
- API error handling

#### Price Calculator
- 5% daily adjustment logic
- Validation of price ranges
- Inactive listing filtering
- Data format verification

#### Data Storage
- CSV file operations for price data
- Historical price changes
- Daily operation logs
- Pandas DataFrame handling

### 2.2 File Structure

pricelabs_tool/
├── config 

## Implementation Plan

### Phase 1: Setup & Configuration (Day 1)
1. Project structure setup
   - Create directory structure
   - Initialize git repo
   - Setup virtual environment
   - Install required packages (requests, pandas)

2. Configuration setup
   - Create config.py with API credentials
   - Setup basic constants (5% adjustment, file paths)
   - Create .gitignore for sensitive data

3. Verification:
   ```bash
   # Test environment
   python -m venv venv
   source venv/bin/activate
   pip install requests pandas
   pip freeze > requirements.txt
   
   # Test config loading
   python -c "from config import API_KEY; print(API_KEY)"
   ```

### Phase 2: PriceLabs API Integration (Day 1-2)
1. API Client Implementation
   - Create api_client.py
   - Implement GET request for current prices
   - Implement PUT/POST request for price updates
   - Basic error handling

2. API Tests:
   ```bash
   # Test API authentication
   curl -H "Authorization: Bearer ${API_KEY}" \
        https://api.pricelabs.co/v1/accounts/current
   
   # Test getting prices
   curl -H "Authorization: Bearer ${API_KEY}" \
        https://api.pricelabs.co/v1/properties/{property_id}/prices
   
   # Test in Python
   python -c "from api_client import PriceLabsAPI; api = PriceLabsAPI(); print(api.get_current_prices())"
   ```

### Phase 3: Price Calculation Logic (Day 2)
1. Price Calculator Implementation
   - Create price_calculator.py
   - Implement 5% adjustment logic
   - Setup pandas DataFrame processing
   - Basic data validation

2. Calculator Tests:
   ```python
   # test_calculator.py
   def test_price_increase():
       assert calculate_adjustment(100, 'increase') == 105
   
   def test_price_decrease():
       assert calculate_adjustment(100, 'decrease') == 95
   
   def test_data_processing():
       # Test with sample DataFrame
       sample_data = {...}
   ```

3. Run Tests:
   ```bash
   python -m pytest test_calculator.py
   ```

### Phase 4: Command Line Interface (Day 3)
1. CLI Development
   - Create app.py
   - Implement increase/decrease commands
   - Add basic error messages
   - Create simple progress feedback

2. CLI Tests:
   ```bash
   # Test increase command
   python app.py increase
   
   # Test decrease command
   python app.py decrease
   
   # Test invalid command
   python app.py invalid_command
   
   # Test help
   python app.py --help
   ```

### Phase 5: Integration Testing & Documentation (Day 3)
1. End-to-End Testing:
   ```bash
   # Full workflow test - increase
   python app.py increase
   
   # Verify changes in PriceLabs
   curl -H "Authorization: Bearer ${API_KEY}" \
        https://api.pricelabs.co/v1/properties/{property_id}/prices
   
   # Full workflow test - decrease
   python app.py decrease
   
   # Check logs
   cat data/changes/price_changes.csv
   ```

2. Error Scenario Tests:
   ```bash
   # Test with invalid API key
   API_KEY=invalid python app.py increase
   
   # Test with API service down
   # (modify api_client to use incorrect URL temporarily)
   python app.py increase
   ```

3. Documentation
   - Update README with setup instructions
   - Document usage examples
   - Add code comments

### Success Metrics
- Tool successfully retrieves prices from PriceLabs
  ```bash
  # Verify GET request works
  curl -H "Authorization: Bearer ${API_KEY}" \
       https://api.pricelabs.co/v1/properties/{property_id}/prices
  ```

- 5% adjustments are calculated correctly
  ```python
  python -m pytest test_calculator.py
  ```

- Modified prices are uploaded back to PriceLabs
  ```bash
  # Before and after comparison
  curl -H "Authorization: Bearer ${API_KEY}" \
       https://api.pricelabs.co/v1/properties/{property_id}/prices > before.json
  python app.py increase
  curl -H "Authorization: Bearer ${API_KEY}" \
       https://api.pricelabs.co/v1/properties/{property_id}/prices > after.json
  diff before.json after.json
  ```

- Basic error handling works
  ```bash
  # Run error scenario tests
  python -m pytest test_error_handling.py
  ```

- Command line interface functions as expected
  ```bash
  # Run CLI tests
  python app.py --help
  python app.py increase
  python app.py decrease
  ``` 