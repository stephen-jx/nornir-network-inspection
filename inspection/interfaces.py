"""
inspection.interfaces — Interface Status & Error Statistics
=============================================================
Strategy:
  1. Try NAPALM get_interfaces() + get_interfaces_counters().
  2. Fallback to CLI 'display interface brief' + 'display interface'.

Output:
  - interfaces: list[dict] — {name, status, speed, mtu,
                               in_errors, out_errors, in_crc_errors,
                               error_rate_pct, alert}
  - total_up: int
  - total_down: int
  - alert_interfaces: list[str]  — interfaces with alerts
"""

import re
import logging

from nornir.core.task import Task, Result

from inspection.base import InspectionTask


class InterfaceCheck(InspectionTask):
    """Check interface status and error statistics."""

    name = "interfaces"

    # Error rate threshold (percentage of total packets)
    ERROR_RATE_YELLOW = 0.01    # 0.01%
    ERROR_RATE_RED = 0.1        # 0.1%

    def run(self, task: Task) -> Result:
        self.pre_check(task)
        logger = logging.getLogger(f"inspection.{self.name}")

        result_data = {
            "interfaces": [],
            "total_up": 0,
            "total_down": 0,
            "alert_interfaces": [],
        }

        # Attempt NAPALM
        napalm_ifaces = self.try_napalm_get(task, "get_interfaces")
        napalm_counters = self.try_napalm_get(task, "get_interfaces_counters")

        if napalm_ifaces:
            result_data["interfaces"] = self._process_napalm_interfaces(
                task, napalm_ifaces, napalm_counters or {}
            )
        else:
            # Fallback to CLI
            logger.debug("[%s] NAPALM failed, falling back to CLI", task.host.name)
            result_data["interfaces"] = self._collect_interfaces_cli(task)

        # Aggregate statistics
        for iface in result_data["interfaces"]:
            if iface.get("status") == "up":
                result_data["total_up"] += 1
            else:
                result_data["total_down"] += 1

            if iface.get("alert"):
                result_data["alert_interfaces"].append(iface["name"])

        logger.info(
            "[%s] Interfaces — up:%d down:%d alerts:%d",
            task.host.name,
            result_data["total_up"],
            result_data["total_down"],
            len(result_data["alert_interfaces"]),
        )

        self.post_check(task, result_data)
        return Result(host=task.host, result=result_data)

    # ------------------------------------------------------------------
    # NAPALM Processing
    # ------------------------------------------------------------------
    def _process_napalm_interfaces(self, task: Task,
                                   ifaces: dict,
                                   counters: dict) -> list[dict]:
        """Process NAPALM structured interface data."""
        results = []

        for name, iface in ifaces.items():
            entry = {
                "name": name,
                "status": "up" if iface.get("is_up") and iface.get("is_enabled") else "down",
                "speed": iface.get("speed", 0),
                "mtu": iface.get("mtu", 0),
                "in_errors": 0,
                "out_errors": 0,
                "in_crc_errors": 0,
                "error_rate_pct": 0.0,
                "alert": False,
            }

            # Merge counters if available
            if name in counters:
                c = counters[name]
                entry["in_errors"] = c.get("in_errors", 0)
                entry["out_errors"] = c.get("out_errors", 0)
                entry["in_crc_errors"] = c.get("in_crc_errors", 0)

            # Calculate error rate
            entry["error_rate_pct"] = self._calc_error_rate(entry)
            entry["alert"] = self._interface_alert(entry)

            results.append(entry)

        return results

    # ------------------------------------------------------------------
    # CLI Fallback
    # ------------------------------------------------------------------
    def _collect_interfaces_cli(self, task: Task) -> list[dict]:
        """Collect interface status via CLI dispatch."""
        if self.is_huawei(task):
            return self._parse_huawei_interfaces(task)
        elif self.is_h3c(task):
            return self._parse_h3c_interfaces(task)
        return []

    def _parse_huawei_interfaces(self, task: Task) -> list[dict]:
        """Parse Huawei interface data."""
        # Step 1: Get brief status
        brief = self.try_netmiko_cli(task, "display interface brief")
        if not brief:
            return []

        interfaces = self._parse_huawei_brief(brief)

        # Step 2: Get detailed error counters for each physical interface
        for iface in interfaces:
            details = self.try_netmiko_cli(
                task, f"display interface {iface['name']}"
            )
            if details:
                self._parse_huawei_interface_errors(iface, details)

        return interfaces

    @staticmethod
    def _parse_huawei_brief(output: str) -> list[dict]:
        """Parse Huawei 'display interface brief'."""
        interfaces = []
        in_table = False

        for line in output.splitlines():
            # Detect table header
            if "Interface" in line and "PHY" in line and "Protocol" in line:
                in_table = True
                continue

            if not in_table:
                continue

            # Table row format:
            # "GigabitEthernet0/0/1     up     up        0.01%  0.01%  0    0"
            # or "GE0/0/1               up     up        --     --    --   --"
            match = re.match(
                r"(\S+)\s+(up|down|\*down)\s+(up|down)",
                line, re.IGNORECASE
            )
            if match:
                iface_name = match.group(1)
                phy_state = match.group(2)

                if iface_name and not iface_name.startswith("Interface"):
                    interfaces.append({
                        "name": iface_name,
                        "status": "up" if phy_state.lower() == "up" else "down",
                        "speed": 0,
                        "mtu": 1500,
                        "in_errors": 0,
                        "out_errors": 0,
                        "in_crc_errors": 0,
                        "error_rate_pct": 0.0,
                        "alert": False,
                    })

            # End of table
            if not line.strip() or line.startswith("---"):
                in_table = False

        return interfaces

    @staticmethod
    def _parse_huawei_interface_errors(iface: dict, output: str) -> None:
        """Parse Huawei 'display interface <name>' error counters."""
        # "Input errors: 1234, CRC: 56, ..."
        in_err = re.search(r"Input\s+errors?\s*:\s*(\d+)", output, re.IGNORECASE)
        out_err = re.search(r"Output\s+errors?\s*:\s*(\d+)", output, re.IGNORECASE)
        crc_err = re.search(r"CRC\s*:\s*(\d+)", output, re.IGNORECASE)

        if in_err:
            iface["in_errors"] = int(in_err.group(1))
        if out_err:
            iface["out_errors"] = int(out_err.group(1))
        if crc_err:
            iface["in_crc_errors"] = int(crc_err.group(1))

        iface["error_rate_pct"] = InterfaceCheck._calc_error_rate(iface)
        iface["alert"] = InterfaceCheck._interface_alert(iface)

    def _parse_h3c_interfaces(self, task: Task) -> list[dict]:
        """Parse H3C interface data."""
        brief = self.try_netmiko_cli(task, "display interface brief")
        if not brief:
            return []

        interfaces = self._parse_h3c_brief(brief)

        for iface in interfaces:
            details = self.try_netmiko_cli(
                task, f"display interface {iface['name']}"
            )
            if details:
                self._parse_h3c_interface_errors(iface, details)

        return interfaces

    @staticmethod
    def _parse_h3c_brief(output: str) -> list[dict]:
        """Parse H3C 'display interface brief'."""
        interfaces = []
        in_table = False

        for line in output.splitlines():
            if "Interface" in line and "Link" in line:
                in_table = True
                continue

            if not in_table:
                continue

            # "GE1/0/1    UP   1G    F(a)   A    1"
            match = re.match(
                r"(\S+)\s+(UP|DOWN|ADM)",
                line, re.IGNORECASE
            )
            if match:
                iface_name = match.group(1)
                status = match.group(2)

                if not iface_name.startswith("Interface"):
                    interfaces.append({
                        "name": iface_name,
                        "status": "up" if status.upper() == "UP" else "down",
                        "speed": 0,
                        "mtu": 1500,
                        "in_errors": 0,
                        "out_errors": 0,
                        "in_crc_errors": 0,
                        "error_rate_pct": 0.0,
                        "alert": False,
                    })

            if not line.strip():
                in_table = False

        return interfaces

    @staticmethod
    def _parse_h3c_interface_errors(iface: dict, output: str) -> None:
        """Parse H3C 'display interface <name>' error counters."""
        in_err = re.search(r"Input\s+errors?\s*:\s*(\d+)", output, re.IGNORECASE)
        out_err = re.search(r"Output\s+errors?\s*:\s*(\d+)", output, re.IGNORECASE)
        crc_err = re.search(r"CRC\s*[:\s]+(\d+)", output, re.IGNORECASE)

        if in_err:
            iface["in_errors"] = int(in_err.group(1))
        if out_err:
            iface["out_errors"] = int(out_err.group(1))
        if crc_err:
            iface["in_crc_errors"] = int(crc_err.group(1))

        iface["error_rate_pct"] = InterfaceCheck._calc_error_rate(iface)
        iface["alert"] = InterfaceCheck._interface_alert(iface)

    # ------------------------------------------------------------------
    # Error Rate Calculation
    # ------------------------------------------------------------------
    @staticmethod
    def _calc_error_rate(iface: dict) -> float:
        """Calculate error rate as percentage of total errors."""
        total_errors = iface.get("in_errors", 0) + iface.get("out_errors", 0)
        # Error rate is heuristic — typically we flag on absolute error count
        # combined with CRC errors rather than a true packet ratio.
        return total_errors

    @staticmethod
    def _interface_alert(iface: dict) -> bool:
        """
        Determine if interface warrants an alert.
        Alerts on: status down, CRC errors present, or high error count.
        """
        # Alert on down status
        if iface.get("status") != "up":
            return True

        # Alert on CRC errors
        if iface.get("in_crc_errors", 0) > 0:
            return True

        # Alert on high input/output errors
        if iface.get("in_errors", 0) > 100 or iface.get("out_errors", 0) > 100:
            return True

        return False
