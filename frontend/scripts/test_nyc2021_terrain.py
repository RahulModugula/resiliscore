"""Scientific checks of interpolation using the retained raw 2021 probes."""
import io
from pathlib import Path
import runpy
import unittest
import zipfile

import numpy as np
from pyproj import Transformer

MODULE = runpy.run_path(str(Path(__file__).with_name("build-nyc2021-terrain.py")))
ROOT = Path(__file__).resolve().parents[2]


class TerrainPrototypeTest(unittest.TestCase):
    def test_only_ground_and_key_points_are_used_and_duplicates_keep_observed_upper_median(self):
        records = np.zeros(6, dtype=MODULE["EVAL"]["RECORD"])
        records["classification"] = [2, 8, 2, 7, 18, 6]
        records["flags"][2] = 4
        records["Z"] = [1, 2, 3, 4, 5, 6]
        points = MODULE["ground_points"](records, np.ones(3), np.zeros(3))
        np.testing.assert_allclose(points[:, 2], np.array([1, 2]) * MODULE["FT"])
        duplicates = np.array([[0, 0, 0], [0, 0, 10], [2, 0, 10], [0, 2, 10]], dtype=float)
        np.testing.assert_allclose(MODULE["interpolate"](duplicates, [[0, 0], [.5, .5]])[0], [10, 10])

    def test_real_depression_excludes_noise_without_filling_unknown_building_ground(self):
        project = Transformer.from_crs(4326, 6539, always_xy=True)
        with zipfile.ZipFile(ROOT / "docs/validation/nyc2021-evidence.zip") as archive:
            for label, point in MODULE["EVAL"]["PROBES"].items():
                name = next(n for n in archive.namelist() if n.endswith("." + label + ".npz"))
                with np.load(io.BytesIO(archive.read(name))) as d:
                    r = d["records"]
                    xyz = MODULE["ground_points"](r, d["scales"], d["offsets"])
                    q = np.array(project.transform(*point)) * MODULE["FT"]
                    height, distance = MODULE["interpolate"](xyz, q)
                    if label == "2017_depression":
                        self.assertTrue((r["classification"] == 7).any())
                        self.assertGreater(height[0], 6)
                        self.assertLess(height[0], 6.3)
                        self.assertLess(distance[0], 3)
                    elif label == "selected_building":
                        self.assertTrue(np.isnan(height[0]), "ground beneath the building must remain unknown")
                        self.assertGreater(distance[0], 10)
                    else:
                        self.assertGreater(height[0], 2.7)
                        self.assertLess(height[0], 3)

    def test_long_and_skinny_triangles_do_not_bridge_unsupported_ground(self):
        points = np.array([[0, 0, 1], [12, 0, 1], [0, 12, 1]], dtype=float)
        height, _ = MODULE["interpolate"](points, [[1, 1], [50, 50]])
        self.assertTrue(np.isnan(height).all())
        skinny = np.array([[0, 0, 1], [4, 0, 1], [2, .01, 1]], dtype=float)
        self.assertTrue(np.isnan(MODULE["interpolate"](skinny, [[2, .005]])[0]).all())

    def test_plane_values_and_source_points_are_preserved(self):
        points = np.array([[0, 0, 1], [2, 0, 3], [0, 2, 5], [2, 2, 7]], dtype=float)
        before = points.copy()
        height, _ = MODULE["interpolate"](points, [[.5, .5], [1, 1]])
        np.testing.assert_allclose(height, [2.5, 4])
        np.testing.assert_array_equal(points, before)


if __name__ == "__main__":
    unittest.main()
