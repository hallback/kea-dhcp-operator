#!/usr/bin/env python3
# Copyright 2025 Johan Hallbäck
# See LICENSE file for licensing details.

"""Charm the application."""

import logging
import ops
# A standalone module for workload-specific logic (no charming concerns):
import kea_dhcp

# Import the data platform library
from charms.data_platform_libs.v0.data_interfaces import (
    DatabaseCreatedEvent,
    DatabaseEndpointsChangedEvent,
    DatabaseRequires,
)

logger = logging.getLogger(__name__)


class KeaDhcpCharm(ops.CharmBase):
    """Charm the application."""

    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        framework.observe(self.on.install, self._on_install)
        framework.observe(self.on.start, self._on_start)
        framework.observe(self.on.config_changed, self._on_config_changed)
        framework.observe(self.on.collect_unit_status, self._on_collect_unit_status)

        # TODO: Consider if the database name should be configurable
        self.database_name = f"{self.app.name.replace('-', '_')}_database"
        # This may also continue more variables, like from the charm config
        self.database = DatabaseRequires(
            self, "database", self.database_name
        )

        framework.observe(self.database.on.database_created, self._on_database_created)
        framework.observe(self.database.on.endpoints_changed, self._on_database_endpoints_changed)
        framework.observe(self.on["database"].relation_broken, self._on_relation_broken)

    def _on_install(self, event: ops.InstallEvent):
        """Install the workload on the machine."""
        kea_dhcp.install()

    def _on_start(self, event: ops.StartEvent):
        """Handle start event."""
        self.unit.status = ops.MaintenanceStatus("starting workload")
        kea_dhcp.start()
        version = kea_dhcp.get_version()
        if version is not None:
            self.unit.set_workload_version(version)
        self.unit.status = ops.ActiveStatus()

    def _on_config_changed(self, event: ops.ConfigChangedEvent):
        # TODO: We must stop requiring DB connection later for Kea in HA mode
        # TODO: Some of this can be removed in the yaml rendering also
        if (keaversion := kea_dhcp.get_version()) is not None:
            self.unit.set_workload_version(keaversion)

        if not all([
            self.config["interfaces"],
            self._connection_string,
        ]):
            logger.warning("charm._on_config_changed(): Deferring - config incomplete")
            event.defer()
            return

        kea_dhcp.render_and_reload(self.config["interfaces"].split(","),
            self._connection_string)

    def _on_collect_unit_status(self, event: ops.CollectStatusEvent):
        """This function is run after every other hook"""
        # NOTE: Kea can start but not work without this setting, but throws no errors
        if not self.config["interfaces"]:
            event.add_status(ops.BlockedStatus('mandatory charm option interfaces it not set'))
            return

        if kea_dhcp.get_version() is None:
            event.add_status(ops.BlockedStatus('kea-admin is not installed'))
            # No need to check more things in this case
            return

        if self._connection_string is None:
            if not self.model.relations.get("database"):
                event.add_status(ops.BlockedStatus('database relation missing'))
            else:
                event.add_status(ops.BlockedStatus('database relation incomplete, check the logs'))
            # Config will not render and service won't start until this is fixed
            return
#
#        if not stork.is_running():
#            event.add_status(ops.BlockedStatus('isc-stork-server is not running'))
#
        event.add_status(ops.ActiveStatus(kea_dhcp.get_status()))

    # First database events observers.
    def _on_database_created(self, event: DatabaseCreatedEvent) -> None:
        """Event triggered when a database was created for this application."""
        # TODO: Test first if _connection_string is None?? Better: Check result!
        kea_dhcp.db_init(self._connection_string)
        kea_dhcp.render_and_reload(self.config["interfaces"].split(","),
            self._connection_string)
        
        self.unit.status = ops.ActiveStatus("Database integration is set up")

    def _on_relation_broken(self, event: ops.RelationBrokenEvent) -> None:
        """Event triggered when a database relation is left."""
        if not any([
            *self.model.relations.get("database"),
        ]):
            # This is what we do when the database relation is broken:
            self.unit.status = ops.BlockedStatus("No database integration available")

    def _on_database_endpoints_changed(self, event: DatabaseEndpointsChangedEvent) -> None:
        """Event triggered when the read/write endpoints of the database change."""
        logger.info(f"database endpoints have been changed to: {event.endpoints}")
        if self._connection_string is None:
            logger.info(f"No DB connection string, error?!")
            return
        else:
            logger.info(f"DB Connection string is now: {self._connection_string}")
            kea_dhcp.render_and_reload(self.config["interfaces"].split(","),
                self._connection_string)

    @property
    def _connection_string(self) -> dict | None:
        """Returns the PostgreSQL connection string."""
        # Check if we have a database relation before we proceed
        if not self.model.relations.get("database"):
            logger.warning("charm._connection_string(): No database related")
            return None

        db_data = list(self.database.fetch_relation_data().values())
        data = (
            db_data[0]
            if db_data
            else next(data for data in self.database.fetch_relation_data().values())
        )

        username = data.get("username")
        password = data.get("password")
        endpoints = data.get("endpoints")
        database = data.get("database")
        if None in [username, password, endpoints]:
            return None

        host, port = endpoints.split(":")
        if not host or host == "None":
            return None

        return ({
            "dbname": database,
            "dbuser": username,
            "dbhost": host,
            "dbpass": password,
            "dbport": port,
            "dbopts": "connect_timeout=5 keepalives=1 keepalives_idle=30 keepalives_count=1 tcp_user_timeout=30"
        })


if __name__ == "__main__":  # pragma: nocover
    ops.main(KeaDhcpCharm)
