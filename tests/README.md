# Test Suite for Highway Ramp Detection System

## Overview

This directory contains comprehensive unit tests for the Google Directions API validation logic used in the highway ramp detection system.

## Test Coverage

### `test_google_validation.py`

Tests for the `GoogleDirectionsValidator` class covering:

#### **1. Initialization Tests**
- ✅ Validator initialization with API key
- ✅ Base URL configuration

#### **2. API Query Tests** (`_query_directions`)
- ✅ Successful API queries
- ✅ Network timeouts
- ✅ HTTP errors
- ✅ Exception handling

#### **3. Route Information Extraction Tests** (`_extract_route_info`)
- ✅ Valid route responses
- ✅ Empty routes
- ✅ Missing route data
- ✅ Response structure validation

#### **4. Distance Calculation Tests** (`_calculate_merge_distance`)
- ✅ GPS segment distance calculation
- ✅ Single point segments
- ✅ Out-of-bounds indices
- ✅ Edge cases (zero distance)

#### **5. Ramp Detection Tests** (`_check_highway_ramps`)
- ✅ Detection of ramp maneuvers (`ramp-right`, `ramp-left`)
- ✅ Detection of exit maneuvers (`exit-right`, `exit-left`)
- ✅ Detection of merge maneuvers
- ✅ No ramp detection when none present
- ✅ Empty/missing maneuver fields
- ✅ All supported maneuver types

#### **6. Validation Reason Tests** (`_get_validation_reason`)
- ✅ Validation with both conditions met
- ✅ Validation with distance only
- ✅ Validation with ramps only
- ✅ Rejection reasons

#### **7. Integration Tests** (`validate_merge_instance`)
- ✅ Successful validation (both conditions)
- ✅ Successful validation (distance only - 3x tolerance)
- ✅ Successful validation (ramps only)
- ✅ Rejected validation (both conditions fail)
- ✅ API failure handling
- ✅ No route found handling
- ✅ Zero distance edge case
- ✅ Complete response structure validation

## Running Tests

### Using unittest (Python standard library)

```bash
# Run all tests in verbose mode
python -m unittest tests.test_google_validation -v

# Run from the project root
cd /path/to/HighwayMergeDetector-main
source venv/bin/activate
python -m unittest tests.test_google_validation -v
```

### Using pytest (if installed)

```bash
pip install pytest
pytest tests/test_google_validation.py -v
```

## Test Statistics

- **Total Tests**: 28
- **Test Categories**: 7
- **Mocking**: All API calls are mocked to avoid external dependencies
- **Coverage**: All public and private methods of `GoogleDirectionsValidator`

## Key Testing Features

1. **No External API Calls**: All Google API calls are mocked using `unittest.mock`
2. **Comprehensive Edge Cases**: Tests cover error conditions, empty data, and boundary cases
3. **Isolated Tests**: Each test is independent and doesn't rely on external state
4. **Fast Execution**: All tests complete in < 0.1 seconds
5. **Clear Test Names**: Descriptive test names explain what each test validates

## Adding New Tests

When adding new validation logic or fixing bugs:

1. Add a test case to the appropriate test class
2. Use descriptive test names starting with `test_`
3. Mock all external dependencies (API calls, file I/O)
4. Test both success and failure paths
5. Run tests before committing: `python -m unittest tests.test_google_validation -v`

## Test Structure

```python
class TestGoogleDirectionsValidator(unittest.TestCase):
    def setUp(self):
        # Set up test fixtures
    
    def test_specific_functionality(self):
        # Arrange, Act, Assert pattern
        pass
```

## Notes

- Tests use mocking to avoid actual API calls during testing
- All tests should pass quickly (< 1 second total)
- Tests are designed to be run in CI/CD pipelines
- No external dependencies required (except Python standard library)
