"""
inspection.log_check — Log Buffer Anomaly Scanner
==================================================
Scans device log buffer for error/exception entries via CLI.

  Huawei:  display logbuffer
  H3C:     display logbuffer

  Keywords scanned:
    critical, error, failed, down, flapping, conflict, exception, alarm

  Alert threshold: > 5 matched entries → warning

Output:
  - total_matches: int           — total matched log entries
  - matched_keywords: dict       — {keyword: count}
  - recent_anomalies: list[str]  — up to 10 most recent matched log lines
  - log_alert: str               — normal / warning
"""

import re
import logging

from nornir.core.task import Task, Result

from inspection.base import InspectionTask


class LogCheck(InspectionTask):
    """Scan device log buffer for anomaly patterns."""

    name = "log_check"

    # Keywords to scan (case-insensitive)
    KEYWORDS = [
        "critical",
        "error",
        "failed",
        "down",
        "flapping",
        "conflict",
        "exception",
        "alarm",
    ]

    # Threshold for warning
    MATCH_THRESHOLD = 5

    # Max recent anomalies to include in result
    MAX_RECENT = 10

    def run(self, task: Task) -> Result:
        self.pre_check(task)
        logger = logging.getLogger(f"inspection.{self.name}")

        result_data = {
            "total_matches": 0,
            "matched_keywords": {},
            "recent_anomalies": [],
            "log_alert": "normal",
        }

        # Collect log buffer via CLI (no NAPALM equivalent)
        output = self.try_netmiko_cli(task, "display logbuffer")
        if not output:
            logger.warning("[%s] Failed to retrieve log buffer", task.host.name)
            result_data["log_alert"] = "warning"
            result_data["recent_anomalies"] = ["无法获取日志缓冲区"]
            self.post_check(task, result_data)
            return Result(host=task.host, result=result_data)

        # Scan for keywords
        matches = self._scan_logs(output)

        result_data["total_matches"] = sum(matches.values())
        result_data["matched_keywords"] = matches

        # Extract recent anomaly lines
        result_data["recent_anomalies"] = self._extract_recent_anomalies(output)

        # Alert assessment
        if result_data["total_matches"] > self.MATCH_THRESHOLD:
            result_data["log_alert"] = "warning"

        logger.info("[%s] Log scan — %d matches (threshold=%d) alert=%s",
                    task.host.name, result_data["total_matches"],
                    self.MATCH_THRESHOLD, result_data["log_alert"])

        self.post_check(task, result_data)
        return Result(host=task.host, result=result_data)

    # ------------------------------------------------------------------
    # Log Scanning
    # ------------------------------------------------------------------
    @classmethod
    def _scan_logs(cls, output: str) -> dict:
        """Scan log buffer output for keyword matches. Returns {keyword: count}."""
        matches = {}
        output_lower = output.lower()

        for keyword in cls.KEYWORDS:
            # Count occurrences of the keyword (word boundary aware for longer keywords)
            count = len(re.findall(re.escape(keyword), output_lower))
            if count > 0:
                matches[keyword] = count

        return matches

    @classmethod
    def _extract_recent_anomalies(cls, output: str) -> list[str]:
        """Extract up to MAX_RECENT lines containing anomaly keywords."""
        matched_lines = []

        for line in output.splitlines():
            line_stripped = line.strip()
            if not line_stripped:
                continue

            line_lower = line_stripped.lower()
            for keyword in cls.KEYWORDS:
                if keyword in line_lower:
                    # Truncate long lines for readability
                    if len(line_stripped) > 200:
                        line_stripped = line_stripped[:197] + "..."
                    matched_lines.append(line_stripped)
                    break

        # Return most recent (the log is typically in chronological order,
        # so the last entries are the most recent)
        if len(matched_lines) > cls.MAX_RECENT:
            matched_lines = matched_lines[-cls.MAX_RECENT:]

        return matched_lines
