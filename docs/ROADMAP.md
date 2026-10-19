# Possible next steps

These are candidates, not release commitments. Prioritize verified boot behavior,
clear compatibility limits, and preserving existing media.

- [x] Publish the latest 14-image USB results and actual screenshots, separating
  installer boot, completed installation, and physical hardware evidence.
  See the [FlexBoot 0.7.5 media report](TESTING-0.7.5.md).
- [ ] Expand the Linux test matrix across live and installer variants. Record
  exact releases and firmware, add profiles only for validated boot mechanisms,
  and keep unsupported images fail-closed.
- [ ] Complete a Server 2025 installation and destination-only boot in a VM;
  test Server 2012 R2, 2016, 2019, 2022 and 2025 on physical hardware. Keep donor
  WinPE and firmware requirements visible and distinguish older test results
  from new runs on the current USB.
- [ ] Extend interruption/recovery tests for cancelled copies, insufficient
  space, and failed metadata/menu publication. Verify existing entries remain
  usable, partial additions stay out of the menu, and resources are cleaned up.
- [ ] Improve pre-copy compatibility explanations: detected OS/build, selected
  boot method, firmware requirements, donor WinPE requirements, and the scope
  of available test evidence.

Suggested order after documentation: Linux compatibility and failure recovery,
then deeper Windows validation and richer compatibility diagnostics.
