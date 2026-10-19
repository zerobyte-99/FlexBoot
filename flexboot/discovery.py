"""Read-only GRUB discovery for a deliberately bounded subset of Linux layouts.

Never execute configuration found inside an ISO. Use the same argument recipes
as host-side profiles; managed entries keep their richer inspection and aliases.
"""
from __future__ import annotations

from .profiles.clonezilla import BOOT_ARGS as CLONEZILLA_ARGS
from .profiles.debian_live import BOOT_ARGS as DEBIAN_ARGS
from .profiles.gparted import BOOT_ARGS as GPARTED_ARGS
from .profiles.ubuntu_casper import DESKTOP_ARGS, SERVER_ARGS

EXFAT_PROFILE_IDS = frozenset(("debian-live", "clonezilla-live", "gparted-live"))


def discovery_config() -> str:
    recipes = {
        "server": SERVER_ARGS,
        "casper": DESKTOP_ARGS,
        "debian": DEBIAN_ARGS,
        "clonezilla": CLONEZILLA_ARGS,
        "gparted": GPARTED_ARGS,
    }
    boot = []
    for kind, args in recipes.items():
        args = args.replace("${iso_path}", '"${iso_path}"')
        boot.append(f'''                if [ "$6" = {kind} ]; then
                  if linux "(loop)$4" {args}; then
                    initrd "(loop)$5"
                  fi
                fi''')
    return r'''
# Read-only discovery. Only the configured data filesystems, never other disks.
insmod regexp
insmod loopback
insmod iso9660
insmod file
insmod probe
function flexboot_probe_iso {
  set fb_kind=
  set fb_kernel=
  set fb_initrd=
  if [ -f (fbscan)/casper/vmlinuz ]; then
    set fb_kernel=/casper/vmlinuz
  elif [ -f (fbscan)/casper/vmlinuz.efi ]; then
    set fb_kernel=/casper/vmlinuz.efi
  fi
  if [ -n "$fb_kernel" ]; then
    for fb_init in /casper/initrd /casper/initrd.lz /casper/initrd.gz /casper/initrd.img /casper/initrd.xz; do
      if [ -z "$fb_initrd" -a -f "(fbscan)$fb_init" ]; then
        set fb_initrd=$fb_init
      fi
    done
    if [ -f (fbscan)/casper/install-sources.yaml -a -f (fbscan)/casper/ubuntu-server-minimal.squashfs ]; then
      set fb_kind=server
    elif [ -f (fbscan)/casper/filesystem.squashfs ]; then
      set fb_kind=casper
    fi
  elif [ -f (fbscan)/live/vmlinuz -a -f (fbscan)/live/filesystem.squashfs ]; then
    set fb_kernel=/live/vmlinuz
    if [ -f (fbscan)/live/initrd.img ]; then
      set fb_initrd=/live/initrd.img
    elif [ -f (fbscan)/live/initrd ]; then
      set fb_initrd=/live/initrd
    fi
    set fb_kind=debian
    if [ -f (fbscan)/Clonezilla-Live-Version ]; then
      set fb_kind=clonezilla
    elif [ -f (fbscan)/GParted-Live-Version -o -f (fbscan)/live/GParted-Live-Version ]; then
      set fb_kind=gparted
    fi
    # Parrot requires additional vendor detection; use the managed importer.
    set fb_label=
    probe --set=fb_label --label (fbscan)
    if regexp '^[Pp][Aa][Rr][Rr][Oo][Tt]' "$fb_label"; then
      set fb_kind=
    fi
  fi
  if [ -z "$fb_kind" -o -z "$fb_initrd" ]; then
    return 1
  fi
  # Tested Ubuntu 24.04.4 Casper cannot rediscover an ISO on exFAT.
  # Keep this family excluded until its initramfs capabilities can be checked.
  if [ "$fb_storage_fs" = exfat ]; then
    if [ "$fb_kind" = casper -o "$fb_kind" = server ]; then
      return 1
    fi
  fi
  # Require a genuine x86 Linux kernel with an x86-64 EFI stub.
  if file --is-x86-linux "(fbscan)$fb_kernel"; then
    if file --is-x86_64-efi "(fbscan)$fb_kernel"; then
      return 0
    fi
  fi
  return 1
}
function flexboot_scan {
  set fb_device=$1
  set fb_storage_fs=
  probe --set=fb_storage_fs --fs "($fb_device)"
  for fb_candidate in "($1)/iso/"*; do
    # Initramfs parsers split whitespace. Read-only discovery cannot create
    # the aliases used by add/sync, so accept only portable simple filenames.
    if regexp --set=1:fb_path --set=2:fb_name '^\([^)]*\)(/iso/([A-Za-z0-9_+.-]+\.[iI][sS][oO]))$' "$fb_candidate"; then
      if [ -f "$fb_candidate" ]; then
        if ! flexboot_managed "$fb_device" "$fb_path"; then
          if loopback fbscan "$fb_candidate"; then
            if flexboot_probe_iso; then
              menuentry "[Linux] $fb_name [discovered]" "$fb_device" "$fb_path" "$fb_kernel" "$fb_initrd" "$fb_kind" {
                set iso_path=$3
                export iso_path
                if loopback loop "($2)$3"; then
''' + "\n".join(boot) + r'''
                fi
              }
            fi
            loopback -d fbscan
          fi
        fi
      fi
    fi
  done
}
if [ -n "$flexboot_data" ]; then
  flexboot_scan "$flexboot_data"
fi
if [ -n "$flexboot_drop_uuid" ]; then
  insmod ntfs
  set flexboot_drop=
  if search --no-floppy --fs-uuid --set=flexboot_drop "$flexboot_drop_uuid"; then
    flexboot_scan "$flexboot_drop"
  fi
fi
'''
