# Development

Run all standard-library tests and syntax checks:

```bash
python3 -m unittest discover -v
python3 -m compileall -q flexboot tests tools
python3 -m flexboot --help
python3 -m flexboot doctor
python3 -m flexboot devices --json
```

Tests use synthetic block-device JSON, temporary directories, mock loop commands, and synthetic ISO path sets. They do not write block devices.

The privileged integration path is opt-in. Review the test and ensure no valuable loop state is in use, then run:

```bash
sudo FLEXBOOT_RUN_IMAGE_TESTS=1 python3 -m unittest tests.test_integration_image -v
sudo python3 -m flexboot image create ./out/flexboot.img --size 2G
sudo python3 -m flexboot image inspect ./out/flexboot.img
```

Inspect active loops afterward with `losetup --list`. QEMU validation uses `python3 -m flexboot image boot ./out/flexboot.img`; hardware acceleration is not required.

Regenerate the code-drawn logo, selection graphics, and Classic Grid background with `python3 tools/generate_assets.py`. This script uses only zlib and PNG primitives from the standard library and preserves the generated background variants.
