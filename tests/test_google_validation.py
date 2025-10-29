#!/usr/bin/env python3
"""
Unit tests for Google Directions API validation logic
"""

import unittest
from unittest.mock import Mock, patch, MagicMock
import sys
from pathlib import Path

# Add core directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'core'))

from highway_ramp_detector import GoogleDirectionsValidator, haversine_distance


class TestGoogleDirectionsValidator(unittest.TestCase):
    """Test suite for GoogleDirectionsValidator"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.api_key = "test_api_key_12345"
        self.validator = GoogleDirectionsValidator(self.api_key)
        
        # Sample merge data
        self.merge_data = {
            'start_lat': 43.6532,
            'start_lon': -79.3832,
            'end_lat': 43.6540,
            'end_lon': -79.3840,
            'segment_start': 0,
            'segment_end': 5
        }
        
        # Sample route GPS points
        self.route = [
            {'lat': 43.6532, 'lon': -79.3832, 'timestamp': 1000},
            {'lat': 43.6534, 'lon': -79.3834, 'timestamp': 1001},
            {'lat': 43.6536, 'lon': -79.3836, 'timestamp': 1002},
            {'lat': 43.6538, 'lon': -79.3838, 'timestamp': 1003},
            {'lat': 43.6540, 'lon': -79.3840, 'timestamp': 1004},
            {'lat': 43.6542, 'lon': -79.3842, 'timestamp': 1005},
        ]
    
    def test_init(self):
        """Test validator initialization"""
        self.assertEqual(self.validator.api_key, self.api_key)
        self.assertEqual(self.validator.base_url, 
                        "https://maps.googleapis.com/maps/api/directions/json")
    
    @patch('highway_ramp_detector.requests.get')
    def test_query_directions_success(self, mock_get):
        """Test successful API query"""
        # Mock successful response
        mock_response = Mock()
        mock_response.json.return_value = {
            'status': 'OK',
            'routes': [{
                'legs': [{
                    'distance': {'value': 1000},
                    'steps': []
                }]
            }]
        }
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response
        
        result = self.validator._query_directions("43.6532,-79.3832", "43.6540,-79.3840")
        
        self.assertIsNotNone(result)
        self.assertEqual(result['status'], 'OK')
        mock_get.assert_called_once()
    
    @patch('highway_ramp_detector.requests.get')
    def test_query_directions_timeout(self, mock_get):
        """Test API query timeout"""
        import requests
        mock_get.side_effect = requests.Timeout("Connection timed out")
        
        result = self.validator._query_directions("43.6532,-79.3832", "43.6540,-79.3840")
        
        self.assertIsNone(result)
    
    @patch('highway_ramp_detector.requests.get')
    def test_query_directions_http_error(self, mock_get):
        """Test API query HTTP error"""
        import requests
        mock_response = Mock()
        mock_response.raise_for_status.side_effect = requests.HTTPError("500 Internal Server Error")
        mock_get.return_value = mock_response
        
        result = self.validator._query_directions("43.6532,-79.3832", "43.6540,-79.3840")
        
        self.assertIsNone(result)
    
    def test_extract_route_info_valid(self):
        """Test extracting route info from valid response"""
        directions_response = {
            'routes': [{
                'legs': [{
                    'distance': {'value': 1500},
                    'steps': [
                        {'maneuver': 'turn-right'},
                        {'maneuver': 'ramp-right'}
                    ]
                }]
            }]
        }
        
        result = self.validator._extract_route_info(directions_response)
        
        self.assertEqual(result['distance'], 1500)
        self.assertEqual(len(result['steps']), 2)
        self.assertEqual(result['steps'][1]['maneuver'], 'ramp-right')
    
    def test_extract_route_info_empty_routes(self):
        """Test extracting route info from empty response"""
        directions_response = {'routes': []}
        
        result = self.validator._extract_route_info(directions_response)
        
        self.assertEqual(result['distance'], 0)
        self.assertEqual(len(result['steps']), 0)
    
    def test_extract_route_info_missing_routes(self):
        """Test extracting route info from response without routes key"""
        directions_response = {}
        
        result = self.validator._extract_route_info(directions_response)
        
        self.assertEqual(result['distance'], 0)
        self.assertEqual(len(result['steps']), 0)
    
    def test_calculate_merge_distance(self):
        """Test calculating GPS segment distance"""
        # Calculate expected distance manually
        expected_distance = 0.0
        for i in range(0, min(5, len(self.route) - 1)):
            dist = haversine_distance(
                self.route[i]['lat'], self.route[i]['lon'],
                self.route[i+1]['lat'], self.route[i+1]['lon']
            ) * 1000
            expected_distance += dist
        
        result = self.validator._calculate_merge_distance(self.merge_data, self.route)
        
        self.assertAlmostEqual(result, expected_distance, places=2)
        self.assertGreater(result, 0)
    
    def test_calculate_merge_distance_single_point(self):
        """Test distance calculation with single point segment"""
        merge_data = {
            'segment_start': 0,
            'segment_end': 1
        }
        route = [{'lat': 43.6532, 'lon': -79.3832}]
        
        result = self.validator._calculate_merge_distance(merge_data, route)
        
        self.assertEqual(result, 0.0)  # No segments to calculate
    
    def test_calculate_merge_distance_out_of_bounds(self):
        """Test distance calculation with out-of-bounds indices"""
        merge_data = {
            'segment_start': 0,
            'segment_end': 100  # Beyond route length
        }
        
        result = self.validator._calculate_merge_distance(merge_data, self.route)
        
        # Should only calculate up to route length
        self.assertGreaterEqual(result, 0)
    
    def test_check_highway_ramps_with_ramp_maneuvers(self):
        """Test detecting ramps when ramp maneuvers are present"""
        steps = [
            {'maneuver': 'turn-right'},
            {'maneuver': 'ramp-right'},
            {'maneuver': 'straight'}
        ]
        
        result = self.validator._check_highway_ramps(steps)
        
        self.assertTrue(result)
    
    def test_check_highway_ramps_with_exit_maneuvers(self):
        """Test detecting ramps when exit maneuvers are present"""
        steps = [
            {'maneuver': 'exit-left'},
            {'maneuver': 'turn-right'}
        ]
        
        result = self.validator._check_highway_ramps(steps)
        
        self.assertTrue(result)
    
    def test_check_highway_ramps_with_merge_maneuver(self):
        """Test detecting ramps when merge maneuver is present"""
        steps = [
            {'maneuver': 'merge'},
            {'maneuver': 'straight'}
        ]
        
        result = self.validator._check_highway_ramps(steps)
        
        self.assertTrue(result)
    
    def test_check_highway_ramps_no_ramp_maneuvers(self):
        """Test when no ramp maneuvers are present"""
        steps = [
            {'maneuver': 'turn-right'},
            {'maneuver': 'turn-left'},
            {'maneuver': 'straight'}
        ]
        
        result = self.validator._check_highway_ramps(steps)
        
        self.assertFalse(result)
    
    def test_check_highway_ramps_empty_maneuver(self):
        """Test when maneuver field is empty"""
        steps = [
            {'maneuver': ''},
            {}
        ]
        
        result = self.validator._check_highway_ramps(steps)
        
        self.assertFalse(result)
    
    def test_check_highway_ramps_no_maneuver_field(self):
        """Test when maneuver field is missing"""
        steps = [
            {'instruction': 'Turn right'},
            {'instruction': 'Go straight'}
        ]
        
        result = self.validator._check_highway_ramps(steps)
        
        self.assertFalse(result)
    
    def test_get_validation_reason_valid_both(self):
        """Test validation reason when both conditions are met"""
        reason = self.validator._get_validation_reason(
            is_valid=True,
            distance_valid=True,
            uses_ramps=True,
            distance_ratio=0.5
        )
        
        self.assertIn("Valid", reason)
        self.assertIn("uses ramps", reason)
        self.assertIn("0.50", reason)
    
    def test_get_validation_reason_valid_distance_only(self):
        """Test validation reason when only distance is valid"""
        reason = self.validator._get_validation_reason(
            is_valid=True,
            distance_valid=True,
            uses_ramps=False,
            distance_ratio=1.2
        )
        
        self.assertIn("Valid", reason)
        self.assertIn("no ramps detected", reason)
        self.assertIn("1.20", reason)
    
    def test_get_validation_reason_valid_ramps_only(self):
        """Test validation reason when only ramps are detected"""
        reason = self.validator._get_validation_reason(
            is_valid=True,
            distance_valid=False,
            uses_ramps=True,
            distance_ratio=5.0
        )
        
        self.assertIn("Valid", reason)
        self.assertIn("uses ramps", reason)
        self.assertIn("5.00", reason)
    
    def test_get_validation_reason_invalid(self):
        """Test validation reason when validation fails"""
        reason = self.validator._get_validation_reason(
            is_valid=False,
            distance_valid=False,
            uses_ramps=False,
            distance_ratio=6.0
        )
        
        self.assertIn("Rejected", reason)
        self.assertIn("no ramps detected", reason)
        self.assertIn("6.00", reason)
    
    @patch.object(GoogleDirectionsValidator, '_query_directions')
    @patch.object(GoogleDirectionsValidator, '_calculate_merge_distance')
    @patch.object(GoogleDirectionsValidator, '_extract_route_info')
    @patch.object(GoogleDirectionsValidator, '_check_highway_ramps')
    def test_validate_merge_instance_success_both_conditions(self, mock_check, mock_extract, mock_calc, mock_query):
        """Test successful validation when both distance and ramps are valid"""
        # Setup mocks
        mock_query.return_value = {'status': 'OK'}
        mock_extract.return_value = {'distance': 1000, 'steps': [{'maneuver': 'ramp-right'}]}
        mock_calc.return_value = 900  # Close distance
        mock_check.return_value = True  # Has ramps
        
        result = self.validator.validate_merge_instance(self.merge_data, self.route)
        
        self.assertTrue(result['valid'])
        self.assertTrue(result['distance_valid'])
        self.assertTrue(result['uses_ramps'])
        self.assertFalse(result['rejected'])
        self.assertIn('Valid', result['reason'])
    
    @patch.object(GoogleDirectionsValidator, '_query_directions')
    @patch.object(GoogleDirectionsValidator, '_calculate_merge_distance')
    @patch.object(GoogleDirectionsValidator, '_extract_route_info')
    @patch.object(GoogleDirectionsValidator, '_check_highway_ramps')
    def test_validate_merge_instance_success_distance_only(self, mock_check, mock_extract, mock_calc, mock_query):
        """Test successful validation when only distance is valid (3x tolerance)"""
        # Setup mocks
        mock_query.return_value = {'status': 'OK'}
        mock_extract.return_value = {'distance': 3000, 'steps': []}  # 3x the distance
        mock_calc.return_value = 1000
        mock_check.return_value = False  # No ramps
        
        result = self.validator.validate_merge_instance(self.merge_data, self.route)
        
        self.assertTrue(result['valid'])
        self.assertTrue(result['distance_valid'])  # Within 3x tolerance
        self.assertFalse(result['uses_ramps'])
        self.assertFalse(result['rejected'])
    
    @patch.object(GoogleDirectionsValidator, '_query_directions')
    @patch.object(GoogleDirectionsValidator, '_calculate_merge_distance')
    @patch.object(GoogleDirectionsValidator, '_extract_route_info')
    @patch.object(GoogleDirectionsValidator, '_check_highway_ramps')
    def test_validate_merge_instance_success_ramps_only(self, mock_check, mock_extract, mock_calc, mock_query):
        """Test successful validation when only ramps are detected"""
        # Setup mocks
        mock_query.return_value = {'status': 'OK'}
        mock_extract.return_value = {'distance': 5000, 'steps': [{'maneuver': 'ramp-left'}]}
        mock_calc.return_value = 1000  # 5x difference (beyond tolerance)
        mock_check.return_value = True  # Has ramps
        
        result = self.validator.validate_merge_instance(self.merge_data, self.route)
        
        self.assertTrue(result['valid'])
        self.assertFalse(result['distance_valid'])  # Beyond 3x tolerance
        self.assertTrue(result['uses_ramps'])  # But has ramps, so valid
        self.assertFalse(result['rejected'])
    
    @patch.object(GoogleDirectionsValidator, '_query_directions')
    @patch.object(GoogleDirectionsValidator, '_calculate_merge_distance')
    @patch.object(GoogleDirectionsValidator, '_extract_route_info')
    @patch.object(GoogleDirectionsValidator, '_check_highway_ramps')
    def test_validate_merge_instance_rejected(self, mock_check, mock_extract, mock_calc, mock_query):
        """Test rejected validation when both conditions fail"""
        # Setup mocks
        mock_query.return_value = {'status': 'OK'}
        mock_extract.return_value = {'distance': 6000, 'steps': []}
        mock_calc.return_value = 1000  # 6x difference (beyond 3x tolerance)
        mock_check.return_value = False  # No ramps
        
        result = self.validator.validate_merge_instance(self.merge_data, self.route)
        
        self.assertFalse(result['valid'])
        self.assertFalse(result['distance_valid'])
        self.assertFalse(result['uses_ramps'])
        self.assertTrue(result['rejected'])
        self.assertIn('Rejected', result['reason'])
    
    @patch.object(GoogleDirectionsValidator, '_query_directions')
    def test_validate_merge_instance_api_failure(self, mock_query):
        """Test validation when API request fails"""
        mock_query.return_value = None
        
        result = self.validator.validate_merge_instance(self.merge_data, self.route)
        
        self.assertFalse(result['valid'])
        self.assertTrue(result['rejected'])
        self.assertEqual(result['reason'], 'API request failed')
    
    @patch.object(GoogleDirectionsValidator, '_query_directions')
    @patch.object(GoogleDirectionsValidator, '_extract_route_info')
    def test_validate_merge_instance_no_route(self, mock_extract, mock_query):
        """Test validation when Google returns no route"""
        mock_query.return_value = {'status': 'OK'}
        mock_extract.return_value = {'distance': 0, 'steps': []}
        
        result = self.validator.validate_merge_instance(self.merge_data, self.route)
        
        self.assertFalse(result['valid'])
        self.assertTrue(result['rejected'])
        self.assertEqual(result['reason'], 'No route found')
    
    @patch.object(GoogleDirectionsValidator, '_query_directions')
    @patch.object(GoogleDirectionsValidator, '_calculate_merge_distance')
    @patch.object(GoogleDirectionsValidator, '_extract_route_info')
    @patch.object(GoogleDirectionsValidator, '_check_highway_ramps')
    def test_validate_merge_instance_zero_distance(self, mock_check, mock_extract, mock_calc, mock_query):
        """Test validation with zero detected distance"""
        mock_query.return_value = {'status': 'OK'}
        mock_extract.return_value = {'distance': 100, 'steps': []}
        mock_calc.return_value = 0  # Zero distance (edge case)
        mock_check.return_value = False
        
        result = self.validator.validate_merge_instance(self.merge_data, self.route)
        
        # With zero distance, ratio calculation should handle it gracefully
        self.assertIn('distance_ratio', result)
        self.assertEqual(result['detected_distance'], 0)
    
    @patch.object(GoogleDirectionsValidator, '_query_directions')
    @patch.object(GoogleDirectionsValidator, '_calculate_merge_distance')
    @patch.object(GoogleDirectionsValidator, '_extract_route_info')
    @patch.object(GoogleDirectionsValidator, '_check_highway_ramps')
    def test_validate_merge_instance_response_structure(self, mock_check, mock_extract, mock_calc, mock_query):
        """Test that validation returns all expected fields"""
        mock_query.return_value = {'status': 'OK'}
        mock_extract.return_value = {'distance': 1000, 'steps': [{'maneuver': 'ramp-right'}]}
        mock_calc.return_value = 950
        mock_check.return_value = True
        
        result = self.validator.validate_merge_instance(self.merge_data, self.route)
        
        # Check all expected fields are present
        required_fields = [
            'valid', 'distance_valid', 'uses_ramps', 'detected_distance',
            'google_distance', 'distance_ratio', 'route_steps', 'rejected', 'reason'
        ]
        for field in required_fields:
            self.assertIn(field, result)
        
        # Check field types
        self.assertIsInstance(result['valid'], bool)
        self.assertIsInstance(result['distance_valid'], bool)
        self.assertIsInstance(result['uses_ramps'], bool)
        self.assertIsInstance(result['detected_distance'], (int, float))
        self.assertIsInstance(result['google_distance'], (int, float))
        self.assertIsInstance(result['distance_ratio'], (int, float))
        self.assertIsInstance(result['route_steps'], int)
        self.assertIsInstance(result['rejected'], bool)
        self.assertIsInstance(result['reason'], str)


if __name__ == '__main__':
    unittest.main()
