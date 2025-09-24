# TrafficFlowRiskBenchmark

**HighD 自然驾驶数据集 → 道路结构与交通流量识别 → HSM（Highway Safety Manual）事故率估计** 的一站式工具集。  
在 **Windows + Miniforge + Spyder** 上即可运行，无需 GPU。

> ✨ 适用场景：批量处理 HighD 数据集的每个 recording，识别**道路结构**（车道数/宽度、限速、段长）与**交通流量**（按方向流量、车型组成、时间序列），并按 **HSM 自由路段（Freeway Segment）** 方法输出**年均事故数**（可含单车/多车、严重度分解、过散参数 `k(L)`）。

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
- [致谢](#致谢)
- [许可证](#许可证)

---

## 特性
- **全自动管线**：递归扫描数据根目录，逐个 recording 输出 `structure.json`、`flow.json`、`hsm_prediction.json`、`report.md`。
- **鲁棒/可移植**：仅依赖 `pandas / numpy / pydantic / typer / matplotlib` 等；对缺失字段、异常值有保护与回退策略。
- **可配置**：以 `config/*.json|yaml` 提供 **HSM 参数/分布**、**AADT 年化因子**、**本地校准系数 C** 等。
- **可验证**：提供单元测试与最小示例片段；报告含关键图表，便于核对与审阅。
- **零外网**：默认不访问外部服务；你只需准备本地 HighD 数据和可选的配置文件。

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
# 处理数据根目录下的全部 recordings
python -m highd_hsm.cli estimate all --data-root D:\data\highD --out D:\work\out --area urban

# 仅处理某个 recording（如 05）
python -m highd_hsm.cli estimate one --id 05 --dir D:\data\highD\05 --out D:\work\out\05 --area urban

# 仅绘制时序曲线（1 分钟粒度）
python -m highd_hsm.cli plot ts --id 05 --dir D:\data\highD\05 --out D:\work\out\05
```

> 运行完成后，查看 `out/<recording_id>/report.md` 或 `*.json` 结构化输出。

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

> **隐私与版权**：HighD 数据版权归其发布方所有，请在许可范围内使用。本项目不附带任何 HighD 数据。

---

## 配置

所有配置均可为空（采用默认值），也可通过文件覆盖。优先级：**命令行参数 > YAML/JSON 配置 > 内置默认**。

### `config/project.yaml`（示例）
```yaml
area: urban              # 或 rural
unit_system: metric      # 内部以 SI 计算，HSM 需要的英制由程序内部统一换算
combine_directions: false
severity_breakdown: true
calibration_C: 1.0       # HSM 本地校准系数，缺省 1.0
report:
  enable: true
  timeseries_bin: "1min"
```

### `config/aadt_factors.json`（示例）
用于将短时观测的**小时流量**年化为 **AADT**（可选）。
```json
{
  "F_DOW": {"Mon":1.00,"Tue":1.02,"Wed":1.03,"Thu":1.03,"Fri":1.05,"Sat":0.95,"Sun":0.90},
  "F_MOY": {"1":0.95,"2":0.97,"3":1.00,"4":1.02,"5":1.05,"6":1.06,"7":1.08,"8":1.07,"9":1.03,"10":1.00,"11":0.98,"12":0.96},
  "HOD_share": {"0":0.03,"1":0.02,"2":0.02,"3":0.02,"4":0.03,"5":0.04,"6":0.05,"7":0.06,"8":0.07,"9":0.06,"10":0.05,"11":0.05,"12":0.05,"13":0.05,"14":0.05,"15":0.06,"16":0.07,"17":0.07,"18":0.06,"19":0.05,"20":0.04,"21":0.04,"22":0.03,"23":0.03}
}
```

### `config/hsm_overrides.json`（示例）
当 HighD 不提供某些几何量（如路肩宽度、隔离带类型等）时，可在此设置**默认假定**：
```json
{
  "lane_width_in": 144,           # 车道宽度（英寸），示例：12 ft
  "inside_shoulder_width_in": 60, # 内侧路肩宽度（英寸）
  "outside_shoulder_width_in": 96,
  "median_barrier": "none",       # "none" | "w-beam" | "concrete"
  "rumble_strip": true
}
```

> 若未提供上述文件，程序将采用内置基准条件（CMF=1.0），并在报告中提示。

---

## 命令行用法

```text
python -m highd_hsm.cli estimate all
    --data-root PATH      数据根目录（包含 01/02/...）
    --out PATH            输出目录
    --area {urban,rural}  区域类型（影响 HSM 系数选择）
    --combine-directions  是否合并双向计算
    --config PATH         可选，YAML 项目配置
    --aadt-factors PATH   可选，AADT 因子 JSON
    --hsm-overrides PATH  可选，缺失几何默认值 JSON
    --calibration-c FLOAT 可选，本地校准系数，默认 1.0
    --verbose             输出更多日志

python -m highd_hsm.cli estimate one
    --id STR              recording id（仅用于命名）
    --dir PATH            单个 recording 目录
    [同上若干参数]
```

---

## 输出文件说明

每个 `out/<id>/` 下将包含：

- `structure.json`：车道数（上/下行）、车道宽度统计、限速（km/h）、估计段长 `L`（m）、录制时长等。
- `flow.json`：按方向流量（veh/h）、车型组成（car/truck）、分钟/5 分钟级的时序 CSV 路径。
- `hsm_prediction.json`：按方向或合并方向的年均事故数（总量/严重度/单车/多车）、`k(L)`、使用的 CMF/校准系数。
- `report.md`：人类可读的摘要与图表（流量曲线、车道宽度分布、预测结果分解等）。

---

## 工作原理（简述）

1. **结构识别**：基于 `upper/lowerLaneMarkings` 推得上/下行**可用车道数**与**宽度**；限速来自 `recordingMeta.speedLimit`；段长 `L` 基于 `tracks.csv` 的**视距/坐标范围**稳健估计（有回退策略）。  
2. **交通流量**：按 `tracksMeta.drivingDirection` 分方向统计**唯一车辆数**，除以录时换算为 veh/h；并输出车型组成与分钟级曲线。  
3. **AADT**：将小时流量通过**系数表**年化（若无系数，则采用简化近似）。  
4. **HSM 预测**：选取**自由路段 SPF** 与 **CMF** 组合，按（AADT、段长、车道数、区域类型）估计**年均事故数**，并给出**过散参数** `k(L)`；允许应用**本地校准系数 C**。

> 备注：HSM 参数与分布来自公开资料/用户提供的参数表；本项目**不包含**手册原文。

---

## 验证与局限

- **地域差异**：HighD（德国）与 HSM（美国多州）存在差异；结果更适合**相对比较/方法演示**或在**本地校准**下使用。  
- **短时→年化误差**：HighD 仅为短时观测；建议尽可能使用地区化的**月/周几/小时因子**或本地**连续计数站**数据。  
- **缺失几何要素**：若无法从背景图像可靠提取（如路肩/隔离带/曲线），默认 **CMF=1.0**，会在报告中明示。  
- **无观测事故数**：默认不启用 EB 合并；若用户提供观测值，可在 `hsm_models/eb.py` 接口启用。

---

## 开发与测试

- 目录结构（简化）：
  ```text
  highd_hsm/
    ├─ highd_hsm/
    │   ├─ io_highd.py       # 数据加载与容错
    │   ├─ structure.py      # 结构识别
    │   ├─ flow.py           # 流量统计与时序
    │   ├─ aadt.py           # 年化
    │   ├─ hsm_models/
    │   │   ├─ freeway_spf.py
    │   │   └─ eb.py
    │   ├─ report.py         # 报告生成
    │   └─ cli.py            # Typer CLI
    ├─ config/               # 示例配置
    └─ tests/                # 单元测试与最小数据片段
  ```

- 运行测试：
  ```bash
  pytest -q
  ```

- 代码风格：PEP 8；建议使用 `ruff`/`black`（可选）。

---

## 常见问题

**Q1：必须提供 AADT 因子表吗？**  
A：不是。若不提供，程序将使用**简化近似**（小时流量×24），但建议在正式分析中提供**地区化因子**。

**Q2：道路几何缺失怎么办？**  
A：可在 `config/hsm_overrides.json` 指定**默认假设**（如车道宽度、路肩、隔离带/护栏等），对应 CMF 将据此取值；若留空则 CMF=1.0。

**Q3：能从背景图像自动识别隔离带/护栏吗？**  
A：当前版本未启用。可在后续版本尝试使用 OpenCV/分割模型提取，再映射为 CMF。

**Q4：如何在 Spyder 中运行？**  
A：确保 Spyder 解释器指向 `highd_hsm` 环境；在 Console 中 `cd` 到项目根目录，执行上面的 CLI 命令即可。

---

## 致谢

- HighD 数据集作者与维护者；
- 开源社区的 `pandas / numpy / matplotlib / pydantic / typer` 等项目；
- 交通安全分析（HSM）相关公开资料与工具的研究者与实践者。

---

## 许可证

本项目示例代码遵循 **MIT License**（或根据你单位合规进行调整）。本项目不包含 HighD 数据与 HSM 原文或受版权保护的参数表。
