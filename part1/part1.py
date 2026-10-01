#!/usr/bin/env python3

import argparse
import time

import google.auth
import googleapiclient.discovery
from googleapiclient.errors import HttpError


DEFAULT_ZONE = "us-west1-b"
DEFAULT_MACHINE_TYPE = "f1-micro"
#DEFAULT_MACHINE_TYPE = "e2-medium"
DEFAULT_INSTANCE_NAME = "lab5-part1"
FIREWALL_NAME = "allow-5000"
NETWORK_NAME = "default"
NETWORK_TAG = "allow-5000"
FLASK_PORT = "5000"


def create_startup_script():
    """
    Startup script executed automatically when the VM boots.
    It installs and starts the Flask tutorial application.
    """
    return """#!/bin/bash

set -e

apt-get update
apt-get install -y python3 python3-pip git

cd /tmp

git clone https://github.com/cu-csci-4253-datacenter/flask-tutorial
cd flask-tutorial

python3 setup.py install
pip3 install -e .

export FLASK_APP=flaskr
flask init-db

nohup flask run -h 0.0.0.0 &
"""


def firewall_rule_exists(compute, project, firewall_name):
    """
    Check whether a firewall rule with the specified name exists.
    """
    try:
        compute.firewalls().get(
            project=project,
            firewall=firewall_name
        ).execute()

        return True

    except HttpError as error:
        if error.resp.status == 404:
            return False
        raise


def create_firewall_rule(compute, project):
    """
    Create allow-5000 if it does not already exist.
    """
    if firewall_rule_exists(compute, project, FIREWALL_NAME):
        print(f"Firewall rule '{FIREWALL_NAME}' already exists.")
        return

    firewall_body = {
        "name": FIREWALL_NAME,
        "network": f"global/networks/{NETWORK_NAME}",
        "direction": "INGRESS",
        "priority": 1000,
        "sourceRanges": ["0.0.0.0/0"],
        "targetTags": [NETWORK_TAG],
        "allowed": [
            {
                "IPProtocol": "tcp",
                "ports": [FLASK_PORT]
            }
        ]
    }

    operation = compute.firewalls().insert(
        project=project,
        body=firewall_body
    ).execute()

    wait_for_global_operation(
        compute,
        project,
        operation["name"]
    )

    print(f"Created firewall rule '{FIREWALL_NAME}'.")


def create_instance(compute, project, zone, instance_name, machine_type):
    """
    Create the VM instance.
    """
    startup_script = create_startup_script()

    instance_config = {
        "name": instance_name,

        "machineType": (
            f"zones/{zone}/machineTypes/{machine_type}"
        ),

        "disks": [
            {
                "boot": True,
                "autoDelete": True,
                "initializeParams": {
                    "sourceImage": (
                        "projects/ubuntu-os-cloud/"
                        "global/images/family/ubuntu-2204-lts"
                    )
                }
            }
        ],

        "networkInterfaces": [
            {
                "network": "global/networks/default",
                "accessConfigs": [
                    {
                        "type": "ONE_TO_ONE_NAT",
                        "name": "External NAT"
                    }
                ]
            }
        ],

        "metadata": {
            "items": [
                {
                    "key": "startup-script",
                    "value": startup_script
                }
            ]
        }
    }

    print(f"Creating VM '{instance_name}'...")

    operation = compute.instances().insert(
        project=project,
        zone=zone,
        body=instance_config
    ).execute()

    wait_for_zone_operation(
        compute,
        project,
        zone,
        operation["name"]
    )

    print(f"VM '{instance_name}' was created.")


def add_network_tag(compute, project, zone, instance_name):
    """
    Apply the allow-5000 network tag using setTags.
    """
    instance = compute.instances().get(
        project=project,
        zone=zone,
        instance=instance_name
    ).execute()

    current_tags = instance.get("tags", {})
    fingerprint = current_tags.get("fingerprint")

    tag_body = {
        "items": [NETWORK_TAG]
    }

    if fingerprint:
        tag_body["fingerprint"] = fingerprint

    print(f"Adding network tag '{NETWORK_TAG}'...")

    operation = compute.instances().setTags(
        project=project,
        zone=zone,
        instance=instance_name,
        body=tag_body
    ).execute()

    wait_for_zone_operation(
        compute,
        project,
        zone,
        operation["name"]
    )

    print(f"Network tag '{NETWORK_TAG}' added.")


def get_external_ip(compute, project, zone, instance_name):
    """
    Retrieve the VM's external IPv4 address.
    """
    instance = compute.instances().get(
        project=project,
        zone=zone,
        instance=instance_name
    ).execute()

    for interface in instance.get("networkInterfaces", []):
        for access_config in interface.get("accessConfigs", []):
            if access_config.get("natIP"):
                return access_config["natIP"]

    return None


def wait_for_zone_operation(compute, project, zone, operation_name):
    """
    Wait until a zonal Compute Engine operation finishes.
    """
    while True:
        result = compute.zoneOperations().get(
            project=project,
            zone=zone,
            operation=operation_name
        ).execute()

        if result["status"] == "DONE":
            if "error" in result:
                raise RuntimeError(
                    f"Operation failed: {result['error']}"
                )
            return

        time.sleep(2)


def wait_for_global_operation(compute, project, operation_name):
    """
    Wait until a global Compute Engine operation finishes.
    """
    while True:
        result = compute.globalOperations().get(
            project=project,
            operation=operation_name
        ).execute()

        if result["status"] == "DONE":
            if "error" in result:
                raise RuntimeError(
                    f"Operation failed: {result['error']}"
                )
            return

        time.sleep(2)


def main():
    parser = argparse.ArgumentParser(
        description="Create the Lab 5 Part 1 VM."
    )

    parser.add_argument(
        "--name",
        default=DEFAULT_INSTANCE_NAME,
        help="Name of the VM instance."
    )

    parser.add_argument(
        "--zone",
        default=DEFAULT_ZONE,
        help="Google Cloud zone."
    )

    parser.add_argument(
        "--machine-type",
        default=DEFAULT_MACHINE_TYPE,
        help="Google Cloud machine type."
    )

    args = parser.parse_args()

    # Authenticate using Application Default Credentials.
    credentials, project = google.auth.default()

    # Create the Compute Engine API client.
    compute = googleapiclient.discovery.build(
        "compute",
        "v1",
        credentials=credentials
    )

    print(f"Google Cloud project: {project}")
    print(f"Zone: {args.zone}")
    print(f"Machine type: {args.machine_type}")
    print()

    # 1. Make sure the firewall rule exists.
    create_firewall_rule(compute, project)

    # 2. Create the VM.
    create_instance(
        compute,
        project,
        args.zone,
        args.name,
        args.machine_type
    )

    # 3. Apply the required network tag.
    add_network_tag(
        compute,
        project,
        args.zone,
        args.name
    )

    # 4. Retrieve the VM's external IP.
    external_ip = get_external_ip(
        compute,
        project,
        args.zone,
        args.name
    )

    if external_ip is None:
        raise RuntimeError(
            "Could not find an external IP address for the VM."
        )

    print()
    print("Flask application should be available at:")
    print(f"http://{external_ip}:5000")


if __name__ == "__main__":
    main()