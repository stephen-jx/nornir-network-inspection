"""
inspection.ntp — NTP Synchronization Status Check
==================================================
Strategy:
  1. Try NAPALM get_ntp_servers() / get_ntp_stats() for NTP info.
  2. Fallback to vendor-specific CLI parsing.

  Huawei:  display ntp status
  H3C:     display ntp-service status

  Alerts:
    - Not synchronized → critical
    - Clock offset > 1000ms → warning

Output:
  - ntp_synchronized: bool
  - ntp_server: str        — reference clock source
  - ntp_offset_ms: float   — clock offset in milliseconds
  - ntp_alert: str         — normal / warning / critical
"""

import re
import logging

from nornir.core.task import Task, Result

from inspection.base import InspectionTask


class NtpCheck(InspectionTask):
    """Check NTP synchronization status on Huawei and H3C devices."""

    name = "ntp"

    # Offset threshold in milliseconds
    OFFSET_WARNING_MS = 1000.0

    def run(self, task: Task) -> Result:
        self.pre_check(task)
        logger = logging.getLogger(f"inspection.{self.name}")

        result_data = {
            "ntp_synchronized": False,
            "ntp_server": "",
            "ntp_offset_ms": 0.0,
            "ntp_alert": "critical",
        }

        # Attempt NAPALM — try get_ntp_stats first, then get_ntp_servers
        ntp_stats = self.try_napalm_get(task, "get_ntp_stats")
        ntp_servers = self.try_napalm_get(task, "get_ntp_servers")

        if ntp_stats:
            result_data["ntp_synchronized"] = True
            # Extract reference peer and offset from NAPALM result
            if isinstance(ntp_stats, dict):
                ref_peer = ntp_stats.get("reference", "") or ntp_stats.get("synchronized", "")
                result_data["ntp_server"] = ref_peer
                offset = ntp_stats.get("offset", 0.0)
                result_data["ntp_offset_ms"] = float(offset) if offset else 0.0
            elif isinstance(ntp_stats, list) and len(ntp_stats) > 0:
                first = ntp_stats[0]
                result_data["ntp_server"] = first.get("remote", "") or first.get("reference", "")
                result_data["ntp_offset_ms"] = float(first.get("offset", 0.0))
            logger.info("[%s] NTP synchronized via NAPALM — server=%s offset=%.1fms",
                        task.host.name, result_data["ntp_server"], result_data["ntp_offset_ms"])
        elif ntp_servers:
            # Have servers but no stats — assume synchronized if servers are configured
            if isinstance(ntp_servers, dict) and ntp_servers:
                result_data["ntp_synchronized"] = True
                first_key = next(iter(ntp_servers))
                result_data["ntp_server"] = ntp_servers[first_key] if isinstance(ntp_servers[first_key], str) else first_key
                logger.info("[%s] NTP servers configured via NAPALM", task.host.name)
            elif isinstance(ntp_servers, list) and len(ntp_servers) > 0:
                result_data["ntp_synchronized"] = True
                result_data["ntp_server"] = ntp_servers[0]
                logger.info("[%s] NTP servers configured via NAPALM", task.host.name)
        else:
            # Fallback to CLI
            logger.debug("[%s] NAPALM NTP failed, falling back to CLI", task.host.name)
            result_data = self._collect_ntp_cli(task, result_data)

        # Assess alert
        result_data["ntp_alert"] = self._assess_ntp_alert(
            result_data["ntp_synchronized"],
            result_data["ntp_offset_ms"],
        )

        logger.info("[%s] NTP — sync=%s offset=%.1fms alert=%s",
                    task.host.name, result_data["ntp_synchronized"],
                    result_data["ntp_offset_ms"], result_data["ntp_alert"])

        self.post_check(task, result_data)
        return Result(host=task.host, result=result_data)

    # ------------------------------------------------------------------
    # CLI Fallback
    # ------------------------------------------------------------------
    def _collect_ntp_cli(self, task: Task, result_data: dict) -> dict:
        """Collect NTP status via CLI (Huawei & H3C)."""
        if self.is_huawei(task):
            output = self.try_netmiko_cli(task, "display ntp status")
            if output:
                result_data = self._parse_huawei_ntp(output, result_data)
        elif self.is_h3c(task):
            output = self.try_netmiko_cli(task, "display ntp-service status")
            if output:
                result_data = self._parse_h3c_ntp(output, result_data)
        return result_data

    @staticmethod
    def _parse_huawei_ntp(output: str, result_data: dict) -> dict:
        """Parse Huawei 'display ntp status' output."""
        # "Clock status: synchronized"
        sync_match = re.search(
            r"Clock\s+status\s*:\s*(synchronized|unsynchronized)",
            output, re.IGNORECASE
        )
        if sync_match:
            result_data["ntp_synchronized"] = sync_match.group(1).lower() == "synchronized"

        # "Clock stratum: 3"
        # "Reference clock ID: 10.1.1.100"
        ref_match = re.search(
            r"Reference\s+clock\s+ID\s*:\s*(\S+)",
            output, re.IGNORECASE
        )
        if ref_match:
            result_data["ntp_server"] = ref_match.group(1)

        # "System poll interval: 64  s" — not used for alert
        # Offset is typically not shown in Huawei 'display ntp status'
        # Try to extract from 'display ntp status verbose' if needed
        return result_data

    @staticmethod
    def _parse_h3c_ntp(output: str, result_data: dict) -> dict:
        """Parse H3C 'display ntp-service status' output."""
        # "Clock status: synchronized"
        sync_match = re.search(
            r"Clock\s+status\s*:\s*(synchronized|unsynchronized)",
            output, re.IGNORECASE
        )
        if sync_match:
            result_data["ntp_synchronized"] = sync_match.group(1).lower() == "synchronized"

        # "Reference clock ID: 10.2.1.100"
        ref_match = re.search(
            r"Reference\s+clock\s+ID\s*:\s*(\S+)",
            output, re.IGNORECASE
        )
        if ref_match:
            result_data["ntp_server"] = ref_match.group(1)

        # "Clock offset: 0.123 ms" or "Offset: 0.456"
        offset_match = re.search(
            r"(?:Clock\s+)?[Oo]ffset\s*:\s*([\d.]+)\s*(?:ms|s)",
            output, re.IGNORECASE
        )
        if offset_match:
            offset_val = float(offset_match.group(1))
            # Convert to ms if value is in seconds
            if "s" in output[offset_match.start():offset_match.end()].lower() and "ms" not in output[offset_match.start():offset_match.end()].lower():
                offset_val *= 1000.0
            result_data["ntp_offset_ms"] = offset_val

        return result_data

    # ------------------------------------------------------------------
    # Alert Assessment
    # ------------------------------------------------------------------
    @classmethod
    def _assess_ntp_alert(cls, synchronized: bool, offset_ms: float) -> str:
        """Determine NTP alert level."""
        if not synchronized:
            return "critical"
        if offset_ms > cls.OFFSET_WARNING_MS:
            return "warning"
        return "normal"
