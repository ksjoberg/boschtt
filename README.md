## Bosch Thermotechnology custom component for home assistant

## Installation

### Option 1: HACS

Under HACS -> Integrations, select "+", search for `boschtt` and install it.


### Option 2: Manual

From the [latest release](https://github.com/ksjoberg/boschtt/releases)

```bash
cd YOUR_HASS_CONFIG_DIRECTORY    # same place as configuration.yaml
mkdir -p custom_components/boschtt
cd custom_components/boschtt
unzip boschtt-X.Y.Z.zip
mv boschtt-X.Y.Z/custom_components/boschtt/* .  
```

### Debug logging
Add this to your configuration.yaml to debug the component.

```
logger:
  default: info
  logs:
    pyBoschtt: debug
    custom_components.boschtt: debug
```
