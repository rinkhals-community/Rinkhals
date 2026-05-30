---
title: Firmware repository
---

## Definition

A firmware repository hosts stock Anycubic firmware files for one printer model
and a `manifest.json` describing the versions it offers. Rinkhals uses these
manifests to list the stock firmwares available for the current printer (for
example in the touch UI when checking for a firmware update).

There is one manifest per model. The Rinkhals manifest
(`files/3-rinkhals/manifest.json`) maps each model code to its firmware
repository manifest URL.

When listing versions, Rinkhals reads the `firmwares` array, sorts entries by
`version` (descending), and skips any entry whose `supported_models` is present
but does not include the current model.

## Schema

| Field | Type | Required | Description |
| -- | -- | -- | -- |
| `$version` | string | Yes | Manifest schema version. Currently `"1"`. |
| `name` | string | No | Human-readable name of the repository. |
| `description` | string | No | Short description of the repository. |
| `repository` | string | No | Base URL of the repository. |
| `self` | string | No | Canonical URL of this manifest. |
| `firmwares` | array | Yes | List of available firmware versions (see below). |

### `firmwares[]`

| Field | Type | Required | Description |
| -- | -- | -- | -- |
| `version` | string | Yes | Firmware version, e.g. `"2.5.0.6"`. Used for sorting and display. |
| `date` | number | No | Release date, as a Unix timestamp (seconds). |
| `changes` | string | No | Changelog text for this version. |
| `md5` | string | No | MD5 checksum of the firmware file. |
| `url` | string | Yes | Download URL of the firmware (`.swu`) file. |
| `supported_models` | array | No | Model codes this entry applies to (e.g. `["KS1"]`). If present, entries not matching the current model are skipped. |

## Example

```json
{
    "$version": "1",
    "name": "Anycubic Kobra S1 firmware (Mirror)",
    "description": "Mirror for Anycubic Kobra S1 stock firmwares",
    "repository": "https://rinkhals.thedju.net",
    "self": "https://rinkhals.thedju.net/Kobra%20S1/manifest.json",
    "firmwares": [
        {
            "version": "2.5.0.6",
            "date": 1742569005,
            "changes": "1. Improved loading and unloading logic\n2. Improved video monitoring stability\n3. Other issues fixed",
            "md5": "c0d7b3857602b2b3ed145fd195b3236d",
            "url": "https://rinkhals.thedju.net/Kobra%20S1/KS1_2.5.0.6.swu",
            "supported_models": [
                "KS1"
            ]
        }
    ]
}
```
