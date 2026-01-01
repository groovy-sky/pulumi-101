#!/usr/bin/env python3
"""
pulumiw - Pulumi Wrapper for multi-service, multi-provider deployments.

Merges global config (services/config/<provider>/Pulumi.<stack>.yaml) with
service-specific overrides (<service>/override.Pulumi.<stack>.yaml) and
generates the final Pulumi.<stack>.yaml before running Pulumi commands.
"""
import argparse
import json
import logging
import os
import subprocess
import sys
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

try:
    import yaml  # PyYAML
except ImportError:
    print("Missing dependency: PyYAML. Install with: pip install pyyaml", file=sys.stderr)
    raise

# =============================================================================
# Constants
# =============================================================================

VALID_SERVICE_TYPES = frozenset({"stateless", "stateful"})
DEFAULT_PROVIDER = "azure"
EXIT_SUCCESS = 0
EXIT_FAILURE = 1
EXIT_CONFIG_ERROR = 2

# =============================================================================
# Logging Setup
# =============================================================================

LOG_FORMAT = "%(levelname)s: %(message)s"
LOG_FORMAT_VERBOSE = "%(asctime)s %(levelname)s [%(name)s] %(message)s"

log = logging.getLogger("pulumiw")


def setup_logging(verbose: bool = False) -> None:
    """Configure logging with appropriate level and format."""
    level = logging.DEBUG if verbose else logging.INFO
    fmt = LOG_FORMAT_VERBOSE if verbose else LOG_FORMAT
    logging.basicConfig(level=level, format=fmt, stream=sys.stderr)


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class ServiceEntry:
    """Represents a service entry from catalog.yaml."""
    name: str
    path: str
    provider: str
    type: str
    description: str = ""

    def validate(self) -> List[str]:
        """Return list of validation errors (empty if valid)."""
        errors = []
        if not self.name:
            errors.append("missing 'name'")
        if not self.path:
            errors.append(f"service '{self.name}': missing 'path'")
        if not self.provider:
            errors.append(f"service '{self.name}': missing 'provider'")
        if self.type not in VALID_SERVICE_TYPES:
            errors.append(
                f"service '{self.name}': invalid 'type' '{self.type}' "
                f"(must be one of: {', '.join(sorted(VALID_SERVICE_TYPES))})"
            )
        return errors


@dataclass
class ProcessResult:
    """Result of processing a service."""
    service_name: str
    success: bool
    message: str = ""
    generated_file: Optional[str] = None


# =============================================================================
# File Utilities
# =============================================================================

def repo_root() -> str:
    """Return the repository root directory (where this script lives)."""
    return os.path.dirname(os.path.abspath(__file__))


def load_yaml(path: str) -> Dict[str, Any]:
    """Load a YAML file, returning empty dict if file doesn't exist."""
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def write_yaml(path: str, data: Dict[str, Any], header_lines: List[str]) -> None:
    """Write YAML file with header comments."""
    with open(path, "w", encoding="utf-8") as f:
        for line in header_lines:
            f.write(f"# {line}\n")
        f.write("\n")
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)


# =============================================================================
# Config Merging
# =============================================================================

def deep_merge(base: Dict[str, Any], overlay: Dict[str, Any]) -> Dict[str, Any]:
    """
    Recursively merge overlay dict into base dict.
    Overlay values take precedence; nested dicts are merged recursively.
    """
    out = dict(base)
    for k, v in overlay.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


# =============================================================================
# Path Helpers
# =============================================================================

def global_config_path(stack: str, provider: str) -> str:
    """Get path to global config for a stack and provider."""
    return os.path.join(repo_root(), "services", "config", provider, f"Pulumi.{stack}.yaml")


def service_override_path(project_dir: str, stack: str) -> str:
    """Get path to service-specific override file."""
    return os.path.join(project_dir, f"override.Pulumi.{stack}.yaml")


def service_stack_file(project_dir: str, stack: str) -> str:
    """Get path to the generated Pulumi stack file."""
    return os.path.join(project_dir, f"Pulumi.{stack}.yaml")


# =============================================================================
# Project Helpers
# =============================================================================

def read_project_name(project_dir: str) -> str:
    """Read 'name:' from <project_dir>/Pulumi.yaml."""
    pulumi_yaml = os.path.join(project_dir, "Pulumi.yaml")
    if not os.path.exists(pulumi_yaml):
        raise FileNotFoundError(f"Pulumi.yaml not found: {pulumi_yaml}")
    data = load_yaml(pulumi_yaml)
    name = data.get("name")
    if not name:
        raise ValueError(f"Pulumi.yaml missing 'name:' in {project_dir}")
    return str(name)


def derive_resource_group_name(service_name: str, vars_: Dict[str, Any], stack: str) -> str:
    """Derive Azure resource group name from naming convention."""
    prefix = (vars_.get("naming") or {}).get("prefix") or "svc"
    return f"rg-{prefix}-{service_name}-{stack}"


# =============================================================================
# Config Mapping (vars → Pulumi config)
# =============================================================================

def map_vars_to_pulumi_config(
    project_name: str,
    service_name: str,
    stack: str,
    vars_: Dict[str, Any],
    provider: str
) -> Dict[str, Any]:
    """
    Map merged variables to Pulumi config keys.
    Returns a dict suitable for the 'config:' section of Pulumi.<stack>.yaml.
    """
    cfg: Dict[str, Any] = {}
    prefix = f"{project_name}:"

    # Project-scoped config
    if vars_.get("location"):
        cfg[f"{prefix}location"] = vars_["location"]

    if "tags" in vars_ and vars_["tags"] is not None:
        cfg[f"{prefix}tags"] = vars_["tags"]

    rg_name = vars_.get("resourceGroupName") or derive_resource_group_name(service_name, vars_, stack)
    cfg[f"{prefix}resourceGroupName"] = rg_name

    # Provider-scoped config
    if provider == "azure":
        azure = vars_.get("azure") or {}
        if azure.get("tenantId"):
            cfg["azure-native:tenantId"] = azure["tenantId"]
        if azure.get("subscriptionId"):
            cfg["azure-native:subscriptionId"] = azure["subscriptionId"]

    # Future: add AWS, GCP provider mappings here

    return cfg


# =============================================================================
# Catalog Loading & Validation
# =============================================================================

def load_catalog() -> List[Dict[str, Any]]:
    """Load service catalog from catalog.yaml."""
    catalog_path = os.path.join(repo_root(), "catalog.yaml")
    if not os.path.exists(catalog_path):
        return []
    data = load_yaml(catalog_path)
    return data.get("services", [])


def parse_service_entry(raw: Dict[str, Any]) -> ServiceEntry:
    """Parse a raw catalog entry into a ServiceEntry."""
    return ServiceEntry(
        name=raw.get("name", ""),
        path=raw.get("path", ""),
        provider=raw.get("provider", DEFAULT_PROVIDER),
        type=raw.get("type", ""),
        description=raw.get("description", ""),
    )


def validate_catalog() -> Tuple[List[ServiceEntry], List[str]]:
    """
    Load and validate catalog.yaml.
    Returns (valid_services, errors).
    """
    raw_services = load_catalog()
    if not raw_services:
        return [], ["catalog.yaml is empty or missing"]

    services: List[ServiceEntry] = []
    errors: List[str] = []

    for i, raw in enumerate(raw_services):
        if not isinstance(raw, dict):
            errors.append(f"catalog entry {i}: not a valid dict")
            continue

        entry = parse_service_entry(raw)
        entry_errors = entry.validate()

        if entry_errors:
            errors.extend(entry_errors)
        else:
            # Also check path exists
            abs_path = os.path.join(repo_root(), entry.path)
            if not os.path.isdir(abs_path):
                errors.append(f"service '{entry.name}': path not found: {entry.path}")
            else:
                services.append(entry)

    return services, errors


def find_service(name: str, services: List[ServiceEntry]) -> Optional[ServiceEntry]:
    """Find a service by name in the catalog."""
    for svc in services:
        if svc.name == name:
            return svc
    return None


# =============================================================================
# Config Generation
# =============================================================================

def generate_config(
    project_dir: str,
    stack: str,
    provider: str,
    service_name: str,
) -> Tuple[str, Dict[str, Any]]:
    """
    Generate merged Pulumi config for a service.
    Returns (output_path, config_data).
    Raises exceptions on validation errors.
    """
    # Load global config
    global_file = global_config_path(stack, provider)
    if not os.path.exists(global_file):
        raise FileNotFoundError(
            f"Global config not found: {global_file}\n"
            f"Create it as: services/config/{provider}/Pulumi.{stack}.yaml"
        )

    global_vars = load_yaml(global_file)
    override_file = service_override_path(project_dir, stack)
    override_vars = load_yaml(override_file)

    # Merge: global + override
    merged_vars = deep_merge(global_vars, override_vars)

    # Read project name from Pulumi.yaml
    project_name = read_project_name(project_dir)

    # Map to Pulumi config
    cfg = map_vars_to_pulumi_config(project_name, service_name, stack, merged_vars, provider)

    # Validate required fields
    location_key = f"{project_name}:location"
    if not cfg.get(location_key):
        raise ValueError(f"Missing 'location' in {global_file} or override file")

    # Load existing stack file to preserve encryptionsalt etc.
    output_path = service_stack_file(project_dir, stack)
    existing = load_yaml(output_path) if os.path.exists(output_path) else {}

    # Merge config section
    if "config" not in existing:
        existing["config"] = {}
    existing["config"].update(cfg)

    return output_path, existing


def write_generated_config(
    output_path: str,
    config_data: Dict[str, Any],
    stack: str,
    provider: str,
) -> None:
    """Write the generated config file with header comments."""
    header = [
        "AUTO-GENERATED by pulumiw.py - DO NOT EDIT",
        f"Config inherited from: services/config/{provider}/Pulumi.{stack}.yaml",
        f"Service overrides: override.Pulumi.{stack}.yaml",
    ]
    write_yaml(output_path, config_data, header)


# =============================================================================
# Pulumi Commands
# =============================================================================

def run_command(cmd: List[str], capture: bool = False) -> int:
    """Run a shell command, logging it first."""
    log.debug("Running: %s", " ".join(cmd))
    if capture:
        result = subprocess.run(cmd, text=True, check=False, capture_output=True)
        if result.stdout:
            log.debug("stdout: %s", result.stdout)
        if result.stderr:
            log.debug("stderr: %s", result.stderr)
        return result.returncode
    return subprocess.call(cmd)


def ensure_stack(project_dir: str, stack: str) -> None:
    """Ensure Pulumi stack exists (select or init)."""
    rc = run_command(["pulumi", "-C", project_dir, "stack", "select", "-s", stack], capture=True)
    if rc == 0:
        return
    rc = run_command(["pulumi", "-C", project_dir, "stack", "init", stack])
    if rc != 0:
        raise RuntimeError(f"Failed to select/init stack '{stack}' in {project_dir}")


def run_pulumi(project_dir: str, stack: str, command: str, extra_args: List[str]) -> int:
    """Run a Pulumi command in the given project directory."""
    cmd = ["pulumi", "-C", project_dir, command, "-s", stack] + extra_args
    log.info("Executing: %s", " ".join(cmd))
    return run_command(cmd)


# =============================================================================
# Service Processing
# =============================================================================

def process_service(
    service: ServiceEntry,
    stack: str,
    command: str,
    extra_args: List[str],
    generate_only: bool = False,
    provider_override: Optional[str] = None,
) -> ProcessResult:
    """
    Process a single service: generate config and optionally run Pulumi.
    Returns ProcessResult with success status and details.
    """
    provider = provider_override or service.provider
    project_dir = os.path.join(repo_root(), service.path)

    try:
        # Generate config
        output_path, config_data = generate_config(
            project_dir=project_dir,
            stack=stack,
            provider=provider,
            service_name=service.name,
        )
        write_generated_config(output_path, config_data, stack, provider)
        log.info("Generated: %s", output_path)

        if generate_only:
            return ProcessResult(
                service_name=service.name,
                success=True,
                message="Config generated (--generate-only)",
                generated_file=output_path,
            )

        # Run Pulumi
        ensure_stack(project_dir, stack)
        rc = run_pulumi(project_dir, stack, command, extra_args)

        if rc == 0:
            return ProcessResult(
                service_name=service.name,
                success=True,
                message=f"Command '{command}' succeeded",
                generated_file=output_path,
            )
        else:
            return ProcessResult(
                service_name=service.name,
                success=False,
                message=f"Command '{command}' failed with exit code {rc}",
                generated_file=output_path,
            )

    except Exception as e:
        log.error("Service '%s' failed: %s", service.name, e)
        return ProcessResult(
            service_name=service.name,
            success=False,
            message=str(e),
        )


# =============================================================================
# CLI
# =============================================================================

def create_parser() -> argparse.ArgumentParser:
    """Create the argument parser."""
    p = argparse.ArgumentParser(
        prog="pulumiw",
        description="Pulumi wrapper for multi-service deployments with shared config",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s dev az-app1 preview          # Preview az-app1 in dev
  %(prog)s dev az-app1 up               # Deploy az-app1 in dev
  %(prog)s prod all up                  # Deploy all services in prod
  %(prog)s dev az-app1 --generate-only  # Generate config only, no Pulumi run
  %(prog)s --validate                   # Validate catalog.yaml

Config resolution:
  1. Global: services/config/<provider>/Pulumi.<stack>.yaml
  2. Override: <service>/override.Pulumi.<stack>.yaml
  3. Generated: <service>/Pulumi.<stack>.yaml (DO NOT EDIT)
""",
    )

    # Positional arguments
    p.add_argument("stack", nargs="?", help="Stack name (dev, prod, etc.)")
    p.add_argument("service", nargs="?", help="Service name or 'all'")
    p.add_argument("command", nargs="?", default="preview", help="Pulumi command (default: preview)")

    # Optional flags
    p.add_argument("--provider", help="Override provider (azure, aws, gcp)")
    p.add_argument("--generate-only", "-g", action="store_true",
                   help="Generate config files only, don't run Pulumi")
    p.add_argument("--validate", action="store_true",
                   help="Validate catalog.yaml and exit")
    p.add_argument("--verbose", "-v", action="store_true",
                   help="Enable verbose logging")
    p.add_argument("--quiet", "-q", action="store_true",
                   help="Suppress info messages, show only errors")

    return p


def parse_args(argv: List[str]) -> Tuple[argparse.Namespace, List[str]]:
    """Parse command line arguments, extracting extra args after '--'."""
    extra: List[str] = []
    if "--" in argv:
        i = argv.index("--")
        extra = argv[i + 1:]
        argv = argv[:i]

    parser = create_parser()
    ns = parser.parse_args(argv)

    # Validation mode doesn't need other args
    if ns.validate:
        return ns, extra

    # Normal mode requires stack
    if not ns.stack:
        parser.error("STACK is required (e.g., dev, prod)")

    # Require service unless using --validate
    if not ns.service:
        parser.error("SERVICE is required (use 'all' for all services)")

    return ns, extra


def cmd_validate() -> int:
    """Run catalog validation and report results."""
    log.info("Validating catalog.yaml...")
    services, errors = validate_catalog()

    if errors:
        log.error("Validation failed with %d error(s):", len(errors))
        for err in errors:
            log.error("  - %s", err)
        return EXIT_CONFIG_ERROR

    log.info("Validation passed: %d service(s) defined", len(services))
    for svc in services:
        log.info("  ✓ %s (%s/%s) - %s", svc.name, svc.provider, svc.type, svc.description or "no description")

    return EXIT_SUCCESS


def cmd_process(
    stack: str,
    service_name: str,
    command: str,
    extra_args: List[str],
    generate_only: bool,
    provider_override: Optional[str],
) -> int:
    """Process service(s) and return exit code."""
    # Validate catalog first
    services, errors = validate_catalog()
    if errors:
        log.error("Catalog validation failed:")
        for err in errors:
            log.error("  - %s", err)
        return EXIT_CONFIG_ERROR

    # Determine which services to process
    if service_name == "all":
        targets = services
    else:
        target = find_service(service_name, services)
        if not target:
            log.error("Service '%s' not found in catalog.yaml", service_name)
            log.info("Available services: %s", ", ".join(s.name for s in services))
            return EXIT_CONFIG_ERROR
        targets = [target]

    # Process services
    results: List[ProcessResult] = []
    for svc in targets:
        log.info("")
        log.info("=" * 60)
        log.info("Service: %s (%s)", svc.name, svc.description or "no description")
        log.info("=" * 60)

        result = process_service(
            service=svc,
            stack=stack,
            command=command,
            extra_args=extra_args,
            generate_only=generate_only,
            provider_override=provider_override,
        )
        results.append(result)

    # Summary
    succeeded = [r for r in results if r.success]
    failed = [r for r in results if not r.success]

    log.info("")
    log.info("=" * 60)
    log.info("Summary: %d succeeded, %d failed", len(succeeded), len(failed))
    log.info("=" * 60)

    if failed:
        log.error("Failed services:")
        for r in failed:
            log.error("  ✗ %s: %s", r.service_name, r.message)
        return EXIT_FAILURE

    for r in succeeded:
        log.info("  ✓ %s", r.service_name)

    return EXIT_SUCCESS


def main(argv: List[str]) -> int:
    """Main entry point."""
    ns, extra = parse_args(argv)

    # Setup logging
    if ns.quiet:
        logging.basicConfig(level=logging.ERROR, format=LOG_FORMAT, stream=sys.stderr)
    else:
        setup_logging(verbose=ns.verbose)

    # Dispatch to command
    if ns.validate:
        return cmd_validate()

    return cmd_process(
        stack=ns.stack,
        service_name=ns.service,
        command=ns.command,
        extra_args=extra,
        generate_only=ns.generate_only,
        provider_override=ns.provider,
    )


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
