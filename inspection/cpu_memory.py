"""
inspection.cpu_memory — CPU & Memory Usage Collection
======================================================
Strategy:
  1. Try NAPALM get_environment() for CPU.
  2. Fallback to vendor-specific CLI commands with regex/TextFSM parsing.

  CPU thresholds:  yellow > 70%,  red > 80%
  MEM thresholds:  yellow > 75%,  red > 85%

Output:
  - cpu_usage_pct: float
  - memory_usage_pct: float
  - memory_total_mb: int
  - memory_used_mb: int
  - cpu_alert: str (normal / warning / critical)
  - memory_alert: str (normal / warning / critical)
"""

import re
import logging

from nornir.core.task import Task, Result

from inspection.base import InspectionTask


class CpuMemoryCheck(InspectionTask):
    """Collect CPU and memory usage from Huawei and H3C devices."""

    name = "cpu_memory"

    # Thresholds
    CPU_YELLOW = 70.0
    CPU_RED = 80.0
    MEM_YELLOW = 75.0
    MEM_RED = 85.0

    def run(self, task: Task) -> Result:
        self.pre_check(task)
        logger = logging.getLogger(f"inspection.{self.name}")

        result_data = {
            "cpu_usage_pct": 0.0,
            "memory_usage_pct": 0.0,
            "memory_total_mb": 0,
            "memory_used_mb": 0,
            "cpu_alert": "normal",
            "memory_alert": "normal",
        }

        # --- CPU Collection ---
        cpu_usage = self._collect_cpu(task)
        if cpu_usage is not None:
            result_data["cpu_usage_pct"] = cpu_usage
            result_data["cpu_alert"] = self._cpu_alert_level(cpu_usage)
            logger.info("[%s] CPU: %.1f%% (%s)",
                        task.host.name, cpu_usage, result_data["cpu_alert"])

        # --- Memory Collection ---
        mem_usage, mem_total, mem_used = self._collect_memory(task)
        if mem_usage is not None:
            result_data["memory_usage_pct"] = mem_usage
            result_data["memory_total_mb"] = mem_total
            result_data["memory_used_mb"] = mem_used
            result_data["memory_alert"] = self._mem_alert_level(mem_usage)
            logger.info("[%s] Memory: %.1f%% (%s)",
                        task.host.name, mem_usage, result_data["memory_alert"])

        self.post_check(task, result_data)
        return Result(host=task.host, result=result_data)

    # ------------------------------------------------------------------
    # CPU Collection
    # ------------------------------------------------------------------
    def _collect_cpu(self, task: Task) -> float | None:
        """Collect CPU usage percentage. Returns None on failure."""

        # Attempt NAPALM get_environment
        env = self.try_napalm_get(task, "get_environment")
        if env and "cpu" in env:
            cpu_data = env["cpu"]
            if isinstance(cpu_data, dict) and "%usage" in cpu_data:
                return float(cpu_data["%usage"])
            if isinstance(cpu_data, list) and len(cpu_data) > 0:
                return float(cpu_data[0].get("%usage", 0))

        # Fallback to CLI
        if self.is_huawei(task):
            return self._parse_huawei_cpu(task)
        elif self.is_h3c(task):
            return self._parse_h3c_cpu(task)
        return None

    def _parse_huawei_cpu(self, task: Task) -> float | None:
        """Parse Huawei 'display cpu-usage' output."""
        output = self.try_netmiko_cli(task, "display cpu-usage")
        if not output:
            return None

        # Look for "CPU Usage Stat. Cycle: 60 (Second)\nCPU Usage       : 23%"
        # or "CPU utilization for five seconds: 15%"
        match = re.search(
            r"CPU\s*(?:Usage|utilization)[^\d]*[:：]\s*(\d+(?:\.\d+)?)\s*%",
            output, re.IGNORECASE
        )
        if match:
            return float(match.group(1))

        # Alternative: per-slot CPU usage table
        # "Slot 1 CPU 0 Usage : 23.4%"
        match = re.search(r"CPU\s+\d+\s+Usage\s*:\s*(\d+\.?\d*)%", output)
        if match:
            return float(match.group(1))

        return None

    def _parse_h3c_cpu(self, task: Task) -> float | None:
        """Parse H3C 'display cpu' output."""
        output = self.try_netmiko_cli(task, "display cpu")
        if not output:
            return None

        # "CPU usage: 15% in last 5 seconds"
        match = re.search(
            r"CPU\s*(?:usage|utilization)[^\d]*[:：]\s*(\d+(?:\.\d+)?)\s*%",
            output, re.IGNORECASE
        )
        if match:
            return float(match.group(1))

        # Per-slot: "Slot 1 CPU 0 CPU usage: 12% in last 5 seconds"
        match = re.search(r"CPU\s+usage\s*:\s*(\d+\.?\d*)%", output)
        if match:
            return float(match.group(1))

        return None

    # ------------------------------------------------------------------
    # Memory Collection
    # ------------------------------------------------------------------
    def _collect_memory(self, task: Task) -> tuple[float | None, int, int]:
        """
        Collect memory usage. Returns (usage_pct, total_mb, used_mb).
        """

        if self.is_huawei(task):
            return self._parse_huawei_memory(task)
        elif self.is_h3c(task):
            return self._parse_h3c_memory(task)
        return None, 0, 0

    def _parse_huawei_memory(self, task: Task) -> tuple[float | None, int, int]:
        """Parse Huawei 'display memory-usage' output."""
        output = self.try_netmiko_cli(task, "display memory-usage")
        if not output:
            return None, 0, 0

        # "Memory utilization percentage : 45%"
        pct_match = re.search(
            r"Memory\s+utilization\s+percentage\s*:\s*(\d+(?:\.\d+)?)\s*%",
            output, re.IGNORECASE
        )
        if pct_match:
            pct = float(pct_match.group(1))

            # Also extract total/used
            # "Total Memory: 2048 M bytes"
            total_match = re.search(r"Total\s+Memory\s*[:\s]+(\d+)\s*M", output, re.IGNORECASE)
            used_match = re.search(r"Used\s+Memory\s*[:\s]+(\d+)\s*M", output, re.IGNORECASE)

            total = int(total_match.group(1)) if total_match else 0
            used = int(used_match.group(1)) if used_match else 0
            return pct, total, used

        return None, 0, 0

    def _parse_h3c_memory(self, task: Task) -> tuple[float | None, int, int]:
        """Parse H3C 'display memory' output."""
        output = self.try_netmiko_cli(task, "display memory")
        if not output:
            return None, 0, 0

        # "Memory utilization: 38%"
        pct_match = re.search(
            r"Memory\s+utilization\s*[:\s]+(\d+(?:\.\d+)?)\s*%",
            output, re.IGNORECASE
        )
        if pct_match:
            pct = float(pct_match.group(1))

            total_match = re.search(r"Total\s*[:\s]+(\d+)\s*M", output, re.IGNORECASE)
            used_match = re.search(r"Used\s*[:\s]+(\d+)\s*M", output, re.IGNORECASE)

            total = int(total_match.group(1)) if total_match else 0
            used = int(used_match.group(1)) if used_match else 0
            return pct, total, used

        return None, 0, 0

    # ------------------------------------------------------------------
    # Alert Level Helpers
    # ------------------------------------------------------------------
    @classmethod
    def _cpu_alert_level(cls, pct: float) -> str:
        if pct > cls.CPU_RED:
            return "critical"
        if pct > cls.CPU_YELLOW:
            return "warning"
        return "normal"

    @classmethod
    def _mem_alert_level(cls, pct: float) -> str:
        if pct > cls.MEM_RED:
            return "critical"
        if pct > cls.MEM_YELLOW:
            return "warning"
        return "normal"
