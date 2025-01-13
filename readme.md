# De Lijn Tracker

- [Description](#description)
- [Features](#features)
- [Setup](#setup)
- [Configuration](#configuration)
- [Change Log](#change-log)
- [Issues](#issues)

## Description

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)

this integration allows to add trackers for stations from the [De Lijn](https://www.delijn.be)

## Features

you can track a specific schedule from a specified station and line number. as soon there are realtime datas available for your schedule, they will be displayed.

## Prerequisites

to run this integration you need this prerequisites:

- [HACS](https://hacs.xyz)
- API key for [De Lijn - Open Data V1 Core API](https://data.delijn.be/product)

## Setup

Recommended to be installed via [HACS](https://github.com/hacs/integration)

1. Go to HACS -> Integrations
2. [Add this repo to your HACS custom repositories](https://hacs.xyz/docs/faq/custom_repositories)
3. Search for "Connectivity Monitor" and install.
4. Restart Home Assistant
5. Open Home Assistant Settings -> Devices & Serivces
6. Shift+reload your browser to clear config flow caches.
7. Click ADD INTEGRATION
8. Search for "De Lijn Tracker"

## Configuration

To configure an item, you have to follow this steps:

1. Open Home Assistant Settings -> Devices & Serivces
2. Click ADD INTEGRATION
3. Search for "De Lijn Tracker"
4. the first time, you have to enter the API key
5. go to the [De Lijn Website](https://www.delijn.be/nl/haltes/) and search for the correct station. in the description of the station is a number with 6 ciphers. the number is also printed on the physical boards on each station. be aware that each direction has a different number.
5. enter the halte_nummer and click `SUBMIT`
6. select the line number and click `SUBMIT`
7. select the scheduled time and click `SUBMIT`

## Issues

- [ ] schedules which doesn't exist on current day, can't be selected
- [ ] schedules which doesn't exist today or tomorrow are displayed as `unknown`
- [ ] delay sensor doesn't work correctly

