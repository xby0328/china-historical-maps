"""Reusable local mapping helpers; course assets stay in their original directory."""
from pathlib import Path
import argparse
import json
import math
import os
import re

import geopandas as gpd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import colors, font_manager
from matplotlib.cm import ScalarMappable
from matplotlib.patches import Patch
import numpy as np
import pandas as pd
from pyproj import CRS
from shapely.geometry import box

DEFAULT_ROOT = Path('course-data')
AEA = '+proj=aea +lat_0=0 +lon_0=105 +lat_1=25 +lat_2=47 +datum=WGS84 +units=m +no_defs'
KEYS = {'prov': '省代码', 'city': '市代码', 'county': 'PAC'}
NAMES = {'prov': '省', 'city': '市', 'county': 'NAME'}
INSET_BOX = box(120000, 320000, 1766004.1, 2557786.0)


def resolve_root(value=None):
    root = Path(value or os.environ.get('CHINA_MAP_COURSE_ROOT', DEFAULT_ROOT))
    if (root / 'provmapdata').is_dir():
        return root.resolve()
    choices = [p for p in root.iterdir() if p.is_dir() and (p / 'provmapdata').is_dir()] if root.is_dir() else []
    if len(choices) == 1:
        return choices[0].resolve()
    raise FileNotFoundError('找不到课程数据根目录；使用 --course-root 或 CHINA_MAP_COURSE_ROOT 指定含 provmapdata 的目录（默认 ./course-data）')


def inventory(root):
    result = {}
    for level in KEYS:
        for version in ['mini', 'long']:
            paths = sorted((root / f'{level}mapdata' / f'{version}shp').glob(f'china{level}*{version}/china{level}*{version}.shp'))
            years = [int(re.search(r'(\d{4})', p.stem)[1]) for p in paths]
            missing_files = [str(p.with_suffix(s)) for p in paths for s in ['.shx', '.dbf', '.prj'] if not p.with_suffix(s).exists()]
            missing_lines = [str(p.with_stem(p.stem + '_line')) for p in paths if not p.with_stem(p.stem + '_line').exists()]
            result[f'{level}-{version}'] = {'years': years, 'count': len(years), 'missing_sidecars': missing_files, 'missing_lines': missing_lines}
    return result


def load_map(root, level, year, version, line=False):
    stem = f'china{level}{year}{version}'
    path = root / f'{level}mapdata' / f'{version}shp' / stem / (stem + ('_line' if line else '') + '.shp')
    for suffix in ['.shp', '.shx', '.dbf', '.prj']:
        if not path.with_suffix(suffix).is_file():
            raise FileNotFoundError(path.with_suffix(suffix))
    g = gpd.read_file(path)
    if g.crs is None or not CRS(g.crs).equals(CRS(AEA), ignore_axis_order=True):
        raise ValueError(f'底图投影与课程版式不同，不能套用 mini 参数：{path}')
    if not line:
        g = g.loc[g[KEYS[level]].notna()].copy()
        g[KEYS[level]] = normalize_codes(g[KEYS[level]])
    if g.empty or g.geometry.isna().any() or g.geometry.is_empty.any() or not g.is_valid.all():
        raise ValueError(f'空或无效几何需要先诊断：{path}')
    return g


def normalize_codes(series):
    values = series.astype('string').str.strip().str.replace(r'\.0+$', '', regex=True)
    invalid = values.isna() | ~values.str.fullmatch(r'\d{6}', na=False)
    if invalid.any():
        raise ValueError(f'行政代码必须为六位整数，不猜测短代码或缺失值：{series[invalid].head(10).tolist()}')
    return values


def map_audit(g, level):
    key, name = KEYS[level], NAMES[level]
    dup = g.loc[g[key].duplicated(False), [key, name]].astype(object)
    duplicates = dup.where(pd.notna(dup), None).to_dict('records')
    return {'features': len(g), 'unique_codes': g[key].nunique(), 'columns': list(g.columns),
            'duplicate_code_features': duplicates, 'missing_names': int(g[name].isna().sum()),
            'bounds': g.total_bounds.tolist(), 'crs': str(g.crs)}


def join_values(g, table, level, key, value):
    if key == value:
        raise ValueError('代码列与指标列不能相同')
    t = table[[key, value]].copy()
    t.columns = ['_key', '_value']
    t['_key'] = normalize_codes(t['_key'])
    if t['_key'].duplicated().any():
        raise ValueError('统计表存在重复行政代码；先筛年份或按明确口径聚合')
    raw = t['_value']
    t['_value'] = pd.to_numeric(raw, errors='coerce')
    if (raw.notna() & t['_value'].isna()).any() or np.isinf(t['_value'].dropna()).any():
        raise ValueError('指标含非数值或无穷值，需要先核查')
    g = g.copy()
    mk, mn = KEYS[level], NAMES[level]
    conflicts = g.groupby(mk)[mn].nunique(dropna=False)
    conflicts = conflicts[conflicts > 1].index
    special = g[mk].isin(conflicts) & (g[mn].isna() | g[mn].astype('string').str.contains('共有', na=False))
    regular = g.loc[~special]
    if (regular.groupby(mk)[mn].nunique(dropna=False) > 1).any():
        raise ValueError('底图同码异名冲突，需要有证据的映射，不能静默合并')
    g['_special'] = special
    g = g.merge(t, left_on=mk, right_on='_key', how='left', validate='many_to_one', indicator=True)
    g.loc[g['_special'], '_value'] = np.nan
    unmatched_data = t.loc[~t['_key'].isin(g[mk])]
    unmatched_map = g.loc[g['_merge'] == 'left_only', [mk, mn]].drop_duplicates()
    audit = {'input_rows': len(t), 'matched_input_codes': int(t['_key'].isin(g[mk]).sum()),
             'unmatched_input_codes': unmatched_data['_key'].tolist(),
             'unmatched_map_codes': unmatched_map.to_dict('records'),
             'missing_input_values': int(t['_value'].isna().sum()),
             'special_features_without_value': int(special.sum())}
    return g, audit, unmatched_data, unmatched_map


def display_overlay(g, long_map, display_map, version):
    """Clip in real coordinates first; display duplicates are never analysis data."""
    if g.crs is None:
        raise ValueError('叠加层缺 CRS')
    real = gpd.clip(g.to_crs(AEA), long_map.geometry.union_all())
    if version == 'long' or real.empty:
        return real
    small = gpd.clip(real, INSET_BOX)
    if not small.empty:
        small = small.copy()
        small.geometry = small.geometry.scale(0.5, 0.5, origin=(0, 0)).translate(2100000, 1665139)
    # Main original features are cropped to the real footprint represented in mini.
    footprint = display_map.geometry.union_all()
    main = gpd.clip(real, footprint)
    return gpd.GeoDataFrame(pd.concat([main, gpd.clip(small, footprint)], ignore_index=True), crs=AEA)


def make_norm(values, scale='linear', bins=None, vmin=None, vmax=None):
    values = np.asarray(pd.Series(values).dropna(), dtype=float)
    if not len(values) or not np.isfinite(values).all():
        raise ValueError('没有可绘制的有限数值')
    low = float(values.min() if vmin is None else vmin)
    high = float(values.max() if vmax is None else vmax)
    if not np.isfinite([low, high]).all() or low > high:
        raise ValueError('色标范围无效')
    if scale == 'discrete':
        if bins is None or len(bins) < 2 or not np.isfinite(bins).all() or np.any(np.diff(bins) <= 0):
            raise ValueError('分段模式需要至少两个严格递增的有限断点')
        if values.min() < bins[0] or values.max() > bins[-1]:
            raise ValueError('数值超出分段断点范围')
        return colors.BoundaryNorm(bins, len(bins)-1, clip=True)
    if scale == 'log':
        if values.min() <= 0 or low <= 0:
            raise ValueError('log 模式要求全部有效值及下限严格大于零；请选择线性/分段或明确变换')
        if low == high:
            low, high = low / 1.01, high * 1.01
        return colors.LogNorm(low, high)
    if low == high:
        delta = max(abs(low)*0.01, 0.5)
        low, high = low-delta, high+delta
    return colors.Normalize(low, high)


def raster_features(path, mode, max_cells=100000, resampling='average'):
    import rasterio
    from rasterio.enums import Resampling
    from rasterio.features import shapes
    from affine import Affine
    if max_cells < 1:
        raise ValueError('max-cells 必须为正数')
    with rasterio.open(path) as src:
        if src.crs is None:
            raise ValueError('栅格缺 CRS')
        factor = max(1, math.sqrt(src.width*src.height/max_cells))
        width, height = max(1, int(src.width/factor)), max(1, int(src.height/factor))
        if width*height > max_cells:
            if width >= height: width = max(1, max_cells//height)
            else: height = max(1, max_cells//width)
        arr = src.read(1, out_shape=(height, width), masked=True, out_dtype='float32', resampling=Resampling[resampling])
        transform = src.transform * Affine.scale(src.width/width, src.height/height)
        data = np.asarray(arr.data, dtype=np.float32)
        valid = ~np.ma.getmaskarray(arr) & np.isfinite(data)
        audit = {'source_shape': [src.height, src.width], 'display_shape': [height, width],
                 'valid_cells': int(valid.sum()), 'resampling': resampling, 'crs': str(src.crs),
                 'nodata': str(src.nodata), 'transform': list(transform), 'bounds':list(src.bounds)}
        if not valid.any():
            raise ValueError('栅格没有有效像元')
        if mode == 'raster-points':
            rows, cols = np.where(valid)
            xs, ys = rasterio.transform.xy(transform, rows, cols)
            g = gpd.GeoDataFrame({'_value': data[rows, cols]}, geometry=gpd.points_from_xy(xs, ys), crs=src.crs)
        else:
            features = [{'type':'Feature','geometry':geom,'properties':{'_value':value}}
                        for geom, value in shapes(data, mask=valid, transform=transform)]
            g = gpd.GeoDataFrame.from_features(features, crs=src.crs)
    return g, audit


def read_table(path, sheet='0'):
    if Path(path).suffix.lower() == '.csv':
        return pd.read_csv(path, dtype='string')
    return pd.read_excel(path, sheet_name=int(sheet) if sheet.isdigit() else sheet)


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding='utf-8')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('mode', choices=['inventory','inspect','base','choropleth','points','raster-points','raster-polygons'])
    p.add_argument('--course-root')
    p.add_argument('--level', choices=list(KEYS), default='prov')
    p.add_argument('--year', type=int, default=2019)
    p.add_argument('--version', choices=['mini','long'], default='mini')
    p.add_argument('--table'); p.add_argument('--sheet', default='0')
    p.add_argument('--key'); p.add_argument('--value')
    p.add_argument('--lon', default='经度'); p.add_argument('--lat', default='纬度')
    p.add_argument('--point-crs', help='Explicitly confirmed coordinate CRS; does not correct GCJ/BD offsets')
    p.add_argument('--tif'); p.add_argument('--max-cells', type=int, default=100000)
    p.add_argument('--resampling', choices=['average','sum','nearest','mode'], default='average')
    p.add_argument('--scale', choices=['linear','log','discrete'], default='linear')
    p.add_argument('--bins'); p.add_argument('--vmin',type=float); p.add_argument('--vmax',type=float)
    p.add_argument('--cmap', default='YlGnBu'); p.add_argument('--title'); p.add_argument('--label')
    p.add_argument('--data-year'); p.add_argument('--source', default='底图：本地 RStata 课程数据')
    p.add_argument('--font'); p.add_argument('--out'); p.add_argument('--formats', default='png,pdf')
    p.add_argument('--dpi',type=int,default=300); p.add_argument('--overwrite', action='store_true')
    args=p.parse_args()
    root=resolve_root(args.course_root)
    if args.mode == 'inventory':
        print(json.dumps(inventory(root), ensure_ascii=False, indent=2)); return
    g=load_map(root,args.level,args.year,args.version)
    audit={'course_root':str(root), 'boundary_year':args.year,'data_year':args.data_year,
           'level':args.level,'version':args.version,'map':map_audit(g,args.level),'arguments':vars(args)}
    if args.mode == 'inspect':
        print(json.dumps(audit,ensure_ascii=False,indent=2,default=str)); return
    if not args.out:
        p.error('绘图模式需要 --out 输出前缀')
    prefix=Path(args.out).resolve()
    formats=args.formats.split(',')
    if any(f not in ['png','pdf','svg'] for f in formats):
        p.error('formats 仅支持 png,pdf,svg')
    suffixes=formats+['audit.json','matched.csv','unmatched_data.csv','unmatched_map.csv','invalid_points.csv']
    if not args.overwrite and any(Path(str(prefix)+'.'+s).exists() for s in suffixes):
        raise FileExistsError('输出前缀已存在；请换新名称，或明确使用 --overwrite')
    prefix.parent.mkdir(parents=True,exist_ok=True)
    font=Path(args.font) if args.font else root/'LXGWWenKai-Regular.ttf'
    if font.is_file():
        font_manager.fontManager.addfont(str(font))
        plt.rcParams['font.family']=font_manager.FontProperties(fname=font).get_name()
    else:
        plt.rcParams['font.family']=['Microsoft YaHei','SimHei','DejaVu Sans']
    plt.rcParams['axes.unicode_minus']=False
    plt.rcParams['pdf.fonttype']=42
    lines=load_map(root,'prov',args.year,args.version,line=True)
    lines=lines[lines['class'].isin(['九段线','海岸线']+(['小地图框格'] if args.version=='mini' else []))]
    overlay=None
    if args.mode=='choropleth':
        if not (args.table and args.key and args.value): p.error('choropleth 需要 table/key/value')
        g, audit['join'], ud, um=join_values(g,read_table(args.table,args.sheet),args.level,args.key,args.value)
        g.drop(columns='geometry').to_csv(str(prefix)+'.matched.csv',index=False,encoding='utf-8-sig')
        ud.to_csv(str(prefix)+'.unmatched_data.csv',index=False,encoding='utf-8-sig')
        um.to_csv(str(prefix)+'.unmatched_map.csv',index=False,encoding='utf-8-sig')
    elif args.mode=='points':
        if not args.table or not args.point_crs: p.error('points 需要 table 和已确认的 point-crs')
        t=read_table(args.table,args.sheet)
        x=pd.to_numeric(t[args.lon],errors='coerce'); y=pd.to_numeric(t[args.lat],errors='coerce')
        valid=np.isfinite(x)&np.isfinite(y)
        if CRS(args.point_crs).is_geographic: valid &= x.between(-180,180)&y.between(-90,90)
        t.loc[~valid].to_csv(str(prefix)+'.invalid_points.csv',index=False,encoding='utf-8-sig')
        overlay=gpd.GeoDataFrame(t.loc[valid].copy(),geometry=gpd.points_from_xy(x[valid],y[valid]),crs=args.point_crs)
        audit['points']={'input':len(t),'valid':int(valid.sum()),'invalid':int((~valid).sum())}
    elif args.mode.startswith('raster-'):
        if not args.tif: p.error('栅格模式需要 tif')
        overlay,audit['raster']=raster_features(args.tif,args.mode,args.max_cells,args.resampling)
    if overlay is not None:
        realmap=load_map(root,'prov',args.year,'long')
        displaymap=load_map(root,'prov',args.year,args.version)
        audit['overlay_features_before_clip']=len(overlay)
        real_overlay=gpd.clip(overlay.to_crs(AEA),realmap.geometry.union_all())
        audit['overlay_real_features_after_clip']=len(real_overlay)
        overlay=display_overlay(real_overlay,realmap,displaymap,args.version)
        audit['overlay_display_features']=len(overlay)
        if overlay.empty: raise ValueError('叠加层与底图没有交集，请核查坐标来源/CRS/范围')
    fig, ax=plt.subplots(figsize=(10,8 if args.version=='mini' else 10),layout='constrained')
    g.plot(ax=ax,color='#eeeeee',edgecolor='#737373',linewidth=0.18,zorder=1)
    thematic=g if args.mode=='choropleth' else overlay if args.mode.startswith('raster-') else None
    if thematic is not None:
        bins=[float(v) for v in args.bins.split(',')] if args.bins else None
        norm=make_norm(thematic['_value'],args.scale,bins,args.vmin,args.vmax)
        cmap=plt.colormaps[args.cmap]
        if args.scale=='discrete': cmap=cmap.resampled(len(bins)-1)
        good=thematic[thematic['_value'].notna()]
        kwargs={'markersize':0.6,'rasterized':True} if args.mode=='raster-points' else {'edgecolor':'#777777' if args.mode=='choropleth' else 'none','linewidth':0.12}
        good.plot(ax=ax,column='_value',cmap=cmap,norm=norm,zorder=2,**kwargs)
        cb=fig.colorbar(ScalarMappable(norm=norm,cmap=cmap),ax=ax,shrink=0.68,pad=0.025)
        cb.set_label(args.label or args.value or '栅格值（单位待核实）')
        if bins: cb.set_ticks(bins)
        audit['color_scale']={'kind':args.scale,'vmin':norm.vmin,'vmax':norm.vmax,'bins':bins,'cmap':args.cmap,
                              'below_range':int((good['_value']<norm.vmin).sum()),'above_range':int((good['_value']>norm.vmax).sum())}
        if args.mode=='choropleth' and g['_value'].isna().any():
            ax.legend(handles=[Patch(facecolor='#eeeeee',edgecolor='#777777',label='无数据 / 非统计图形')],loc='lower left',frameon=False,fontsize=9)
    elif overlay is not None:
        overlay.plot(ax=ax,color='#C35034',markersize=2,alpha=0.65,rasterized=True,zorder=2)
    for cls, group in lines.groupby('class'):
        group.plot(ax=ax,color='#4D6480' if cls=='海岸线' else '#555555',linewidth=0.5,zorder=4)
    bounds=np.vstack([g.total_bounds,lines.total_bounds])
    xmin,ymin=bounds[:,:2].min(axis=0); xmax,ymax=bounds[:,2:].max(axis=0)
    dx=(xmax-xmin)*0.025; dy=(ymax-ymin)*0.025
    ax.set_xlim(xmin-dx,xmax+dx); ax.set_ylim(ymin-dy,ymax+dy)
    ax.set_aspect('equal'); ax.set_axis_off()
    title=args.title or f'{args.year} 年中国'+{'prov':'省级','city':'市级','county':'县级'}[args.level]+'地图'
    if args.data_year and not args.title: title=f'{args.data_year} 年数据（{args.year} 年边界）'
    ax.set_title(title,fontsize=16,pad=14)
    fig.supxlabel(args.source,fontsize=8,color='#555555')
    for fmt in formats: fig.savefig(str(prefix)+'.'+fmt,dpi=args.dpi,bbox_inches='tight')
    plt.close(fig)
    dump(Path(str(prefix)+'.audit.json'),audit)
    print(json.dumps({'output':str(prefix),'audit':audit.get('join',audit.get('points',audit.get('raster',audit['map'])))},ensure_ascii=False,default=str))


if __name__=='__main__':
    main()
