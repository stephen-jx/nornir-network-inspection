"""
inspection.config_backup — Configuration Backup
=================================================
Strategy:
  1. Try NAPALM get_config(retrieve='running').
  2. Fallback to CLI 'display current-configuration'.

Output:
  - backup_path: str  — file path of saved config
  - backup_status: str — ok / failed
  - config_size: int  — byte count of saved config
"""

import logging
from datetime import datetime
from pathlib import Path

from nornir.core.task import Task, Result

from inspection.base import InspectionTask


class ConfigBackup(InspectionTask):
    """Backup device running configuration to local file."""

    name = "config_backup"

    def run(self, task: Task) -> Result:
        self.pre_check(task)
        logger = logging.getLogger(f"inspection.{self.name}")

        result_data = {
            "backup_path": "",
            "backup_status": "failed",
            "config_size": 0,
        }

        # --- Attempt NAPALM ---
        config = self.try_napalm_get(task, "get_config", retrieve="running")

        if not config:
            # --- Fallback to CLI ---
            logger.debug("[%s] NAPALM get_config failed, falling back to CLI", task.host.name)
            config_output = self.try_netmiko_cli(task, "display current-configuration")
            if config_output:
                # NAPALM returns dict with 'running' key; CLI returns raw string
                config = {"running": config_output}

        if config and config.get("running"):
            try:
                config_text = config["running"]
                backup_path = self._save_config(task, config_text)
                result_data["backup_path"] = str(backup_path)
                result_data["backup_status"] = "ok"
                result_data["config_size"] = len(config_text.encode("utf-8"))
                logger.info("[%s] Config backed up → %s (%d bytes)",
                            task.host.name, backup_path.name, result_data["config_size"])
            except Exception as exc:
                logger.error("[%s] Config backup failed: %s", task.host.name, exc)
                result_data["backup_status"] = "failed"
        else:
            logger.warning("[%s] Config backup failed — no config retrieved", task.host.name)

        self.post_check(task, result_data)
        return Result(host=task.host, result=result_data)

    # ------------------------------------------------------------------
    # Save Config to File
    # ------------------------------------------------------------------
    def _save_config(self, task: Task, config_text: str) -> Path:
        """Save configuration to local file with timestamp."""
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        host_dir = self.backup_dir / task.host.name
        host_dir.mkdir(parents=True, exist_ok=True)

        filename = f"{task.host.name}_running-config_{timestamp}.cfg"
        filepath = host_dir / filename

        filepath.write_text(config_text, encoding="utf-8")
        return filepath
