---
AIGC:
    Label: "1"
    ContentProducer: 001191440300708461136T1XGW3
    ProduceID: b214d85dd7720d6aebc0d527816314fb_7d3d2482680011f18805525400d9a7a1
    ReservedCode1: OgCHs5qE4q9pZrnpJZxRt7kNr/zG+QvIN6vx1agi2UyOlA71sV6AMJqkBmkXV9iw/HyEMvckhsVUSyAyke+pvVRnIFEjP0NuqqQ11H8aPKocrMEp6Yvsqjk1ASUFCIu1f5bk5DfMaI0uhAOWDgK4T/mhUGIfUzCZATwgB8gaaEp4kZMklYPCa1wHz+U=
    ContentPropagator: 001191440300708461136T1XGW3
    PropagateID: b214d85dd7720d6aebc0d527816314fb_7d3d2482680011f18805525400d9a7a1
    ReservedCode2: OgCHs5qE4q9pZrnpJZxRt7kNr/zG+QvIN6vx1agi2UyOlA71sV6AMJqkBmkXV9iw/HyEMvckhsVUSyAyke+pvVRnIFEjP0NuqqQ11H8aPKocrMEp6Yvsqjk1ASUFCIu1f5bk5DfMaI0uhAOWDgK4T/mhUGIfUzCZATwgB8gaaEp4kZMklYPCa1wHz+U=
---

# 网络巡检系统实施计划

## Phase 1: 项目骨架搭建（基础架构）

### 目标
搭建可运行的最小骨架，Nornir 能加载设备清单并连接到设备。

### 任务清单

- [x] 1.1 创建项目目录结构（`inventory/`, `inspection/`, `logs/`, `reports/`, `config_backups/`）
- [x] 1.2 编写 `requirements.txt`：nornir, nornir-napalm, nornir-netmiko, napalm, netmiko, openpyxl, textfsm, pyyaml
- [x] 1.3 编写 `config.yaml`：配置 threaded runner、日志、inventory 路径
- [x] 1.4 编写 `inventory/defaults.yaml`：全局默认连接参数
- [x] 1.5 编写 `inventory/groups.yaml`：huawei 和 h3c 组的 platform 和连接参数
- [x] 1.6 编写 `inventory/hosts.yaml`：含华为和 H3C 示例设备条目
- [x] 1.7 编写 `main.py` 骨架：argparse 命令行参数、InitNornir、基础 run 测试
- [x] 1.8 编写 `inspection/__init__.py`：包初始化
- [x] 1.9 编写 `inspection/base.py`：InspectionTask 抽象基类
- [ ] 1.10 验证：`python main.py --test` 能列出设备清单

### 命令行参数设计

```
python main.py [options]

Options:
  --inventory PATH    设备清单目录路径（默认 ./inventory）
  --config PATH       Nornir 配置文件路径（默认 ./config.yaml）
  --output PATH       Excel 报表输出目录（默认 ./reports）
  --backup-dir PATH   配置备份存档目录（默认 ./config_backups）
  --log-dir PATH      日志输出目录（默认 ./logs）
  --debug             启用 DEBUG 级别日志
  --dry-run           仅列出设备，不执行巡检
  --modules MODULES   指定巡检模块，逗号分隔（默认全部）
  --test              测试连接单个设备
  --host HOST         指定单台设备巡检
```

## Phase 2: 巡检模块逐个实现

### 目标
实现全部 5 个巡检模块，每个模块独立可测。

### 2.1 PingCheck — 设备可达性检查

**文件**：`inspection/ping.py`

**实现步骤**：
1. 继承 `InspectionTask`，实现 `run(task)` 方法
2. 尝试 `task.host.get_facts()`（NAPALM）
3. 提取 hostname, uptime, vendor, os_version
4. 例外处理：连接失败 → 标记 unreachable，记录日志
5. 存储结果到 `task.host["ping_result"]`

**NAPALM API**：`get_facts()`
**兜底**：Netmiko `send_command("display version")` 正则提取

**验证**：单设备运行，确认返回正确的 hostname 和 uptime

### 2.2 CpuMemoryCheck — CPU/内存使用率采集

**文件**：`inspection/cpu_memory.py`

**实现步骤**：
1. 继承 `InspectionTask`
2. CPU：
   - 尝试 `task.host.get_environment()` 提取 cpu
   - 华为兜底：`display cpu-usage` → TextFSM `huawei_vrp_display_cpu_usage.textfsm`
   - H3C 兜底：`display cpu` → 正则解析百分比
3. 内存：
   - 华为兜底：`display memory-usage` → TextFSM
   - H3C 兜底：`display memory` → 正则解析
4. 存储结果到 `task.host["cpu_memory_result"]`

**告警**：CPU > 80% → 记录 WARNING 日志；Memory > 85% → WARNING

**验证**：分别在华为/H3C 设备上运行，确认采集值与设备 display 命令一致

### 2.3 HardwareCheck — 硬件健康检查

**文件**：`inspection/hardware.py`

**实现步骤**：
1. 继承 `InspectionTask`
2. 尝试 `task.host.get_environment()`（NAPALM）
3. 提取 fan / power / temperature 结构
4. 华为兜底：
   - `display environment` → TextFSM 解析温度、风扇
   - `display power` → TextFSM 解析电源
5. H3C 兜底：
   - `display environment` → 正则解析
   - `display power` → 正则解析
6. 状态判定（Normal → OK，其他 → WARNING/ERROR）
7. 存储结果到 `task.host["hardware_result"]`

**告警**：任意风扇/电源非 Normal → WARNING；温度超阈值 → WARNING

**验证**：确认返回的硬件状态与设备实际状态一致

### 2.4 InterfaceCheck — 接口状态及错包检查

**文件**：`inspection/interfaces.py`

**实现步骤**：
1. 继承 `InspectionTask`
2. 尝试 `task.host.get_interfaces()`（NAPALM）
3. 尝试 `task.host.get_interfaces_counters()`（NAPALM）
4. 合并接口状态和计数器数据
5. 华为兜底：
   - `display interface brief` → TextFSM 解析 up/down 和速率
   - `display interface` → 解析错包计数器
6. H3C 兜底：
   - `display interface brief` → TextFSM 解析
   - `display interface` → 正则解析错包
7. 计算错包率
8. 存储结果到 `task.host["interface_result"]`

**告警**：关键接口（管理口、上联口）down → ERROR；错包率 > 0.1% → WARNING

**验证**：确认接口列表、状态与设备 `display interface brief` 一致

### 2.5 ConfigBackup — 配置备份

**文件**：`inspection/config_backup.py`

**实现步骤**：
1. 继承 `InspectionTask`
2. 尝试 `task.host.get_config(retrieve='running')`（NAPALM）
3. 华为兜底：`display current-configuration`
4. H3C 兜底：`display current-configuration`
5. 按 `{hostname}_running-config_{YYYYMMDD-HHMMSS}.cfg` 命名
6. 保存到 `config_backups/{hostname}/` 目录
7. 存储结果到 `task.host["backup_result"]`

**验证**：确认生成的配置文件内容完整，与手动 `display current-configuration` 一致

## Phase 3: Excel 报表生成与主流程编排

### 目标
将所有巡检模块的结果汇总为一份标准化的 Excel 报表。

### 3.1 ExcelReporter

**文件**：`inspection/reporter.py`

**功能**：
1. 接收聚合后的巡检结果 dict
2. 创建汇总 Sheet：
   - 表头：设备名称、管理 IP、厂商、可达性、CPU、内存、风扇、电源、温度、接口 up/down 数、错包率、配置备份、巡检时间
   - 条件着色：绿色（正常）、黄色（预警）、红色（告警）
   - 冻结首行、自动列宽
3. 每设备创建接口详情 Sheet：
   - 表头：接口名、状态、速率、MTU、入错包、出错包、CRC 错包、告警
   - 问题接口红色高亮
4. 文件名：`reports/inspection_{YYYYMMDD}_{HHMMSS}.xlsx`

### 3.2 主流程编排 (main.py)

**流程**：
```
1. parse_args() → 解析命令行参数
2. setup_logging() → 配置日志
3. InitNornir(config_file=args.config) → 初始化 Nornir
4. if --test: 连接测试单设备
5. if --dry-run: 打印设备清单，退出
6. 按顺序执行巡检模块：
   for module in [PingCheck, CpuMemoryCheck, HardwareCheck, InterfaceCheck, ConfigBackup]:
       result = nr.run(task=module().run, name=module.name)
       aggregate_results(result)
7. 生成 Excel 报表
8. 打印巡检摘要到终端
```

## Phase 4: 日志、异常处理、命令行参数完善

### 目标
生产就绪的日志系统、全面的异常处理和灵活的命令行参数。

### 4.1 日志系统

- 主控日志：`logs/inspection_{date}.log`（INFO 级别）
- 设备日志：`logs/{hostname}_{date}.log`（DEBUG 级别可选）
- 格式：`%(asctime)s - %(name)s - %(levelname)s - %(message)s`
- RotatingFileHandler：单文件最大 10MB，保留 5 个备份

### 4.2 异常处理矩阵

| 异常类型 | 处理方式 |
|----------|---------|
| ConnectionException | 标记 unreachable，记录 ERROR 日志 |
| AuthenticationException | 跳过该设备，记录 ERROR |
| CommandErrorException | CLI 命令执行失败，记录 WARNING，尝试降级 |
| TimeoutException | 重试 1 次，仍失败则标记 ERROR |
| Exception | 通用兜底，记录完整 traceback |

### 4.3 命令行完善

- `--retry N`：失败重试次数（默认 1）
- `--timeout N`：连接超时秒数（默认 60）
- `--num-workers N`：并发线程数（默认 20）
- `--no-color`：Excel 不使用条件着色
- `--skip-unreachable`：跳过不可达设备的后续巡检（默认行为）

## Phase 5: NTP / 合规审计 / 日志扫描模块追加

### 目标
扩展巡检覆盖范围，新增 NTP 同步状态检查、配置合规审计、日志异常扫描三个模块。

### 5.1 NtpCheck — NTP 同步状态检查

**文件**：`inspection/ntp.py`

**实现步骤**：
1. 继承 `InspectionTask`，实现 `run(task)` 方法
2. NAPALM 优先尝试 `get_ntp_stats()` 和 `get_ntp_servers()`
3. 华为兜底：`display ntp status` → 正则解析 Clock status、Reference clock ID
4. H3C 兜底：`display ntp-service status` → 正则解析同步状态、参考时钟、时钟偏差
5. 告警判定：未同步 → critical，偏差 > 1000ms → warning
6. 存储结果含 `ntp_synchronized`, `ntp_server`, `ntp_offset_ms`, `ntp_alert` 字段

**验证**：分别在华为/H3C 设备上运行，确认 NTP 状态与设备 `display ntp status` 一致

### 5.2 ComplianceCheck — 配置合规审计

**文件**：`inspection/compliance.py`

**实现步骤**：
1. 继承 `InspectionTask`
2. 通过 Netmiko CLI 逐项抓取 running-config 片段
3. 合规项及命令：
   - AAA 认证：华为 `display current-configuration | include aaa`，H3C `display current-configuration | include authentication-mode`
   - SNMP 只读团体字：`display current-configuration | include snmp-agent community read`
   - NTP Server：`display current-configuration | include ntp`
   - SSH 已启用：`display current-configuration | include ssh`
   - Telnet 已禁用：`display current-configuration | include telnet`（反向检查 — 无匹配即为通过）
   - 登录 Banner：`display current-configuration | include header login`
4. 每项结果：pass / fail / skip，附带 detail 说明
5. 告警判定：任一必需项 fail → warning
6. 存储结果含 `checks`, `pass_count`, `fail_count`, `compliance_alert` 字段

**验证**：对照设备 running-config 逐项核对合规检查结果

### 5.3 LogCheck — 日志异常扫描

**文件**：`inspection/log_check.py`

**实现步骤**：
1. 继承 `InspectionTask`
2. 通过 CLI 抓取日志缓冲区：华为/H3C 均为 `display logbuffer`
3. 扫描关键词：critical, error, failed, down, flapping, conflict, exception, alarm
4. 统计各关键词命中次数，累加得到 `total_matches`
5. 提取最近 10 条异常日志原文放入 `recent_anomalies`
6. 告警判定：匹配条数 > 5 → warning
7. 存储结果含 `total_matches`, `matched_keywords`, `recent_anomalies`, `log_alert` 字段

**验证**：在设备上触发少量异常日志，确认扫描结果与实际日志一致

### 5.4 集成更新

- `inspection/__init__.py`：注册 `NtpCheck`, `ComplianceCheck`, `LogCheck`
- `main.py`：在 `ALL_MODULES` 中注册三个新模块，导入对应类
- `inspection/reporter.py`：汇总 Sheet 新增"NTP 状态"、"合规审计"、"日志异常"三列，与现有告警三级着色一致
- `DESIGN.md`：追加 4.6/4.7/4.8 三个模块描述
- `IMPLEMENTATION.md`：本 Phase 5 说明
*（内容由AI生成，仅供参考）*
