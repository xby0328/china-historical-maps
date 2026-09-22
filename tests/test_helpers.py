"""Synthetic-only tests. No course files or network access required."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import china_map as cm
import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import box


class MapHelpersTest(unittest.TestCase):
    def test_codes_and_duplicate_input(self):
        self.assertEqual(cm.normalize_codes(pd.Series([110000.0])).iloc[0], '110000')
        with self.assertRaises(ValueError):
            cm.normalize_codes(pd.Series(['1100']))
        g=self.provinces()
        with self.assertRaises(ValueError):
            cm.join_values(g,pd.DataFrame({'code':['110000','110000'],'value':[1,2]}),'prov','code','value')

    def provinces(self):
        return gpd.GeoDataFrame({'省代码':['110000','120000','150000','150000'],
            '省':['北京市','天津市','内蒙古自治区','中朝共有']},
            geometry=[box(i,0,i+1,1) for i in range(4)],crs=cm.AEA)

    def test_missing_zero_and_source_conflict(self):
        table=pd.DataFrame({'code':['110000','150000','999999'],'value':[0,5,8]})
        g,audit,_,_=cm.join_values(self.provinces(),table,'prov','code','value')
        self.assertEqual(g.loc[g['省']=='北京市','_value'].iloc[0],0)
        self.assertTrue(g.loc[g['省'].isin(['天津市','中朝共有']),'_value'].isna().all())
        self.assertEqual(audit['unmatched_input_codes'],['999999'])

    def test_unnamed_duplicate_geometry_is_not_colored(self):
        g=gpd.GeoDataFrame({'PAC':['710024','710024'],'NAME':['苗栗县',None]},
            geometry=[box(0,0,1,1),box(1,0,2,1)],crs=cm.AEA)
        joined,*_=cm.join_values(g,pd.DataFrame({'code':['710024'],'value':[10]}),'county','code','value')
        self.assertTrue(joined.loc[joined['NAME'].isna(),'_value'].isna().all())

    def test_norm(self):
        for values in ([0,1],[-1,2],[]):
            with self.assertRaises(ValueError): cm.make_norm(values,'log')
        n=cm.make_norm([5,5],'log')
        self.assertLess(n.vmin,5)
        self.assertGreater(n.vmax,5)
        d=cm.make_norm([0,10,20],'discrete',[0,10,20])
        self.assertEqual(list(d([0,9,10,20])),[0,0,1,1])

    def test_inset_clips_before_transform(self):
        full=gpd.GeoDataFrame(geometry=[box(-1e7,-1e7,1e7,1e7)],crs=cm.AEA)
        poly=gpd.GeoDataFrame(geometry=[box(100000,300000,200000,400000)],crs=cm.AEA)
        overlay=cm.display_overlay(poly,full,full,'mini')
        self.assertEqual(len(overlay),2)
        self.assertTrue(np.allclose(overlay.iloc[1].geometry.bounds,[2160000,1825139,2200000,1865139]))

    def test_raster_mask_and_transform(self):
        import rasterio
        from rasterio.transform import from_origin
        from affine import Affine
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'synthetic.tif'
            data=np.array([[0,-1,2,3,4],[5,-9999,7,8,9],[10,11,12,13,14]],dtype='float32')
            with rasterio.open(path,'w',driver='GTiff',width=5,height=3,count=1,dtype='float32',
                               crs='EPSG:4326',transform=from_origin(100,40,1,1),nodata=-9999) as dst:
                dst.write(data,1)
            g,_=cm.raster_features(path,'raster-points',100,'nearest')
            self.assertEqual(len(g),14)
            self.assertIn(0,g['_value'].values)
            self.assertIn(-1,g['_value'].values)
            self.assertNotIn(-9999,g['_value'].values)
            _,a=cm.raster_features(path,'raster-points',4,'average')
            height,width=a['display_shape']
            self.assertLessEqual(width*height,4)
            tr=Affine(*a['transform'][:6])
            self.assertTrue(np.allclose(tr*(width,height),(105,37)))
            polygons,_=cm.raster_features(path,'raster-polygons',100,'nearest')
            self.assertAlmostEqual(sum(x.area for x in polygons.geometry),14)


if __name__=='__main__':
    unittest.main()
