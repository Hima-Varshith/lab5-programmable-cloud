#!/usr/bin/env python3

import argparse
import os
import time

import google.auth
import googleapiclient.discovery


DEFAULT_ZONE = "us-west1-b"
SOURCE_INSTANCE = "lab5-part1"

SNAPSHOT_NAME = f"base-snapshot-{SOURCE_INSTANCE}"
IMAGE_NAME = f"base-image-{SOURCE_INSTANCE}"

MACHINE_TYPE = "f1-micro"
#MACHINE_TYPE = "e2-medium"

CLONE_NAMES = [
    "lab5-clone-1",
    "lab5-clone-2",
    "lab5-clone-3",
]


def wait_for_zone_operation(compute, project, zone, operation_name):
    """Wait for a zonal Compute Engine operation to finish."""
    while True:
        result = compute.zoneOperations().get(
            project=project,
            zone=zone,
            operation=operation_name,
        ).execute()

        if result["status"] == "DONE":
            if "error" in result:
                raise RuntimeError(
                    f"Zonal operation failed: {result['error']}"
                )
            return

        time.sleep(2)


def wait_for_global_operation(compute, project, operation_name):
    """Wait for a global Compute Engine operation to finish."""
    while True:
        result = compute.globalOperations().get(
            project=project,
            operation=operation_name,
        ).execute()

        if result["status"] == "DONE":
            if "error" in result:
                raise RuntimeError(
                    f"Global operation failed: {result['error']}"
                )
            return

        time.sleep(2)


def get_boot_disk(compute, project, zone, instance_name):
    """
    Find the boot disk attached to the source VM.
    """
    instance = compute.instances().get(
        project=project,
        zone=zone,
        instance=instance_name,
    ).execute()

    for disk in instance.get("disks", []):
        if disk.get("boot"):
            source = disk["source"]
            return source.split("/")[-1]

    raise RuntimeError(
        f"Could not find boot disk for instance '{instance_name}'."
    )


def create_snapshot(compute, project, zone, disk_name):
    """
    Create a snapshot from the Part 1 boot disk.
    """
    print(f"Creating snapshot '{SNAPSHOT_NAME}' from disk '{disk_name}'...")

    snapshot_body = {
        "name": SNAPSHOT_NAME,
    }

    operation = compute.disks().createSnapshot(
        project=project,
        zone=zone,
        disk=disk_name,
        body=snapshot_body,
    ).execute()

    wait_for_zone_operation(
        compute,
        project,
        zone,
        operation["name"],
    )

    print(f"Snapshot '{SNAPSHOT_NAME}' created.")


def create_image(compute, project):
    """
    Create a custom image from the snapshot.
    """
    print(f"Creating image '{IMAGE_NAME}'...")

    image_body = {
        "name": IMAGE_NAME,
        "sourceSnapshot": (
            f"projects/{project}/global/snapshots/{SNAPSHOT_NAME}"
        ),
    }

    operation = compute.images().insert(
        project=project,
        body=image_body,
    ).execute()

    wait_for_global_operation(
        compute,
        project,
        operation["name"],
    )

    print(f"Image '{IMAGE_NAME}' created.")


def create_clone(compute, project, zone, instance_name):
    """
    Create one VM from the custom image and return the creation time.
    """
    instance_body = {
        "name": instance_name,

        "machineType": (
            f"zones/{zone}/machineTypes/{MACHINE_TYPE}"
        ),

        "disks": [
            {
                "boot": True,
                "autoDelete": True,
                "initializeParams": {
                    "sourceImage": (
                        f"projects/{project}/global/images/{IMAGE_NAME}"
                    )
                },
            }
        ],

        "networkInterfaces": [
            {
                "network": "global/networks/default",
                "accessConfigs": [
                    {
                        "type": "ONE_TO_ONE_NAT",
                        "name": "External NAT",
                    }
                ],
            }
        ],
    }

    print(f"Creating VM '{instance_name}'...")

    start_time = time.time()

    operation = compute.instances().insert(
        project=project,
        zone=zone,
        body=instance_body,
    ).execute()

    wait_for_zone_operation(
        compute,
        project,
        zone,
        operation["name"],
    )

    end_time = time.time()

    creation_time = end_time - start_time

    print(
        f"VM '{instance_name}' created in "
        f"{creation_time:.2f} seconds."
    )

    return creation_time


def main():
    parser = argparse.ArgumentParser(
        description="Lab 5 Part 2 - Clone a VM using a snapshot/image."
    )

    parser.add_argument(
        "--zone",
        default=DEFAULT_ZONE,
        help="Google Cloud zone.",
    )

    parser.add_argument(
        "--instance",
        default=SOURCE_INSTANCE,
        help="Source Part 1 VM.",
    )

    args = parser.parse_args()

    credentials, project = google.auth.default()

    compute = googleapiclient.discovery.build(
        "compute",
        "v1",
        credentials=credentials,
    )

    print(f"Google Cloud project: {project}")
    print(f"Source VM: {args.instance}")
    print(f"Zone: {args.zone}")
    print()

    # Step 1: Find the boot disk of the Part 1 VM.
    disk_name = get_boot_disk(
        compute,
        project,
        args.zone,
        args.instance,
    )

    print(f"Boot disk found: {disk_name}")
    print()

    # Step 2: Create a snapshot from that disk.
    create_snapshot(
        compute,
        project,
        args.zone,
        disk_name,
    )

    print()

    # Step 3: Create a custom image from the snapshot.
    create_image(
        compute,
        project,
    )

    print()

    # Step 4: Create three VMs and record creation times.
    timing_results = []

    for clone_name in CLONE_NAMES:
        creation_time = create_clone(
            compute,
            project,
            args.zone,
            clone_name,
        )

        timing_results.append(
            (clone_name, creation_time)
        )

    # Step 5: Print timing results.
    print()
    print("VM creation timing results:")
    print("--------------------------------")

    for name, elapsed in timing_results:
        print(f"{name}: {elapsed:.2f} seconds")


if __name__ == "__main__":
    main()