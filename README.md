# China Historical Maps Skill

用 Python 绘制中国历年省、市、区县专题地图的 Agent Skill。包含标准 `SKILL.md`、中文方法说明和可独立运行的命令行助手。

支持南海小地图（mini）和长版（long）、连续/分段填色、经纬度散点、栅格点及栅格多边形；输出 PNG、PDF/SVG、数据匹配表与审计 JSON。

**本仓库不包含底图、原课程代码、讲义、字体、企业数据或 TIFF。** 绘制课程地图需要自行准备有权使用的 RStata 课程数据；安装 Skill 本身不会下载数据。本助手仅适配文档描述的课程数据结构和投影，不会把任意地图自动转换为该版式。

## 给 Agent 的安装指令

将以下内容交给支持本地 `SKILL.md` 的 Agent：

> 从 https://github.com/xby0328/china-historical-maps 安装 china-historical-maps Skill。把仓库根目录作为一个完整 Skill 文件夹放入你支持的技能目录，保留 scripts、references 和 agents。阅读 SKILL.md，安装 requirements.txt 中缺少的依赖，并让我指定本地课程数据目录。不要下载或上传课程原始数据。

不支持自动发现 Skills 的 Agent 也可以克隆仓库，按 `SKILL.md` 指引使用 Python 脚本。

## 安装

先确保有 Git 和 Python 3.10+（本机已在 Python 3.12 验证）。选择目标 Agent 实际使用的技能目录；同名目录已存在时先检查，不要覆盖已有修改。

例如 Codex 默认目录下安装：

```powershell
git clone https://github.com/xby0328/china-historical-maps.git "$HOME/.codex/skills/china-historical-maps"
python -m pip install -r "$HOME/.codex/skills/china-historical-maps/requirements.txt"
```

macOS/Linux 可使用相同命令并按环境将 `python` 改为 `python3`。若 Codex 使用自定义技能目录，或使用其他 Agent，将目标路径替换为对应目录。Agent 有技能安装器时，也可直接提供仓库 URL。安装后如未被自动识别，重新启动会话。

## 配置数据

数据根目录应包含：

```text
course-data/
  provmapdata/
    minishp/chinaprov2019mini/chinaprov2019mini.shp
    longshp/chinaprov2019long/chinaprov2019long.shp
  citymapdata/
  countymapdata/
```

同目录需保留 `.shx`、`.dbf`、`.prj` 和 `_line.shp` 的配套文件。课程提供 1949—2021 年的两种版式；县级连接代码为 `PAC`，市级为 `市代码`，省级为 `省代码`。

PowerShell 中设置当前会话的数据位置：

```powershell
$env:CHINA_MAP_COURSE_ROOT = 'D:/your-course-data'
```

macOS/Linux：

```sh
export CHINA_MAP_COURSE_ROOT='/path/to/your-course-data'
```

也可每次传入 `--course-root PATH`。未配置时，查找当前工作目录下的 `course-data`，不会自动搜索整块硬盘。数据始终留在本地。

## 使用

在 Agent 中：

> 使用 $china-historical-maps，按我的 Excel 中“市代码”和“指标”绘制城市填色图，采用 2021 年边界、南海小地图。先核对匹配与缺失，再输出 PNG、PDF 和审计结果。

直接命令行使用（在仓库根目录执行）：

```sh
python scripts/china_map.py inventory
python scripts/china_map.py inspect --level county --year 2019 --version mini
python scripts/china_map.py base --level prov --year 2019 --version mini --out results/province2019
python scripts/china_map.py choropleth --level city --year 2021 --table data.csv --key 市代码 --value 指标 --out results/city_indicator
python scripts/china_map.py points --year 2019 --version long --table points.csv --point-crs EPSG:4326 --out results/points
```

中文字体可用 `--font /path/to/font.ttf` 显式指定；默认优先使用课程目录中的 `LXGWWenKai-Regular.ttf`。Linux/macOS 用户宜指定已有中文字体，避免中文缺字。

更多图型、跨年比较和扩展方式见 [调用示例](references/recipes.md)，课程字段与原代码修正见 [课程笔记](references/course.md)。

## 数据处理约定

- 数据年份与边界年份分别记录；`--data-year` 仅作元数据，不自动筛选面板数据。
- 缺失保留为缺失，未匹配地区不会自动填零；重复统计代码直接报错。
- 不自动猜测历史行政区映射。课程底图的同码特殊图形保留轮廓，指标留空。
- mini 含经过平移缩放的显示图形，不能用于距离、面积或空间统计；分析与裁剪先使用 long。
- 地图和色条共用同一个归一化规则；log 拒绝零与负值；分段显式记录断点。
- 栅格默认有界降采样用于展示；统计分析应使用符合变量含义的分辨率、聚合规则和精度。
- 默认拒绝覆盖已有同名输出。

## 验证

无需课程数据的辅助函数测试：

```sh
python -m unittest discover -s tests -v
```

本地课程验证已覆盖六种示例图、2019 年三级两版读取、232 个课程样例城市代码匹配，以及 nodata、零/缺失、跨插图裁剪等。438 套底图已核查文件清单；未逐一验证全部历史行政边界的准确性。此仓库未提供这些课程验证图，测试中只构造合成几何和小型栅格。

## 来源与许可

方法学习来源：RStata《使用 Python 绘制历年中国各省市区县地图（小地图版本+长版）》。仓库包含重新编写的辅助程序与方法摘要，不转载课程模块或原始素材。

本仓库新编写的代码和文档采用 [MIT License](LICENSE)。该许可不适用于 RStata 或其他第三方的课程、地图、字体及数据；这些材料继续受各自许可约束。
