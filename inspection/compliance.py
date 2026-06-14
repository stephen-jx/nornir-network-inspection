"""
inspection.compliance — Configuration Compliance Audit
========================================================
Checks running-config against a set of compliance rules via CLI.

Compliance items (all via Netmiko CLI):
  1. AAA authentication configured
     - Huawei: display current-configuration | include aaa
     - H3C:    display current-configuration | include authentication-mode
  2. SNMP read-only community string set
     - Both:   display current-configuration | include snmp-agent community read
  3. NTP server configured
     - Both:   display current-configuration | include ntp
  4. SSH enabled & Telnet disabled
     - Both:   display current-configuration | include ssh
               display current-configuration | include telnet
  5. Login banner configured
     - Both:   display current-configuration | include header

  Each check result: pass / fail / skip
  Alert: any required item fails → warning

Output:
  - checks: list[dict] — {item, result, detail, severity}
  - pass_count: int
  - fail_count: int
  - compliance_alert: str — normal / warning
"""

import re
import logging

from nornir.core.task import Task, Result

from inspection.base import InspectionTask


class ComplianceCheck(InspectionTask):
    """Audit device configuration compliance."""

    name = "compliance"

    # Compliance rules definition
    RULES = [
        {
            "id": "AAA",
            "name": "AAA 认证配置",
            "huawei_cmd": "display current-configuration | include aaa",
            "h3c_cmd": "display current-configuration | include authentication-mode",
            "pass_pattern": r"(aaa|authentication-mode\s+(?:scheme|local|radius|hwtacacs))",
            "severity": "required",
        },
        {
            "id": "SNMP_RO",
            "name": "SNMP 只读团体字",
            "huawei_cmd": "display current-configuration | include snmp-agent community read",
            "h3c_cmd": "display current-configuration | include snmp-agent community read",
            "pass_pattern": r"snmp-agent\s+community\s+read",
            "severity": "required",
        },
        {
            "id": "NTP_SERVER",
            "name": "NTP Server 配置",
            "huawei_cmd": "display current-configuration | include ntp",
            "h3c_cmd": "display current-configuration | include ntp",
            "pass_pattern": r"(ntp-service\s+unicast-server|ntp\s+unicast-server|ntp-server)",
            "severity": "required",
        },
        {
            "id": "SSH_ENABLED",
            "name": "SSH 已启用",
            "huawei_cmd": "display current-configuration | include ssh",
            "h3c_cmd": "display current-configuration | include ssh",
            "pass_pattern": r"(ssh\s+server\s+enable|ssh\s+server\s+port|stelnet\s+server\s+enable)",
            "severity": "required",
        },
        {
            "id": "TELNET_DISABLED",
            "name": "Telnet 已禁用",
            "huawei_cmd": "display current-configuration | include telnet",
            "h3c_cmd": "display current-configuration | include telnet",
            "pass_pattern": None,  # Special handling: no match = pass (Telnet not configured)
            "fail_pattern": r"telnet\s+server\s+enable",
            "invert": True,        # Absence of pattern is good
            "severity": "recommended",
        },
        {
            "id": "BANNER",
            "name": "登录 Banner 已配置",
            "huawei_cmd": "display current-configuration | include header login",
            "h3c_cmd": "display current-configuration | include header login",
            "pass_pattern": r"header\s+login",
            "severity": "recommended",
        },
    ]

    def run(self, task: Task) -> Result:
        self.pre_check(task)
        logger = logging.getLogger(f"inspection.{self.name}")

        result_data = {
            "checks": [],
            "pass_count": 0,
            "fail_count": 0,
            "compliance_alert": "normal",
        }

        for rule in self.RULES:
            check_result = self._check_rule(task, rule)
            result_data["checks"].append(check_result)

            if check_result["result"] == "pass":
                result_data["pass_count"] += 1
            elif check_result["result"] == "fail":
                result_data["fail_count"] += 1

            logger.debug("[%s] %s → %s", task.host.name, rule["id"], check_result["result"])

        # Determine alert: warning if any required check fails
        failed_required = [
            c for c in result_data["checks"]
            if c["result"] == "fail" and c["severity"] == "required"
        ]
        if failed_required:
            result_data["compliance_alert"] = "warning"

        logger.info("[%s] Compliance — pass:%d fail:%d alert:%s",
                    task.host.name, result_data["pass_count"],
                    result_data["fail_count"], result_data["compliance_alert"])

        self.post_check(task, result_data)
        return Result(host=task.host, result=result_data)

    # ------------------------------------------------------------------
    # Rule Check
    # ------------------------------------------------------------------
    def _check_rule(self, task: Task, rule: dict) -> dict:
        """Execute a single compliance rule check.

        Returns dict: {item, name, result, detail, severity}
        """
        base = {
            "item": rule["id"],
            "name": rule["name"],
            "result": "skip",
            "detail": "",
            "severity": rule.get("severity", "required"),
        }

        # Select command by vendor
        cmd = rule["huawei_cmd"] if self.is_huawei(task) else rule["h3c_cmd"]

        output = self.try_netmiko_cli(task, cmd)
        if output is None:
            base["result"] = "skip"
            base["detail"] = "CLI 命令执行失败"
            return base

        # Inverted check: absence of pattern is pass
        if rule.get("invert"):
            fail_pattern = rule.get("fail_pattern", "")
            if fail_pattern and re.search(fail_pattern, output, re.IGNORECASE):
                base["result"] = "fail"
                base["detail"] = f"检测到不应存在的配置"
            else:
                base["result"] = "pass"
                base["detail"] = "未检测到，符合预期"
            return base

        # Normal check: presence of pattern is pass
        pass_pattern = rule.get("pass_pattern", "")
        if pass_pattern and re.search(pass_pattern, output, re.IGNORECASE):
            base["result"] = "pass"
            base["detail"] = "已配置"
        else:
            base["result"] = "fail"
            base["detail"] = "未检测到配置"

        return base
