#!/usr/bin/env python3
import argparse
import json
import os
import subprocess
import sys
from typing import Any, Dict, List, Tuple

try:
    import yaml  # PyYAML
except ImportError:
    print("Missing dependency: PyYAML. Install with: pip install pyyaml", file=sys.stderr)
    raise


def repo_root() -> str:
    return os.path.dirname(os.path.abspath(__file__))


def run(cmd: List[str], capture: bool = False):
    print("+ " + " ".join(cmd))
    if capture:
        return subprocess.run(cmd, text=True, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return subprocess.call(cmd)


def load_yaml(path: str) -> Dict[str, Any]:
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def deep_merge(base: Dict[str, Any], overlay: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(base)
    for k, v in overlay.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)  # type: ignore[arg-type]
        else:
            out[k] = v
    return out


def vars_path_for_stack(stack: str) -> str:
    return os.path.join(repo_root(), "services", f"Pulumi.{stack}.yaml")


def service_override_path(project_dir: str, stack: str) -> str:
    return os.path.join(project_dir, f"override.Pulumi.{stack}.yaml")


def read_project_name(project_dir: str) -> str:
    """
    Reads `name:` from <project_dir>/Pulumi.yaml.
    Works for runtime: yaml or python, etc.
    """
    pulumi_yaml = os.path.join(project_dir, "Pulumi.yaml")
    if not os.path.exists(pulumi_yaml):
        raise FileNotFoundError(f"Pulumi.yaml not found in project directory: {pulumi_yaml}")
    data = load_yaml(pulumi_yaml)
    name = data.get("name")
    if not name:
        raise ValueError(f"Pulumi.yaml in {project_dir} is missing 'name:'")
    return str(name)


def derive_rg_name(project_dir: str, vars_: Dict[str, Any], stack: str) -> str:
    service = os.path.basename(os.path.abspath(project_dir))
    prefix = (vars_.get("naming") or {}).get("prefix") or "svc"
    return f"rg-{prefix}-{service}-{stack}"


def map_vars_to_pulumi_config(project_dir: str, stack: str, vars_: Dict[str, Any]) -> Dict[str, Any]:
    """
    Map variables to Pulumi config keys.
    For YAML runtime, we use project-namespaced config (project:location, project:resourceGroupName, etc.)
    """
    project = read_project_name(project_dir)
    cfg_prefix = f"{project}:"  # Use project name as prefix

    cfg: Dict[str, Any] = {}

    # Project-scoped config
    if vars_.get("location"):
        cfg[cfg_prefix + "location"] = vars_["location"]

    if "tags" in vars_ and vars_["tags"] is not None:
        cfg[cfg_prefix + "tags"] = vars_["tags"]

    rg_name = vars_.get("resourceGroupName") or derive_rg_name(project_dir, vars_, stack)
    cfg[cfg_prefix + "resourceGroupName"] = rg_name

    # Provider-scoped config (NOT project-prefixed)
    azure = vars_.get("azure") or {}
    if azure.get("tenantId"):
        cfg["azure-native:tenantId"] = azure["tenantId"]
    if azure.get("subscriptionId"):
        cfg["azure-native:subscriptionId"] = azure["subscriptionId"]

    return cfg


def ensure_stack(project_dir: str, stack: str) -> None:
    rc = run(["pulumi", "-C", project_dir, "stack", "select", "-s", stack])
    if isinstance(rc, int) and rc == 0:
        return
    rc = run(["pulumi", "-C", project_dir, "stack", "init", stack])
    if isinstance(rc, int) and rc != 0:
        raise RuntimeError(f"Failed to select/init stack '{stack}' in {project_dir}")


def set_config(project_dir: str, stack: str, key: str, value: Any) -> None:
    base = ["pulumi", "-C", project_dir, "config", "set", "-s", stack]

    if isinstance(value, (dict, list)):
        # For complex types, use JSON without --path flag for better compatibility
        cmd = base + [key, json.dumps(value)]
        rc = run(cmd)
        if isinstance(rc, int) and rc != 0:
            raise RuntimeError(f"Failed to set config '{key}'")
        return

    if value is None:
        return

    cmd = base + [key, str(value)]
    rc = run(cmd)
    if isinstance(rc, int) and rc != 0:
        raise RuntimeError(f"Failed to set config '{key}'")


def apply_config(project_dir: str, stack: str, cfg: Dict[str, Any]) -> None:
    """
    Apply config by directly editing the Pulumi.<stack>.yaml file.
    Adds a header comment to indicate this is auto-generated.
    """
    stack_file = os.path.join(project_dir, f"Pulumi.{stack}.yaml")
    
    # Load existing stack file or create new structure
    if os.path.exists(stack_file):
        existing = load_yaml(stack_file)
    else:
        existing = {}
    
    # Ensure config section exists
    if "config" not in existing:
        existing["config"] = {}
    
    # Merge in new config values
    for k, v in cfg.items():
        existing["config"][k] = v
    
    # Write back to file with header comment
    with open(stack_file, "w", encoding="utf-8") as f:
        f.write("# AUTO-GENERATED by pulumiw.py - DO NOT EDIT\n")
        f.write("# Config is inherited from services/Pulumi.{}.yaml\n".format(stack))
        f.write("# Use override.Pulumi.{}.yaml for service-specific customization\n\n".format(stack))
        yaml.dump(existing, f, default_flow_style=False, sort_keys=False)


def load_catalog() -> List[Dict[str, str]]:
    """Load service catalog from catalog.yaml"""
    catalog_path = os.path.join(repo_root(), "catalog.yaml")
    if not os.path.exists(catalog_path):
        return []
    data = load_yaml(catalog_path)
    return data.get("services", [])


def process_project(project_dir: str, stack: str, cmd: str, extra: List[str]) -> int:
    """Process a single project with the given stack and command"""
    global_vars_file = vars_path_for_stack(stack)
    if not os.path.exists(global_vars_file):
        print(
            f"Vars file not found for stack '{stack}': {global_vars_file}\n"
            f"Create it as services/Pulumi.{stack}.yaml",
            file=sys.stderr,
        )
        return 2

    global_vars = load_yaml(global_vars_file)
    override_vars = load_yaml(service_override_path(project_dir, stack))
    vars_ = deep_merge(global_vars, override_vars)

    cfg = map_vars_to_pulumi_config(project_dir, stack, vars_)

    # Validate location exists
    project = read_project_name(project_dir)
    if f"{project}:location" not in cfg or not cfg[f"{project}:location"]:
        print(f"Missing 'location' in {global_vars_file} (or service override).", file=sys.stderr)
        return 2

    ensure_stack(project_dir, stack)
    apply_config(project_dir, stack, cfg)

    pulumi_cmd = ["pulumi", "-C", project_dir, cmd, "-s", stack] + extra
    rc = run(pulumi_cmd)
    return int(rc) if isinstance(rc, int) else 1


def parse_args(argv: List[str]) -> Tuple[argparse.Namespace, List[str]]:
    p = argparse.ArgumentParser(
        description="pulumiw - run Pulumi projects with shared vars by stack name",
        usage="%(prog)s STACK [SERVICE] [COMMAND] [options]"
    )
    
    # Positional arguments for shorthand syntax
    p.add_argument("stack", nargs="?", help="Stack name (dev, prod, etc.)")
    p.add_argument("service", nargs="?", help="Service name from catalog (az-app1, etc.) or 'all'")
    p.add_argument("command", nargs="?", default="preview", help="Pulumi command (default: preview)")
    
    # Legacy flag-based arguments (for backwards compatibility)
    p.add_argument("--project", help="Project folder, e.g. services/az-app1")
    p.add_argument("--stack", dest="stack_flag", help="Pulumi stack name")
    p.add_argument("--cmd", help="Pulumi command, e.g. preview/up/destroy")
    p.add_argument("--all", action="store_true", help="Apply to all services in catalog.yaml")

    extra: List[str] = []
    if "--" in argv:
        i = argv.index("--")
        extra = argv[i + 1 :]
        argv = argv[:i]

    ns = p.parse_args(argv)
    
    # Normalize: prefer flags over positional for backwards compatibility
    if ns.stack_flag:
        ns.stack = ns.stack_flag
    if ns.cmd:
        ns.command = ns.cmd
    if ns.project and not ns.service:
        # Extract service name from project path
        ns.service = os.path.basename(os.path.abspath(ns.project))
    
    # If service is "all", set the --all flag
    if ns.service == "all":
        ns.all = True
        ns.service = None
    
    # Validate required arguments
    if not ns.stack:
        p.error("STACK is required (either as positional argument or --stack)")
    
    return ns, extra


def main(argv: List[str]) -> int:
    ns, extra = parse_args(argv)

    stack = ns.stack
    cmd = ns.command

    if ns.all:
        # Process all services from catalog
        services = load_catalog()
        if not services:
            print("No services found in catalog.yaml", file=sys.stderr)
            return 2
        
        print(f"Processing {len(services)} service(s) for stack '{stack}'...\n")
        failed = []
        
        for svc in services:
            svc_name = svc.get("name", "unknown")
            svc_path = svc.get("path")
            if not svc_path:
                print(f"Skipping service '{svc_name}': no path defined", file=sys.stderr)
                continue
            
            project_dir = os.path.abspath(svc_path)
            if not os.path.isdir(project_dir):
                print(f"Skipping service '{svc_name}': path not found: {project_dir}", file=sys.stderr)
                continue
            
            print(f"\n{'='*60}")
            print(f"Service: {svc_name} ({svc.get('description', 'no description')})")
            print(f"{'='*60}\n")
            
            rc = process_project(project_dir, stack, cmd, extra)
            if rc != 0:
                failed.append(svc_name)
        
        if failed:
            print(f"\n{'='*60}")
            print(f"Failed services: {', '.join(failed)}")
            print(f"{'='*60}")
            return 1
        
        print(f"\n{'='*60}")
        print(f"All services completed successfully")
        print(f"{'='*60}")
        return 0
    
    # Single service mode
    if not ns.service and not ns.project:
        print("Error: SERVICE name or --project is required unless using 'all'", file=sys.stderr)
        return 2
    
    # Resolve service to project directory
    if ns.service and not ns.project:
        # Look up service in catalog
        services = load_catalog()
        project_dir = None
        for svc in services:
            if svc.get("name") == ns.service:
                project_dir = os.path.abspath(svc.get("path"))
                break
        
        if not project_dir:
            print(f"Error: Service '{ns.service}' not found in catalog.yaml", file=sys.stderr)
            return 2
    else:
        project_dir = os.path.abspath(ns.project)
    
    if not os.path.isdir(project_dir):
        print(f"Project folder not found: {project_dir}", file=sys.stderr)
        return 2

    return process_project(project_dir, stack, cmd, extra)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))