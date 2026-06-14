#!/usr/bin/env python3
"""
main.py — Network Inspection Main Entry Point
==============================================
Orchestrates the full inspection workflow:
  1. Parse CLI arguments
  2. Initialize Nornir with inventory
  3. Run inspection modules in sequence
  4. Generate Excel report

Usage:
  python main.py                          # Run all inspection modules
  python main.py --dry-run                # List devices without inspection
  python main.py --modules ping,cpu       # Run specific modules
  python main.py --host core-sw-01        # Inspect single device
  python main.py --debug                  # Enable debug logging
"""

import argparse
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

from nornir import InitNornir
from nornir.core.filter import F

# Inspection modules (will be fully implemented in Phase 2)
from inspection.ping import PingCheck
from inspection.cpu_memory import CpuMemoryCheck
from inspection.hardware import HardwareCheck
from inspection.interfaces import InterfaceCheck
from inspection.config_backup import ConfigBackup
from inspection.ntp import NtpCheck
from inspection.compliance import ComplianceCheck
from inspection.log_check import LogCheck
from inspection.reporter import ExcelReporter

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DEFAULT_CONFIG = "config.yaml"
DEFAULT_INVENTORY = "inventory"
DEFAULT_REPORTS = "reports"
DEFAULT_BACKUPS = "config_backups"
DEFAULT_LOGS = "logs"

# All available inspection modules (name -> class)
ALL_MODULES = {
    "ping":          PingCheck,
    "cpu_memory":    CpuMemoryCheck,
    "hardware":      HardwareCheck,
    "interfaces":    InterfaceCheck,
    "config_backup": ConfigBackup,
}


# ---------------------------------------------------------------------------
# Logging Setup
# ---------------------------------------------------------------------------
def setup_logging(log_dir: str, debug: bool = False) -> None:
    """Configure application logging: file + console."""
    Path(log_dir).mkdir(parents=True, exist_ok=True)

    level = logging.DEBUG if debug else logging.INFO
    log_file = Path(log_dir) / f"inspection_{datetime.now().strftime('%Y%m%d')}.log"

    # Root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # File handler
    fh = logging.FileHandler(str(log_file), encoding="utf-8")
    fh.setLevel(level)
    fh.setFormatter(logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    ))
    root_logger.addHandler(fh)

    # Console handler
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.WARNING if not debug else logging.DEBUG)
    ch.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    root_logger.addHandler(ch)

    logger = logging.getLogger(__name__)
    logger.info("Logging initialized (level=%s)", "DEBUG" if debug else "INFO")


# ---------------------------------------------------------------------------
# CLI Argument Parser
# ---------------------------------------------------------------------------
def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Network Inspection Tool — Huawei & H3C Mixed Environment",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # Paths
    parser.add_argument(
        "--config", default=DEFAULT_CONFIG,
        help="Path to Nornir config YAML (default: %(default)s)"
    )
    parser.add_argument(
        "--inventory", default=DEFAULT_INVENTORY,
        help="Inventory directory path (default: %(default)s)"
    )
    parser.add_argument(
        "--output", default=DEFAULT_REPORTS,
        help="Excel report output directory (default: %(default)s)"
    )
    parser.add_argument(
        "--backup-dir", default=DEFAULT_BACKUPS,
        help="Config backup archive directory (default: %(default)s)"
    )
    parser.add_argument(
        "--log-dir", default=DEFAULT_LOGS,
        help="Log output directory (default: %(default)s)"
    )

    # Runtime options
    parser.add_argument(
        "--debug", action="store_true",
        help="Enable DEBUG level logging"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="List devices and exit without running inspection"
    )
    parser.add_argument(
        "--test", action="store_true",
        help="Test connectivity to all devices and exit"
    )
    parser.add_argument(
        "--host",
        help="Run inspection on a single device (by host name)"
    )
    parser.add_argument(
        "--modules",
        help="Comma-separated inspection modules to run (default: all). "
             f"Available: {', '.join(ALL_MODULES.keys())}"
    )
    parser.add_argument(
        "--num-workers", type=int, default=20,
        help="Number of concurrent threads (default: %(default)d)"
    )
    parser.add_argument(
        "--retry", type=int, default=1,
        help="Retry count for failed tasks (default: %(default)d)"
    )

    return parser.parse_args()


# ---------------------------------------------------------------------------
# Nornir Initialization
# ---------------------------------------------------------------------------
def init_nornir(config_file: str, num_workers: int):
    """Initialize Nornir with the given config file."""
    logger = logging.getLogger(__name__)

    if not Path(config_file).exists():
        logger.error("Config file not found: %s", config_file)
        sys.exit(1)

    nr = InitNornir(config_file=config_file)

    # Override num_workers if specified
    if hasattr(nr.config.runner, 'options'):
        nr.config.runner.options["num_workers"] = num_workers

    logger.info("Nornir initialized with %d workers, %d hosts",
                num_workers, len(nr.inventory.hosts))
    return nr


# ---------------------------------------------------------------------------
# Test Connectivity
# ---------------------------------------------------------------------------
def test_connectivity(nr):
    """Quick connectivity test using PingCheck."""
    logger = logging.getLogger(__name__)
    logger.info("Running connectivity test on all devices...")

    checker = PingCheck()
    result = nr.run(task=checker.run, name="test_connectivity")

    reachable = 0
    unreachable = 0
    for host_name, multi_result in result.items():
        if multi_result.failed:
            logger.warning("  %-20s UNREACHABLE — %s", host_name, multi_result[0].exception)
            unreachable += 1
        else:
            facts = multi_result[0].result or {}
            logger.info("  %-20s OK — hostname=%s uptime=%s",
                        host_name, facts.get("hostname", "?"), facts.get("uptime", "?"))
            reachable += 1

    logger.info("Connectivity test complete: %d reachable, %d unreachable",
                reachable, unreachable)
    return reachable, unreachable


# ---------------------------------------------------------------------------
# Dry Run — List Devices
# ---------------------------------------------------------------------------
def dry_run(nr):
    """Print device inventory summary."""
    logger = logging.getLogger(__name__)
    print(f"\n{'='*70}")
    print(f"Device Inventory Summary ({len(nr.inventory.hosts)} hosts)")
    print(f"{'='*70}")
    print(f"{'Host Name':<25} {'IP':<18} {'Group':<12} {'Role':<15} {'Site'}")
    print(f"{'-'*25} {'-'*18} {'-'*12} {'-'*15} {'-'*30}")

    for name, host in nr.inventory.hosts.items():
        groups = ",".join(host.groups) if host.groups else "-"
        role = host.data.get("role", "-")
        site = host.data.get("site", "-")
        print(f"{name:<25} {host.hostname:<18} {groups:<12} {role:<15} {site}")

    print(f"{'='*70}\n")


# ---------------------------------------------------------------------------
# Resolve Modules
# ---------------------------------------------------------------------------
def resolve_modules(module_arg: str | None) -> list:
    """Resolve module names to (name, class) tuples."""
    if module_arg:
        names = [n.strip() for n in module_arg.split(",")]
        invalid = set(names) - set(ALL_MODULES.keys())
        if invalid:
            print(f"ERROR: Unknown modules: {', '.join(invalid)}")
            print(f"Available: {', '.join(ALL_MODULES.keys())}")
            sys.exit(1)
        return [(n, ALL_MODULES[n]) for n in names]

    # Default: all modules in dependency order
    return list(ALL_MODULES.items())


# ---------------------------------------------------------------------------
# Main Workflow
# ---------------------------------------------------------------------------
def main():
    args = parse_args()

    # Setup logging
    setup_logging(args.log_dir, args.debug)
    logger = logging.getLogger(__name__)

    # Ensure output directories exist
    for d in [args.output, args.backup_dir, args.log_dir]:
        Path(d).mkdir(parents=True, exist_ok=True)

    # Initialize Nornir
    nr = init_nornir(args.config, args.num_workers)

    # Filter to single host if specified
    if args.host:
        if args.host not in nr.inventory.hosts:
            logger.error("Host '%s' not found in inventory", args.host)
            sys.exit(1)
        nr = nr.filter(F(name=args.host))
        logger.info("Filtered to single host: %s", args.host)

    # Dry run
    if args.dry_run:
        dry_run(nr)
        return

    # Connectivity test
    if args.test:
        reachable, unreachable = test_connectivity(nr)
        sys.exit(0 if unreachable == 0 else 1)

    # Resolve modules to run
    modules = resolve_modules(args.modules)
    logger.info("Inspection modules to run: %s", [m[0] for m in modules])

    # Run inspection modules in sequence
    all_results = {}   # host_name -> {module_name: result_dict}

    for module_name, module_cls in modules:
        logger.info("=" * 50)
        logger.info("Running module: %s", module_name)
        logger.info("=" * 50)

        instance = module_cls(
            backup_dir=args.backup_dir,
            retry_count=args.retry,
        )

        try:
            result = nr.run(task=instance.run, name=module_name)

            # Aggregate results
            for host_name, multi_result in result.items():
                if host_name not in all_results:
                    all_results[host_name] = {}

                if multi_result.failed:
                    logger.warning("  %s: FAILED — %s", host_name, multi_result[0].exception)
                    all_results[host_name][module_name] = {
                        "status": "failed",
                        "error": str(multi_result[0].exception),
                    }
                else:
                    task_result = multi_result[0].result or {}
                    all_results[host_name][module_name] = task_result
                    logger.info("  %s: OK", host_name)

        except Exception as exc:
            logger.error("Module '%s' raised exception: %s", module_name, exc, exc_info=args.debug)

    # Generate Excel report
    logger.info("=" * 50)
    logger.info("Generating Excel report...")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = Path(args.output) / f"inspection_{timestamp}.xlsx"

    reporter = ExcelReporter()
    reporter.generate(all_results, str(report_path))

    logger.info("Report saved: %s", report_path)
    print(f"\nInspection complete. Report: {report_path}")


# ---------------------------------------------------------------------------
# Entry Point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    main()
