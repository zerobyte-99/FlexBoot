import json
import unittest
from pathlib import Path

from flexboot.devices import Device, DeviceIdentity, parse_lsblk
from flexboot.errors import SafetyError
from flexboot.safety import check_unattended_confirmation, protected_device_names, revalidate_identity, validate_physical_target


def disk(name="sdb", transport="usb", children=(), **kwargs):
    defaults = dict(name=name, path=Path("/dev") / name, type="disk", size=16 * 1024**3, major_minor="8:16", transport=transport, children=children)
    defaults.update(kwargs)
    return Device(**defaults)


class DeviceSafetyTests(unittest.TestCase):
    def test_lsblk_parses_sd_nvme_mmc_and_lvm_topology(self):
        raw = {"blockdevices": [
            {"name":"sda","path":"/dev/sda","type":"disk","size":100,"children":[{"name":"sda1","path":"/dev/sda1","type":"part","pkname":"sda","size":90,"mountpoints":["/"]}]},
            {"name":"nvme0n1","path":"/dev/nvme0n1","type":"disk","size":100,"children":[{"name":"nvme0n1p1","path":"/dev/nvme0n1p1","type":"part","pkname":"nvme0n1","size":100}]},
            {"name":"mmcblk0","path":"/dev/mmcblk0","type":"disk","size":100},
            {"name":"dm-0","path":"/dev/mapper/root","type":"lvm","pkname":"nvme0n1p1","size":50,"mountpoints":["/"]},
        ]}
        parsed = parse_lsblk(json.dumps(raw))
        self.assertEqual([x.name for x in parsed], ["sda", "nvme0n1", "mmcblk0", "dm-0"])

    def test_partition_rejected(self):
        with self.assertRaises(SafetyError):
            validate_physical_target(Device("sdb1", Path("/dev/sdb1"), "part", 2 * 1024**3), protected_names=set())

    def test_system_root_boot_and_efi_backing_disk_rejected(self):
        part = Device("sda1", Path("/dev/sda1"), "part", 10, parent_name="sda")
        root = disk("sda", children=(part,))
        protected = protected_device_names([root], ["/dev/sda1"])
        self.assertIn("sda", protected)
        with self.assertRaises(SafetyError): validate_physical_target(root, protected_names=protected)

    def test_lvm_like_nested_root_protects_physical_ancestor(self):
        logical = Device("dm-0", Path("/dev/mapper/root"), "lvm", 10)
        crypt = Device("dm-crypt", Path("/dev/mapper/crypt"), "crypt", 20, children=(logical,))
        part = Device("nvme0n1p3", Path("/dev/nvme0n1p3"), "part", 30, children=(crypt,))
        root = disk("nvme0n1", transport="nvme", children=(part,))
        protected = protected_device_names([root], ["/dev/mapper/root"])
        self.assertTrue({"dm-0", "dm-crypt", "nvme0n1p3", "nvme0n1"}.issubset(protected))

    def test_usb_candidate_and_non_usb_override(self):
        validate_physical_target(disk(), protected_names=set())
        with self.assertRaises(SafetyError): validate_physical_target(disk(transport="nvme"), protected_names=set())
        validate_physical_target(disk(transport="nvme"), protected_names=set(), allow_non_usb=True)

    def test_mounted_child_rejected(self):
        child = Device("sdb1", Path("/dev/sdb1"), "part", 100, mountpoints=("/media/x",))
        with self.assertRaises(SafetyError): validate_physical_target(disk(children=(child,)), protected_names=set())

    def test_identity_changes_abort_including_missing_serial(self):
        before = DeviceIdentity("/dev/sdb", "8:16", 100, "", "")
        revalidate_identity(before, DeviceIdentity("/dev/sdb", "8:16", 100, "", ""))
        with self.assertRaises(SafetyError): revalidate_identity(before, DeviceIdentity("/dev/sdc", "8:32", 100, "", ""))
        with self.assertRaises(SafetyError): revalidate_identity(DeviceIdentity("/dev/sdb", "8:16", 100, "A"), DeviceIdentity("/dev/sdb", "8:16", 100, "B"))

    def test_unattended_requires_two_factors(self):
        ident = DeviceIdentity("/dev/sdb", "8:16", 100, "SERIAL")
        for expected, confirmed in ((None, True), ("SERIAL", False), ("WRONG", True)):
            with self.assertRaises(SafetyError): check_unattended_confirmation(ident, expected, confirmed)
        check_unattended_confirmation(ident, "SERIAL", True)


if __name__ == "__main__": unittest.main()
