# 基于 HighD 自然驾驶数据集的道路结构与交通流量识别 + HSM 事故率估计：完整开发计划（Windows + Miniforge + Spyder）

> 目标：对 **HighD** 数据集的每个录制片段（recording），自动识别**道路结构**（车道数/方向、车道宽度、限速、片段长度等）和**交通流量**（按方向/整段的流量、车型组成等），并按 **HSM（Highway Safety Manual）** 预测法计算**事故发生率/年**（可按总量与分类型）。项目要求“方便落地、鲁棒性强”，开发环境为 Windows + Miniforge + Spyder。

---

## 0. 快速结论（给开发者）

- **数据→变量映射**（HighD → HSM）：
  - **可直接获取**：`speedLimit`（m/s）、`upperLaneMarkings` / `lowerLaneMarkings`（像素已换算为 m，决定可用车道数量与车道宽度）、`numVehicles / numCars / numTrucks`、`duration`、`frameRate`、`drivingDirection`、逐帧轨迹（`tracks.csv`）。
  - **可由数据推断/计算**：录制路段**有效长度 L（m）**、**按方向的流量（veh/h）**、**货车比例（%）**、**按小时/分钟粒度的时段流量曲线**、**平均速度/密度**等。
  - **HSM 需要但 HighD 缺失或难以可靠提取**：**路肩宽度/类型、中央分隔带宽度/防护栏、横坡/侧向净空、水平曲线参数、匝道密度**等。默认使用**HSM 基准条件（CMF=1.0）**或从**配置文件**读取用户侧默认值/场景值。

- **交通量到 AADT 的换算**：HSM 使用 **AADT**。HighD 为**短时观测**（单段约 10–20 min），需通过**季节/星期几/月份/小时**等**扩展系数**估计 AADT。实现中提供：
  1) **直接使用观测小时流量 × 24**（演示/无系数时的“保守”占位）；  
  2) **用户提供地区化系数表（JSON）**：按**月份、星期几、小时**自动调整；  
  3) 预留**多来源系数融合**接口（若接入本地连续计数站/省级系数表）。

- **HSM 算法覆盖**：实现 **Freeway（高速公路主线）段** 的 **SPF + CMF** 组合，输出：
  - 总事故/年（All Severities）及可选**分严重度（FI / PDO）**与**单车/多车**分解；
  - **置信/离散参数 k**按 HSM / NCHRP 公式随段长 L 计算，用于与 EB 法兼容（若未来提供观测事故数）。
  - **本项目不强制 EB**（Empirical Bayes），因 HighD 不含历史事故记录；若用户提供 **观测事故数**，则可启用 EB 期望值。

- **工程化特点**：
  - **零外网**运行（除非用户加载本地系数表）；纯 **pandas + numpy**；**Typer CLI** + **Pydantic 配置**；**完善日志与单元测试**；
  - **鲁棒性**：对缺列、异常值、极端空载/超密状态做容错；对**奇异车道标记**自动回退；
  - **可视化报告**：每个 recording 输出 `structure.json`、`flow.json`、`hsm_prediction.json`，并生成一份 `report.md`（含关键图表）。

---

## 1. 背景与调研摘要

### 1.1 HighD 数据集要点（与本项目最相关）
- **数据组成**（每个 recording）：背景**道路图像**（移除车辆后的片段图）、`recordingMeta.csv`、`tracksMeta.csv`、`tracks.csv`。`recordingMeta` 含 **`speedLimit`（m/s）**、**`upperLaneMarkings` / `lowerLaneMarkings`**（以 m 为单位的车道线 y 坐标列表）、录制**时长**、**车辆数量**等；`tracks.csv` 提供逐帧**位置/速度/加速度**与**周边关系**（前车/侧车/后车 id、`laneId` 等）。
- **道路形态**：典型**德国高速（Autobahn）**，每个方向**2–3 车道**，总时长约 **16.5 小时**、**6 个站点**、**60 段录制**。
- **坐标系**：图像坐标已换算为 **米**；**车道线 y 坐标**可直接用于车道计数/宽度估计；**`laneId`** 基于车道线推导，**首尾 id 通常非可用车道**（应剔除）。

> 参考文献请见文末“References”。

### 1.2 HSM 预测法（Predictive Method）要点
- **核心**：用 **SPF（Safety Performance Function）** 预测在**基准条件**下的年均事故数（随 **AADT**、**段长 L**、**区域类型**、**车道数 n** 等变化），再用 **CMF**（事故修正因子）叠乘反映几何/管控差异（如**车道宽度、路肩宽度/类型、隔离带/护栏、曲线、拥堵时长**…）。
- **自由路段（Freeway Segments）** 的单车/多车事故均有各自的 **SPF 形式与系数表**；**离散参数 k** 随段长变化；可输出 **严重度分布** 与 **碰撞类型分布**。  
- **本地校准（Calibration Factor, C）**：HSM 推荐将多州数据拟合的 SPF 用**本地事故数据**校准（乘以 C）；无本地数据时，可先用 **C=1** 并声明不确定性。
- **EB（经验贝叶斯）**：需要**观测事故数**与 **k** 参数，组合得到**期望事故数**。HighD 不含事故记录，默认仅给出 **预测值**。

> 参考文献请见文末“References”。

### 1.3 AADT 估计（短时观测 → 年平均）
- HighD 的 recording 时长约 10–20 分钟，需以**小时流量**为中间量，再用**季节/星期几/月份**等**扩展系数**年化为 **AADT**。项目提供：
  - **最简模式**：`AADT ≈ hourly_flow × 24`（演示用/无系数时）；
  - **系数模式**：加载 **JSON** 系数：`AADT = hourly_flow × DOW_factor × MOY_factor × 24 / HOD_share`；
  - **高级模式**：接入本地**连续计数站系数**或省/州 DOT 公布的**季节/日别系数表**。

---

## 2. 目标与产出

### 2.1 项目目标
1. **自动解析 HighD**：一键处理整个数据根目录，逐 recording 产出结构、流量与 HSM 预测结果；  
2. **稳定/可移植**：Windows + Miniforge + Spyder 即可运行；无 GPU 依赖；  
3. **可配置/可扩展**：外部 JSON 配置 HSM 参数/地区化 AADT 系数；  
4. **复现实验**：附**单元测试**、**示例数据子集**与**对照算例**；  
5. **输出**：结构化（JSON/CSV）+ 可读报告（Markdown/HTML）。

### 2.2 交付物
- `structure.json`：车道数（双向/各向）、车道宽度均值/方差、限速、有效段长 L、观测时间窗、录制元数据；
- `flow.json`：按方向的总流量（veh/h）、分车型（car/truck）比例、分钟级/5 分钟级时间序列；
- `hsm_prediction.json`：按方向或合并方向的年均事故数（总量 / FI / PDO；单车 / 多车），可选置信区间（基于过散参数）；
- `report.md`：含可视化图（时段流量曲线、车道宽度分布、预测事故分解）。

---

## 3. 方案设计

### 3.1 数据→特征提取

**(A) 道路结构**  
- **车道数**：从 `upperLaneMarkings`（上行）与 `lowerLaneMarkings`（下行）列表长度各减去 1 即得**标线间隔数量**；剔除首尾非可用车道（依据 `laneId` 规则），得到可用车道数。  
- **车道宽度**：相邻标线 y 值差分的**绝对值**的统计量（均值/标准差/四分位），上行与下行分开计算。  
- **限速**：来自 `recordingMeta.speedLimit`（单位 m/s，转换为 km/h）。  
- **段长 L**（m）：用 `tracks.csv` 中任一时刻车辆的 `frontSightDistance + backSightDistance + vehicle_length` 估计；或取全体车辆/时刻的**稳健均值**（剔除异常）。若 `front/backSightDistance` 不可用，退化为 **x 坐标范围**的稳健跨度。

**(B) 交通流量**  
- **按方向流量（veh/h）**：将 `tracksMeta.drivingDirection` 分组，计数该方向的**唯一车辆数**除以 `recordingMeta.duration`（秒）再 ×3600。  
- **车型组成**：`numCars/numTrucks`；也可由 `tracksMeta.class` 汇总。  
- **时序曲线**：基于 `tracks.csv` 的 `initialFrame/finalFrame` 或按车辆穿越一个固定 **x=const** 横截面的事件计数，生成 **1-min 或 5-min** 分辨率曲线。  
- **速度/密度**（可选）：从 `xVelocity` 取均值作为时刻速度；密度用**车辆数/段长**近似。

**(C) AADT 估计**  
- **最简**：`AADT_dir = hourly_flow_dir × 24`；  
- **系数**：`AADT_dir = hourly_flow_dir × F_DOW(weekday) × F_MOY(month) × 24 / HOD_share(hour)`；系数从 `config/aadt_factors.json` 读取；无则回退到最简。

### 3.2 HSM 事故预测（Freeway Segment）

- **SPF 选择**：按**区域类型（默认 Urban/Rural，可配置）**与**方向车道数 n**（按方向的车道数）选择 **单车 / 多车** SPF。若仅有“合并方向” SPFs，也提供**双向合并**计算选项。  
- **输入**：`AADT_dir` 或合并方向 `AADT_total`、**段长 L（mi）**、**车道数 n**、区域类型。  
- **CMF**：若无路肩/隔离带/曲线等信息，取 **1.0**（基准条件）。配置文件允许设置：`lane_width_in`, `inside_shoulder_width_in`, `outside_shoulder_width_in`, `median_width_ft`, `barrier_presence`, `rumble_strip`, `congestion_hours_plph` 等，用以自动生成对应 CMF 值（缺省 1.0）。  
- **输出**：
  - `N_spf_sv_fi/pdo`、`N_spf_mv_fi/pdo`；`N_total = Σ`；
  - **k(L)**：按 HSM/ NCHRP 公式由 **段长 L** 计算；  
  - （可选）**严重度/碰撞类型分布**（采用默认分布，或用户侧本地化分布表）。
- **校准与 EB**：
  - **Calibration**：结果乘以 `C`（默认 1.0，可配置）；
  - **EB**：保留 API：若用户提供观测事故数 `N_obs` 与时段，按 HSM EB 公式返回 `N_expected`。

> 注：HighD 为德国高速，与 HSM（基于北美多州数据）存在地域差异。建议用于**相对风险比较/场景敏感性**或在**本地校准系数**辅助下使用。

---

## 4. 工程实现计划

### 4.1 目录结构

```
highd_hsm/
├─ README.md
├─ pyproject.toml / setup.cfg           # 或 minimal setup.py
├─ env/                                  # conda 环境文件
│   └─ environment.yml
├─ highd_hsm/
│  ├─ __init__.py
│  ├─ config.py                          # Pydantic BaseSettings + 默认参数
│  ├─ io_highd.py                        # 读取 recordingMeta / tracksMeta / tracks
│  ├─ structure.py                       # 车道数/宽度/限速/段长估计
│  ├─ flow.py                            # 流量、组成与时序曲线
│  ├─ aadt.py                            # 短时→AADT 的因子化换算
│  ├─ hsm_models/
│  │   ├─ __init__.py
│  │   ├─ freeway_spf.py                 # SPF/CMF/k(L) + 严重度/碰撞分布
│  │   └─ eb.py                          # 经验贝叶斯（可选）
│  ├─ report.py                          # Markdown 报告生成
│  ├─ cli.py                             # Typer 命令行
│  └─ utils.py                           # 单位换算/稳健统计/异常检测
├─ config/
│  ├─ project.yaml                       # 全局配置（区域类型、单位、输出选项…）
│  ├─ aadt_factors.json                  # 月份/星期几/小时系数（可为空）
│  └─ hsm_overrides.json                 # 车道/路肩/隔离带等缺失量的默认假设
├─ tests/
│  ├─ test_structure.py
│  ├─ test_flow.py
│  ├─ test_aadt.py
│  ├─ test_freeway_spf.py
│  └─ data_snippets/                     # 极小子集/合成数据用于单测
└─ examples/
   └─ run_demo.cmd                       # Windows 一键运行脚本
```

### 4.2 关键模块设计

- `io_highd.py`
  - `load_recording(recording_dir) -> dict`：返回 DataFrames 与 meta；
  - 容错：缺列、分号分隔的车道线解析、单位检查（m/s→km/h 等）；

- `structure.py`
  - `infer_lanes(meta) -> {up: n, down: n}`；`lane_width_stats(meta)`；
  - `estimate_segment_length(tracks_df) -> L_m`（多策略：`front+backSight` 稳健均值 → `x` 范围回退）；

- `flow.py`
  - `directional_flow(tracks_meta_df, duration_s)`：返回上/下行 veh/h；
  - `composition(tracks_meta_df)`：车/卡车比例；
  - `timeseries(tracks_df, bin='1min'|'5min')`：时序曲线；

- `aadt.py`
  - `to_aadt(hourly_flow, weekday, month, hour, factors_cfg) -> aadt`;  
  - 支持**合并方向**与**按方向**；

- `hsm_models/freeway_spf.py`
  - **系数表**：以**JSON/CSV**封装（来源于公开文献/手册条目），按（区域、n、事故类型、严重度）检索 `a,b,c` 等；
  - `predict_freeway_segment(aadt, L_miles, n, area, cmf_bundle, calibration=1.0) -> dict`；
  - `k_from_length(L_miles, params)`；
  - `default_distributions(area)`：严重度与事故类型分布；

- `report.py`
  - 生成 per-recording 的 `report.md`，插图来自 matplotlib（SVG/PNG）。

- `cli.py`（Typer）
  - `estimate all --data-root D:\highD --out out\ --area urban`  
  - `estimate one --id 05 --dir D:\highD\05 --out out\05`  
  - `plot ts --id 05`

### 4.3 依赖与环境

- **Miniforge/Conda** 环境（CPU）：`pandas`, `numpy`, `scipy`, `pydantic`, `typer`, `rich`, `matplotlib`, `pytest`。  
- 可选：`pyyaml`、`jinja2`（报告模板）、`tqdm`（进度）。

`env/environment.yml`：
```yaml
name: highd_hsm
channels: [conda-forge, defaults]
dependencies:
  - python>=3.10
  - pandas
  - numpy
  - scipy
  - matplotlib
  - pydantic
  - typer
  - rich
  - pyyaml
  - pytest
  - pip
  - pip:
      - tqdm
      - jinja2
```

**Windows + Spyder**：在该环境中 `conda install spyder -c conda-forge`，或在现有 Spyder 里切换到本环境内核。

### 4.4 输出与文件格式

- `out/{recording_id}/structure.json`：
```json
{
  "lanes": {"up": 3, "down": 2},
  "lane_width_m": {"up": {"mean": 3.6, "std": 0.1}, "down": {"mean": 3.6, "std": 0.1}},
  "speed_limit_kmh": 120,
  "segment_length_m": 420.5,
  "duration_s": 1034,
  "notes": "usable lanes exclude first/last laneId"
}
```
- `out/{recording_id}/flow.json`：
```json
{
  "flow_vehph": {"up": 1820.0, "down": 1650.0, "both": 3470.0},
  "composition": {"cars": 0.88, "trucks": 0.12},
  "timeseries": "out/05/flow_1min.csv"
}
```
- `out/{recording_id}/hsm_prediction.json`：
```json
{
  "area": "urban",
  "n_lanes_per_dir": {"up": 3, "down": 2},
  "aadt_per_dir": {"up": 36480, "down": 33000},
  "segment_length_mi": 0.261,
  "cmf": {"lane_width": 1.0, "shoulder_inside": 1.0, "shoulder_outside": 1.0, "median_barrier": 1.0},
  "calibration_C": 1.0,
  "results": {
    "sv": {"FI": 0.42, "PDO": 1.35},
    "mv": {"FI": 0.78, "PDO": 2.10},
    "total_all_sev": 4.65
  },
  "k_overdispersion": 0.37
}
```

---

## 5. 开发里程碑（建议 2–3 周）

1) **D1–D3**：项目脚手架、`io_highd`、`structure` 原型，单测通过；  
2) **D4–D6**：`flow` + `aadt`（最简与系数模式），作图；  
3) **D7–D10**：`freeway_spf`（SV/MV + 严重度分布 + k(L)），端到端跑通 2–3 个 recordings；  
4) **D11–D13**：鲁棒性/异常数据处理、日志、CLI 集成；  
5) **D14–D15**：撰写 `README` & `report.md` 模板、整理示例输出。

---

## 6. 质量与鲁棒性

- **健壮统计**：段长与车道宽度使用**中位数/IQR**；离群检测（如 1.5×IQR 规则）；  
- **容错**：缺失 `front/backSightDistance` → 用 x 范围；`upper/lowerLaneMarkings` 异常 → 用 `laneId` 众数反推可用车道数；  
- **单位统一**：HighD 以米/秒为主；HSM 需要英里/年等 → 统一转换函数；  
- **日志**：每个 recording 输出 `run.log`（INFO/WARNING/ERROR）；  
- **测试**：≥80% 覆盖率；对极端“空载/超载/短极短时长”做用例；  
- **再现**：固定随机种子，仅在需要时使用随机性。

---

## 7. 使用示例（Windows）

```bat
:: 1) 创建环境
conda env create -f env\environment.yml
conda activate highd_hsm

:: 2) 安装（开发模式）
pip install -e .

:: 3) 运行全部
python -m highd_hsm.cli estimate all --data-root D:\data\highD --out D:\work\out --area urban

:: 4) 单个 recording
python -m highd_hsm.cli estimate one --id 05 --dir D:\data\highD\05 --out D:\work\out\05
```

---

## 8. 风险与注意事项

- **地域与口径差异**：HighD（德国） vs. HSM（美国）；应**声明用途**以**相对比较/方法演示**为主，或由用户提供**本地校准 C**；  
- **AADT 年化误差**：短时观测外推存在不确定性；建议尽量使用**周全时跨日计数**或**地区化系数表**；  
- **缺失几何要素**：如路肩/隔离带/曲线等，默认 CMF=1.0；若从背景图像自动识别，此为**后续扩展**（CV/几何重建）；  
- **版权**：HSM 原始系数属于 AASHTO 出版物，项目将**不直接分发手册原文**，而是通过**可配置参数**加载公开来源/用户提供的系数。

---

## 9. 可能的后续增强

- **从背景图像自动识别**隔离带类型/护栏/路肩宽度（OpenCV+几何标尺）；  
- **拥堵时长 CMF**：由时序速度<阈值的小时比例近似；  
- **Ramp/Weaving 分析**：若有更丰富的地图/匝道数据可切换到 HSM Chapter 19 模块；  
- **可视化 Dashboard**：Streamlit/Panel；  
- **与 IHSDM/州 DOT 工具对比**：做验证性对照。

---

## 10. References（精选）

- **HighD 数据集**
  - Krajewski, R. et al. *The highD Dataset: A Drone Dataset of Naturalistic Vehicle Trajectories on German Highways...* arXiv:1810.05642, 2018.  
  - HighD 数据格式说明（LevelXData，PDF）。
  - Wang, Z. *Lane Change Inconsistencies in the highD Dataset*. *Findings*, 2020.

- **HSM / 自由路段预测法**
  - NCHRP Project 17-45 Final Report（含 Freeway SPFs/CMFs/离散参数与分布、示例等，公开 PDF）。
  - TxDOT / WSDOT / NYSDOT 等 HSM 指南与用户手册（章节导航与公式索引）。
  - FHWA：HSM 实施与工具介绍；IHSDM 概览。

- **AADT 年化与短期计数扩展**
  - FHWA **Traffic Monitoring Guide (TMG)**（2013/2022 版），季节/星期几/月份/小时因子法；  
  - 各州 DOT **短时计数因子**公开表（例如 WSDOT、Ohio DOT 等）。

> 实际项目中，请将上述公开资料中的**参数表**整理成 `data/hsm_coefficients/*.csv` 与 `config/aadt_factors.json`，以便透明、可追溯地运行。

---

## 11. 附：示例 `config/aadt_factors.json`

```json
{
  "F_DOW": {"Mon": 1.00, "Tue": 1.02, "Wed": 1.03, "Thu": 1.03, "Fri": 1.05, "Sat": 0.95, "Sun": 0.90},
  "F_MOY": {"1": 0.95, "2": 0.97, "3": 1.00, "4": 1.02, "5": 1.05, "6": 1.06, "7": 1.08, "8": 1.07, "9": 1.03, "10": 1.00, "11": 0.98, "12": 0.96},
  "HOD_share": {"0": 0.03, "1": 0.02, "2": 0.02, "3": 0.02, "4": 0.03, "5": 0.04, "6": 0.05, "7": 0.06, "8": 0.07, "9": 0.06, "10": 0.05, "11": 0.05, "12": 0.05, "13": 0.05, "14": 0.05, "15": 0.06, "16": 0.07, "17": 0.07, "18": 0.06, "19": 0.05, "20": 0.04, "21": 0.04, "22": 0.03, "23": 0.03}
}
```

---

## 12. 对 Codex/开发者的实现提示

- **先打通端到端**（不依赖系数表）：最简 AADT → C=1 → CMF=1；检查维度/单位/I/O；  
- 然后逐步接入：`aadt_factors.json`、HSM 系数 CSV；最后加 EB（若有观测）。  
- 所有参数**可覆写**：CLI 参数 > YAML > 默认；  
- 数据驱动的部分（如默认严重度/碰撞分布），采用**可替换表**，并在 `report.md` 中落款来源。

---

## 13. 相关 GitHub 项目（可借鉴的工具/代码）

- **RobertKrajewski/highD-dataset**：HighD 官方工具箱（Matlab/Python），包含数据读取与可视化示例，便于快速核对字段与坐标系。  
- **ChaDolI/HighD_Preprocessing**：HighD 预处理与可视化示例（添加航向角、绘制/导出视频等），可参考轨迹管线与可视化代码。  
- **westny/dronalize**：面向无人机俯拍轨迹数据的通用处理/可视化工具箱，可借鉴其数据清洗与可视化组织方式。  
- **anita graser · movement-analysis-tools（汇总）**：轨迹/移动数据分析工具集合，适合查找通用的轨迹预处理/插值/特征工程方案。  
- **（可选）Lane Detection 示例项目**：若后续尝试从背景图像估计几何量（如隔离带/护栏），可参考 OpenCV 传统管线或深度分割（UNet 等）的示例仓库。