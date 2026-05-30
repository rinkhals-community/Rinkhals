---
title: Rinkhals schemas
---

## Overview

Rinkhals uses a few JSON manifest formats to describe apps and firmware. This
section documents their structure so app and firmware-repository authors know
what fields are expected.

- [App](app-manifest.md) - the `app.json` manifest that ships with every
  Rinkhals app, describing its name, version, resource hints and the settings
  exposed in the touch UI.
- [App repository](app-repository-manifest.md) - the manifest that lists the
  apps offered by an app repository. This format is planned and not yet
  implemented.
- [Firmware repository](firmware-repository-manifest.md) - the per-model
  manifest that lists the stock Anycubic firmware versions available for a
  printer.

JSON comments (`//`) are tolerated in these manifests where noted; Rinkhals
strips them before parsing.
