# TrafficFlowRiskBenchmark

**HighD 自然驾驶数据集 → 道路结构与交通流量识别 → HSM（Highway Safety Manual）事故率估计** 的一站式工具集。
在 **Windows + Miniforge + Spyder** 上即可运行，无需 GPU。项目严格按照 `develop_plan.md` 实现：完成数据加载、道路结构识别、交通流量统计、AADT 年化、HSM 预测以及 Markdown 报告生成，并提供单元测试与示例数据。

---

## 目录
- [特性](#特性)
- [安装](#安装)
- [快速开始](#快速开始)
- [数据准备](#数据准备)
- [配置](#配置)
- [命令行用法](#命令行用法)
- [输出文件说明](#输出文件说明)
- [工作原理（简述）](#工作原理简述)
- [验证与局限](#验证与局限)
- [开发与测试](#开发与测试)
- [常见问题](#常见问题)
- [许可证](#许可证)

---

## 特性
- **全自动管线**：递归扫描数据根目录，逐个 recording 输出 `structure.json`、`flow.json`、`aadt.json`、`hsm_prediction.json` 与可选 `report.md`。
- **鲁棒/可移植**：纯标准库实现，无需额外第三方依赖；对缺失字段、异常值提供回退策略（例如车道数可由 `laneId` 反推）。
- **可配置**：`config/aadt_factors.json` 提供 AADT 年化因子；`data/hsm_coefficients/*.csv` 配置 SPF 系数与严重度分布；命令行参数可覆盖默认值。
- **示例数据与测试**：内置简化版 HighD 片段（见 `tests/data/highd_sample`），并以 `pytest` 进行回归测试。
- **零外网依赖**：所有系数均本地化；用户可替换为本地/正式参数表。

---

## 安装

> 前置：已安装 **Miniforge**（或 Anaconda）与 **Git**，并在 Windows 上使用 **Spyder**。

1. 克隆项目
   ```bash
   git clone https://example.com/highd-hsm.git
   cd highd-hsm
   ```

2. 创建并激活 Conda 环境
   ```bash
   conda env create -f env/environment.yml
   conda activate highd_hsm
   ```

3. （可选）在该环境中安装 Spyder 或选择该环境作为 Spyder 的 Python 解释器
   ```bash
   conda install spyder -c conda-forge
   ```

4. 开发模式安装
   ```bash
   pip install -e .
   ```

> ✅ 在 Spyder 中：首选项 → Python 解释器 → 选择 `highd_hsm` 环境中的解释器，即可在 IDE 内运行/调试。

---

## 快速开始

```bash
# 处理数据根目录下的全部 recordings（输出写入 D:\work\out）
python -m highd_hsm.cli estimate-all D:\data\highD D:\work\out --area urban

# 仅处理某个 recording（例如目录 D:\data\highD\05）
python -m highd_hsm.cli estimate-one D:\data\highD\05 D:\work\out\05 --area urban
```

运行完成后，查看 `out/<recording_id>/report.md` 或各 `*.json` 结果。

---

## 数据准备

将 HighD 数据集置于一个根目录（例如 `D:\data\highD`），目录结构类似：
```
highD/
 ├─ 01/
 │   ├─ recordingMeta.csv
 │   ├─ tracksMeta.csv
 │   ├─ tracks.csv
 │   └─ background.png
 ├─ 02/
 └─ ...
```

项目使用：
- `recordingMeta.csv`：时长、帧率、`speedLimit`（m/s）、`upperLaneMarkings` / `lowerLaneMarkings`（单位为米的 y 坐标列表）等；
- `tracksMeta.csv`：每辆车的起止帧、`drivingDirection`、类型（car/truck）等；
- `tracks.csv`：逐帧的 `x/y`、`xVelocity`、`laneId`、邻车关系等。

> **版权提示**：HighD 数据版权归其发布方所有，请在许可范围内使用。本项目不附带任何 HighD 原始数据。

---

## 配置

所有配置均可为空（采用默认值），也可通过文件覆盖。优先级：**命令行参数 > 配置文件 > 内置默认**。

### `config/aadt_factors.json`
提供基于 FHWA Traffic Monitoring Guide 的示例季节/星期/小时因子，可直接替换为本地化参数。

### `data/hsm_coefficients/freeway_spf.csv`
定义自由路段（Freeway Segment）单车/多车事故的 SPF 系数。字段：
- `facility` / `area_type`：匹配 CLI 参数（均为小写）；
- `collision_type`：`sv`（single-vehicle）或 `mv`（multi-vehicle）；
- `intercept`、`aadt_exponent`、`length_exponent`、`lanes_exponent`：对数形式系数。

### `data/hsm_coefficients/severity_distribution.csv`
为不同碰撞类型提供 FI / PDO 占比，输出分严重度的事故数。

---

## 命令行用法

```text
python -m highd_hsm.cli estimate-all DATA_ROOT OUT_DIR [选项]
    --area TEXT                区域类型（urban/rural），默认 urban
    --facility TEXT            设施类型，默认 freeway
    --calibration FLOAT        HSM 校准系数 C，默认 1.0
    --aadt-factors PATH        AADT 因子 JSON
    --coefficients PATH        SPF 系数 CSV
    --severity PATH            严重度分布 CSV
    --no-report                不生成 Markdown 报告
    -v, --verbose              详细日志

python -m highd_hsm.cli estimate-one RECORDING_DIR OUT_DIR [同上选项]
```

---

## 输出文件说明

每个 `out/<recording>/` 包含：
- `structure.json`：车道数（上/下行）、车道宽度统计、限速（km/h）、估计段长 `L`（m）、录制时长等；
- `flow.json`：按方向的流量（veh/h）、车型组成、1 分钟粒度的流量时序；
- `aadt.json`：按方向的小时流量与年化结果（含所用因子）；
- `hsm_prediction.json`：单车/多车、FI/PDO 分解、总年均事故数、过散参数 `k(L)`、校准系数；
- `report.md`：结构化摘要（若启用）。

---

## 工作原理（简述）

1. **结构识别**：解析 `upper/lowerLaneMarkings` 推得上下行车道数/宽度；若异常，回退到 `laneId` 众数。段长 `L` 基于 `x` 坐标的 5–95 百分位差值。
2. **交通流量**：按 `drivingDirection` 统计唯一车辆数并换算 veh/h，生成 1 分钟粒度时序、车型占比、平均速度等。
3. **AADT 年化**：将小时流量乘以 24（默认）或使用 `config/aadt_factors.json` 中的季节/星期/小时因子进行年化。
4. **HSM 预测**：调用 Freeway SPF，依据 AADT、车道数、段长（换算为英里）与区域类型输出单车/多车事故数及严重度分解；同时返回过散参数 `k(L)` 以供 EB 法使用。

---

## 验证与局限

- **地域差异**：HighD（德国）与 HSM（美国）存在差异；结果更适合方法演示或在本地校准后使用。
- **短时→年化误差**：HighD 仅为短时观测；建议使用地区化的月/周几/小时因子或连续计数站数据校准。
- **缺失几何要素**：若无法可靠获得路肩/隔离带等几何量，CMF 默认为 1.0；用户可在配置中覆盖。
- **无观测事故数**：未包含 EB 合并；若提供观测事故，可在后续版本扩展。

---

## 开发与测试

- 目录结构（摘要）：
  ```text
  highd_hsm/
    ├─ cli.py                 # argparse 命令行接口
    ├─ config.py              # dataclass 配置模型
    ├─ io/highd.py            # HighD 数据加载
    ├─ pipeline/
    │   ├─ structure.py       # 道路结构识别
    │   ├─ flow.py            # 流量统计
    │   ├─ aadt.py            # 年化计算
    │   └─ run.py             # 管线编排 & 报告
    └─ hsm/spf.py             # 自由路段 SPF 实现
  tests/
    ├─ data/highd_sample/     # 简化示例数据
    └─ unit/test_pipeline.py  # Pytest 用例
  ```
- 运行测试：
  ```bash
  pytest -q
  ```
- 代码风格遵循 PEP 8，默认无需额外格式化工具。

---

## 常见问题

**Q1：必须提供 AADT 因子表吗？** 不是。若不提供，程序将使用 `小时流量 × 24` 的保守近似。

**Q2：如何自定义 HSM 系数？** 将 `data/hsm_coefficients/freeway_spf.csv` 替换为本地表格（保留列名即可）。

**Q3：为什么生成的报告没有图表？** 若 `tracksMeta` 缺少 `initialFrame` 或者时序为空，则不会绘制流量曲线，Markdown 中会提示缺失。

---

## 许可证

本项目示例代码遵循 **MIT License**。项目不包含任何 HighD 原始数据或受版权保护的 HSM 手册内容，请自行确保数据与参数来源的合法性。
