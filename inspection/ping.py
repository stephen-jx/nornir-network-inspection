"""
inspection.ping — Device Reachability Check
============================================
Uses NAPALM get_facts() as primary method.
Falls back to Netmiko 'display version' on failure.

Output:
  - reachable: bool
  - hostname: str
  - uptime: int (seconds)
  - vendor: str
  - os_version: str
  - serial_number: str
"""

import re
import logging

from nornir.core.task import Task, Result

from inspection.base import InspectionTask


class PingCheck(InspectionTask):
    """Check device reachability and collect basic facts."""

    name = "ping"

    def run(self, task: Task) -> Result:
        self.pre_check(task)
        logger = logging.getLogger(f"inspection.{self.name}")

        result_data = {
            "reachable": False,
            "hostname": "",
            "uptime": 0,
            "vendor": self.get_vendor(task),
            "os_version": "",
            "serial_number": "",
        }

        # --- Attempt NAPALM get_facts ---
        facts = self.try_napalm_get(task, "get_facts")

        if facts:
            result_data["reachable"] = True
            result_data["hostname"] = facts.get("hostname", task.host.name)
            result_data["uptime"] = facts.get("uptime", 0)
            result_data["os_version"] = facts.get("os_version", "")
            result_data["serial_number"] = facts.get("serial_number", "")
            logger.info("[%s] Reachable via NAPALM — uptime: %s",
                        task.host.name, result_data["uptime"])
        else:
            # --- Fallback: Netmiko 'display version' ---
            logger.debug("[%s] NAPALM failed, falling back to Netmiko CLI", task.host.name)
            version_output = self.try_netmiko_cli(task, "display version")

            if version_output:
                result_data["reachable"] = True
                # Parse hostname from display version
                # Huawei format: "Huawei Versatile Routing Platform Software\nVRP (R) software, Version ...\nHUAWEI-CORE-01 uptime is ..."
                # H3C format:   "H3C Comware Platform Software\n...\nH3C-CORE-01 uptime is ..."
                hostname_match = re.search(
                    r"(\S+)\s+uptime\s+is", version_output, re.IGNORECASE
                )
                if hostname_match:
                    result_data["hostname"] = hostname_match.group(1)

                # Parse uptime
                uptime_match = re.search(
                    r"uptime\s+is\s+(.+)", version_output, re.IGNORECASE
                )
                if uptime_match:
                    result_data["uptime"] = self._parse_uptime(uptime_match.group(1))

                # Parse version
                version_match = re.search(
                    r"Version\s+([\d.]+)", version_output
                )
                if version_match:
                    result_data["os_version"] = version_match.group(1)

                logger.info("[%s] Reachable via CLI — hostname: %s",
                            task.host.name, result_data["hostname"])
            else:
                logger.warning("[%s] Unreachable — both NAPALM and CLI failed", task.host.name)
                result_data["reachable"] = False

        self.post_check(task, result_data)
        return Result(host=task.host, result=result_data)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _parse_uptime(uptime_str: str) -> int:
        """
        Parse uptime string like '1 week, 2 days, 3 hours, 4 minutes'
        into total seconds.
        """
        total_seconds = 0
        patterns = [
            (r"(\d+)\s*weeks?", 604800),
            (r"(\d+)\s*days?", 86400),
            (r"(\d+)\s*hours?", 3600),
            (r"(\d+)\s*minutes?", 60),
            (r"(\d+)\s*seconds?", 1),
        ]
        for pattern, multiplier in patterns:
            match = re.search(pattern, uptime_str.lower())
            if match:
                total_seconds += int(match.group(1)) * multiplier
        return total_seconds
