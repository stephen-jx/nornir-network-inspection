"""
inspection.hardware — Fan / Power / Temperature Health Check
=============================================================
Strategy:
  1. Try NAPALM get_environment() for structured hardware data.
  2. Fallback to vendor-specific CLI parsing.

Output:
  - fans: list[dict]  — {id, status, slot}
  - powers: list[dict] — {id, status, slot}
  - temperatures: list[dict] — {sensor, temperature, threshold, status}
  - fan_alert: str   — normal / warning / critical
  - power_alert: str — normal / warning / critical
  - temp_alert: str  — normal / warning / critical
"""

import re
import logging

from nornir.core.task import Task, Result

from inspection.base import InspectionTask


class HardwareCheck(InspectionTask):
    """Check fan, power supply, and temperature health."""

    name = "hardware"

    # Temperature thresholds (Celsius) — will be overridden if device reports own thresholds
    TEMP_YELLOW = 50
    TEMP_RED = 65

    def run(self, task: Task) -> Result:
        self.pre_check(task)
        logger = logging.getLogger(f"inspection.{self.name}")

        result_data = {
            "fans": [],
            "powers": [],
            "temperatures": [],
            "fan_alert": "normal",
            "power_alert": "normal",
            "temp_alert": "normal",
        }

        # Attempt NAPALM
        env = self.try_napalm_get(task, "get_environment")
        if env:
            result_data["fans"] = env.get("fans", []) or {}
            result_data["powers"] = env.get("power", []) or {}
            result_data["temperatures"] = env.get("temperature", []) or {}
        else:
            # Fallback to CLI
            logger.debug("[%s] NAPALM get_environment failed, falling back to CLI", task.host.name)
            result_data["fans"] = self._collect_fans_cli(task)
            result_data["powers"] = self._collect_powers_cli(task)
            result_data["temperatures"] = self._collect_temps_cli(task)

        # Assess alerts
        result_data["fan_alert"] = self._assess_fans(result_data["fans"])
        result_data["power_alert"] = self._assess_powers(result_data["powers"])
        result_data["temp_alert"] = self._assess_temps(result_data["temperatures"])

        logger.info(
            "[%s] Hardware — fans:%s power:%s temp:%s",
            task.host.name,
            result_data["fan_alert"],
            result_data["power_alert"],
            result_data["temp_alert"],
        )

        self.post_check(task, result_data)
        return Result(host=task.host, result=result_data)

    # ------------------------------------------------------------------
    # CLI Fallback: Fans
    # ------------------------------------------------------------------
    def _collect_fans_cli(self, task: Task) -> list[dict]:
        """Collect fan status via CLI (Huawei & H3C)."""
        fans = []

        if self.is_huawei(task):
            output = self.try_netmiko_cli(task, "display fan")
            if output:
                fans = self._parse_huawei_fans(output)
        elif self.is_h3c(task):
            output = self.try_netmiko_cli(task, "display fan")
            if output:
                fans = self._parse_h3c_fans(output)

        return fans

    @staticmethod
    def _parse_huawei_fans(output: str) -> list[dict]:
        """Parse Huawei 'display fan' output."""
        fans = []
        # "FanID   FanNum  Status   Speed    Mode    Airflow"
        # "1       1       Normal    60%     Auto     Front-to-Back"
        for line in output.splitlines():
            match = re.search(
                r"(\d+)\s+\d+\s+(Normal|Abnormal|Fail)\s+(\d+)%",
                line, re.IGNORECASE
            )
            if match:
                fans.append({
                    "id": match.group(1),
                    "status": "ok" if match.group(2).lower() == "normal" else "error",
                    "speed_pct": int(match.group(3)),
                })
        return fans

    @staticmethod
    def _parse_h3c_fans(output: str) -> list[dict]:
        """Parse H3C 'display fan' output."""
        fans = []
        # "Fan 1 State: Normal"
        for line in output.splitlines():
            match = re.search(r"Fan\s+(\d+)\s+State\s*:\s*(Normal|Abnormal|Fail)", line, re.IGNORECASE)
            if match:
                fans.append({
                    "id": match.group(1),
                    "status": "ok" if match.group(2).lower() == "normal" else "error",
                })
        return fans

    # ------------------------------------------------------------------
    # CLI Fallback: Power Supplies
    # ------------------------------------------------------------------
    def _collect_powers_cli(self, task: Task) -> list[dict]:
        """Collect power supply status via CLI."""
        powers = []

        if self.is_huawei(task):
            output = self.try_netmiko_cli(task, "display power")
            if output:
                powers = self._parse_huawei_powers(output)
        elif self.is_h3c(task):
            output = self.try_netmiko_cli(task, "display power")
            if output:
                powers = self._parse_h3c_powers(output)

        return powers

    @staticmethod
    def _parse_huawei_powers(output: str) -> list[dict]:
        """Parse Huawei 'display power' output."""
        powers = []
        # "PowerID  Status    Mode    Current(A)  Voltage(V)  Power(W)"
        # "1        Normal    AC      2.5         12.0        30"
        for line in output.splitlines():
            match = re.search(
                r"(\d+)\s+(Normal|Abnormal|Fail|NotSupply)",
                line, re.IGNORECASE
            )
            if match:
                status_raw = match.group(2).lower()
                powers.append({
                    "id": match.group(1),
                    "status": "ok" if status_raw in ("normal",) else "error",
                })
        return powers

    @staticmethod
    def _parse_h3c_powers(output: str) -> list[dict]:
        """Parse H3C 'display power' output."""
        powers = []
        # "Power 1 State: Normal"
        for line in output.splitlines():
            match = re.search(r"Power\s+(\d+)\s+State\s*:\s*(Normal|Abnormal|Fail|Absent)", line, re.IGNORECASE)
            if match:
                status_raw = match.group(2).lower()
                powers.append({
                    "id": match.group(1),
                    "status": "ok" if status_raw == "normal" else "error",
                })
        return powers

    # ------------------------------------------------------------------
    # CLI Fallback: Temperatures
    # ------------------------------------------------------------------
    def _collect_temps_cli(self, task: Task) -> list[dict]:
        """Collect temperature sensor readings via CLI."""
        temps = []

        if self.is_huawei(task):
            output = self.try_netmiko_cli(task, "display environment")
            if output:
                temps = self._parse_huawei_temps(output)
        elif self.is_h3c(task):
            output = self.try_netmiko_cli(task, "display environment")
            if output:
                temps = self._parse_h3c_temps(output)

        return temps

    @staticmethod
    def _parse_huawei_temps(output: str) -> list[dict]:
        """Parse Huawei 'display environment' temperature section."""
        temps = []
        in_temp_section = False

        for line in output.splitlines():
            if "temperature" in line.lower() and ("slot" in line.lower() or "sensor" in line.lower()):
                in_temp_section = True
                continue

            if in_temp_section:
                # "1    40   55    Normal"
                match = re.search(
                    r"(\d+)\s+(\d+)\s+(\d+)\s+(Normal|Abnormal|Warning)",
                    line, re.IGNORECASE
                )
                if match:
                    temp_val = int(match.group(2))
                    threshold = int(match.group(3))
                    status_raw = match.group(4).lower()
                    temps.append({
                        "slot": match.group(1),
                        "temperature": temp_val,
                        "threshold": threshold,
                        "status": "ok" if status_raw == "normal" else "warning",
                    })
                elif line.strip() == "" or any(k in line.lower() for k in ["fan", "power"]):
                    in_temp_section = False

        return temps

    @staticmethod
    def _parse_h3c_temps(output: str) -> list[dict]:
        """Parse H3C 'display environment' temperature section."""
        temps = []
        # "Slot 1 Temperature: 38C, Normal"
        for line in output.splitlines():
            match = re.search(
                r"(?:Slot\s+)?(\d+)\s+Temperature\s*:\s*(\d+)\s*C?\s*,\s*(Normal|Abnormal|Warning|High)",
                line, re.IGNORECASE
            )
            if match:
                temp_val = int(match.group(2))
                status_raw = match.group(3).lower()
                temps.append({
                    "slot": match.group(1),
                    "temperature": temp_val,
                    "threshold": HardwareCheck.TEMP_RED,
                    "status": "ok" if status_raw == "normal" else "warning",
                })
        return temps

    # ------------------------------------------------------------------
    # Alert Assessment
    # ------------------------------------------------------------------
    @staticmethod
    def _assess_fans(fans: list[dict]) -> str:
        if not fans:
            return "normal"
        errors = [f for f in fans if f.get("status") != "ok"]
        if errors:
            return "critical" if len(errors) == len(fans) else "warning"
        return "normal"

    @staticmethod
    def _assess_powers(powers: list[dict]) -> str:
        if not powers:
            return "normal"
        errors = [p for p in powers if p.get("status") != "ok"]
        if errors:
            return "critical" if len(errors) == len(powers) else "warning"
        return "normal"

    @staticmethod
    def _assess_temps(temps: list[dict]) -> str:
        if not temps:
            return "normal"
        critical_count = 0
        for t in temps:
            temp = t.get("temperature", 0)
            threshold = t.get("threshold", HardwareCheck.TEMP_RED)
            if temp > threshold:
                return "critical"
            if temp > threshold * 0.8:
                critical_count += 1
        if critical_count > 0:
            return "warning"
        return "normal"
