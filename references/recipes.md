# 调用与扩展

以下命令中的 `SKILL` 替换为 实际 Skill 安装目录；`OUT` 替换为项目输出路径。直接用 PowerShell 调用普通脚本，不用 python -c。

```powershell
python SKILL/scripts/china_map.py inventory
python SKILL/scripts/china_map.py inspect --level county --year 2019 --version mini
python SKILL/scripts/china_map.py base --level prov --year 2019 --version mini --out OUT/province2019
python SKILL/scripts/china_map.py choropleth --level city --year 2021 --version mini --table data.csv --key 市代码 --value GDP --data-year 2020 --title '2020年GDP（2021年边界）' --out OUT/gdp2020
python SKILL/scripts/china_map.py choropleth --level county --year 2019 --table data.xlsx --key 县代码 --value 指标 --scale discrete --bins 0,10,20,50,100 --out OUT/county2019
python SKILL/scripts/china_map.py points --year 2019 --version long --table points.xlsx --lon 经度 --lat 纬度 --point-crs EPSG:4326 --out OUT/points2019
python SKILL/scripts/china_map.py raster-points --year 2021 --tif cn2022.tif --data-year 2022 --max-cells 100000 --resampling average --out OUT/nightlight2022
python SKILL/scripts/china_map.py raster-polygons --year 2015 --tif NH3_em_anthro_2015_sector_ENE.tif --max-cells 100000 --resampling average --out OUT/nh3_2015
```

`--out` 为无扩展名输出前缀；生成 `.png`、`.pdf`、`.audit.json`，数据合并时另有 matched/unmatched CSV。`--formats png,pdf,svg` 可定制。默认 300 dpi。`--vmin/--vmax` 固定跨年色标；`--bins` 固定分段。离散区间为左闭右开（最后一段包括最大值）；超出断点范围报错。常量数据线性色标扩展极小显示范围；常量正数 log 采用局部乘法扩展。无有效数值直接报错。

表格 CSV 以字符串读代码，XLSX 支持 `--sheet`。脚本只处理单次截面，不自行筛选混合年份。先在项目脚本中筛年份/聚合，或传入预处理表。`--data-year` 是显示与审计元数据，不执行筛选。

`--scale log` 只接收严格正值。包含零的计数可线性/分段，或在项目脚本显式变换并正确反标图例。不要为了运行成功偷偷删除零或把零改成一。脚本不做自动补零、不提供未经核对的历史代码映射。图例缺失色为灰色，并显示“无数据 / 非统计图形”。

## 项目脚本复用

将 skill/scripts 加入 sys.path 后 `import china_map as cm`；读代码见函数签名。`resolve_root`、`load_map`、`normalize_codes`、`join_values`、`display_overlay`、`make_norm`、`raster_features` 可分别复用。保持真实几何和显示几何两个变量，先做统计再做显示。

- 多年图：循环 year，先汇总全期合法值确定共同 norm；固定背景、尺寸和断点。历史行政区变化须按研究设计决定逐年边界或统一边界，报告跨界转换方式。
- 点分类/大小：主脚本 `points` 提供单色基线；分类列用固定映射及 legend，气泡面积与值成比例，并给大小图例。经纬度数据来源未确认时，先报告来源不确定，不能称为已准确定位。
- 空间统计：在 long 上检查同码冲突/行政区重叠后才 sjoin；对边界点明确 intersects 多匹配或 within 漏匹配的处理，报告未匹配和多匹配。
- 子区域：用已审查的代码筛 long 面，选出相关线层并合理 clip；不要给局部省图套全国比例尺、坐标范围和南海仿射变换。
- 中文标签：课程字体优先作为可选字体，论文可指定宋体/黑体等。用 representative_point，必要时手动避让；不要对县级全国图强行逐县标注。
- 指北针/比例尺：助手基线不自动绘制，以免误报方向和精度。需要时真北通过当前位置到其北侧一小纬度的投影向量确定；尺度在真实主图局部计算，并标注插图缩放 0.5，不能共用主图比例尺。

## 栅格

助手 `--max-cells` 通过有界降采样限制预览像元数；输出审计记录原分辨率、目标尺寸、有效像元、CRS 和重采样方法。默认平均仅用于连续强度展示，类别数据显式 nearest/mode。总量数据明确 sum，不能把平均图声称为区域总量。极大栅格/正式统计改用窗口、区域 mask 或重投影栅格显示，避免构造百万个 Point/Polygon。

masked read 处理 nodata 与 mask，并额外剔除 NaN/Inf；仿射用 `src.transform * Affine.scale(src.width/new_width, src.height/new_height)`，坐标取像元中心。先投影到课程 Albers 并裁剪 long 中国几何，再调用 display_overlay。多边形化前使用 float32 会有精度变化，仅作显示；分析使用原始数据精度。多边形化合并相邻等值像元，不是逐像元统计表。

交付时核对 TIFF 元数据/原始说明中的单位、年份、产品名称。课程夜光标题 2022 与所写数据源 2000—2020 不一致，不照抄成已核实来源。
