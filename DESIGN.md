---
AIGC:
    Label: "1"
    ContentProducer: 001191440300708461136T1XGW3
    ProduceID: b214d85dd7720d6aebc0d527816314fb_72519e12680011f1aa625254006c9bbf
    ReservedCode1: CLPzvYRabov9bjuyGErbyQGIiL500m8CcsvweUD4x2jnECz7xMXpRHQivqjynFjuyNbowpZHGhZb/LYZd/Ngtqzi8HWf1R/lzdXVLTgUl/xM0vORihCdGoBSOTMdofAr33NA+eOfBlPcWnQ9lJzLfw9HbSfmbG0Ik2cxbC8ZtVVKRfrRu2rrG+EFmRc=
    ContentPropagator: 001191440300708461136T1XGW3
    PropagateID: b214d85dd7720d6aebc0d527816314fb_72519e12680011f1aa625254006c9bbf
    ReservedCode2: CLPzvYRabov9bjuyGErbyQGIiL500m8CcsvweUD4x2jnECz7xMXpRHQivqjynFjuyNbowpZHGhZb/LYZd/Ngtqzi8HWf1R/lzdXVLTgUl/xM0vORihCdGoBSOTMdofAr33NA+eOfBlPcWnQ9lJzLfw9HbSfmbG0Ik2cxbC8ZtVVKRfrRu2rrG+EFmRc=
---

# 网络巡检系统设计方案

## 1. 项目概述与目标

本项目旨在为华为（Huawei）+ H3C 混合网络环境构建一套自动化网络巡检系统。系统通过 Nornir 框架并发调度，使用 NAPALM 优先获取结构化数据，Napalm 无法覆盖的指标由 Netmiko CLI 兜底采集，最终生成标准化的 Excel 巡检报表。

### 目标

- **全覆盖基础巡检**：设备可达性、CPU/内存使用率、风扇/电源/温度、接口状态及错包统计、配置备份
- **厂商兼容**：华为 VRP 系列交换机/路由器、H3C Comware 系列交换机/路由器
- **并发高效**：Nornir threaded 模式并发执行，大幅缩短巡检耗时
- **结构化报表**：Excel 格式输出，按设备分 Sheet，支持条件着色与汇总页
- **可扩展**：基类抽象 + 插件式巡检模块，新增巡检项只需实现子类

## 2. 技术栈选型

| 组件 | 选型 | 角色 |
|------|------|------|
| 编排框架 | Nornir 3.x | 并发任务调度、设备清单管理、结果聚合 |
| 结构化采集 | NAPALM | 优先通过 get_facts / get_environment / get_interfaces 等 API 获取结构化数据 |
| CLI 兜底 | Netmiko | NAPALM 不支持或返回空的指标，通过 CLI + TextFSM/正则解析 |
| 文本解析 | TextFSM + 正则 | 解析华为 display / H3C display 命令输出 |
| Excel 生成 | openpyxl | 生成带样式的巡检报表 |
| 配置管理 | PyYAML | 解析设备清单 YAML |
| 日志 | Python logging | 记录巡检过程，分设备日志和主控日志 |

### 为什么 Nornir？

- 纯 Python，无 Agent，无额外服务端
- 原生支持多厂商并发，threaded 模式适合 I/O 密集型巡检
- 与 NAPALM / Netmiko 无缝集成
- 设备清单 YAML 管理，简单直观

### NAPALM vs Netmiko 分工

| 巡检项 | NAPALM | Netmiko 兜底 |
|--------|--------|-------------|
| 设备可达性 | `get_facts()` | `ping` 或 `display version` |
| CPU 使用率 | `get_environment()` 部分支持 | `display cpu-usage` (Huawei) / `display cpu` (H3C) |
| 内存使用率 | 不支持 | `display memory-usage` (Huawei) / `display memory` (H3C) |
| 风扇/电源/温度 | `get_environment()` | `display environment` / `display fan` / `display power` |
| 接口状态 | `get_interfaces()` | `display interface brief` |
| 接口错包 | `get_interfaces_counters()` 部分支持 | `display interface` |
| 配置备份 | `get_config()` | `display current-configuration` |

## 3. 架构设计

### 3.1 目录结构

```
network-inspection/
├── config.yaml                 # Nornir 配置文件
├── requirements.txt            # Python 依赖清单
├── main.py                     # 主入口脚本
├── DESIGN.md                   # 设计方案（本文档）
├── IMPLEMENTATION.md           # 实施计划
├── inventory/                  # 设备清单
│   ├── hosts.yaml              # 设备列表
│   ├── groups.yaml             # 设备组配置（huawei / h3c）
│   └── defaults.yaml           # 全局默认配置
├── inspection/                 # 巡检模块包
│   ├── __init__.py
│   ├── base.py                 # 巡检基类
│   ├── ping.py                 # 设备可达性检查
│   ├── cpu_memory.py           # CPU/内存采集
│   ├── hardware.py             # 风扇/电源/温度
│   ├── interfaces.py           # 接口状态及错包
│   ├── config_backup.py        # 配置备份
│   ├── ntp.py                  # NTP 同步状态检查
│   ├── compliance.py           # 配置合规审计
│   ├── log_check.py            # 日志异常扫描
│   └── reporter.py             # Excel 报表生成
├── logs/                       # 日志输出目录（运行时自动创建）
├── reports/                    # Excel 报表输出目录（运行时自动创建）
└── config_backups/             # 配置备份存档目录（运行时自动创建）
```

### 3.2 模块划分

| 模块 | 职责 |
|------|------|
| `main.py` | 命令行入口，巡检流程编排，结果汇总 |
| `base.py` | 定义 `InspectionTask` 抽象基类：`run()` 接口、`task_data` 存储、NAPALM/Netmiko 辅助方法 |
| `ping.py` | `PingCheck`：NAPALM `get_facts()` 确认可达 |
| `cpu_memory.py` | `CpuMemoryCheck`：NAPALM 优先 → Netmiko CLI 兜底 |
| `hardware.py` | `HardwareCheck`：NAPALM `get_environment()` → CLI 兜底 |
| `interfaces.py` | `InterfaceCheck`：NAPALM `get_interfaces()` → CLI 兜底 |
| `config_backup.py` | `ConfigBackup`：NAPALM `get_config()` → CLI 兜底 |
| `reporter.py` | `ExcelReporter`：接收各模块结果，生成带样式的 Excel |

### 3.3 数据流

```
main.py
  │
  ├─ 1. InitNornir(config.yaml) ──→ Nornir 对象
  │
  ├─ 2. 按模块顺序遍历 task_list
  │     │
  │     └─ nr.run(task=module.run, name=module.name)
  │           │
  │           └─ 每个 device 并发执行：
  │                 │
  │                 ├─ 尝试 NAPALM API → 成功 → 结构化 dict
  │                 │
  │                 └─ NAPALM 失败/不支持 → Netmiko CLI → TextFSM/regex 解析
  │
  ├─ 3. 收集 MultiResult → 按设备聚合结果
  │
  └─ 4. ExcelReporter.generate(results) → reports/inspection_YYYYMMDD_HHMMSS.xlsx
```

## 4. 巡检模块清单

### 4.1 设备可达性 (PingCheck)

- **方法**：NAPALM `get_facts()` 检查 hostname / uptime 是否正常返回
- **兜底**：Netmiko 连接测试
- **输出**：reachable (bool), hostname (str), uptime (int), vendor (str), os_version (str)

### 4.2 CPU/内存使用率 (CpuMemoryCheck)

- **方法**：
  - NAPALM：尝试 `get_environment()` 中的 cpu 字段
  - 华为 CLI：`display cpu-usage` → TextFSM 解析
  - H3C CLI：`display cpu` → 正则解析
  - 内存：华为 `display memory-usage`，H3C `display memory`
- **输出**：cpu_usage_pct (float), memory_usage_pct (float), memory_total (int), memory_used (int)
- **告警阈值**：CPU > 80% 告警，Memory > 85% 告警

### 4.3 硬件健康 (HardwareCheck)

- **方法**：
  - NAPALM：`get_environment()` 获取 fan/power/temperature
  - 华为 CLI：`display environment` / `display fan` / `display power`
  - H3C CLI：`display environment` / `display fan` / `display power`
- **输出**：fans (list[dict]), powers (list[dict]), temperatures (list[dict])
- **告警条件**：风扇状态非 Normal/Active，电源非 Normal，温度超过厂商阈值

### 4.4 接口状态 (InterfaceCheck)

- **方法**：
  - NAPALM：`get_interfaces()` + `get_interfaces_counters()`
  - 华为 CLI：`display interface brief` + `display interface <name>`
  - H3C CLI：`display interface brief` + `display interface <name>`
- **输出**：interfaces (list[dict])，每项含 name, status(up/down), speed, mtu, in_errors, out_errors, in_crc_errors
- **告警条件**：管理口/上联口 down，错包率 > 0.1%

### 4.5 配置备份 (ConfigBackup)

- **方法**：
  - NAPALM：`get_config(retrieve='running')`
  - 华为 CLI：`display current-configuration`
  - H3C CLI：`display current-configuration`
- **输出**：backup_path (str)，文件命名 `{hostname}_running-config_{YYYYMMDD-HHMMSS}.cfg`
- **存档目录**：`config_backups/{hostname}/`

## 5. 设备清单 YAML 格式定义

### hosts.yaml 字段说明

```yaml
# 设备名称（唯一标识，Nornir 使用）
"core-sw-01":
  hostname: "192.168.1.1"          # 管理 IP（必填）
  groups:                           # 所属组（必填，决定连接参数）
    - huawei
  data:                             # 自定义数据（可选，巡检时可用）
    role: core                      # 设备角色
    site: "北京数据中心"             # 位置
```

### groups.yaml 字段说明

```yaml
huawei:
  platform: "huawei_vrp"            # NAPALM driver 名称
  connection_options:
    napalm:
      extras:
        optional_args:
          secret: ""                # enable 密码（如需）
    netmiko:
      extras:
        device_type: "huawei"       # Netmiko device_type
        secret: ""                  # enable 密码
```

## 6. 输出 Excel 报表格式

### Sheet: 汇总 (Summary)

| 列 | 说明 |
|----|------|
| 设备名称 | hostname |
| 管理 IP | management IP |
| 厂商 | Huawei / H3C |
| 可达性 | 正常 / 不可达 |
| CPU 使用率 | xx% (绿色<70%/黄色70-80%/红色>80%) |
| 内存使用率 | xx% (同上) |
| 风扇状态 | 正常 / 异常(n/总数) |
| 电源状态 | 正常 / 异常(n/总数) |
| 温度状态 | 正常 / 异常(n/总数) |
| 接口 up 数 | N |
| 接口 down 数 | N (红色>0) |
| 错包率 | xx% |
| 配置备份 | 已备份 / 失败 |
| 巡检时间 | YYYY-MM-DD HH:MM:SS |

### Sheet: 接口详情 (Interfaces)

每设备一个 Sheet，列出所有接口的详细信息。

| 列 | 说明 |
|----|------|
| 接口名称 | GigabitEthernet0/0/1 |
| 状态 | up / down |
| 速率 | 1000Mbps |
| MTU | 1500 |
| 入方向错包 | N |
| 出方向错包 | N |
| CRC 错包 | N |
| 告警 | True/False |

## 7. 错误处理与告警策略

### 错误分类

| 级别 | 类型 | 处理方式 |
|------|------|---------|
| ERROR | 设备不可达 | 标记为 unreachable，跳过后续巡检 |
| ERROR | 认证失败 | 记录日志，跳过该设备 |
| WARNING | NAPALM 不支持 | 自动降级到 Netmiko CLI |
| WARNING | 指标超阈值 | 在 Excel 中红色/黄色高亮 |
| INFO | 正常结果 | 记录到日志 |

### 告警阈值

| 指标 | 黄色预警 | 红色告警 |
|------|---------|---------|
| CPU 使用率 | 70-80% | > 80% |
| 内存使用率 | 75-85% | > 85% |
| 温度 | 80% 厂商阈值 | > 厂商阈值 |
| 接口错包率 | > 0.01% | > 0.1% |
| 风扇/电源状态 | — | 非 Normal |
| 接口状态 | — | 关键接口 down |

### 日志策略

- 主日志：`logs/inspection_YYYYMMDD.log`，记录整体流程和严重错误
- 设备日志：`logs/{hostname}_YYYYMMDD.log`，记录单设备详细巡检过程
- 级别：INFO 默认，DEBUG 可选（命令行 --debug）
*（内容由AI生成，仅供参考）*
