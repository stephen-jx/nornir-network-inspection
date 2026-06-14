# Network Inspection Tool

> 华为 + H3C 混合网络环境自动化巡检系统 — Nornir 并发调度，NAPALM / Netmiko 双引擎采集，Excel 报表输出。

[![Python](https://img.shields.io/badge/Python-3.9+-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Nornir](https://img.shields.io/badge/Nornir-3.x-orange.svg)](https://nornir.tech/)

---

## 特性

- **9 大巡检模块**：设备可达性、CPU/内存使用率、风扇/电源/温度、接口状态与错包、配置备份、NTP 同步、配置合规审计、日志异常扫描
- **双引擎采集**：NAPALM 优先获取结构化数据，Netmiko CLI 兜底解析
- **多厂商兼容**：华为 VRP 系列与 H3C Comware 系列交换机、路由器
- **高并发执行**：Nornir threaded 模式，大幅缩短巡检耗时
- **Excel 报表**：汇总 Sheet + 每设备接口详情 Sheet，三级条件着色（绿/黄/红）
- **设备清单**：静态 YAML 管理，支持按组分配连接参数和凭据
- **灵活运行**：全量巡检、指定模块、单台设备、连接测试、dry-run

---

## 快速开始

### 环境要求

- Python 3.9+
- 目标设备已开启 SSH

### 安装

```bash
git clone <repo-url>
cd network-inspection
pip install -r requirements.txt
```

**依赖清单**：`nornir`、`nornir-napalm`、`nornir-netmiko`、`napalm`、`netmiko`、`openpyxl`、`textfsm`、`pyyaml`

### 配置设备清单

编辑 `inventory/hosts.yaml`，添加你的设备：

```yaml
"core-sw-01":
  hostname: "10.1.1.1"
  groups:
    - huawei
  data:
    role: core
    site: "北京数据中心"
    vendor: huawei
```

编辑 `inventory/groups.yaml`，按厂商组配置连接参数：

```yaml
huawei:
  platform: huawei_vrp
  username: admin
  password: your_password
  connection_options:
    napalm:
      platform: huawei_vrp
    netmiko:
      extras:
        device_type: huawei

h3c:
  platform: hp_comware
  username: admin
  password: your_password
  connection_options:
    napalm:
      platform: hp_comware
    netmiko:
      extras:
        device_type: hp_comware
```

### 运行

```bash
# 全量巡检（所有模块，所有设备）
python main.py

# 连接测试
python main.py --test

# 仅列出设备清单
python main.py --dry-run

# 指定模块
python main.py --modules ping,cpu_memory,ntp

# 单台设备
python main.py --host core-sw-01

# 开启调试日志
python main.py --debug
```

**输出物**：
- Excel 报表：`reports/inspection_YYYYMMDD_HHMMSS.xlsx`
- 配置备份：`config_backups/{hostname}/{hostname}_running-config_{timestamp}.cfg`
- 运行日志：`logs/inspection_YYYYMMDD.log`

---

## 命令行用法

```
python main.py [选项]

路径选项:
  --config PATH         Nornir 配置文件路径（默认 config.yaml）
  --inventory PATH      设备清单目录路径（默认 inventory）
  --output PATH         Excel 报表输出目录（默认 reports）
  --backup-dir PATH     配置备份存档目录（默认 config_backups）
  --log-dir PATH        日志输出目录（默认 logs）

运行选项:
  --modules MODULES     指定巡检模块，逗号分隔（默认全部）
  --host HOST           单台设备巡检
  --debug               开启 DEBUG 级别日志
  --dry-run             仅列出设备，不执行巡检
  --test                连通性测试
  --num-workers N       并发线程数（默认 20）
  --retry N             失败重试次数（默认 1）
```

---

## 巡检模块说明

| 模块 | 命令 | 功能 | 告警条件 |
|------|------|------|---------|
| 设备可达性 | `ping` | NAPALM `get_facts()` 检查主机名、uptime、厂商、版本 | 不可达 → 跳过后续巡检 |
| CPU/内存 | `cpu_memory` | NAPALM `get_environment()` → CLI 兜底（`display cpu-usage` 等） | CPU > 80% / Memory > 85% |
| 硬件健康 | `hardware` | NAPALM `get_environment()` → `display environment/fan/power` | 风扇/电源非 Normal，温度超厂商阈值 |
| 接口状态 | `interfaces` | NAPALM `get_interfaces()` → `display interface brief` | 关键口 down，错包率 > 0.1% |
| 配置备份 | `config_backup` | NAPALM `get_config()` → `display current-configuration` | 备份失败 |
| NTP 同步 | `ntp` | NAPALM `get_ntp_stats()` → `display ntp status` / `display ntp-service status` | 未同步，时钟偏差 > 1000ms |
| 合规审计 | `compliance` | Netmiko CLI 检查 AAA/SNMP/NTP/SSH/Telnet/Banner 配置 | 任一必需项 fail |
| 日志异常 | `log_check` | CLI 抓取 `display logbuffer`，扫描异常关键词 | 匹配条数 > 5 |

**告警三级着色**：绿色（normal）、黄色（warning）、红色（critical）。

---

## 项目结构

```
network-inspection/
├── README.md
├── DESIGN.md                     # 设计方案
├── IMPLEMENTATION.md             # 实施计划
├── config.yaml                   # Nornir 配置
├── requirements.txt              # Python 依赖
├── main.py                       # 主入口
├── inventory/
│   ├── hosts.yaml                # 设备列表
│   ├── groups.yaml               # 设备组配置
│   └── defaults.yaml             # 全局默认值
├── inspection/
│   ├── __init__.py
│   ├── base.py                   # 巡检基类
│   ├── ping.py                   # 设备可达性
│   ├── cpu_memory.py             # CPU/内存使用率
│   ├── hardware.py               # 硬件健康
│   ├── interfaces.py             # 接口状态及错包
│   ├── config_backup.py          # 配置备份
│   ├── ntp.py                    # NTP 同步状态
│   ├── compliance.py             # 配置合规审计
│   ├── log_check.py              # 日志异常扫描
│   └── reporter.py               # Excel 报表生成
├── logs/                         # 日志（运行时）
├── reports/                      # 报表（运行时）
└── config_backups/               # 配置备份存档（运行时）
```

---

## License

[MIT](LICENSE)
