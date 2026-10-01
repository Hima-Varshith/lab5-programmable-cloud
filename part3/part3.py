#!/usr/bin/env python3

import argparse
import os
import time

import googleapiclient.discovery
import google.oauth2.service_account as service_account


# -------------------------------------------------------------------
# Configuration
# -------------------------------------------------------------------

DEFAULT_ZONE = "us-west1-b"

VM1_NAME = "lab5-part3-vm1"
VM2_NAME = "lab5-part3-vm2"

MACHINE_TYPE = "f1-micro"
#MACHINE_TYPE = "e2-medium"

IMAGE_PROJECT = "ubuntu-os-cloud"
IMAGE_FAMILY = "ubuntu-2204-lts"

NETWORK = "global/networks/default"
NETWORK_TAG = "allow-5000"

SERVICE_CREDENTIALS_FILE = "service-credentials.json"


# -------------------------------------------------------------------
# Wait for a zonal Compute Engine operation
# -------------------------------------------------------------------

def wait_for_zone_operation(compute, project, zone, operation_name):
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


# -------------------------------------------------------------------
# Startup script for VM-2
#
# VM-2 is the Flask application server.
# -------------------------------------------------------------------

def create_vm2_startup_script():
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


# -------------------------------------------------------------------
# Python program that will run INSIDE VM-1
#
# This program uses the service-account credentials to create VM-2.
# -------------------------------------------------------------------

def create_vm2_launch_code(project, zone):
    vm2_startup_script = create_vm2_startup_script()

    return f'''#!/usr/bin/env python3

import time

import googleapiclient.discovery
import google.oauth2.service_account as service_account


PROJECT = {project!r}
ZONE = {zone!r}

VM2_NAME = {VM2_NAME!r}
MACHINE_TYPE = {MACHINE_TYPE!r}

IMAGE_PROJECT = {IMAGE_PROJECT!r}
IMAGE_FAMILY = {IMAGE_FAMILY!r}

NETWORK = {NETWORK!r}
NETWORK_TAG = {NETWORK_TAG!r}

CREDENTIALS_FILE = "/srv/service-credentials.json"


def wait_for_operation(compute, project, zone, operation_name):
    while True:
        result = compute.zoneOperations().get(
            project=project,
            zone=zone,
            operation=operation_name
        ).execute()

        if result["status"] == "DONE":
            if "error" in result:
                raise RuntimeError(
                    f"VM-2 creation failed: {{result['error']}}"
                )
            return

        time.sleep(2)


# Authenticate using the service-account credentials
credentials = service_account.Credentials.from_service_account_file(
    filename=CREDENTIALS_FILE
)

compute = googleapiclient.discovery.build(
    "compute",
    "v1",
    credentials=credentials
)


# Startup script that VM-2 will run
startup_script = {vm2_startup_script!r}


# VM-2 configuration
instance_config = {{
    "name": VM2_NAME,

    "machineType": (
        f"zones/{{ZONE}}/machineTypes/{{MACHINE_TYPE}}"
    ),

    "disks": [
        {{
            "boot": True,
            "autoDelete": True,
            "initializeParams": {{
                "sourceImage": (
                    f"projects/{{IMAGE_PROJECT}}/global/"
                    f"images/family/{{IMAGE_FAMILY}}"
                )
            }}
        }}
    ],

    "networkInterfaces": [
        {{
            "network": NETWORK,
            "accessConfigs": [
                {{
                    "type": "ONE_TO_ONE_NAT",
                    "name": "External NAT"
                }}
            ]
        }}
    ],

    # Apply the allow-5000 tag so the existing firewall rule
    # can allow Flask traffic on port 5000.
    "tags": {{
        "items": [NETWORK_TAG]
    }},

    "metadata": {{
        "items": [
            {{
                "key": "startup-script",
                "value": startup_script
            }}
        ]
    }}
}}


print("Creating VM-2...")

operation = compute.instances().insert(
    project=PROJECT,
    zone=ZONE,
    body=instance_config
).execute()


wait_for_operation(
    compute,
    PROJECT,
    ZONE,
    operation["name"]
)

print("VM-2 was created successfully.")
'''


# -------------------------------------------------------------------
# Startup script for VM-1
#
# VM-1 retrieves the required data from the metadata server,
# saves it locally, and runs the VM-2 creation program.
# -------------------------------------------------------------------

def create_vm1_startup_script():
    return """#!/bin/bash

set -e

apt-get update
apt-get install -y python3 python3-pip curl

mkdir -p /srv
cd /srv


# Download VM-2 startup script from VM metadata
curl \
  -H "Metadata-Flavor: Google" \
  http://metadata/computeMetadata/v1/instance/attributes/vm2-startup-script \
  > vm2-startup-script.sh


# Download VM-2 creation program from VM metadata
curl \
  -H "Metadata-Flavor: Google" \
  http://metadata/computeMetadata/v1/instance/attributes/vm2-launch-code \
  > vm2-launch-code.py


# Download service-account credentials from VM metadata
curl \
  -H "Metadata-Flavor: Google" \
  http://metadata/computeMetadata/v1/instance/attributes/service-credentials \
  > service-credentials.json


# Download project ID
curl \
  -H "Metadata-Flavor: Google" \
  http://metadata/computeMetadata/v1/instance/attributes/project \
  > project.txt


# Restrict access to the credential file
chmod 600 /srv/service-credentials.json


# Install libraries needed by the VM-2 creation program
pip3 install --upgrade \
    google-api-python-client \
    google-auth \
    google-auth-httplib2


# Run the program that creates VM-2
python3 /srv/vm2-launch-code.py
"""


# -------------------------------------------------------------------
# Create VM-1
#
# VM-1 receives all the information it needs through metadata.
# -------------------------------------------------------------------

def create_vm1(compute, project, zone, credentials_json):

    vm1_startup_script = create_vm1_startup_script()
    vm2_startup_script = create_vm2_startup_script()
    vm2_launch_code = create_vm2_launch_code(project, zone)

    instance_config = {
        "name": VM1_NAME,

        "machineType": (
            f"zones/{zone}/machineTypes/{MACHINE_TYPE}"
        ),

        "disks": [
            {
                "boot": True,
                "autoDelete": True,
                "initializeParams": {
                    "sourceImage": (
                        f"projects/{IMAGE_PROJECT}/global/"
                        f"images/family/{IMAGE_FAMILY}"
                    )
                }
            }
        ],

        "networkInterfaces": [
            {
                "network": NETWORK,
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
                    "value": vm1_startup_script
                },
                {
                    "key": "vm2-startup-script",
                    "value": vm2_startup_script
                },
                {
                    "key": "vm2-launch-code",
                    "value": vm2_launch_code
                },
                {
                    "key": "service-credentials",
                    "value": credentials_json
                },
                {
                    "key": "project",
                    "value": project
                }
            ]
        }
    }

    print(f"Creating {VM1_NAME}...")

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

    print(f"{VM1_NAME} was created successfully.")


# -------------------------------------------------------------------
# Get a VM instance
# -------------------------------------------------------------------

def get_instance(compute, project, zone, instance_name):
    return compute.instances().get(
        project=project,
        zone=zone,
        instance=instance_name
    ).execute()


# -------------------------------------------------------------------
# Get external IP address
# -------------------------------------------------------------------

def get_external_ip(compute, project, zone, instance_name):

    instance = get_instance(
        compute,
        project,
        zone,
        instance_name
    )

    for interface in instance.get("networkInterfaces", []):
        for access_config in interface.get("accessConfigs", []):
            if access_config.get("natIP"):
                return access_config["natIP"]

    return None


# -------------------------------------------------------------------
# Main
# -------------------------------------------------------------------

def main():

    parser = argparse.ArgumentParser(
        description="Lab 5 Part 3 - Create a VM that creates another VM."
    )

    parser.add_argument(
        "--zone",
        default=DEFAULT_ZONE,
        help="Google Cloud zone."
    )

    args = parser.parse_args()

    # ---------------------------------------------------------------
    # Load service-account credentials
    # ---------------------------------------------------------------

    credentials = (
        service_account.Credentials
        .from_service_account_file(
            filename=SERVICE_CREDENTIALS_FILE
        )
    )

    # ---------------------------------------------------------------
    # Google Cloud project
    # ---------------------------------------------------------------

    project = (
        os.getenv("GOOGLE_CLOUD_PROJECT")
        or "dcsc-fall26-ucb"
    )

    # ---------------------------------------------------------------
    # Build Compute Engine API client
    # ---------------------------------------------------------------

    compute = googleapiclient.discovery.build(
        "compute",
        "v1",
        credentials=credentials
    )

    # ---------------------------------------------------------------
    # Read the service-account JSON file
    # ---------------------------------------------------------------

    with open(
        SERVICE_CREDENTIALS_FILE,
        "r",
        encoding="utf-8"
    ) as credentials_file:
        credentials_json = credentials_file.read()

    print(f"Google Cloud project: {project}")
    print(f"Zone: {args.zone}")
    print()
    print(f"VM-1: {VM1_NAME}")
    print(f"VM-2: {VM2_NAME}")
    print()

    # ---------------------------------------------------------------
    # Laptop -> VM-1
    # ---------------------------------------------------------------

    create_vm1(
        compute,
        project,
        args.zone,
        credentials_json
    )

    print()
    print(
        f"{VM1_NAME} is now running."
    )

    print(
        f"{VM1_NAME} will use the service account "
        f"to create {VM2_NAME}."
    )

    # ---------------------------------------------------------------
    # Show VM-1 external IP
    # ---------------------------------------------------------------

    time.sleep(10)

    vm1_ip = get_external_ip(
        compute,
        project,
        args.zone,
        VM1_NAME
    )

    print()

    if vm1_ip:
        print(f"VM-1 external IP: {vm1_ip}")
    else:
        print("VM-1 external IP not found.")

    print()
    print(
        f"Check Google Cloud Console for {VM2_NAME}."
    )

    print(
        f"When VM-2 finishes starting, Flask should be available "
        f"on port 5000."
    )


if __name__ == "__main__":
    main()