# Copyright 2025 Johan Hallbäck
# See LICENSE file for licensing details.

"""Functions for managing and interacting with the workload.

The intention is that this module could be used outside the context of a charm.
"""

import logging
import sys
import subprocess

from charmlibs import apt
from charms.operator_libs_linux.v1.systemd import service_restart, service_enable, service_running
from jinja2 import Environment, FileSystemLoader

logger = logging.getLogger(__name__)


def install() -> None:
    """Install the workload (by installing a snap, for example)."""
    # You'll need to implement this function.
    try:
        apt.update()
        apt.add_package(["kea", "postgresql-client-common", "postgresql-client-16"])
    except PackageError as e:
        logger.error("could not install package. Reason: %s", e.message)
        sys.exit(1)


def start() -> None:
    """Start the workload (by running a commamd, for example)."""
    # You'll need to implement this function.
    # Ideally, this function should only return once the workload is ready to use.


def get_version() -> str | None:
    """Get the running version of the workload."""
    # If we can't get the version, it is assumed the software isn't installed
    try:
        cmd = ["kea-admin", "--version"]
        sp = subprocess.run(cmd, check=True, capture_output=True, encoding="utf-8")
        logger.info(f"kea_dhcp.get_version()): got version: {sp.stdout}")
        # Remove trailing newline
        return sp.stdout.rstrip()
    except Exception as e:
        logger.warning(f"kea-admin.get_version()): Failed to get version: {e}")
        return None

    return None

def get_status() -> str:
    return "This is the default normal status"

def db_init(dbconn) -> int:
    """Initialize the database"""
    logger.debug(f": {dbconn}")

    keavers = ["kea-admin", "db-version", "pgsql", "-h", dbconn["dbhost"], "-u", dbconn["dbuser"],
        "-p", dbconn["dbpass"], "-n", dbconn["dbname"]]
    keainit = ["kea-admin", "db-init", "pgsql", "-h", dbconn["dbhost"], "-u", dbconn["dbuser"],
        "-p", dbconn["dbpass"], "-n", dbconn["dbname"]]

    sp = subprocess.run(keavers, check=False, capture_output=True, encoding="utf-8")
    if sp.returncode == 3:
        logger.info(f"DB does not exist, we can try to create it: {sp}")
        try:
            subprocess.run(keainit, check=True, capture_output=True, encoding="utf-8")
            logger.info(f"Database creation result: {sp}")
        except Exception as e:
            # Throw an error to ensure automatic retry later
            logger.error(f"Error initializing database: {str(e)}")
            sys.exit(1)
    elif sp.returncode != 0:
        logger.info(f"DB init unknown result: {sp}")
        sys.exit(1)

    return 0


def render_and_reload(interfaces, dbconn) -> int:
    # This should later only reload on actual config change
    env = Environment(loader=FileSystemLoader("templates"),
            keep_trailing_newline=True, trim_blocks=False)
    kea_dhcp4_conf_tmpl = env.get_template("shared_lease_db/kea-dhcp4.conf.j2")
    
    # TODO: If we have no postgres relation, we must do something here
    kea_dhcp4_conf = kea_dhcp4_conf_tmpl.render(
        interfaces=interfaces,
        dbhost=dbconn["dbhost"],
        dbname=dbconn["dbname"],
        dbuser=dbconn["dbuser"],
        dbpass=dbconn["dbpass"],
    )
    with open("/etc/kea/kea-dhcp4.conf", "w") as file:
        file.write(kea_dhcp4_conf)

    # reload/restart in some way here
    service_restart("kea-dhcp4-server")