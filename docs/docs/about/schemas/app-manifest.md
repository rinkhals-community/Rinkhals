---
title: App
---

## Definition

Every Rinkhals app ships an `app.json` file next to its `app.sh`. This manifest
describes the app to Rinkhals: its name, version and description, optional
resource hints, and any settings that should be exposed in the Rinkhals touch UI.

At startup Rinkhals reads `$version` and only loads apps whose schema version it
understands (currently `1`). Apps with a missing or unsupported `$version` are
skipped. The `name`, `description`, `version` and `properties` fields are also
read by the touch UI to render the app's settings page.

JSON comments (`//`) are tolerated in `app.json`; Rinkhals strips them before
parsing.

## Schema

| Field | Type | Required | Description |
| -- | -- | -- | -- |
| `$version` | string | Yes | Manifest schema version. Must be `"1"`. Apps with any other value are skipped at startup. |
| `name` | string | Yes | Display name shown in the touch UI. |
| `description` | string | Yes | Short description shown in the touch UI. |
| `version` | string | Yes | The app's own version (free-form, e.g. `"1.0"` or a commit hash). |
| `url` | string | No | App or project URL. |
| `requirements` | object | No | Resource hints (see below). Informational only; not currently enforced by the loader. |
| `properties` | object | No | User-configurable settings shown in the touch UI (see below). |

### `requirements`

| Field | Type | Description |
| -- | -- | -- |
| `cpu` | number | Approximate CPU usage, in percent. |
| `memory` | number | Approximate memory usage, in MB. |

### `properties`

`properties` is an object whose keys are the property names used to store the
value. Each value is an object describing how the property is presented and
edited:

| Field | Type | Description |
| -- | -- | -- |
| `display` | string | Label shown in the UI. If omitted, the property is not shown. |
| `type` | string | One of `text`, `number`, `enum`, `report`, `qr`. |
| `default` | any | Default value used until the user sets one. |
| `options` | array | Valid choices, for `enum` types. |
| `validation` | string | Regex used to validate `text` input. Declared in the schema; not yet enforced by the touch UI. |
| `range` | array | `[min, max]` valid range for `number` input. Declared in the schema; not yet enforced by the touch UI. |

Property `type` values:

- `text` - editable free text.
- `number` - editable numeric value.
- `enum` - a choice among `options`. As a special case, an enum whose options
  are exactly `["False", "True"]` is rendered as a checkbox.
- `report` - a read-only value shown to the user (not editable).
- `qr` - a value shown to the user with a button to display it as a QR code.

## Example

```json
{
    "$version": "1", // Schema version

    "name": "Example app",
    "description": "Simple example app to showcase the app system",
    "version": "1.0",
    "url": "https://github.com/rinkhals-community/Rinkhals.Apps/tree/master/apps/example", // App or project URL

    "requirements":
    {
        "cpu": 0, // CPU usage in %
        "memory": 0 // Memory usage in MB
    },

    // Those properties will be exposed in Rinkhals UI
    "properties": {
        "text_input": {
            "display": "IP address", // Optional: if display is not set, the property won't be shown in the UI
            "type": "text", // Optional: property type for the UI (text, number, enum, report or qr)
            "validation": "^[0-9]{1,3}\\.[0-9]{1,3}\\.[0-9]{1,3}\\.[0-9]{1,3}$", // Optional: regex to validate strings
            "default": "0.0.0.0" // Optional: default value
        },
        "number_input": {
            "display": "Number",
            "type": "number",
            "range": [ 1024, 65536 ], // Optional: valid range for the number
            "default": 5678
        },
        "enum_input": {
            "display": "Option",
            "type": "enum",
            "options": [ "Choice 1", "Choice 2", "Choice 3" ] // Optional: valid choices for this enum
        },

        "text_output": {
            "display": "Status",
            "type": "report" // Reports will be shown to the user but not editable
        },
        "link_output": {
            "display": "Link",
            "type": "qr" // This property will be shown to the user with a QR code
        }
    }
}
```
