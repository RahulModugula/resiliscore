"""Checks raster decoding independently of downloaded source data."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

import numpy as np
import rasterio
from rasterio.transform import from_origin

spec = importlib.util.spec_from_file_location('manhattan_dem', Path(__file__).with_name('build-manhattan-dem.py'))
dem = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dem)


class DecodeTests(unittest.TestCase):
    def test_north_first_rows_become_south_first_pixel_centers_and_nodata_stays_unknown(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'sample.tif'
            with rasterio.open(path, 'w', driver='GTiff', width=3, height=2, count=1, dtype='float32', crs='EPSG:4326', transform=from_origin(10, 22, 1, 1), nodata=-9999) as dataset:
                dataset.write(np.array([[11, 0, 13], [21, -9999, float('nan')]], dtype='float32'), 1)
            geometry = {'type': 'Polygon', 'coordinates': [[[10, 20], [13, 20], [13, 22], [10, 22], [10, 20]]]}
            values, centers, metadata = dem.decode(path, [geometry])
        self.assertEqual(centers, [10.5, 20.5, 12.5, 21.5])
        self.assertEqual(metadata['extent'], [10, 20, 13, 22])
        self.assertEqual(values[0, 0], 21)
        self.assertTrue(np.isnan(values[0, 1]))
        self.assertTrue(np.isnan(values[0, 2]))
        self.assertEqual(values[1].tolist(), [11, 0, 13])
        grid = dem.crop(values, centers, None)
        self.assertEqual(grid['elevationsM'], [21, None, None, 11, 0, 13])
        self.assertEqual(grid['raster']['extent'], [10, 20, 13, 22])

    def test_overview_subsampling_retains_actual_shared_samples_instead_of_averaging_hills(self):
        values = np.arange(36, dtype='float64').reshape(6, 6)
        values[0, 0] = np.nan
        grid = dem.crop(values, [0.5, 0.5, 5.5, 5.5], None, stride=5)
        self.assertEqual(grid['bounds'], [0.5, 0.5, 5.5, 5.5])
        self.assertEqual(grid['elevationsM'], [None, 5, 30, 35])
        self.assertEqual(grid['width'], 2)
        self.assertEqual(grid['height'], 2)


if __name__ == '__main__':
    unittest.main()
