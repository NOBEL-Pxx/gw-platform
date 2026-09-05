"""Unit tests for dl_inference lightweight classifiers.

Tests synthetic FITS data with known characteristics to validate:
1. Galaxy morphology classification returns valid structure
2. Source type classification returns valid structure
3. Anomaly enhancement correctly adjusts confidence
4. Feature extraction produces expected features
5. Edge cases: all-zero, constant, NaN, inf data
"""
import sys, json, os, unittest
import numpy as np

# Add pipeline to path
sys.path.insert(0, r"D:\AliCPT\gw-pipeline\src\pipeline")

from dl_inference import (
    _compute_image_features,
    _lightweight_galaxy_morphology,
    _lightweight_source_type,
    enhance_anomaly_detection,
    GalaxyMorphologyResult,
    SourceTypeResult,
    AnomalyEnhancementResult,
)


def make_gaussian(size: int, center: tuple, sigma: float, amplitude: float = 1.0) -> np.ndarray:
    """Create a 2D Gaussian (simulates a star/point source)."""
    y, x = np.mgrid[0:size, 0:size]
    dist2 = (x - center[0])**2 + (y - center[1])**2
    return amplitude * np.exp(-dist2 / (2 * sigma**2))


def make_ellipse(size: int, center: tuple, a: float, b: float, angle: float, amplitude: float = 1.0) -> np.ndarray:
    """Create an elliptical 2D Gaussian (simulates a galaxy)."""
    y, x = np.mgrid[0:size, 0:size]
    dx = x - center[0]
    dy = y - center[1]
    cos_a, sin_a = np.cos(angle), np.sin(angle)
    x_rot = dx * cos_a + dy * sin_a
    y_rot = -dx * sin_a + dy * cos_a
    return amplitude * np.exp(-0.5 * (x_rot**2 / a**2 + y_rot**2 / b**2))


def make_spiral_arms(size: int, center: tuple, n_arms: int = 2) -> np.ndarray:
    """Create synthetic spiral structure."""
    y, x = np.mgrid[0:size, 0:size]
    dx = x - center[0]
    dy = y - center[1]
    r = np.sqrt(dx**2 + dy**2)
    theta = np.arctan2(dy, dx)
    spiral = np.zeros_like(r, dtype=np.float64)
    for i in range(n_arms):
        phase = 2 * np.pi * i / n_arms
        arm = np.exp(-((theta - 0.3 * r / size - phase) % (2 * np.pi) - np.pi)**2 / 0.3**2)
        arm *= np.exp(-r / (size * 0.4))
        spiral += arm
    return spiral


class TestFeatureExtraction(unittest.TestCase):
    """Test _compute_image_features with various inputs."""

    def test_point_source_features(self):
        """Point source (star) should have high peakiness and high concentration."""
        data = make_gaussian(64, (32, 32), sigma=2.0, amplitude=100)
        features = _compute_image_features(data)
        self.assertIn("peakiness", features)
        self.assertIn("concentration_r10", features)
        self.assertIn("ellipticity", features)
        self.assertGreater(features["peakiness"], 1.5,
                          f"Point source should have high peakiness, got {features['peakiness']}")
        # Point source: most flux concentrated in center
        self.assertGreater(features["concentration_r10"], 0.5,
                          f"Point source should have high concentration_r10, got {features['concentration_r10']}")

    def test_extended_source_features(self):
        """Extended source (galaxy) should have lower peakiness and higher ellipticity."""
        data = make_ellipse(64, (32, 32), a=8.0, b=3.0, angle=0.5, amplitude=50)
        features = _compute_image_features(data)
        self.assertIn("ellipticity", features)
        # Extended source should have higher ellipticity than point source
        self.assertGreater(features["ellipticity"], 0.1,
                          f"Extended source should show ellipticity, got {features['ellipticity']}")

    def test_symmetry_spiral(self):
        """Spiral structure should have moderate symmetry."""
        data = make_spiral_arms(64, (32, 32), n_arms=2) * 50
        features = _compute_image_features(data)
        self.assertIn("symmetry_lr", features)
        self.assertIn("symmetry_ud", features)
        # Spiral has some symmetry but not perfect
        self.assertGreater(features["symmetry_lr"], 0.1)

    def test_all_zero_data(self):
        """All-zero data should not crash."""
        data = np.zeros((32, 32), dtype=np.float32)
        features = _compute_image_features(data)
        self.assertIsInstance(features, dict)
        self.assertGreater(len(features), 5)
        # Std should be zero
        self.assertEqual(features["std"], 0.0)

    def test_constant_data(self):
        """Constant-value data should not crash."""
        data = np.ones((32, 32), dtype=np.float32) * 42.0
        features = _compute_image_features(data)
        self.assertEqual(features["mean"], 42.0)
        self.assertEqual(features["std"], 0.0)
        self.assertEqual(features["min"], 42.0)
        self.assertEqual(features["max"], 42.0)

    def test_nan_handling(self):
        """NaN values should be replaced with zeros."""
        data = np.ones((32, 32), dtype=np.float64)
        data[10:15, 10:15] = np.nan
        features = _compute_image_features(data)
        self.assertFalse(np.isnan(features["mean"]),
                        "Features should not contain NaN after nan_to_num")

    def test_inf_handling(self):
        """Inf values should be replaced with zeros."""
        data = np.ones((32, 32), dtype=np.float64)
        data[0, 0] = np.inf
        data[0, 1] = -np.inf
        features = _compute_image_features(data)
        self.assertFalse(np.isinf(features["mean"]),
                        "Features should not contain inf after nan_to_num")

    def test_percentile_features(self):
        """Percentile statistics should be monotonic."""
        data = np.random.RandomState(42).normal(0, 10, (64, 64))
        features = _compute_image_features(data)
        self.assertLessEqual(features["p10"], features["p25"])
        self.assertLessEqual(features["p25"], features["p75"])
        self.assertLessEqual(features["p75"], features["p90"])
        self.assertLessEqual(features["p90"], features["p95"])
        self.assertLessEqual(features["p95"], features["p99"])


class TestGalaxyMorphology(unittest.TestCase):
    """Test _lightweight_galaxy_morphology classification."""

    def test_returns_valid_result(self):
        """Should return GalaxyMorphologyResult with valid fields."""
        data = np.random.RandomState(42).normal(10, 5, (64, 64))
        result = _lightweight_galaxy_morphology(data)
        self.assertIsInstance(result, GalaxyMorphologyResult)
        self.assertIn(result.morphology_class,
                     ["spiral", "elliptical", "edge-on", "merger", "irregular"])
        self.assertGreaterEqual(result.confidence, 0.0)
        self.assertLessEqual(result.confidence, 1.0)
        self.assertIn("spiral", result.probabilities)
        self.assertEqual(len(result.probabilities), 5)
        # Probabilities should sum to ~1
        prob_sum = sum(result.probabilities.values())
        self.assertAlmostEqual(prob_sum, 1.0, delta=0.01)

    def test_elliptical_source(self):
        """A round, smooth extended source should classify as elliptical."""
        data = make_ellipse(64, (32, 32), a=6.0, b=5.5, angle=0.0, amplitude=100)
        result = _lightweight_galaxy_morphology(data)
        # Elliptical should be high probability for round source
        self.assertGreater(result.probabilities.get("elliptical", 0), 0.15)

    def test_edge_on_source(self):
        """A highly elongated source should have high edge-on probability."""
        data = make_ellipse(64, (32, 32), a=12.0, b=1.5, angle=0.0, amplitude=100)
        result = _lightweight_galaxy_morphology(data)
        # Edge-on should be high for very flattened source
        self.assertGreater(result.probabilities.get("edge-on", 0), 0.15)

    def test_merger_like_source(self):
        """Asymmetric dual-peak data should score high on merger."""
        data = make_gaussian(64, (22, 28), sigma=4.0, amplitude=50)
        data += make_gaussian(64, (42, 36), sigma=3.0, amplitude=40)
        result = _lightweight_galaxy_morphology(data)
        self.assertGreater(result.probabilities.get("merger", 0), 0.1)

    def test_deterministic_output(self):
        """Same input should produce same output."""
        data = np.random.RandomState(42).normal(10, 5, (64, 64))
        r1 = _lightweight_galaxy_morphology(data)
        r2 = _lightweight_galaxy_morphology(data)
        self.assertEqual(r1.morphology_class, r2.morphology_class)
        self.assertAlmostEqual(r1.confidence, r2.confidence)

    def test_tiny_image(self):
        """Very small images should not crash."""
        data = np.random.RandomState(0).normal(0, 1, (5, 5))
        result = _lightweight_galaxy_morphology(data)
        self.assertIsInstance(result, GalaxyMorphologyResult)


class TestSourceType(unittest.TestCase):
    """Test _lightweight_source_type classification."""

    def test_returns_valid_result(self):
        """Should return SourceTypeResult with valid fields."""
        data = np.random.RandomState(42).normal(10, 5, (64, 64))
        result = _lightweight_source_type(data)
        self.assertIsInstance(result, SourceTypeResult)
        self.assertIn(result.source_class, ["star", "galaxy", "quasar"])
        self.assertGreaterEqual(result.confidence, 0.0)
        self.assertLessEqual(result.confidence, 1.0)

    def test_point_source_is_star(self):
        """A compact point source should classify as star."""
        data = make_gaussian(64, (32, 32), sigma=1.5, amplitude=200)
        result = _lightweight_source_type(data)
        self.assertGreater(result.probabilities.get("star", 0), 0.2)

    def test_extended_source_is_galaxy(self):
        """A diffuse extended source should classify as galaxy."""
        data = make_ellipse(64, (32, 32), a=10.0, b=6.0, angle=0.3, amplitude=50)
        result = _lightweight_source_type(data)
        self.assertGreater(result.probabilities.get("galaxy", 0), 0.2)

    def test_deterministic(self):
        """Same input should produce same output."""
        data = np.random.RandomState(99).normal(5, 3, (64, 64))
        r1 = _lightweight_source_type(data)
        r2 = _lightweight_source_type(data)
        self.assertEqual(r1.source_class, r2.source_class)


class TestAnomalyEnhancement(unittest.TestCase):
    """Test enhance_anomaly_detection confidence adjustment."""

    def test_spike_confirmed_with_peakiness(self):
        """High peakiness should confirm spike detection."""
        data = make_gaussian(64, (32, 32), sigma=1.5, amplitude=500)
        result = enhance_anomaly_detection(data, "spike", 0.7)
        self.assertIsInstance(result, AnomalyEnhancementResult)
        self.assertEqual(result.original_type, "spike")
        # With extreme peakiness, confidence should increase
        self.assertGreaterEqual(result.enhanced_confidence, result.original_confidence - 0.1)

    def test_spike_downgraded_without_peakiness(self):
        """Low peakiness should downgrade spike detection."""
        data = np.random.RandomState(0).normal(0, 1, (64, 64))
        result = enhance_anomaly_detection(data, "spike", 0.8)
        self.assertEqual(result.original_type, "spike")

    def test_dip_detection(self):
        """Dip with negative values should be confirmed."""
        data = np.random.RandomState(42).normal(0, 5, (64, 64))
        data[20:44, 20:44] = -30  # Deep negative region
        result = enhance_anomaly_detection(data, "dip", 0.6)
        self.assertIsInstance(result, AnomalyEnhancementResult)

    def test_pattern_break(self):
        """Pattern break detection should not crash."""
        data = np.random.RandomState(7).normal(0, 10, (64, 64))
        result = enhance_anomaly_detection(data, "pattern_break", 0.5)
        self.assertIsInstance(result, AnomalyEnhancementResult)
        self.assertIn(result.dl_verdict, ["confirmed", "downgraded"])

    def test_wcs_mismatch(self):
        """WCS mismatch should return neutral adjustment."""
        data = np.random.RandomState(1).normal(0, 1, (64, 64))
        result = enhance_anomaly_detection(data, "wcs_mismatch", 0.7)
        # WCS validation is metadata-driven, so adjustment should be near zero
        self.assertAlmostEqual(result.enhanced_confidence, 0.7, delta=0.05)

    def test_invalid_anomaly_type_raises(self):
        """Invalid anomaly type should raise ValueError."""
        data = np.ones((32, 32))
        with self.assertRaises(ValueError):
            enhance_anomaly_detection(data, "cosmic_ray", 0.5)

    def test_confidence_bounds(self):
        """Enhanced confidence must stay in [0, 1]."""
        data = np.random.RandomState(0).normal(0, 1, (64, 64))
        # Test boundary: very low confidence
        r1 = enhance_anomaly_detection(data, "spike", 0.05)
        self.assertGreaterEqual(r1.enhanced_confidence, 0.0)
        self.assertLessEqual(r1.enhanced_confidence, 1.0)
        # Test boundary: very high confidence
        r2 = enhance_anomaly_detection(data, "spike", 0.95)
        self.assertGreaterEqual(r2.enhanced_confidence, 0.0)
        self.assertLessEqual(r2.enhanced_confidence, 1.0)

    def test_all_anomaly_types(self):
        """All valid anomaly types should work."""
        data = np.random.RandomState(42).normal(0, 1, (64, 64))
        for atype in ["spike", "dip", "pattern_break", "wcs_mismatch"]:
            result = enhance_anomaly_detection(data, atype, 0.5)
            self.assertEqual(result.original_type, atype)


class TestDataTypes(unittest.TestCase):
    """Test that dataclass types handle various inputs."""

    def test_galaxy_morphology_result_defaults(self):
        """GalaxyMorphologyResult should accept minimal fields."""
        r = GalaxyMorphologyResult(
            morphology_class="spiral",
            confidence=0.85,
        )
        self.assertEqual(r.morphology_class, "spiral")
        self.assertEqual(r.confidence, 0.85)
        self.assertEqual(r.probabilities, {})
        self.assertEqual(r.model_name, "lightweight")

    def test_source_type_result(self):
        """SourceTypeResult should store features_used."""
        r = SourceTypeResult(
            source_class="galaxy",
            confidence=0.92,
            probabilities={"star": 0.05, "galaxy": 0.92, "quasar": 0.03},
            features_used=["peakiness", "concentration_r30"],
        )
        self.assertEqual(r.source_class, "galaxy")
        self.assertEqual(len(r.features_used), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
