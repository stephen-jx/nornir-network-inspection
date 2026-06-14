"""
inspection.base — Abstract base class for all inspection modules.
===============================================================
Defines the common interface, NAPALM/Netmiko helper methods,
and result storage conventions.
"""

import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Optional

from nornir.core.task import Task, Result
from nornir_napalm.plugins.tasks import napalm_get
from nornir_netmiko.tasks import netmiko_send_command


class InspectionTask(ABC):
    """
    Abstract base class for all inspection modules.

    Subclasses MUST implement:
      - run(task: Task) -> Result

    Optional hooks:
      - pre_check(task)  — called before main logic
      - post_check(task) — called after main logic
    """

    # Module display name (override in subclass)
    name: str = "base"

    # Whether this module requires NAPALM (default True; set False for CLI-only)
    require_napalm: bool = True

    def __init__(self, backup_dir: str = "config_backups", retry_count: int = 1):
        self.backup_dir = Path(backup_dir)
        self.retry_count = retry_count
        self.logger = logging.getLogger(f"inspection.{self.name}")

    # ------------------------------------------------------------------
    # Abstract method — subclasses must implement
    # ------------------------------------------------------------------
    @abstractmethod
    def run(self, task: Task) -> Result:
        """
        Execute the inspection logic for a single device.

        Args:
            task: Nornir Task object — use task.host for device info.

        Returns:
            Result object with inspection data in result attribute.
        """
        ...

    # ------------------------------------------------------------------
    # NAPALM helpers
    # ------------------------------------------------------------------
    def try_napalm_get(self, task: Task, getter: str, **kwargs) -> Optional[Any]:
        """
        Attempt to call a NAPALM getter (e.g. 'get_facts', 'get_environment').

        Returns the structured data on success, or None on failure.
        """
        try:
            result = task.run(
                task=napalm_get,
                getters=[getter],
                **kwargs,
            )
            if result.failed:
                self.logger.debug("[%s] NAPALM %s failed: %s",
                                 task.host.name, getter, result[0].exception)
                return None
            return result.result.get(getter, None)
        except Exception as exc:
            self.logger.debug("[%s] NAPALM %s exception: %s",
                             task.host.name, getter, exc)
            return None

    # ------------------------------------------------------------------
    # Netmiko (CLI) helpers
    # ------------------------------------------------------------------
    def try_netmiko_cli(self, task: Task, command: str,
                        use_textfsm: bool = False) -> Optional[str]:
        """
        Execute a CLI command via Netmiko and return raw output.

        Args:
            task: Nornir Task.
            command: CLI command string (e.g. 'display version').
            use_textfsm: Whether to use TextFSM template for structured output.

        Returns:
            Raw command output string, or None on failure.
        """
        try:
            result = task.run(
                task=netmiko_send_command,
                command_string=command,
                use_textfsm=use_textfsm,
            )
            if result.failed:
                self.logger.debug("[%s] CLI '%s' failed: %s",
                                 task.host.name, command, result[0].exception)
                return None
            return result.result
        except Exception as exc:
            self.logger.debug("[%s] CLI '%s' exception: %s",
                             task.host.name, command, exc)
            return None

    # ------------------------------------------------------------------
    # Vendor detection
    # ------------------------------------------------------------------
    def get_vendor(self, task: Task) -> str:
        """Detect vendor from host group or data field."""
        groups = task.host.groups
        if "huawei" in groups:
            return "huawei"
        if "h3c" in groups:
            return "h3c"
        return task.host.data.get("vendor", "unknown")

    def is_huawei(self, task: Task) -> bool:
        return self.get_vendor(task) == "huawei"

    def is_h3c(self, task: Task) -> bool:
        return self.get_vendor(task) == "h3c"

    # ------------------------------------------------------------------
    # Hooks (optional override)
    # ------------------------------------------------------------------
    def pre_check(self, task: Task) -> None:
        """Hook called before main run logic."""
        self.logger.info("[%s] Starting %s inspection...", task.host.name, self.name)

    def post_check(self, task: Task, result: dict) -> None:
        """Hook called after main run logic."""
        self.logger.info("[%s] %s inspection complete", task.host.name, self.name)

    # ------------------------------------------------------------------
    # Result builder
    # ------------------------------------------------------------------
    def make_result(self, task: Task, data: dict,
                    status: str = "ok",
                    hostname: str = None) -> Result:
        """Build a standardized Result dict and wrap in nornir Result."""
        result_data = {
            "module": self.name,
            "host": task.host.name,
            "hostname": hostname or task.host.hostname,
            "vendor": self.get_vendor(task),
            "status": status,
            "timestamp": task.host.defaults.data.get("_timestamp", ""),
            **data,
        }
        return Result(host=task.host, result=result_data)
